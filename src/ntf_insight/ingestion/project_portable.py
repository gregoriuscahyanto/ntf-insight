"""Projektbezogener PC-Transfer ohne Ersetzung fremder Projekte.

Ein .ntfproject ist ein Hüllenarchiv über einem streng selektierten, durch
portable_backup vollständig überprüften Mini-Gesamtstand. Import fügt
nur fehlende Projekte hinzu; dieselbe Projektidentität wird nie stillschweigend
überschrieben. Rohbelege können jedoch gemeinsame Dokumente enthalten, z. B.
eine QEC-Excel mit Fällen mehrerer Sachnummern. Das ist explizit freizugeben.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import duckdb

from ntf_insight.ingestion.artifacts import SourceArtifact, sha256_file
from ntf_insight.ingestion.portable_backup import (
    DATABASE_NAME, DATA_FOLDERS, _CHUNK, _relative,
    _safe_file, _snapshot_database, _write_member, export_portable_backup,
    restore_portable_backup,
)
from ntf_insight.storage.cluster_evidence_store import part_key
from ntf_insight.storage.duckdb_store import DuckDBStore
from ntf_insight.storage.qec_workflow_store import QecWorkflowStore
from ntf_insight.storage.workflow_projects import WorkflowProjectStore

PROJECT_EXTENSION = ".ntfproject"
FORMAT = "ntf-insight-project"
VERSION = 1
INNER = "projekt.ntfbackup"
MANIFEST = "projekt_manifest.json"
_IDENTIFIER = re.compile(r"[a-z][a-z0-9_]*\Z")
MAX_PROJECT_BYTES = 32 * 1024**3

# Every table is handled explicitly; new project-bearing tables must get a
# documented selector before export. Unknown populated tables fail closed.
SCOPED_TABLES = frozenset({
    "source_artifacts", "parse_runs", "case_snapshots", "manual_changes",
    "dtc_trigger_definitions", "ecu_change_records",
    "source_knowledge_documents", "source_knowledge_rows",
    "quicktest_reports", "quicktest_sources", "quicktest_pages",
    "quicktest_ecus", "quicktest_dtcs", "quicktest_parameters",
    "qec_workflow_decisions", "qec_cluster_handoff",
    "chatgpt_export_mapping", "chatgpt_imports", "chatgpt_cluster",
    "chatgpt_fallanalysen", "cluster_evidence_files",
    "workflow_first_ai_packages", "workflow_second_ai_exports",
    "workflow_ai_rounds", "workflow_progress", "workflow_current_context",
    "workflow_projects", "workflow_ssl_selection", "workflow_source_activity",
    "workflow_source_log",
    "dtc_manual_review_marks", "confirmed_root_causes",
})


@dataclass(frozen=True)
class ProjectExportResult:
    path: Path
    profile_id: str
    part_number: str
    case_count: int
    fin_count: int
    file_count: int
    shared_source_warning: bool


@dataclass(frozen=True)
class ProjectImportResult:
    profile_id: str
    part_number: str
    case_count: int
    file_count: int
    replaced: bool = False
    backup_path: Path | None = None


@dataclass(frozen=True)
class ProjectPackageIdentity:
    """Unverbindliche Vorschau; der eigentliche Import prueft alle SHA-256."""

    profile_id: str
    part_number: str
    component_name: str


def inspect_project_identity(source: Path) -> ProjectPackageIdentity:
    """Sichere, schnelle Identitaetsvorschau ohne GiB-Daten im GUI-Thread.

    Alle hier angezeigten Metadaten stammen aus einer untrusted ZIP; vor
    dem Import validiert _unpack_project den kompletten Inhalt erneut.
    """
    path = Path(source).absolute()
    if (path.suffix.lower() != PROJECT_EXTENSION or not path.is_file()
            or path.is_symlink()):
        raise ValueError("Bitte ein reguläres .ntfproject-Paket auswählen.")
    with ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != 2 or set(names) != {INNER, MANIFEST}:
            raise ValueError("Projektpaket enthält fehlende oder unerwartete Einträge.")
        for info in archive.infolist():
            _relative(info.filename)
            if info.is_dir() or info.file_size > MAX_PROJECT_BYTES:
                raise ValueError("Projektpaket enthält einen unzulässigen Eintrag.")
        if archive.getinfo(MANIFEST).file_size > 16 * 1024:
            raise ValueError("Projektmanifest zu groß.")
        manifest = json.loads(archive.read(MANIFEST))
    if not isinstance(manifest, dict) or (
        manifest.get("format") != FORMAT or manifest.get("version") != VERSION
    ):
        raise ValueError("Inkompatibles Projektpaket.")
    entry = manifest.get("projektdatei")
    if (not isinstance(entry, dict) or entry.get("name") != INNER
            or type(entry.get("bytes")) is not int
            or not 0 < entry["bytes"] <= MAX_PROJECT_BYTES
            or not isinstance(entry.get("sha256"), str)
            or not re.fullmatch(r"[a-f0-9]{64}", entry["sha256"])):
        raise ValueError("Projektmanifest enthält eine ungültige Dateiidentität.")
    profile = manifest.get("profil")
    part = manifest.get("sachnummer")
    name = manifest.get("bauteil")
    if (not isinstance(profile, str) or not profile
            or len(profile) > 80
            or not all(c.isalnum() or c in "_-" for c in profile)
            or not isinstance(part, str) or not part.strip()
            or len(part) > 120 or any(ord(c) < 32 for c in part)
            or not isinstance(name, str) or not name.strip()
            or len(name) > 100 or any(ord(c) < 32 for c in name)):
        raise ValueError("Projektidentität im Paket ist ungültig.")
    return ProjectPackageIdentity(profile, part, name)


def _tables(con) -> set[str]:
    return {
        row[0] for row in con.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='main' AND table_type='BASE TABLE'"
        ).fetchall()
    }


def _retain(con, table: str, column: str, values: set[str], available: set[str]) -> None:
    if table not in available:
        return
    if not _IDENTIFIER.fullmatch(table) or not _IDENTIFIER.fullmatch(column):
        raise ValueError("Ungültiger Tabellenname im Export.")
    if not values:
        con.execute(f'DELETE FROM "{table}"')
        return
    ordered = sorted(values)
    marks = ",".join("?" for _ in ordered)
    con.execute(
        f'DELETE FROM "{table}" WHERE "{column}" NOT IN ({marks})',
        ordered,
    )


def _project_rows(con, table: str, profile: str, key: str, available: set[str]) -> None:
    if table in available:
        con.execute(
            f'DELETE FROM "{table}" WHERE profile_id <> ? OR part_key <> ?',
            [profile, key],
        )


def _scope_snapshot(database: Path, data_root: Path, profile: str, part: str) -> tuple[set[str], dict[str, set[str]], bool]:
    """Reduce all known mutable tables to the QEC cohort of one part number."""
    key = part_key(part)
    store = DuckDBStore(database)
    qec = QecWorkflowStore(store)
    qec_rows = qec.rows(data_root / "qec")
    targeted = [row for row in qec_rows if part_key(row["part_number"]) == key]
    target_sources = {row["source_sha256"] for row in targeted}
    case_ids = {str(x["case_id"]) for x in targeted}
    fins = {str(x["fin"]).upper() for x in targeted}
    references = {str(x["reference"]) for x in targeted if x["reference"]}
    shared_source = any(
        row["source_sha256"] in target_sources and
        part_key(row["part_number"]) != key
        for row in qec_rows
    )

    with duckdb.connect(str(database)) as con:
        available = _tables(con)
        unknown = available - SCOPED_TABLES
        for table in sorted(unknown):
            if not _IDENTIFIER.fullmatch(table):
                raise ValueError("Unerwartete Tabelle im Datenbestand.")
            if con.execute(f'SELECT EXISTS(SELECT 1 FROM "{table}" LIMIT 1)').fetchone()[0]:
                raise ValueError(
                    "Projekttransfer für neue Tabelle noch nicht definiert: " + table
                )
        projects = con.execute(
            "SELECT component_name,ecu_json FROM workflow_projects "
            "WHERE profile_id=? AND part_key=?",
            [profile, key],
        ).fetchone()
        if projects is None:
            raise ValueError("Bitte vorhandenen QEC-Bestand zuerst als Projekt übernehmen.")
        ecu_names = {str(x).upper() for x in json.loads(projects[1])}
        for case_id, fin, payload in con.execute(
            "SELECT case_id,vin,payload_json FROM case_snapshots"
        ).fetchall():
            try:
                obj = json.loads(payload)
            except (TypeError, ValueError):
                continue
            if part_key(str(obj.get("qec_part_number") or "")) == key:
                case_ids.add(case_id)
                fins.add(str(fin).upper())

        # Find report IDs before removing quicktests; all ECU, DTC and page
        # records are tied to these report IDs.
        report_ids: set[str] = set()
        if "quicktest_reports" in available and fins:
            report_ids = {
                str(report_id) for report_id, fin in con.execute(
                    "SELECT report_id,fin FROM quicktest_reports"
                ).fetchall() if str(fin).upper() in fins
            }
        if "quicktest_ecus" in available:
            for report_id, ecu_code, ecu_name in con.execute(
                "SELECT report_id,ecu_code,ecu_name FROM quicktest_ecus"
            ).fetchall():
                if report_id in report_ids:
                    ecu_names.update(
                        str(value).upper() for value in (ecu_code, ecu_name)
                        if value and str(value).strip()
                    )

        _project_rows(con, "workflow_projects", profile, key, available)
        if "workflow_progress" in available:
            con.execute(
                "DELETE FROM workflow_progress WHERE profile_id<>? OR "
                "regexp_replace(upper(part_number),'[^A-Z0-9]','','g')<>?",
                [profile, key],
            )
        _project_rows(con, "cluster_evidence_files", profile, key, available)
        _project_rows(con, "workflow_first_ai_packages", profile, key, available)
        _project_rows(con, "workflow_second_ai_exports", profile, key, available)
        _project_rows(con, "workflow_ssl_selection", profile, key, available)
        _project_rows(con, "workflow_source_activity", profile, key, available)
        _project_rows(con, "workflow_source_log", profile, key, available)
        _retain(con, "workflow_current_context", "profile_id", set(), available)

        package_ids = {
            str(x[0]) for x in con.execute(
                "SELECT paket_id FROM workflow_first_ai_packages"
            ).fetchall()
        } if "workflow_first_ai_packages" in available else set()
        _retain(con, "workflow_ai_rounds", "paket_id", package_ids, available)
        _retain(con, "chatgpt_export_mapping", "paket_id", package_ids, available)
        _retain(con, "chatgpt_imports", "paket_id", package_ids, available)
        analysis_ids = {
            str(row[0]) for row in con.execute(
                "SELECT analyse_id FROM chatgpt_imports"
            ).fetchall()
        } if "chatgpt_imports" in available else set()
        _retain(con, "chatgpt_cluster", "analyse_id", analysis_ids, available)
        _retain(con, "chatgpt_fallanalysen", "analyse_id", analysis_ids, available)
        _retain(con, "chatgpt_fallanalysen", "case_id", case_ids, available)
        _retain(con, "case_snapshots", "case_id", case_ids, available)
        _retain(con, "manual_changes", "case_id", case_ids, available)
        _retain(con, "confirmed_root_causes", "case_id", case_ids, available)
        _retain(con, "qec_workflow_decisions", "case_id", case_ids, available)
        _retain(con, "qec_cluster_handoff", "fin", fins, available)
        _retain(con, "quicktest_reports", "report_id", report_ids, available)
        for table in (
            "quicktest_sources", "quicktest_pages", "quicktest_ecus",
            "quicktest_dtcs", "quicktest_parameters",
        ):
            _retain(con, table, "report_id", report_ids, available)

        selected_shas: set[str] = set()
        selected_shas.update(target_sources)
        for table, column in (
            ("cluster_evidence_files", "sha256"),
            ("workflow_first_ai_packages", "sha256"),
            ("quicktest_sources", "artifact_sha256"),
        ):
            if table in available:
                selected_shas.update(
                    str(row[0]) for row in con.execute(
                        f'SELECT DISTINCT "{column}" FROM "{table}"'
                    ).fetchall()
                )

        # Only VIN-/reference-matched source rows. Whole shared QEC/TP source
        # files are retained as immutable originals, but unrelated parsed rows
        # are removed from the project DB.
        if "source_knowledge_rows" in available:
            rows = con.execute(
                "SELECT source_sha256,record_number,fin,reference "
                "FROM source_knowledge_rows"
            ).fetchall()
            keep = [
                (sha, num) for sha, num, fin, reference in rows
                if (
                    str(fin or "").upper() in fins
                    or (reference is not None and str(reference) in references)
                )
            ]
            if keep:
                con.execute(
                    "CREATE TEMP TABLE _keep_knowledge "
                    "(source_sha256 VARCHAR,record_number INTEGER)"
                )
                con.executemany("INSERT INTO _keep_knowledge VALUES (?,?)", keep)
                con.execute(
                    "DELETE FROM source_knowledge_rows r WHERE NOT EXISTS "
                    "(SELECT 1 FROM _keep_knowledge k WHERE "
                    "k.source_sha256=r.source_sha256 AND k.record_number=r.record_number)"
                )
                con.execute("DROP TABLE _keep_knowledge")
            else:
                con.execute("DELETE FROM source_knowledge_rows")
            selected_shas.update(
                str(row[0]) for row in con.execute(
                    "SELECT DISTINCT source_sha256 FROM source_knowledge_rows"
                ).fetchall()
            )
            for (ecu,) in con.execute(
                "SELECT DISTINCT json_extract_string(payload_json, '$.EcuNm') "
                "FROM source_knowledge_rows"
            ).fetchall():
                if ecu and str(ecu).strip():
                    ecu_names.add(str(ecu).strip().upper())
        if "source_knowledge_documents" in available:
            _retain(
                con, "source_knowledge_documents", "source_sha256",
                selected_shas, available,
            )
            con.execute(
                "UPDATE source_knowledge_documents d SET row_count=("
                "SELECT COUNT(*) FROM source_knowledge_rows r "
                "WHERE r.source_sha256=d.source_sha256)"
            )

        # Explicit per-case / per-FIN provenance can capture additional
        # diagnostic files without importing every raw source on the machine.
        if "source_artifacts" in available:
            for sha, payload in con.execute(
                "SELECT sha256,payload_json FROM source_artifacts"
            ).fetchall():
                artifact = SourceArtifact.model_validate_json(payload)
                if (
                    artifact.vin_hint and artifact.vin_hint.upper() in fins
                    or artifact.case_id_hint and artifact.case_id_hint in case_ids
                ):
                    selected_shas.add(str(sha))
        _retain(con, "source_artifacts", "sha256", selected_shas, available)
        _retain(con, "parse_runs", "artifact_sha256", selected_shas, available)
        ecu_names = {
            value for value in ecu_names if value and len(value) <= 48
        }
        for table in (
            "dtc_trigger_definitions", "ecu_change_records",
            "dtc_manual_review_marks",
        ):
            if table not in available:
                continue
            if not ecu_names:
                if con.execute(
                    f'SELECT EXISTS(SELECT 1 FROM "{table}" LIMIT 1)'
                ).fetchone()[0]:
                    raise ValueError(
                        "Relevante Steuergeräte fehlen. Bitte vor dem Export "
                        "in Projekteinstellungen die ECU-Liste festlegen."
                    )
                continue
            names = sorted(ecu_names)
            placeholders = ",".join("?" for _ in names)
            con.execute(
                f'DELETE FROM "{table}" WHERE upper(ecu) NOT IN ({placeholders})',
                names,
            )
        con.execute("CHECKPOINT")
    return fins, {"references": references, "shas": selected_shas, "cases": case_ids}, shared_source


def _stage_files(
    original_root: Path, project_root: Path, source_db: Path,
    fins: set[str], references: set[str],
    *, progress: Callable[[int, str], None] | None = None,
) -> int:
    """Copy only referenced archive objects and FIN-scoped downloaded reports."""
    total = 0
    with duckdb.connect(str(source_db)) as con:
        rows = con.execute(
            "SELECT sha256,payload_json FROM source_artifacts"
        ).fetchall()
        for sha, payload in rows:
            artifact = SourceArtifact.model_validate_json(payload)
            path = _safe_file(original_root, Path(artifact.archived_path))
            relative = path.relative_to(original_root)
            if relative.parts[0] != "raw" or len(relative.parts) < 3:
                raise ValueError("Projekt-Quelldatei liegt außerhalb von raw/.")
            destination = project_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
            digest = sha256_file(destination)
            if digest != sha:
                raise ValueError("Quelldatei stimmt nicht mit dem gespeicherten SHA-256 überein.")
            modified = artifact.model_copy(update={
                "archived_path": str(destination),
            })
            con.execute(
                "UPDATE source_artifacts SET payload_json=? WHERE sha256=?",
                [modified.model_dump_json(), sha],
            )
            total += 1
            if progress and total % 25 == 0:
                progress(25, f"{total} Rohbelege geprüft und kopiert")
    for folder in ("quicktests", "qec", "tips"):
        parent = original_root / folder
        if not parent.is_dir():
            continue
        if parent.is_symlink():
            raise ValueError("Quellenordner darf kein symbolischer Link sein.")
        for fin in fins:
            source = parent / fin
            if not source.is_dir() or source.is_symlink():
                continue
            for path in source.rglob("*"):
                if path.is_symlink():
                    raise ValueError("Symbolischer Link im Projektbericht.")
                if not path.is_file():
                    continue
                rel = path.relative_to(original_root)
                if folder == "qec":
                    nested = path.relative_to(source).parts
                    if (
                        len(nested) < 2 or not nested[0].startswith("ref_")
                        or nested[0][4:] not in references
                    ):
                        continue
                dest = project_root / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(_safe_file(original_root, path), dest)
                total += 1
                if progress and total % 25 == 0:
                    progress(30, f"{total} Projektdateien gesichert")
    return total


def export_project(
    data_dir: Path, destination: Path, profile_id: str, part_number: str,
    *, progress: Callable[[int, str], None] | None = None,
) -> ProjectExportResult:
    """Create a project-only package, without all other projects' database rows."""
    root, destination = Path(data_dir).absolute(), Path(destination).absolute()
    if (
        destination.suffix.lower() != PROJECT_EXTENSION
        or destination.exists() or destination.is_symlink()
        or destination.is_relative_to(root)
    ):
        raise ValueError("Projekt-ZIP außerhalb des Datenordners als neue .ntfproject speichern.")
    project = WorkflowProjectStore(DuckDBStore(root / DATABASE_NAME)).get(
        profile_id, part_number,
    )
    if project is None:
        raise ValueError("Projekt noch nicht angelegt. Altbestand zuerst übernehmen.")
    if progress:
        progress(3, "Projektdatenbank konsistent sichern")
    with tempfile.TemporaryDirectory(prefix="ntf-project-") as tmp:
        temp = Path(tmp)
        inner_root = temp / "filtered"
        inner_root.mkdir()
        snapshot = inner_root / DATABASE_NAME
        _snapshot_database(_safe_file(root, root / DATABASE_NAME), snapshot)
        if progress:
            progress(12, "Projektfälle und zugehörige FINs filtern")
        fins, keys, shared = _scope_snapshot(
            snapshot, root, profile_id, part_number,
        )
        if progress:
            progress(20, "Projektbezogene Rohbelege kopieren")
        _stage_files(
            root, inner_root, snapshot, fins, keys["references"], progress=progress,
        )
        backup = temp / INNER
        if progress:
            progress(40, "Projektarchiv schreiben und Prüfsummen bilden")
        export_portable_backup(
            inner_root, backup,
            progress=(lambda message: progress(55, message)) if progress else None,
        )
        if backup.stat().st_size > MAX_PROJECT_BYTES:
            raise ValueError("Projektpaket überschreitet 32 GiB.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, tempname = tempfile.mkstemp(
            prefix=".ntf-project-", suffix=".partial", dir=destination.parent,
        )
        os.close(fd)
        temporary = Path(tempname)
        try:
            if progress:
                progress(78, "Fertiges Projektpaket bündeln und prüfen")
            with ZipFile(temporary, "w", compression=ZIP_DEFLATED) as archive:
                entry = _write_member(archive, INNER, backup)
                manifest = {
                    "format": FORMAT, "version": VERSION,
                    "profil": project.profile_id,
                    "sachnummer": project.part_number,
                    "bauteil": project.component_name,
                    "erstellt_utc": datetime.now(timezone.utc).isoformat(),
                    "projektdatei": entry,
                    "qec_rohquelle_moeglicherweise_geteilt": shared,
                    "andere_projekt_tabellen_ausgeschlossen": True,
                    "encrypted": False,
                }
                archive.writestr(
                    MANIFEST, json.dumps(manifest, ensure_ascii=False, indent=2),
                )
            if destination.exists():
                raise FileExistsError("Die Ziel-Projektdatei existiert inzwischen.")
            os.replace(temporary, destination)
            if progress:
                progress(100, "Projektpaket vollständig erstellt")
        finally:
            temporary.unlink(missing_ok=True)
    return ProjectExportResult(
        destination, project.profile_id, project.part_number,
        len(keys["cases"]), len(fins),
        len(keys["shas"]), shared,
    )


