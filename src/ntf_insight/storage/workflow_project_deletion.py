"""Kontrolliertes Löschen eines sachnummernbezogenen NTF-Projekts.

- "Entfernen" löscht nur den Projekteinstieg, NICHT die Falldaten.
- "Vollständig löschen" löscht ausschließlich eindeutig zuordenbare
  Fälle/FIN-Diagnosen/KI-Stände/Belege. Gemeinsame oder unklare Quell-
  und Fallreferenzen blockieren den gesamten Vorgang (fail closed).
- Dateien werden vor dem DB-Commit reversibel in ein Quarantäneverzeichnis
  verschoben. Bei Fehler wird die DB zurückgerollt und Dateien restauriert.
"""
from __future__ import annotations

import json
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from ntf_insight.ingestion.artifacts import SourceArtifact
from ntf_insight.ingestion.project_portable import SCOPED_TABLES, _tables
from ntf_insight.storage.cluster_evidence_store import part_key
from ntf_insight.storage.duckdb_store import DuckDBStore
from ntf_insight.storage.qec_workflow_store import QecWorkflowStore
from ntf_insight.storage.workflow_projects import NTFProject, WorkflowProjectStore

_SHA = re.compile(r"[a-f0-9]{64}\Z")


@dataclass(frozen=True)
class ProjectDeleteResult:
    project: NTFProject
    complete: bool
    cases_deleted: int = 0
    report_count: int = 0
    files_deleted: int = 0
    shared_files_retained: int = 0


def _existing_project(store: DuckDBStore, profile: str, number: str) -> NTFProject:
    project = WorkflowProjectStore(store).get(profile, number)
    if project is None:
        raise ValueError("Dieses Projekt existiert nicht mehr.")
    return project


def _reset_context(con, profile: str, number: str) -> None:
    if "workflow_current_context" not in _tables(con):
        return
    row = con.execute(
        "SELECT profile_id,part_number FROM workflow_current_context WHERE slot=1"
    ).fetchone()
    if row and row[0] == profile and part_key(row[1]) == part_key(number):
        con.execute("DELETE FROM workflow_current_context WHERE slot=1")


def remove_project_assignment(
    store: DuckDBStore, profile: str, number: str,
) -> ProjectDeleteResult:
    """Nur Projekt-Registrierung entfernen; alle Rohdaten bleiben unverändert."""
    project = _existing_project(store, profile, number)
    with store.connect() as con:
        con.execute("BEGIN TRANSACTION")
        try:
            con.execute(
                "DELETE FROM workflow_projects WHERE profile_id=? AND part_key=?",
                [project.profile_id, part_key(project.part_number)],
            )
            _reset_context(con, project.profile_id, project.part_number)
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
    return ProjectDeleteResult(project, complete=False)


def _delete_where(con, table: str, column: str, values: set[str]) -> None:
    if not values or table not in _tables(con):
        return
    if not re.fullmatch(r"[a-z][a-z0-9_]*", table + column):
        raise ValueError("Ungültige Löschzuordnung.")
    ordered = sorted(values)
    placeholders = ",".join("?" for _ in ordered)
    con.execute(
        f'DELETE FROM "{table}" WHERE "{column}" IN ({placeholders})', ordered,
    )


def _checked_path(root: Path, candidate: Path) -> Path:
    """Nur normale Dateien/Verzeichnisse IN der verwalteten lokalen Datenablage."""
    path = Path(candidate).absolute()
    if path == root or not path.is_relative_to(root):
        raise ValueError("Projektdatei liegt außerhalb des verwalteten Datenordners.")
    current = path
    while current != root:
        if current.is_symlink():
            raise ValueError("Symbolischer Link in Projektunterlagen nicht zulässig.")
        current = current.parent
    return path


