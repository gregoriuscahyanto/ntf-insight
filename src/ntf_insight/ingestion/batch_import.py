"""Local bulk import of raw files and ZIP bundles into normalized case timelines.

Security and provenance:
- archives are never sent to GitHub or a remote endpoint;
- ZIP members are read without executing code, symlinks or traversing paths;
- only QEC (or uniquely matching persisted) cases anchor vehicle histories;
- missing/ambiguous FIN links remain unassigned, not silently fabricated;
- event IDs are deterministic, so repeated imports are idempotent.
"""
from __future__ import annotations

import shutil
import stat
import tempfile
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Callable, Iterable
from zipfile import ZipFile, is_zipfile

from ntf_insight.domain.case import NTFCase
from ntf_insight.domain.events import CaseEvent
from ntf_insight.ingestion.artifacts import (
    ParseRun, ParseStatus, SourceArtifact, SourceType, sha256_file,
)
from ntf_insight.ingestion.parser_execution import ParserExecutionService
from ntf_insight.ingestion.failed_quicktests import find_failed_quicktest_artifacts
from ntf_insight.ingestion.real_source_parsers import (
    AutoExportParser,
    ParsedSource,
    QECWorkbookParser,
    QuickTestPdfParser,
)
from ntf_insight.ingestion.reference_source_parsers import (
    AutoExportSummaryParser,
    CandelaParser,
    PartHistoryParser,
    QECDetailsParser,
    SupplierAnalysisDocumentParser,
    iter_autoexport_rows,
)
from ntf_insight.ingestion.service import SourceImportService
from ntf_insight.ingestion.source_detection import detect_source_type
from ntf_insight.ingestion.qec_json import QECJsonParser
from ntf_insight.ingestion.tips_json import TipsJsonParser
from ntf_insight.ingestion.fin_zip_import import is_fin_export, prepare_fin_export, install_fin_export
from ntf_insight.ingestion.qec_primary import validate_single_qec_list
from ntf_insight.storage.quicktest_store import QuickTestStore
from ntf_insight.storage.source_knowledge_store import SourceKnowledgeStore


MAX_ZIP_MEMBERS = 1000
MAX_MEMBER_BYTES = 160 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 700 * 1024 * 1024
MAX_COMPRESSION_RATIO = 200


@dataclass
class ImportSummary:
    files_archived: int = 0
    files_parsed: int = 0
    selected_failed_quicktests: int = 0
    remaining_failed_quicktests: int | None = None
    files_pending: int = 0
    files_unchanged: int = 0
    files_failed: int = 0
    cancelled: bool = False
    cases_created: int = 0
    qec_findings_linked: int = 0
    qec_findings_conflicted: int = 0
    events_linked: int = 0
    events_unassigned: int = 0
    rows_scanned: int = 0
    rows_skipped: int = 0
    rows_invalid: int = 0
    tips_linked: int = 0
    tips_unassigned: int = 0
    duplicates: int = 0
    quicktests_saved: int = 0
    fin_zips_imported: int = 0
    fin_files_installed: int = 0
    fin_file_conflicts: int = 0
    quicktests_without_case: int = 0
    reference_sources: int = 0
    reference_rows: int = 0
    issues: list[str] = field(default_factory=list)
    source_counts: dict[str, int] = field(default_factory=dict)