def _unpack_project(source: Path, root: Path) -> tuple[dict, Path]:
    """Strict outer format plus integrity check; inner ZIP is checked separately."""
    if source.suffix.lower() != PROJECT_EXTENSION or source.is_symlink():
        raise ValueError("Bitte ein reguläres .ntfproject-Paket auswählen.")
    with ZipFile(source) as archive:
        names = archive.namelist()
        if len(names) != 2 or set(names) != {INNER, MANIFEST}:
            raise ValueError("Projektpaket enthält fehlende oder unerwartete Einträge.")
        for info in archive.infolist():
            _relative(info.filename)
            if info.is_dir() or info.file_size > MAX_PROJECT_BYTES:
                raise ValueError("Unzulässiger Projekteinsatz im Archiv.")
        if archive.getinfo(MANIFEST).file_size > 16 * 1024:
            raise ValueError("Projektmanifest zu groß.")
        manifest = json.loads(archive.read(MANIFEST))
        if not isinstance(manifest, dict) or manifest.get("format") != FORMAT or manifest.get("version") != VERSION:
            raise ValueError("Inkompatibles Projektpaket.")
        entry = manifest.get("projektdatei")
        if not isinstance(entry, dict) or entry.get("name") != INNER:
            raise ValueError("Ungültige Projektdatei im Manifest.")
        target = root / INNER
        digest = hashlib.sha256()
        count = 0
        with archive.open(INNER) as source_stream, target.open("wb") as out:
            while block := source_stream.read(_CHUNK):
                count += len(block)
                digest.update(block)
                if count > MAX_PROJECT_BYTES or count > entry.get("bytes", -1):
                    raise ValueError("Projektarchiv überschreitet angegebene Größe.")
                out.write(block)
        if count != entry.get("bytes") or digest.hexdigest() != entry.get("sha256"):
            raise ValueError("Projektdatei-Prüfsumme falsch.")
    return manifest, target


