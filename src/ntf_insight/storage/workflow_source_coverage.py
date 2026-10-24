"""Belastbare Quelle-/FIN-Fortschrittsdaten für die fünf Workflow-Schritte.

"lokal" = nachweislich vorhandene, referenzgeprüfte Download-/Archivdatei.
"geparst" = aktuelle Dateiprüfsumme mit persistiertem fachlichem Parsergebnis.
Eine erfolgreiche Portalsuche ist NICHT gleichbedeutend mit einem Download,
und ein Archivbeleg ist NICHT gleichbedeutend mit einem geparsten Datensatz.

QEC: Nenner QEC-Fall (FIN + Referenz). Diagnosis/TIPS: Nenner ausgewählte
FIN-Kohorte; Anzahl Dokumente im Portal im Voraus unbekannt.
TP/Celonis: Dokument- und Parse-Zähler, FIN-Zuordnung ggf. unbekannt.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from ntf_insight.acquisition.diagnosis_viewer import read_last_attempt
from ntf_insight.acquisition.qec_archive import local_qec_archive
from ntf_insight.acquisition.tips_archive import local_tips_cases
from ntf_insight.ingestion.artifacts import ParseStatus, sha256_file
from ntf_insight.ingestion.real_source_parsers import AutoExportParser, QuickTestPdfParser
from ntf_insight.ingestion.qec_json import QECJsonParser
from ntf_insight.ingestion.tips_json import TipsJsonParser
from ntf_insight.storage.cluster_evidence_store import EvidenceFile
from ntf_insight.storage.duckdb_store import DuckDBStore



@lru_cache(maxsize=8192)
def _hash_cached(path: str, size: int, mtime_ns: int) -> str:
    del size, mtime_ns  # Dateiidentität ist Teil des Cache-Schlüssels.
    return sha256_file(Path(path))


def _file_hash(path: Path) -> str | None:
    try:
        if path.is_symlink() or not path.is_file():
            return None
        stat = path.stat()
        return _hash_cached(str(path), stat.st_size, stat.st_mtime_ns)
    except OSError:
        return None


@dataclass(frozen=True)
class SourceCoverage:
    category: str
    total_cases: int | None
    downloaded_cases: int | None
    parsed_cases: int | None
    local_documents: int
    parsed_documents: int
    partial_documents: int = 0
    unsupported_parser: bool = False
    pending_paths: tuple[Path, ...] = ()
    missing_fins: tuple[str, ...] = ()
    missing_qec: tuple[tuple[str, str], ...] = ()
    case_label: str = "FINs"
    documents_label: str = "Dokumente"
    note: str = ""
    parsed_qec: frozenset[tuple[str, str]] = frozenset()

    @property
    def pending_documents(self) -> int:
        return max(0, self.local_documents - self.parsed_documents)

    @property
    def can_resume_parsing(self) -> bool:
        return not self.unsupported_parser and bool(self.pending_paths)

    def display(self) -> str:
        if self.unsupported_parser:
            docs = f"{self.local_documents} archiviert · Parser nicht verfügbar"
        else:
            docs = (
                f"{self.local_documents} {self.documents_label} lokal · "
                f"{self.parsed_documents} geparst"
            )
            if self.partial_documents:
                docs += f" ({self.partial_documents} mit Hinweisen)"
        if self.total_cases is None:
            coverage = f"{self.case_label}: nicht sicher zuordenbar"
        else:
            downloaded = "?" if self.downloaded_cases is None else str(self.downloaded_cases)
            parsed = "?" if self.parsed_cases is None else str(self.parsed_cases)
            coverage = (
                f"{self.case_label}: {downloaded}/{self.total_cases} "
                f"mit Dokument · {parsed}/{self.total_cases} geparst"
            )
        return docs + "\n" + coverage


def _persisted(store: DuckDBStore) -> tuple[dict[str, tuple[str, str]], dict]:
    """Index je SHA und Parser; gezählt nur mit persistiertem Ergebnis."""
    latest: dict[tuple[str, str], object] = {}
    for run in store.load_parse_runs():
        key = (run.artifact_sha256, run.parser_name)
        old = latest.get(key)
        if old is None or (run.completed_at or run.started_at) >= (
            old.completed_at or old.started_at
        ):
            latest[key] = run
    with store.connect() as con:
        quicktest_rows = con.execute(
            "SELECT s.artifact_sha256,r.fin FROM quicktest_sources s "
            "JOIN quicktest_reports r ON s.report_id=r.report_id"
        ).fetchall() if _has_table(con, "quicktest_reports") and _has_table(
            con, "quicktest_sources"
        ) else []
        document_rows = con.execute(
            "SELECT source_sha256,source_kind,metadata_json "
            "FROM source_knowledge_documents"
        ).fetchall() if _has_table(con, "source_knowledge_documents") else []
    quicktests = {
        str(sha): str(fin).upper() for sha, fin in quicktest_rows
    }
    documents = {}
    for sha, kind, metadata in document_rows:
        try:
            values = json.loads(metadata or "{}")
        except (TypeError, ValueError):
            values = {}
        documents[str(sha)] = (str(kind), values if isinstance(values, dict) else {})
    return latest, {"quicktests": quicktests, "documents": documents}


def _has_table(con, name: str) -> bool:
    return con.execute(
        "SELECT EXISTS(SELECT 1 FROM information_schema.tables "
        "WHERE table_schema='main' AND table_name=?)", [name],
    ).fetchone()[0]


def _was_parsed(
    sha: str | None, parser: type, kind: str,
    latest: dict, index: dict,
    *,
    fin: str = "", reference: str = "",
) -> tuple[bool, bool]:
    if not sha:
        return False, False
    run = latest.get((sha, parser.name))
    if (
        run is None or run.parser_version != parser.version
        or run.status not in (ParseStatus.SUCCESS, ParseStatus.PARTIAL)
    ):
        return False, False
    if kind == "quicktest":
        persisted = index["quicktests"].get(sha) == fin
    else:
        documented = index["documents"].get(sha)
        persisted = bool(documented and documented[0] == kind)
        if persisted and fin:
            persisted = str(documented[1].get("fin") or "").upper() == fin
        if persisted and reference:
            persisted = str(documented[1].get("reference") or "") == reference
    return persisted, (persisted and run.status == ParseStatus.PARTIAL)


def _download_file_for_qec(root: Path, fin: str, reference: str) -> Path | None:
    info = local_qec_archive(root, fin, reference)
    if info is None:
        return None
    path = info.folder / "qec.json"
    return path if path.is_file() and not path.is_symlink() else None


def _tp_sources(
    store: DuckDBStore, target_fins: set[str],
) -> dict[str, set[str]]:
    """Quelle und nachweislich geparste FINs (keine Schätzung anhand Dateinamen)."""
    if not target_fins:
        return {}
    if len(target_fins) > 10000:
        raise ValueError("Zu viele FINs für die Dokumentenabdeckung.")
    eligible = sorted(target_fins)
    placeholders = ",".join("?" for _ in eligible)
    with store.connect() as con:
        if not (
            _has_table(con, "source_knowledge_rows")
            and _has_table(con, "source_knowledge_documents")
        ):
            return {}
        rows = con.execute(
            "SELECT DISTINCT r.source_sha256,r.fin FROM source_knowledge_rows r "
            "JOIN source_knowledge_documents d ON d.source_sha256=r.source_sha256 "
            "WHERE d.source_kind='autoexport_rows' "
            "AND json_extract_string(d.metadata_json, '$.source_type')='tp_dashboard' "
            "AND (CASE WHEN length(trim(r.fin))=20 "
            "AND left(upper(trim(r.fin)),3)='MBC' "
            "THEN substr(upper(trim(r.fin)),4) ELSE upper(trim(r.fin)) END) "
            f"IN ({placeholders})",
            eligible,
        ).fetchall()
    by_sha: dict[str, set[str]] = {}
    for sha, raw_fin in rows:
        fin = str(raw_fin).strip().upper()
        if fin.startswith("MBC") and len(fin) == 20:
            fin = fin[3:]
        if fin in target_fins:
            by_sha.setdefault(str(sha), set()).add(fin)
    return by_sha


def get_workflow_coverage(
    store: DuckDBStore, data_dir: Path, qec_rows: list[dict],
    context_files: list[EvidenceFile] | tuple[EvidenceFile, ...] = (),
) -> dict[str, SourceCoverage]:
    """Einmalige Momentaufnahme für QEC, QuickTest, TIPS, TP und Celonis."""
    root = Path(data_dir)
    fins = {
        str(row.get("fin") or "").strip().upper() for row in qec_rows
    } - {""}
    latest, index = _persisted(store)
    result: dict[str, SourceCoverage] = {}
    evidence: dict[str, dict[str, EvidenceFile]] = {}
    for item in context_files:
        evidence.setdefault(item.category, {})[item.sha256] = item

    # QEC: Pro Fall eine FIN/Referenz; nur passgenaues lokales JSON
    # lässt sich mit dem aktuellen strukturierten Parser fortsetzen.
    cases = {
        (str(r.get("fin") or "").upper(), str(r.get("reference") or ""))
        for r in qec_rows if r.get("fin") and r.get("reference")
    }
    qec_local = 0
    qec_parsed = 0
    qec_partial = 0
    qec_pending: list[Path] = []
    qec_parsed_cases: set[tuple[str, str]] = set()
    qec_missing: list[tuple[str, str]] = []
    for fin, ref in sorted(cases):
        info = local_qec_archive(root / "qec", fin, ref)
        if info is None:
            qec_missing.append((fin, ref))
            continue
        qec_local += 1
        path = _download_file_for_qec(root / "qec", fin, ref)
        if path is None:  # altes Legacy-Format: erneut als JSON abrufen
            qec_missing.append((fin, ref))
            continue
        sha = _file_hash(path)
        success, partial = _was_parsed(
            sha, QECJsonParser, "qec_live_report",
            latest, index, fin=fin, reference=ref,
        )
        qec_parsed += int(success)
        if success:
            qec_parsed_cases.add((fin, ref))
        qec_partial += int(partial)
        if not success:
            qec_pending.append(path)
    result["qec"] = SourceCoverage(
        "qec", len(cases), qec_local, qec_parsed,
        qec_local, qec_parsed, qec_partial,
        pending_paths=tuple(qec_pending),
        missing_qec=tuple(qec_missing),
        case_label="QEC-Fälle",
        documents_label="Berichte",
        parsed_qec=frozenset(qec_parsed_cases),
    )

    # Diagnosis: echte PDFs, nicht nur Abrufstatus/Ordner. Portalanzahl
    # pro FIN kann vor dem Abruf nicht vorausgesetzt werden.
    quick_sources: dict[str, tuple[Path, str]] = {}
    for fin in sorted(fins):
        folder = root / "quicktests" / fin
        if folder.is_symlink() or not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.pdf")):
            sha = _file_hash(path)
            if sha:
                quick_sources.setdefault(sha, (path, fin))
    for sha, item in evidence.get("diagnosis_viewer", {}).items():
        if item.source_path.suffix.lower() != ".pdf":
            continue
        actual_sha = _file_hash(item.source_path)
        if actual_sha == sha:
            verified_fin = index["quicktests"].get(sha, "")
            # Nicht aus dem Dateinamen auf eine FIN schließen.
            quick_sources.setdefault(sha, (item.source_path, verified_fin))
    # Auch direkt über Datenquellen importierte QuickTests dürfen nicht
    # verschwinden, wenn der ursprüngliche Portalordner nicht mehr existiert.
    all_artifacts = {artifact.sha256: artifact for artifact in store.load_artifacts()}
    for sha, fin in index["quicktests"].items():
        if fin not in fins or sha in quick_sources:
            continue
        artifact = all_artifacts.get(sha)
        if artifact is None:
            continue
        path = Path(artifact.archived_path)
        if path.suffix.lower() == ".pdf" and _file_hash(path) == sha:
            quick_sources[sha] = (path, fin)
    quick_parsed: set[str] = set()
    quick_local_fins: set[str] = set()
    quick_pending: list[Path] = []
    quick_parsed_docs = 0
    quick_partial = 0
    for sha, (path, fin_hint) in quick_sources.items():
        verified_fin = index["quicktests"].get(sha, "")
        fin = verified_fin if verified_fin in fins else fin_hint
        if fin in fins:
            quick_local_fins.add(fin)
        success, partial = _was_parsed(
            sha, QuickTestPdfParser, "quicktest",
            latest, index, fin=fin,
        ) if fin in fins else (False, False)
        if success:
            quick_parsed_docs += 1
            quick_partial += int(partial)
            quick_parsed.add(fin)
        else:
            quick_pending.append(path)
    quick_missing = []
    for fin in sorted(fins):
        previous = read_last_attempt(root / "quicktests", fin)
        if previous is not None and previous.status in {
            "Erfolgreich", "Keine Quicktests"
        }:
            # Erfolgreiche Suche ohne Treffer zählt trotzdem nicht als Download.
            continue
        if fin not in quick_local_fins or (
            previous is not None and previous.status in {
                "Teilweise erfolgreich", "Abgebrochen", "Fehler",
            }
        ):
            quick_missing.append(fin)
    result["diagnosis_viewer"] = SourceCoverage(
        "diagnosis_viewer", len(fins), len(quick_local_fins),
        len(quick_parsed), len(quick_sources), quick_parsed_docs, quick_partial,
        pending_paths=tuple(quick_pending),
        missing_fins=tuple(quick_missing),
        note="Portalsitzungen pro FIN vorab unbekannt.",
    )

    # TIPS: Ein tips.json = ein heruntergeladener TIPS-Fallbericht, nicht
    # alle enthaltenen Anhänge. Fehlerhafte/teilweise Portalabrufe werden
    # trotz einzelner Berichtdateien erneut angeboten.
    tips_reports: dict[str, tuple[Path, str, str]] = {}
    for fin in sorted(fins):
        for path in local_tips_cases(root, fin):
            sha = _file_hash(path)
            if sha:
                tips_reports.setdefault(
                    sha, (path, fin, path.parent.name.removeprefix("fall_"))
                )
    for sha, item in evidence.get("tips_writer", {}).items():
        if item.source_path.suffix.lower() != ".json":
            continue  # TIPS-CSV muss gesondert über "Einlesen" importiert werden.
        if _file_hash(item.source_path) == sha and sha not in tips_reports:
            doc = index["documents"].get(sha)
            metadata = doc[1] if doc and doc[0] == "tips_live_case" else {}
            fin = str(metadata.get("fin") or "").upper()
            reference = str(metadata.get("reference") or "")
            tips_reports[sha] = (item.source_path, fin, reference)
    for sha, doc in index["documents"].items():
        if doc[0] != "tips_live_case" or sha in tips_reports:
            continue
        fin = str(doc[1].get("fin") or "").upper()
        if fin not in fins:
            continue
        artifact = all_artifacts.get(sha)
        if artifact:
            path = Path(artifact.archived_path)
            if path.suffix.lower() == ".json" and _file_hash(path) == sha:
                tips_reports[sha] = (
                    path, fin, str(doc[1].get("reference") or ""),
                )
    tips_pending: list[Path] = []
    tips_parsed_fins: set[str] = set()
    tips_parsed_docs = 0
    tips_partial = 0
    tips_local_fins: set[str] = set()
    for sha, (path, fin, reference) in tips_reports.items():
        if fin in fins:
            tips_local_fins.add(fin)
        success, partial = _was_parsed(
            sha, TipsJsonParser, "tips_live_case",
            latest, index, fin=fin, reference=reference,
        ) if fin in fins else (False, False)
        if success:
            tips_parsed_docs += 1
            tips_partial += int(partial)
            tips_parsed_fins.add(fin)
        else:
            tips_pending.append(path)
    tips_missing = []
    for fin in sorted(fins):
        state = root / "tips" / fin / "abrufstatus.json"
        status = None
        if state.is_file() and not state.is_symlink():
            try:
                data = json.loads(state.read_text(encoding="utf-8-sig"))
                if data.get("fin") == fin:
                    status = data.get("status")
            except (OSError, ValueError, TypeError, UnicodeError):
                pass
        if status in {"Erfolgreich", "Keine TIPS-Faelle"}:
            continue
        tips_missing.append(fin)
    result["tips_writer"] = SourceCoverage(
        "tips_writer", len(fins), len(tips_local_fins), len(tips_parsed_fins),
        len(tips_reports), tips_parsed_docs, tips_partial,
        pending_paths=tuple(tips_pending),
        missing_fins=tuple(tips_missing),
        documents_label="Fallberichte",
        note="TIPS-Anhänge sind zusätzliche, nicht automatisch geparste Dokumente.",
    )

    # TP: Originaldateien sind häufig große Sammel-CSV. Ihre bloße
    # Existenz beweist noch keine FIN-Zuordnung. Nur echte geparste
    # Provenienz-Zeilen liefern FIN-Abdeckung.
    tp_fin_sources = _tp_sources(store, fins)
    tp_documents = index["documents"]
    tp_selected: dict[str, Path] = {
        sha: entry.source_path
        for sha, entry in evidence.get("tp_dashboard", {}).items()
        if entry.source_path.is_file()
    }
    for sha in tp_fin_sources:
        artifact = all_artifacts.get(sha)
        if artifact:
            path = Path(artifact.archived_path)
            if path.is_file() and not path.is_symlink():
                tp_selected[sha] = path
    tp_done = 0
    tp_partial = 0
    tp_parsed_fins: set[str] = set()
    tp_pending: list[Path] = []
    for sha, path in tp_selected.items():
        documented = tp_documents.get(sha)
        correct = bool(
            documented and documented[0] == "autoexport_rows"
            and documented[1].get("source_type") == "tp_dashboard"
        )
        parsed, partial = _was_parsed(
            sha, AutoExportParser, "autoexport_rows", latest, index,
        ) if correct else (False, False)
        tp_done += int(parsed)
        if parsed:
            tp_parsed_fins.update(tp_fin_sources.get(sha, set()))
        tp_partial += int(partial)
        if not parsed and path.suffix.lower() == ".csv":
            tp_pending.append(path)
    result["tp_dashboard"] = SourceCoverage(
        "tp_dashboard", len(fins), None, len(tp_parsed_fins),
        len(tp_selected), tp_done, tp_partial,
        pending_paths=tuple(tp_pending),
        case_label="FINs",
        documents_label="CSV-Dateien",
        note="CSV-Dokumentzahl kann mehrere FINs enthalten; Downloadzahl im Portal unbekannt.",
    )

    # Celonis: Ohne strukturierten Celonis-Parser gibt es hier nur
    # einen belegten Archivbestand, keine erfundene Parse-/FIN-Abdeckung.
    celonis_files = evidence.get("celonis", {})
    result["celonis"] = SourceCoverage(
        "celonis", None, None, None,
        sum(1 for item in celonis_files.values() if item.source_path.is_file()),
        0, unsupported_parser=True,
        documents_label="Dateien",
        case_label="Fälle",
        note="Manuelle Originaldateien; strukturierter Parser noch nicht vorhanden.",
    )
    return result