class LocalBatchImporter:
    """Bulk archive + parse with deterministic local case updates."""

    def __init__(self, sources: SourceImportService) -> None:
        self.sources = sources
        self.execution = ParserExecutionService(sources.store)
        self.quicktests = QuickTestStore(sources.store)
        self.knowledge = SourceKnowledgeStore(sources.store)

    def retry_failed_quicktests(
        self,
        on_progress: Callable[[str], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> ImportSummary:
        """Retry only stored failed/partial/non-persisted PDFs from the raw archive.

        This intentionally bypasses the complete quicktests/<FIN> directory
        search and the version-triggered reprocessing of successful v2 files.
        The regular, complete QuickTest import remains a separate action.
        """
        if on_progress:
            on_progress("Fehlerhafte QuickTests anhand der gespeicherten Parser-Läufe ermitteln …")
        failures = find_failed_quicktest_artifacts(self.sources)
        selected = len(failures)
        if not selected:
            if on_progress:
                on_progress("Keine bereits bekannten, nicht parsebaren QuickTest-PDFs vorhanden.")
            return ImportSummary(selected_failed_quicktests=0, remaining_failed_quicktests=0)

        verified: list[Path] = []
        damaged = 0
        for index, artifact in enumerate(failures, start=1):
            if should_cancel is not None and should_cancel():
                return ImportSummary(
                    cancelled=True, selected_failed_quicktests=selected,
                    remaining_failed_quicktests=selected,
                )
            # Check ONLY selected archive bytes; never inspect the entire
            # downloaded corpus, and never parse a modified archived original.
            path = Path(artifact.archived_path)
            if sha256_file(path) != artifact.sha256:
                damaged += 1
            else:
                verified.append(path)
            if on_progress and (index % 25 == 0 or index == selected):
                on_progress(
                    f"Nur Fehlerdateien: {index}/{selected} Archivprüfsummen geprüft …"
                )

        if not verified:
            result = ImportSummary(
                selected_failed_quicktests=selected, files_failed=damaged,
            )
        else:
            result = self.import_paths(
                verified,
                on_progress=on_progress,
                # The archive may still label an older failed detection as
                # OTHER. These files are known QuickTest parser attempts.
                forced_source_type=SourceType.SHORT_TEST,
                should_cancel=should_cancel,
            )
            result.selected_failed_quicktests = selected
            result.files_failed += damaged
        if damaged:
            result.issues.append(
                f"{damaged} archivierte QuickTest-Datei(en) wegen abweichender "
                "SHA-256-Prüfsumme nicht erneut eingelesen."
            )
        # Pure DB/archive metadata lookup: the user can immediately see how
        # many known parser problems remain, without scanning downloads.
        result.remaining_failed_quicktests = len(find_failed_quicktest_artifacts(self.sources))
        return result

    @staticmethod
    def _validate_zip(path: Path) -> None:
        if not is_zipfile(path):
            raise ValueError("Datei ist kein gültiges ZIP-Archiv.")
        with ZipFile(path) as package:
            members = [info for info in package.infolist() if not info.is_dir()]
            if len(members) > MAX_ZIP_MEMBERS:
                raise ValueError("ZIP enthält zu viele Dateien.")
            total = sum(info.file_size for info in members)
            if total > MAX_UNCOMPRESSED_BYTES:
                raise ValueError("ZIP überschreitet die zulässige entpackte Größe.")
            for info in members:
                raw = info.filename
                normalized = raw.replace("\\", "/")
                parts = PurePosixPath(normalized).parts
                if (
                    not parts
                    or raw.startswith(("/", "\\"))
                    or any(":" in part for part in parts)
                    or ".." in parts
                    or "\x00" in raw
                ):
                    raise ValueError("Unsicherer ZIP-Pfad erkannt.")
                mode = info.external_attr >> 16
                stem = Path(parts[-1]).stem.upper().split(".")[0]
                if stem in {"CON", "PRN", "AUX", "NUL"} or (
                    len(stem) == 4 and stem[:3] in {"COM", "LPT"} and stem[3:].isdigit()
                ):
                    raise ValueError("ZIP enthält einen reservierten Dateinamen.")
                if stat.S_IFMT(mode) == stat.S_IFLNK:
                    raise ValueError("ZIP enthält nicht unterstützte symbolische Links.")
                if info.file_size > MAX_MEMBER_BYTES:
                    raise ValueError("ZIP enthält eine zu große Einzeldatei.")
                ratio = info.file_size / max(info.compress_size, 1)
                if ratio > MAX_COMPRESSION_RATIO:
                    raise ValueError("ZIP weist eine verdächtige Kompressionsrate auf.")

    def _extract_zip(self, path: Path, target: Path) -> list[Path]:
        self._validate_zip(path)
        extracted = []
        with ZipFile(path) as package:
            for index, info in enumerate(package.infolist()):
                if info.is_dir():
                    continue
                suffix = Path(info.filename).suffix.lower()
                if suffix not in {".csv", ".pdf", ".xlsx", ".cdd", ".smr-d", ".json"}:
                    continue
                filename = Path(info.filename.replace("\\", "/")).name
                member_dir = target / str(index)
                member_dir.mkdir(parents=True, exist_ok=True)
                destination = member_dir / filename
                with package.open(info) as source, destination.open("wb") as output:
                    shutil.copyfileobj(source, output, length=1024 * 1024)
                extracted.append(destination)
        return extracted

    def import_paths(
        self,
        paths: Iterable[Path],
        on_progress: Callable[[str], None] | None = None,
        forced_source_type: SourceType | None = None,
        source_system: str | None = None,
        vin_hint: str | None = None,
        only_new: bool = False,
        local_kind: str | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> ImportSummary:
        def progress(text: str) -> None:
            if on_progress is not None:
                on_progress(text)

        paths = [Path(path) for path in paths]
        if only_new and local_kind not in {"quicktests", "qec"}:
            raise ValueError("Inkrementeller Import benötigt QuickTests oder QEC als Quellenart.")

        # Completed state is persisted in DuckDB and survives app restarts.
        # Failed files are also skipped when unchanged; a manual retry or
        # future parser-version bump explicitly retries them.
        already_done: set[str] = set()
        if only_new:
            expected_name, expected_version = (
                (QuickTestPdfParser.name, QuickTestPdfParser.version)
                if local_kind == "quicktests" else (QECJsonParser.name, QECJsonParser.version)
            )
            recent: dict[str, ParseRun] = {}
            for run in self.sources.store.load_parse_runs():
                if run.parser_name != expected_name or run.parser_version != expected_version:
                    continue
                previous = recent.get(run.artifact_sha256)
                if previous is None or (run.completed_at or run.started_at) >= (
                    previous.completed_at or previous.started_at
                ):
                    recent[run.artifact_sha256] = run
            if local_kind == "quicktests":
                with self.sources.store.connect() as connection:
                    persisted = {
                        row[0] for row in connection.execute(
                            "SELECT artifact_sha256 FROM quicktest_sources"
                        ).fetchall()
                    }
            else:
                persisted = {
                    document["source_sha256"]
                    for document in self.knowledge.documents()
                    if document["source_kind"] == "qec_live_report"
                }
            for sha, run in recent.items():
                if run.status == ParseStatus.FAILED or (
                    run.status in {ParseStatus.SUCCESS, ParseStatus.PARTIAL} and sha in persisted
                ):
                    already_done.add(sha)

        def stop_requested() -> bool:
            return should_cancel is not None and should_cancel()

        from_zip = set()
        summary = ImportSummary()
        previously_archived_items = self.sources.list_artifacts()
        previously_archived = {artifact.sha256 for artifact in previously_archived_items}
        archived_paths = {
            Path(artifact.archived_path).resolve(): artifact
            for artifact in previously_archived_items
        }
        with tempfile.TemporaryDirectory(prefix="ntf-source-import-") as temp:
            extracted = []
            zip_hashes = set()
            for path in paths:
                if path.suffix.casefold() != ".zip":
                    extracted.append(path)
                    continue
                progress("ZIP-Archiv prüfen …")
                self._validate_zip(path)
                # Validate ZIP members before persisting the ZIP itself.
                # No rejected second QEC-FIN cohort must pollute the archive.
                zip_digest = sha256_file(path)
                if is_fin_export(path):
                    plan = prepare_fin_export(path, Path(temp) / ("fin_" + zip_digest))
                    outcome = install_fin_export(plan, self.sources.archive.root.parent)
                    extracted.extend(outcome.quicktest_paths)
                    from_zip.update(outcome.quicktest_paths)
                    summary.fin_zips_imported += 1
                    summary.fin_files_installed += sum(outcome.counts.values())
                    summary.fin_file_conflicts += len(outcome.conflicts)
                    if outcome.conflicts:
                        summary.issues.append(
                            f"FIN {plan.fin}: {len(outcome.conflicts)} unterschiedliche QEC-/TIPS-Dateien "
                            "nicht überschrieben. Konflikte bitte im Zielverzeichnis prüfen."
                        )
                else:
                    zip_members = self._extract_zip(path, Path(temp) / zip_digest)
                    extracted.extend(zip_members)
                    from_zip.update(zip_members)

            # Validate primary QEC workbooks before any member is archived.
            validate_single_qec_list(extracted, previously_archived_items)
            for path in paths:
                if path.suffix.casefold() != ".zip":
                    continue
                package_artifact = self.sources.import_raw(
                    path, SourceType.OTHER, source_system=source_system
                )
                zip_hashes.add(package_artifact.sha256)
                if package_artifact.sha256 not in previously_archived:
                    summary.files_archived += 1
            progress("Originaldateien archivieren …")
            known = previously_archived | zip_hashes
            artifacts: list[SourceArtifact] = []
            processed = set()
            for position, path in enumerate(extracted, start=1):
                if stop_requested():
                    summary.cancelled = True
                    break
                if only_new:
                    digest = sha256_file(path)
                    if digest in previously_archived and digest in already_done:
                        summary.files_unchanged += 1
                        if position % 20 == 0 or position == len(extracted):
                            progress(
                                f"Dateien abgleichen ({position}/{len(extracted)}) · "
                                f"{summary.files_unchanged} unverändert übersprungen …"
                            )
                        continue
                progress(
                    f"Originaldateien archivieren ({position}/{len(extracted)}) · "
                    f"{summary.files_unchanged} unverändert übersprungen …"
                )
                try:
                    source_type = (
                        forced_source_type
                        if forced_source_type is not None and path not in from_zip
                        else detect_source_type(path)
                    )
                except Exception:
                    source_type = SourceType.OTHER
                    summary.issues.append(
                        "Eine Quelldatei konnte nicht automatisch erkannt werden; "
                        "sie wurde nur archiviert."
                    )
                archived_original = archived_paths.get(path.resolve())
                if archived_original is not None:
                    # Re-parse an existing raw file without overwriting its
                    # original filename, initial import timestamp or provenance.
                    artifact = archived_original.model_copy(
                        update={"source_type": source_type}
                    )
                    self.sources.store.save_artifact(artifact)
                else:
                    artifact = self.sources.import_raw(
                        path,
                        source_type,
                        source_system=source_system,
                        vin_hint=vin_hint if path not in from_zip else None,
                    )
                if artifact.sha256 in processed:
                    summary.duplicates += 1
                    continue
                processed.add(artifact.sha256)
                if artifact.sha256 not in known:
                    summary.files_archived += 1
                artifacts.append(artifact)
                if only_new and source_type == SourceType.OTHER:
                    # An already-downloaded file that cannot be recognized is a
                    # failed attempt, not a permanent infinite reparse candidate.
                    self.sources.store.save_parse_run(ParseRun(
                        artifact_sha256=artifact.sha256,
                        parser_name=expected_name,
                        parser_version=expected_version,
                        status=ParseStatus.FAILED,
                        started_at=datetime.now(timezone.utc),
                        completed_at=datetime.now(timezone.utc),
                        error_message="Dateiformat nicht als erwarteter Bericht erkannt.",
                    ))
                    summary.files_failed += 1
                label = str(source_type)
                summary.source_counts[label] = summary.source_counts.get(label, 0) + 1

            # Safe checkpoint: originals are durable; unparsed ones are retried
            # on the next scan. No canonical case data has been modified yet.
            if summary.cancelled:
                return summary

            # A second QEC FIN cohort must never enter the archive/database.
            validate_single_qec_list(
                [Path(artifact.archived_path) for artifact in artifacts],
                previously_archived_items,
            )

            # Case lists are applied before free-floating diagnostic/repair events.
            case_artifacts = [
                a for a in artifacts
                if a.source_type == SourceType.VEHICLE_CASE_LIST
                and a.original_name.lower().endswith(".xlsx")
            ]
            others = [a for a in artifacts if a not in case_artifacts]
            existing = {case.case_id: case for case in self.sources.store.load_cases()}
            pending: list[tuple[SourceArtifact, ParsedSource]] = []
            for artifact in case_artifacts:
                if stop_requested():
                    summary.cancelled = True
                    break
                progress("QEC-Fälle und SSL-Endbefunde einlesen …")
                # First archive all original Excel fields. A 'Schadteile'
                # export without FIN is a valid reference-only source, but
                # MUST NOT be parsed into invented vehicle cases.
                detail = None
                try:
                    detail, _ = self.execution.execute(
                        artifact, QECDetailsParser()
                    )
                    summary.reference_rows += self.knowledge.save_records(
                        artifact.sha256, detail.kind, detail.records,
                        metadata=detail.metadata,
                    )
                    summary.reference_sources += 1
                    summary.issues.extend(detail.issues)
                except Exception as exc:
                    summary.issues.append(
                        "QEC-Zusatzfelder konnten nicht gespeichert werden: "
                        f"{type(exc).__name__}"
                    )
                sheets = (detail.metadata.get("sheets", {}) if detail else {})
                supplement = sheets.get("Schadteile", {})
                supplement_headers = set(supplement.get("columns", ()))
                if (
                    not any(
                        {"Referenznr.", "FIN", "Rep.-Datum"} <=
                        set(info.get("columns", ()))
                        for info in sheets.values()
                    )
                    and {
                        "Referenznr.", "SSL Endbefund",
                        "SSL-Endbefund Benennung",
                    } <= supplement_headers
                ):
                    summary.files_parsed += 1
                    # Records will enrich known cases by matching only QEC
                    # reference; import order is irrelevant (see below).
                    continue
                parser = QECWorkbookParser(artifact.sha256)
                try:
                    result, _ = self.execution.execute(artifact, parser)
                except Exception as exc:
                    summary.issues.append(f"{artifact.original_name}: {type(exc).__name__}")
                    continue
                summary.files_parsed += 1
                summary.issues.extend(result.issues)
                for case in result.cases:
                    prior = existing.get(case.case_id)
                    if prior is None:
                        existing[case.case_id] = case
                        summary.cases_created += 1
                        continue
                    if prior.vin != case.vin:
                        summary.issues.append("Gleiche Fall-ID mit widersprüchlicher FIN; Fall übersprungen.")
                        continue
                    # Imported cases can be re-imported. An existing case and
                    # manually corrected events take precedence.
                    for attr in (
                        "diagnostic_sessions", "diagnostics", "ecu_states",
                        "repairs", "tips_observations", "replacements",
                        "software_events", "supplier_findings",
                    ):
                        ids = {event.event_id for event in getattr(prior, attr)}
                        for event in getattr(case, attr):
                            if event.event_id not in ids:
                                getattr(prior, attr).append(event)
                                ids.add(event.event_id)
                    if not prior.investigated_replacement_id:
                        prior.investigated_replacement_id = case.investigated_replacement_id
                    # SSL findings are post-case reference labels, not inferred
                    # diagnostic observations. Preserve original QEC wording even
                    # when its completion date was absent.
                    if (
                        getattr(case, "qec_ssl_end_finding", None)
                        and not getattr(prior, "qec_ssl_end_finding", None)
                    ):
                        prior.qec_ssl_end_finding = case.qec_ssl_end_finding
                        prior.qec_ssl_end_date = getattr(case, "qec_ssl_end_date", None)

            # SSL-only QEC exports lack FINs but carry real 'Referenznr.'.
            # Join against already imported, FIN-identified QEC cases.
            # Also revisit previously archived QEC details on EVERY import so
            # uploading the two exports in either order works identically.
            ssl_by_reference, ambiguous_ssl_refs = (
                self.knowledge.qec_ssl_findings_by_reference()
            )
            for case in existing.values():
                reference = str(getattr(case, "qec_reference", "") or "").strip()
                if not reference:
                    continue
                if reference in ambiguous_ssl_refs:
                    summary.qec_findings_conflicted += 1
                    continue
                entry = ssl_by_reference.get(reference)
                if entry is None:
                    continue
                case_part = str(getattr(case, "qec_part_number", "") or "").strip()
                other_part = entry["part_number"]
                if case_part and other_part and case_part != other_part:
                    summary.qec_findings_conflicted += 1
                    continue
                previous_text = str(
                    getattr(case, "qec_ssl_end_finding", "") or ""
                ).strip()
                previous_code = str(
                    getattr(case, "qec_ssl_end_code", "") or ""
                ).strip()
                if (
                    previous_text and entry["finding"]
                    and previous_text != entry["finding"]
                ) or (
                    previous_code and entry["code"]
                    and previous_code != entry["code"]
                ):
                    summary.qec_findings_conflicted += 1
                    continue
                changed = False
                if not previous_text and entry["finding"]:
                    case.qec_ssl_end_finding = entry["finding"]
                    changed = True
                if not previous_code and entry["code"]:
                    case.qec_ssl_end_code = entry["code"]
                    changed = True
                # Only retain an actually supplied and parseable completion
                # date; do not turn the pump swap into a finding timestamp.
                if not getattr(case, "qec_ssl_end_date", None):
                    raw_date = entry["end_date"][:10]
                    try:
                        found_date = date.fromisoformat(raw_date).isoformat()
                    except ValueError:
                        found_date = ""
                    if found_date:
                        case.qec_ssl_end_date = found_date
                        changed = True
                if changed:
                    case.qec_ssl_end_source_ref = entry["source_ref"]
                    summary.qec_findings_linked += 1
            if summary.qec_findings_conflicted:
                summary.issues.append(
                    f"{summary.qec_findings_conflicted} QEC-Referenzen haben "
                    "widersprüchliche oder nicht passende Endbefunddaten. "
                    "Die bestehenden Fälle wurden dafür nicht verändert."
                )

            # Import order must not decide whether historical AutoExport data
            # reaches new QEC cases: revisit already archived CSVs when a new
            # investigated case was created. Original raw rows are retained;
            # never index the complete 423k-row source a second time merely
            # to attach matching FIN events to a newly added QEC case.
            replay_shas: set[str] = set()
            indexed_raw_shas = {
                doc["source_sha256"]
                for doc in self.knowledge.documents()
                if (
                    doc["source_kind"] == "autoexport_rows"
                    and doc["metadata"].get("raw_schema_version") == 2
                )
            }
            if summary.cases_created:
                current_shas = {artifact.sha256 for artifact in artifacts}
                for archived in previously_archived_items:
                    if (
                        archived.sha256 not in current_shas
                        and archived.source_type in {
                            SourceType.SHORT_TEST,
                            SourceType.TP_DASHBOARD,
                            SourceType.WORKSHOP_HISTORY,
                            SourceType.TIPS_CASE,
                        }
                        and Path(archived.original_name).suffix.casefold() == ".csv"
                    ):
                        others.append(archived)
                        replay_shas.add(archived.sha256)

            case_fin: dict[str, list[NTFCase]] = defaultdict(list)
            for case in existing.values():
                case_fin[case.vin].append(case)
            allowed_fins = set(case_fin)

            for artifact in others:
                if stop_requested():
                    summary.cancelled = True
                    break
                suffix = Path(artifact.original_name).suffix.casefold()
                # Global source knowledge is NOT a per-FIN diagnosis event.
                reference_parser = None
                if artifact.source_type == SourceType.QEC_REPORT and suffix == ".json":
                    reference_parser = QECJsonParser()
                elif artifact.source_type == SourceType.TIPS_CASE and suffix == ".json":
                    reference_parser = TipsJsonParser()
                elif artifact.source_type == SourceType.DIAGNOSTIC_DESCRIPTION and suffix == ".cdd":
                    reference_parser = CandelaParser()
                elif artifact.source_type == SourceType.PART_HISTORY and suffix == ".pdf":
                    reference_parser = PartHistoryParser()
                elif artifact.source_type == SourceType.SUPPLIER_FINDING and suffix == ".pdf":
                    reference_parser = SupplierAnalysisDocumentParser()
                elif artifact.source_type == SourceType.AUTOEXPORT_SUMMARY and suffix == ".csv":
                    reference_parser = AutoExportSummaryParser()
                if reference_parser is not None:
                    progress(f"Referenzquelle einlesen: {reference_parser.name} …")
                    try:
                        catalog, _ = self.execution.execute(
                            artifact, reference_parser
                        )
                        summary.reference_rows += self.knowledge.save_records(
                            artifact.sha256, catalog.kind, catalog.records,
                            metadata=catalog.metadata,
                        )
                        summary.reference_sources += 1
                        summary.files_parsed += 1
                        summary.issues.extend(catalog.issues)
                    except Exception as exc:
                        summary.files_failed += 1
                        summary.issues.append(
                            f"{artifact.original_name}: {type(exc).__name__}"
                        )
                    continue

                if artifact.source_type in {
                    SourceType.SHORT_TEST,
                            SourceType.TP_DASHBOARD, SourceType.WORKSHOP_HISTORY,
                    SourceType.TIPS_CASE,
                } and suffix == ".csv":
                    # Store all FINs, not only those with QEC. When QEC
                    # is uploaded later, previously indexed AutoExport CSVs
                    # are re-parsed for case association WITHOUT deleting and
                    # re-inserting the large immutable raw history.
                    if not (
                        artifact.sha256 in replay_shas
                        and artifact.sha256 in indexed_raw_shas
                    ):
                        try:
                            rows = iter_autoexport_rows(
                                Path(artifact.archived_path)
                            )
                            total = self.knowledge.save_records(
                                artifact.sha256, "autoexport_rows", rows,
                                metadata={
                                    "fin_independent": True,
                                    "raw_fields_preserved": True,
                                    "source_type": str(artifact.source_type),
                                    "raw_schema_version": 2,
                                },
                                # Handle the actual 423k-row diagnosis export.
                                maximum_rows=1_000_000,
                            )
                            summary.reference_rows += total
                            summary.reference_sources += 1
                        except Exception as exc:
                            # No false "parsed" state after incomplete archival.
                            summary.files_pending += 1
                            summary.issues.append(
                                "AutoExport-Rohzeilen konnten nicht vollstaendig "
                                f"gespeichert werden: {type(exc).__name__}. "
                                "Quelle bleibt archiviert und muss neu verarbeitet werden."
                            )
                            continue
                parser = None
                if artifact.source_type in {
                    SourceType.SHORT_TEST,
                            SourceType.TP_DASHBOARD, SourceType.WORKSHOP_HISTORY,
                    SourceType.TIPS_CASE,
                } and suffix == ".csv":
                    parser = AutoExportParser(
                        artifact.sha256, artifact.source_type, allowed_fins
                    )
                elif artifact.source_type == SourceType.SHORT_TEST and suffix == ".pdf":
                    parser = QuickTestPdfParser(artifact.sha256)

                if parser is None:
                    summary.files_pending += 1
                    continue
                progress(f"Lokale Quelle parsen ({summary.files_parsed + 1}/{len(artifacts)}) …")
                try:
                    result, _ = self.execution.execute(artifact, parser)
                except Exception as exc:
                    summary.files_failed += 1
                    summary.issues.append(f"{artifact.original_name}: {type(exc).__name__}")
                    continue
                summary.files_parsed += 1
                summary.issues.extend(result.issues)
                summary.rows_scanned += result.processed_rows
                summary.rows_skipped += result.skipped_rows
                summary.rows_invalid += result.invalid_rows
                if isinstance(parser, QuickTestPdfParser):
                    if result.quicktest_report is None:
                        self.sources.store.save_parse_run(ParseRun(
                            artifact_sha256=artifact.sha256,
                            parser_name=parser.name,
                            parser_version=parser.version,
                            status=ParseStatus.FAILED,
                            started_at=datetime.now(timezone.utc),
                            completed_at=datetime.now(timezone.utc),
                            error_message="QuickTest ohne vollständig extrahierbaren Bericht.",
                        ))
                        summary.files_failed += 1
                        summary.issues.append(
                            f"{artifact.original_name}: QuickTest ohne vollständige Extraktion."
                        )
                        continue
                    created = self.quicktests.save_report(
                        result.quicktest_report, artifact.sha256
                    )
                    if created:
                        summary.quicktests_saved += 1
                    else:
                        summary.duplicates += 1
                    # Vehicle diagnostics always persist under the report's own FIN,
                    # even when no QEC case/replacement has been supplied yet.
                    continue
                pending.append((artifact, result))

            for _, document in pending:
                for attr, events in (
                    ("diagnostic_sessions", document.sessions),
                    ("diagnostics", document.diagnostics),
                    ("ecu_states", document.ecu_states),
                    ("repairs", document.repairs),
                    ("tips_observations", document.tips_observations),
                ):
                    for event in events:
                        if attr == "tips_observations" and event.tips_case_id:
                            # A human-reviewed link must win over automated
                            # replay of the same TIPS episode into another QEC.
                            already_linked = any(
                                candidate.vin == event.vin
                                and any(
                                    linked.tips_case_id == event.tips_case_id
                                    and linked.occurred_at.date()
                                    == event.occurred_at.date()
                                    for linked in candidate.tips_observations
                                )
                                for candidate in existing.values()
                            )
                            if already_linked:
                                continue
                        case = self._case_for_event(event, case_fin, attr)
                        if case is None:
                            summary.events_unassigned += 1
                            if attr == "tips_observations":
                                summary.tips_unassigned += 1
                            continue
                        existing_ids = {
                            current.event_id for current in getattr(case, attr)
                        }
                        if event.event_id in existing_ids:
                            continue
                        getattr(case, attr).append(event)
                        summary.events_linked += 1
                        if attr == "tips_observations":
                            summary.tips_linked += 1

            # Associate FIN-scoped QuickTests with suitable cases as a *derived
            # projection*. This also picks up PDFs uploaded before their QEC case.
            # The independent report tables retain ALL tests even without a case.
            for report in self.quicktests.list_reports():
                if report["fin"] not in case_fin:
                    summary.quicktests_without_case += 1
                    continue
                sessions, diagnostics, ecu_states = self.quicktests.case_projection(
                    report["report_id"]
                )
                for attr, events in (
                    ("diagnostic_sessions", sessions),
                    ("diagnostics", diagnostics),
                    ("ecu_states", ecu_states),
                ):
                    for event in events:
                        case = self._case_for_event(event, case_fin, attr)
                        if case is None:
                            summary.events_unassigned += 1
                            continue
                        if any(
                            current.event_id == event.event_id
                            for current in getattr(case, attr)
                        ):
                            continue
                        getattr(case, attr).append(event)
                        summary.events_linked += 1

            # Count all independent raw TIPS records without a QEC association,
            # including FINs excluded from the normalized case-event parser.
            # This is a persistent coverage figure, not just this file batch.
            raw_tips = self.knowledge.count_rows("autoexport_tips")
            linked_tips_ids = {
                event.event_id
                for case in existing.values()
                for event in case.tips_observations
            }
            summary.tips_unassigned = max(0, raw_tips - len(linked_tips_ids))

            progress("Verknüpfte Fälle dauerhaft speichern …")
            self.sources.store.save_cases(list(existing.values()))
            if summary.quicktests_without_case:
                summary.issues.append(
                    f"{summary.quicktests_without_case} QuickTest(s) sind FIN-bezogen gespeichert "
                    "und warten auf einen passenden QEC-Fall. Sie sind im FIN-QuickTest-Explorer sichtbar."
                )
            if summary.events_unassigned:
                summary.issues.append(
                    f"{summary.events_unassigned} Datensätze blieben ohne eindeutige Fallzuordnung."
                )
            if zip_hashes:
                progress("ZIP-Import abgeschlossen.")
        return summary

    @staticmethod
    def _case_for_event(
        event: CaseEvent,
        cases_by_fin: dict[str, list[NTFCase]],
        attr: str,
    ) -> NTFCase | None:
        candidates = cases_by_fin.get(event.vin, [])
        if not candidates:
            return None

        # Even a FIN with only one QEC case can have many years of history.
        # Keep temporal context bounded to avoid unrelated fault episodes.
        if len(candidates) == 1:
            case = candidates[0]
            replacement = case.investigated_replacement()
            if replacement is None:
                return case
            days = (event.occurred_at - replacement.occurred_at).total_seconds() / 86400
            before, after = (365, 180) if attr != "repairs" else (30, 30)
            return case if -before <= days <= after else None

        # Match events on multi-case FINs only with a unique nearest replacement.
        # If equally near, do not silently attach to every unrelated claim.
        ranked = []
        for case in candidates:
            replacement = case.investigated_replacement()
            if replacement is None:
                continue
            delta_days = (event.occurred_at - replacement.occurred_at).total_seconds() / 86400
            max_before, max_after = (365, 180) if attr != "repairs" else (30, 30)
            if -max_before <= delta_days <= max_after:
                ranked.append((abs(delta_days), case.case_id, case))
        ranked.sort(key=lambda item: (item[0], item[1]))
        if not ranked:
            return None
        if len(ranked) > 1 and abs(ranked[0][0] - ranked[1][0]) < 0.5:
            return None
        return ranked[0][2]