def import_project(
    source: Path, data_dir: Path,
    *, progress: Callable[[int, str], None] | None = None,
) -> ProjectImportResult:
    """Merge a new project into the local DuckDB; other projects stay intact.

    Repeated imports of an existing project are deliberately rejected. Future
    updates require an explicit, conflict-aware per-project replacement.
    """
    source, root = Path(source).absolute(), Path(data_dir).absolute()
    if root.is_symlink() or source.is_relative_to(root) or not source.is_file():
        raise ValueError("Projektpaket muss außerhalb des Datenordners liegen.")
    if progress:
        progress(2, "Projektpaket und Manifest prüfen")
    with tempfile.TemporaryDirectory(prefix="ntf-project-import-") as tmp:
        staging = Path(tmp)
        manifest, package = _unpack_project(source, staging)
        if progress:
            progress(20, "Originaldaten und Prüfsummen validieren")
        project_root = staging / "imported"
        restore_portable_backup(package, project_root)
        if progress:
            progress(45, "Projektidentität und lokale Konflikte prüfen")
        incoming_db = project_root / DATABASE_NAME
        profile = manifest.get("profil")
        part = manifest.get("sachnummer")
        incoming_project = WorkflowProjectStore(DuckDBStore(incoming_db)).get(
            profile, part,
        )
        if incoming_project is None or (
            incoming_project.profile_id != profile
            or incoming_project.part_number != part
        ):
            raise ValueError("Projektkonfiguration und Manifest widersprechen sich.")

        root.mkdir(parents=True, exist_ok=True)
        target_store = DuckDBStore(root / DATABASE_NAME)
        if WorkflowProjectStore(target_store).get(profile, part):
            raise ValueError(
                "Dieses Projekt existiert auf dem Ziel-PC bereits. "
                "Ein stilles Überschreiben/Zusammenführen ist nicht sicher."
            )

        # Optional evidence tables may not yet exist on a fresh PC.
        # Initialize only application-defined schemas, never execute DDL from
        # the imported package.
        from ntf_insight.reporting.chatgpt_exchange import ChatGPTAnalyseStore
        from ntf_insight.storage.cluster_evidence_store import ClusterEvidenceStore
        from ntf_insight.storage.dtc_review_store import DtcReviewStore
        from ntf_insight.storage.ml_feedback import MLFeedbackStore
        from ntf_insight.storage.quicktest_store import QuickTestStore
        from ntf_insight.storage.source_knowledge_store import SourceKnowledgeStore
        from ntf_insight.storage.workflow_ai_chain import WorkflowAIChainStore
        from ntf_insight.storage.workflow_progress import WorkflowProgressStore

        for store_type in (
            ChatGPTAnalyseStore, ClusterEvidenceStore, DtcReviewStore,
            QuickTestStore, SourceKnowledgeStore, WorkflowAIChainStore,
            WorkflowProgressStore, QecWorkflowStore,
        ):
            store_type(target_store)
        MLFeedbackStore(target_store.path)

        # Read the fully verified staged project and locate every file first.
        if progress:
            progress(55, "Projektdateien zuordnen und Konflikte prüfen")
        staged_files: list[tuple[Path, Path]] = []
        for folder in DATA_FOLDERS:
            source_folder = project_root / folder
            if not source_folder.is_dir():
                continue
            for path in source_folder.rglob("*"):
                if path.is_symlink():
                    raise ValueError("Symbolische Links im Projektbestand sind unzulässig.")
                if path.is_file():
                    relative = path.relative_to(project_root)
                    target = root / relative
                    _relative(relative.as_posix())
                    _safe_file(project_root, path)
                    current = target.parent
                    while current != root:
                        if current.is_symlink():
                            raise ValueError("Verknüpfter Zielordner ist nicht erlaubt.")
                        current = current.parent
                    if target.exists():
                        if target.is_symlink() or not target.is_file():
                            raise ValueError("Zielpfad eines Projektdokuments ist belegt.")
                        if (
                            sha256_file(target) != sha256_file(path)
                        ):
                            raise ValueError("Gleichnamiger lokaler Bericht hat anderen Inhalt.")
                    else:
                        staged_files.append((path, target))
        if progress:
            progress(70, f"{len(staged_files)} Projektdateien sicher übernehmen")
        copied: list[Path] = []
        try:
            for path, target in staged_files:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
                copied.append(target)

            if progress:
                progress(82, "Projekttabellen transaktional übernehmen")
            with duckdb.connect(str(target_store.path)) as con:
                con.execute(
                    f"ATTACH '{str(incoming_db).replace(chr(39), chr(39)*2)}' "
                    "AS project_source (READ_ONLY)"
                )
                con.execute("BEGIN TRANSACTION")
                try:
                    incoming_tables = {
                        name for (name,) in con.execute(
                            "SELECT table_name FROM information_schema.tables "
                            "WHERE table_catalog='project_source' "
                            "AND table_schema='main' AND table_type='BASE TABLE'"
                        ).fetchall()
                    }
                    target_tables = _tables(con)
                    for table in sorted(incoming_tables):
                        if table not in SCOPED_TABLES:
                            raise ValueError("Unbekannte Projekttabelle: " + table)
                        if table in {"workflow_current_context", "source_artifacts"}:
                            continue
                        rows = con.execute(
                            f'SELECT COUNT(*) FROM project_source.main."{table}"'
                        ).fetchone()[0]
                        if not rows:
                            continue
                        if table not in target_tables:
                            raise ValueError("Ziel-App kennt Projekttabelle nicht: " + table)
                        con.execute(f'SELECT * FROM main."{table}" LIMIT 0')
                        columns = [item[0] for item in con.description]
                        con.execute(
                            f'SELECT * FROM project_source.main."{table}" LIMIT 0'
                        )
                        other_cols = [item[0] for item in con.description]
                        if columns != other_cols or not all(
                            _IDENTIFIER.fullmatch(name) for name in columns
                        ):
                            raise ValueError("Tabellenschema ist nicht kompatibel.")
                        columns_info = con.execute(
                            f'PRAGMA table_info("{table}")'
                        ).fetchall()
                        primary = [
                            row[1] for row in sorted(
                                columns_info, key=lambda row: int(row[5])
                            ) if row[5]
                        ]
                        if primary:
                            join = " AND ".join(
                                f't."{column}"=i."{column}"'
                                for column in primary
                            )
                            differs = " OR ".join(
                                f't."{column}" IS DISTINCT FROM i."{column}"'
                                for column in columns
                            )
                            conflicting = con.execute(
                                f'SELECT EXISTS(SELECT 1 FROM main."{table}" t '
                                f'JOIN project_source.main."{table}" i ON {join} '
                                f'WHERE {differs} LIMIT 1)'
                            ).fetchone()[0]
                            if conflicting:
                                raise ValueError(
                                    "Projektimport würde vorhandene Daten verändern: "
                                    + table
                                )
                        con.execute(
                            f'INSERT INTO main."{table}" BY NAME '
                            f'SELECT * FROM project_source.main."{table}" '
                            f'ON CONFLICT DO NOTHING'
                        )
                    rows = con.execute(
                        "SELECT sha256,payload_json,source_type,original_name "
                        "FROM project_source.main.source_artifacts"
                    ).fetchall()
                    for sha, payload, source_type, original_name in rows:
                        artifact = SourceArtifact.model_validate_json(payload)
                        relative = Path(artifact.archived_path).relative_to(project_root)
                        if relative.parts[0] != "raw":
                            raise ValueError("Ungültiger Rohdatenpfad im Projekt.")
                        updated = artifact.model_copy(update={
                            "archived_path": str(root / relative),
                        })
                        con.execute(
                            "INSERT INTO source_artifacts "
                            "(sha256,source_type,original_name,payload_json) "
                            "VALUES (?,?,?,?) ON CONFLICT DO NOTHING",
                            [sha,source_type,original_name,updated.model_dump_json()],
                        )
                    con.execute("COMMIT")
                except Exception:
                    con.execute("ROLLBACK")
                    raise
                finally:
                    con.execute("DETACH project_source")
        except Exception:
            for target in copied:
                target.unlink(missing_ok=True)
            raise
        if progress:
            progress(95, "Übernahme prüfen und Abschluss vorbereiten")
        with duckdb.connect(str(incoming_db), read_only=True) as source_db:
            count = source_db.execute(
                "SELECT COUNT(*) FROM case_snapshots"
            ).fetchone()[0]
    if progress:
        progress(100, "Projektimport erfolgreich abgeschlossen")
    return ProjectImportResult(profile, part, count, len(staged_files))