def _prepare_paths(
    root: Path, source_paths: list[Path], fins: set[str],
) -> list[Path]:
    paths: list[Path] = []
    for raw_path in source_paths:
        path = _checked_path(root, raw_path)
        if path.is_file():
            if not path.is_relative_to(root / "raw"):
                raise ValueError("Ein Rohbeleg liegt außerhalb des raw-Archivs.")
            paths.append(path)
        elif path.exists():
            raise ValueError("Nicht reguläre Rohdatei kann nicht gelöscht werden.")
    for folder in ("quicktests", "qec", "tips"):
        for fin in fins:
            # Die FIN ist ein Dateipfadsegment; keine User-Pfade zulassen.
            if not re.fullmatch(r"[A-Z0-9]{10,24}", fin):
                raise ValueError("Ungültige FIN für lokale Dateibereinigung.")
            path = _checked_path(root, root / folder / fin)
            if not path.exists():
                continue
            if not path.is_dir():
                raise ValueError("Ungültiger lokaler Fahrzeugarchivordner.")
            for entry in path.rglob("*"):
                _checked_path(root, entry)
                if not (entry.is_file() or entry.is_dir()):
                    raise ValueError("Nicht reguläre Unterlage im Fahrzeugordner.")
            paths.append(path)
    # Niemals Eltern und Kinder doppelt einplanen.
    return sorted(set(paths), key=lambda x: (len(x.parts), str(x)))


def _move_to_quarantine(root: Path, paths: list[Path]) -> tuple[Path, list[tuple[Path, Path]]]:
    quarantine = Path(tempfile.mkdtemp(prefix=".ntf-project-delete-", dir=root))
    moved: list[tuple[Path, Path]] = []
    try:
        for path in paths:
            target = quarantine / path.relative_to(root)
            target.parent.mkdir(parents=True, exist_ok=True)
            path.rename(target)
            moved.append((path, target))
    except Exception:
        _restore_moved(moved)
        shutil.rmtree(quarantine, ignore_errors=False)
        raise
    return quarantine, moved


def _restore_moved(moved: list[tuple[Path, Path]]) -> None:
    for original, staged in reversed(moved):
        if staged.exists():
            original.parent.mkdir(parents=True, exist_ok=True)
            staged.rename(original)


