"""Local bulk import of raw files and ZIP bundles into normalized case timelines.

Security and provenance:
- archives are never sent to GitHub or a remote endpoint;
- ZIP members are read without executing code, symlinks or traversing paths;
- only QEC (or uniquely matching persisted) cases anchor vehicle histories;
- missing/ambiguous FIN links remain unassigned, not silently fabricated;
- event IDs are deterministic, so repeated imports are idempotent.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import stat
import tempfile
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Callable, Iterable
from zipfile import ZipFile, is_zipfile

from ntf_insight.domain.case import NTFCase
from ntf_insight.domain.events import CaseEvent
from ntf_insight.ingestion.artifacts import SourceArtifact, SourceType
from ntf_insight.ingestion.parser_execution import ParserExecutionService
from ntf_insight.ingestion.real_source_parsers import (
    AutoExportParser,
    ParsedSource,
    QECWorkbookParser,
    QuickTestPdfParser,
)
from ntf_insight.ingestion.service import SourceImportService
from ntf_insight.ingestion.source_detection import detect_source_type


MAX_ZIP_MEMBERS = 1000
MAX_MEMBER_BYTES = 160 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 700 * 1024 * 1024
MAX_COMPRESSION_RATIO = 200


@dataclass
class ImportSummary:
    files_archived: int = 0
    files_parsed: int = 0
    files_pending: int = 0
    cases_created: int = 0
    events_linked: int = 0
    events_unassigned: int = 0
    duplicates: int = 0
    issues: list[str] = field(default_factory=list)
    source_counts: dict[str, int] = field(default_factory=dict)


def _quicktest_fingerprint(
    session,
    diagnostics,
    ecu_states,
) -> str:
    """Logical report identity, unaffected by PDF producer metadata/byte hashes."""
    payload = {
        "fin": session.vin,
        "timestamp": session.occurred_at.isoformat(),
        "mileage_km": session.mileage_km,
        "diagnostics": sorted(
            (
                event.ecu.strip().upper(),
                event.dtc_code.strip().upper(),
                event.status,
                event.occurrence_count,
                event.dtc_text,
                json.dumps(event.freeze_frame, sort_keys=True, ensure_ascii=False),
            )
            for event in diagnostics
        ),
        "ecu_states": sorted(
            (
                event.ecu.strip().upper(),
                event.hardware_version,
                event.software_version,
            )
            for event in ecu_states
        ),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _existing_quicktests(cases: list[NTFCase]) -> set[str]:
    signatures = set()
    for case in cases:
        for session in case.diagnostic_sessions:
            if session.label != "QuickTest PDF":
                continue
            signature = _quicktest_fingerprint(
                session,
                [
                    event for event in case.diagnostics
                    if event.session_id == session.session_id
                ],
                [
                    event for event in case.ecu_states
                    if event.session_id == session.session_id
                ],
            )
            signatures.add(signature)
    return signatures


class LocalBatchImporter:
    """Bulk archive + parse with deterministic local case updates."""

    def __init__(self, sources: SourceImportService) -> None:
        self.sources = sources
        self.execution = ParserExecutionService(sources.store)

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
                if suffix not in {".csv", ".pdf", ".xlsx", ".cdd", ".smr-d"}:
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
    ) -> ImportSummary:
        def progress(text: str) -> None:
            if on_progress is not None:
                on_progress(text)

        paths = [Path(path) for path in paths]
        from_zip = set()
        summary = ImportSummary()
        previously_archived = {artifact.sha256 for artifact in self.sources.list_artifacts()}
        with tempfile.TemporaryDirectory(prefix="ntf-source-import-") as temp:
            extracted = []
            zip_hashes = set()
            for path in paths:
                if path.suffix.casefold() != ".zip":
                    extracted.append(path)
                    continue
                progress("ZIP-Archiv prüfen …")
                self._validate_zip(path)
                package_artifact = self.sources.import_raw(
                    path, SourceType.OTHER, source_system=source_system
                )
                zip_hashes.add(package_artifact.sha256)
                if package_artifact.sha256 not in previously_archived:
                    summary.files_archived += 1
                zip_members = self._extract_zip(path, Path(temp) / package_artifact.sha256)
                extracted.extend(zip_members)
                from_zip.update(zip_members)

            progress("Originaldateien archivieren …")
            known = previously_archived | zip_hashes
            artifacts: list[SourceArtifact] = []
            processed = set()
            for path in extracted:
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
                label = str(source_type)
                summary.source_counts[label] = summary.source_counts.get(label, 0) + 1

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
                progress("QEC-Fälle einlesen …")
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
                        "repairs", "replacements", "software_events", "supplier_findings",
                    ):
                        ids = {event.event_id for event in getattr(prior, attr)}
                        for event in getattr(case, attr):
                            if event.event_id not in ids:
                                getattr(prior, attr).append(event)
                                ids.add(event.event_id)
                    if not prior.investigated_replacement_id:
                        prior.investigated_replacement_id = case.investigated_replacement_id

            case_fin: dict[str, list[NTFCase]] = defaultdict(list)
            for case in existing.values():
                case_fin[case.vin].append(case)
            allowed_fins = set(case_fin)

            seen_quicktests = _existing_quicktests(list(existing.values()))
            for artifact in others:
                suffix = Path(artifact.original_name).suffix.casefold()
                parser = None
                if artifact.source_type in {SourceType.SHORT_TEST, SourceType.WORKSHOP_HISTORY} and suffix == ".csv":
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
                    summary.issues.append(f"{artifact.original_name}: {type(exc).__name__}")
                    continue
                summary.files_parsed += 1
                summary.issues.extend(result.issues)
                if isinstance(parser, QuickTestPdfParser) and len(result.sessions) == 1:
                    fingerprint = _quicktest_fingerprint(
                        result.sessions[0], result.diagnostics, result.ecu_states
                    )
                    if fingerprint in seen_quicktests:
                        # Both original PDF artifacts remain archived. Identical
                        # diagnostic observations are not counted twice even if
                        # PDF producer metadata yields different byte-level hashes.
                        summary.duplicates += 1
                        continue
                    seen_quicktests.add(fingerprint)
                pending.append((artifact, result))

            for _, document in pending:
                for attr, events in (
                    ("diagnostic_sessions", document.sessions),
                    ("diagnostics", document.diagnostics),
                    ("ecu_states", document.ecu_states),
                    ("repairs", document.repairs),
                ):
                    for event in events:
                        case = self._case_for_event(event, case_fin, attr)
                        if case is None:
                            summary.events_unassigned += 1
                            continue
                        existing_ids = {
                            current.event_id for current in getattr(case, attr)
                        }
                        if event.event_id in existing_ids:
                            continue
                        getattr(case, attr).append(event)
                        summary.events_linked += 1

            progress("Verknüpfte Fälle dauerhaft speichern …")
            self.sources.store.save_cases(list(existing.values()))
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