def fully_delete_project(
    store: DuckDBStore, data_dir: Path, profile: str, number: str,
) -> ProjectDeleteResult:
    """Lösche eindeutige Projektbelege, lehne gemischte Quellarchivalien ab."""
    project = _existing_project(store, profile, number)
    root = Path(data_dir).absolute()
    if root.is_symlink() or store.path.absolute() != root / "ntf-insight.duckdb":
        raise ValueError("Projekt-DB und lokaler Projektordner stimmen nicht überein.")
    key = part_key(project.part_number)

    # Aktive QEC-Quellen sind potenziell geteilt. Nicht nur DB-Zeilen,
    # sondern den tatsächlichen Inhalt jeder unveränderlichen Excel prüfen.
    qec_rows = (
        QecWorkflowStore(store).rows(root / "qec")
        if project.profile_id == "coolant_pump" else []
    )
    ours = [r for r in qec_rows if part_key(r["part_number"]) == key]
    our_cases = {str(r["case_id"]) for r in ours}
    our_fins = {str(r["fin"]).upper() for r in ours}
    our_sources = {str(r["source_sha256"]) for r in ours}
    if any(
        r["source_sha256"] in our_sources
        and part_key(r["part_number"]) != key
        for r in qec_rows
    ):
        raise ValueError(
            "Eine QEC-Excel wird auch von anderen Sachnummern verwendet. "
            "Vollständiges Löschen ist deshalb nicht sicher. "
            "Stattdessen 'Projekt entfernen' verwenden."
        )
    other_fins = {
        str(r["fin"]).upper() for r in qec_rows
        if part_key(r["part_number"]) != key
    }

    with store.connect() as con:
        available = _tables(con)
        unknown = available - SCOPED_TABLES
        for table in sorted(unknown):
            if not re.fullmatch(r"[a-z][a-z0-9_]*", table):
                raise ValueError("Unbekannter Tabellenname in Projektdaten.")
            if con.execute(
                f'SELECT EXISTS(SELECT 1 FROM "{table}" LIMIT 1)'
            ).fetchone()[0]:
                raise ValueError(
                    "Die App kennt noch keine sichere Löschregel für " + table
                )
        all_case_rows = con.execute(
            "SELECT case_id,vin,payload_json FROM case_snapshots"
        ).fetchall()
        for case_id, vin, data in all_case_rows:
            try:
                payload = json.loads(data)
            except (ValueError, TypeError) as exc:
                raise ValueError("Ein gespeicherter Fall ist nicht lesbar.") from exc
            case_part = part_key(str(payload.get("qec_part_number") or ""))
            case_profile = str(payload.get("component_profile_id") or "")
            if case_id in our_cases and case_profile and case_profile != project.profile_id:
                raise ValueError(
                    "Widersprüchliche Profilzuordnung eines QEC-Falls. "
                    "Vollständiges Löschen verweigert."
                )
            if case_part == key and not case_profile and case_id not in our_cases:
                raise ValueError(
                    "Ein Fall dieser Sachnummer hat keine eindeutige "
                    "Bauteilprofil-Zuordnung. Vollständiges Löschen verweigert."
                )
            if case_part == key and (
                case_profile == project.profile_id or case_id in our_cases
            ):
                our_cases.add(str(case_id))
                our_fins.add(str(vin).upper())
            else:
                other_fins.add(str(vin).upper())
        if our_fins & other_fins:
            raise ValueError(
                "Mindestens eine FIN wird von mehreren Bauteilprojekten genutzt. "
                "Aus Sicherheitsgründen ist nur 'Projekt entfernen' erlaubt."
            )

        packages = {
            x[0] for x in con.execute(
                "SELECT paket_id FROM workflow_first_ai_packages "
                "WHERE profile_id=? AND part_key=?", [profile, key],
            ).fetchall()
        } if "workflow_first_ai_packages" in available else set()
        for package in packages:
            if con.execute(
                "SELECT EXISTS(SELECT 1 FROM workflow_first_ai_packages "
                "WHERE paket_id=? AND (profile_id<>? OR part_key<>?))",
                [package, profile, key],
            ).fetchone()[0]:
                raise ValueError(
                    "Ein ChatGPT-Paket wird von mehreren Projekten genutzt."
                )
            mappings = con.execute(
                "SELECT art,original_id,fin FROM chatgpt_export_mapping "
                "WHERE paket_id=?", [package],
            ).fetchall()
            if any(
                art == "fall" and original_id not in our_cases
                or art == "fahrzeug" and str(fin or original_id).upper() not in our_fins
                or fin and str(fin).upper() not in our_fins
                for art, original_id, fin in mappings
            ):
                raise ValueError(
                    "Die KI-Analyse enthält Fälle anderer Projekte. "
                    "Vollständiges Löschen nicht sicher."
                )

        if our_cases and "chatgpt_fallanalysen" in available:
            legacy_rows = con.execute(
                "SELECT analyse_id,case_id FROM chatgpt_fallanalysen"
            ).fetchall()
            known_ids = {
                row[0] for row in con.execute(
                    "SELECT analyse_id FROM chatgpt_imports "
                    f"WHERE paket_id IN ({','.join('?' for _ in packages)})",
                    sorted(packages),
                ).fetchall()
            } if packages and "chatgpt_imports" in available else set()
            if any(
                case_id in our_cases and analyse_id not in known_ids
                for analyse_id, case_id in legacy_rows
            ):
                raise ValueError(
                    "Mindestens eine ChatGPT-Analyse der Projektfälle ist "
                    "noch keinem Projektpaket zugeordnet. Bitte erst "
                    "den Datenstand sichern bzw. die Zuordnung prüfen."
                )

        knowledge_sources: set[str] = set()
        knowledge_rows = con.execute(
            "SELECT source_sha256,fin FROM source_knowledge_rows"
        ).fetchall() if "source_knowledge_rows" in available else []
        for sha, fin in knowledge_rows:
            if str(fin or "").upper() in our_fins:
                knowledge_sources.add(str(sha))
        for sha in knowledge_sources:
            source_fins = {
                str(fin or "").upper()
                for source, fin in knowledge_rows if str(source) == sha
            }
            if not source_fins <= our_fins:
                raise ValueError(
                    "Ein TP-/Diagnose-Quelldokument enthält auch andere FINs "
                    "oder nicht eindeutig zuordenbare Zeilen. "
                    "Bitte nur 'Projekt entfernen' verwenden."
                )

        reports = {
            row[0] for row in con.execute(
                "SELECT report_id,fin FROM quicktest_reports"
            ).fetchall() if str(row[1]).upper() in our_fins
        } if "quicktest_reports" in available else set()
        if len(reports) > 1000000:
            raise ValueError("Unplausibel viele QuickTest-Berichte.")
        report_shas = {
            row[0] for row in con.execute(
                "SELECT artifact_sha256,report_id FROM quicktest_sources"
            ).fetchall() if row[1] in reports
        } if "quicktest_sources" in available else set()
        evidence_shas = {
            row[0] for row in con.execute(
                "SELECT sha256 FROM cluster_evidence_files "
                "WHERE profile_id=? AND part_key=?", [profile, key],
            ).fetchall()
        } if "cluster_evidence_files" in available else set()
        package_shas = {
            row[0] for row in con.execute(
                "SELECT sha256 FROM workflow_first_ai_packages "
                "WHERE profile_id=? AND part_key=?", [profile, key],
            ).fetchall()
        } if "workflow_first_ai_packages" in available else set()
        hinted_shas: set[str] = set()
        all_artifacts = {
            row[0]: SourceArtifact.model_validate_json(row[1])
            for row in con.execute(
                "SELECT sha256,payload_json FROM source_artifacts"
            ).fetchall()
        }
        for sha, artifact in all_artifacts.items():
            if (
                artifact.vin_hint and artifact.vin_hint.upper() in our_fins
                or artifact.case_id_hint and artifact.case_id_hint in our_cases
            ):
                hinted_shas.add(sha)
        candidates = (
            our_sources | knowledge_sources | report_shas
            | evidence_shas | package_shas | hinted_shas
        )
        for sha in candidates:
            if not _SHA.fullmatch(sha) or sha not in all_artifacts:
                raise ValueError("Projektquelle hat eine beschädigte SHA-Verknüpfung.")
        report_count = len(reports)
        case_count = len(our_cases)

        # Preflight in a SAVEPOINT-like rollback: evaluate resulting
        # references before staging any physical deletion.
        con.execute("BEGIN TRANSACTION")
        try:
            _delete_where(con, "case_snapshots", "case_id", our_cases)
            _delete_where(con, "manual_changes", "case_id", our_cases)
            _delete_where(con, "confirmed_root_causes", "case_id", our_cases)
            _delete_where(con, "qec_workflow_decisions", "case_id", our_cases)
            _delete_where(con, "qec_cluster_handoff", "fin", our_fins)
            for table in (
                "quicktest_sources", "quicktest_pages", "quicktest_ecus",
                "quicktest_dtcs", "quicktest_parameters",
            ):
                _delete_where(con, table, "report_id", reports)
            _delete_where(con, "quicktest_reports", "report_id", reports)
            _delete_where(
                con, "source_knowledge_rows", "source_sha256", knowledge_sources
            )
            _delete_where(
                con, "source_knowledge_documents", "source_sha256", knowledge_sources
            )
            analysis_ids = {
                row[0] for row in con.execute(
                    "SELECT analyse_id FROM chatgpt_imports WHERE paket_id IN "
                    f"({','.join('?' for _ in packages)})",
                    sorted(packages),
                ).fetchall()
            } if packages and "chatgpt_imports" in available else set()
            for table in ("chatgpt_fallanalysen", "chatgpt_cluster"):
                _delete_where(con, table, "analyse_id", analysis_ids)
            _delete_where(con, "chatgpt_imports", "analyse_id", analysis_ids)
            _delete_where(con, "chatgpt_export_mapping", "paket_id", packages)
            _delete_where(con, "workflow_ai_rounds", "paket_id", packages)
            for table in (
                "workflow_first_ai_packages", "workflow_second_ai_exports",
                "cluster_evidence_files", "workflow_ssl_selection",
                "workflow_source_activity", "workflow_source_log",
            ):
                if table in available:
                    con.execute(
                        f'DELETE FROM "{table}" WHERE profile_id=? AND part_key=?',
                        [profile, key],
                    )
            if "workflow_progress" in available:
                stored_numbers = [
                    row[0] for row in con.execute(
                        "SELECT part_number FROM workflow_progress "
                        "WHERE profile_id=?", [profile],
                    ).fetchall()
                ]
                for saved_part in stored_numbers:
                    if part_key(saved_part) == key:
                        con.execute(
                            "DELETE FROM workflow_progress WHERE "
                            "profile_id=? AND part_number=?",
                            [profile, saved_part],
                        )
            con.execute(
                "DELETE FROM workflow_projects WHERE profile_id=? AND part_key=?",
                [profile, key],
            )
            _reset_context(con, profile, project.part_number)

            removable: set[str] = set()
            shared: set[str] = set()
            for sha in candidates:
                # Shared source content must remain. Do not drop shared
                # parse_runs/artifact metadata even when one project goes.
                dependencies = (
                    ("cluster_evidence_files", "sha256"),
                    ("workflow_first_ai_packages", "sha256"),
                    ("quicktest_sources", "artifact_sha256"),
                    ("source_knowledge_documents", "source_sha256"),
                    ("source_knowledge_rows", "source_sha256"),
                    ("qec_workflow_decisions", "source_sha256"),
                    ("qec_cluster_handoff", "source_sha256"),
                )
                used = any(
                    con.execute(
                        f'SELECT EXISTS(SELECT 1 FROM "{table}" '
                        f'WHERE "{column}"=?)', [sha],
                    ).fetchone()[0]
                    for table, column in dependencies if table in available
                )
                if used:
                    shared.add(sha)
                else:
                    removable.add(sha)
            _delete_where(con, "parse_runs", "artifact_sha256", removable)
            _delete_where(con, "source_artifacts", "sha256", removable)

            raw_paths = [
                Path(all_artifacts[sha].archived_path) for sha in removable
            ]
            paths = _prepare_paths(root, raw_paths, our_fins)
            quarantine, moved = _move_to_quarantine(root, paths)
            try:
                con.execute("COMMIT")
            except Exception:
                con.execute("ROLLBACK")
                try:
                    _restore_moved(moved)
                except Exception as exc:
                    raise RuntimeError(
                        f"Löschung fehlgeschlagen! Dateien bitte aus "
                        f"{quarantine} wiederherstellen."
                    ) from exc
                shutil.rmtree(quarantine)
                raise
        except Exception:
            # The inner COMMIT path has already rolled back, if needed.
            try:
                con.execute("ROLLBACK")
            except Exception:
                pass
            raise

    # Keine Quarantänedatei vor einem erfolgreichen DB-COMMIT entfernen.
    try:
        shutil.rmtree(quarantine)
    except OSError as exc:
        raise OSError(
            "Projektdaten gelöscht, aber Restdateien liegen noch im "
            f"Quarantäneverzeichnis: {quarantine}"
        ) from exc
    return ProjectDeleteResult(
        project=project,
        complete=True,
        cases_deleted=case_count,
        report_count=report_count,
        files_deleted=len(paths),
        shared_files_retained=len(shared),
    )
