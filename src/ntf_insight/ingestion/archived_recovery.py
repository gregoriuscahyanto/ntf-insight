"""Repair previously archived QEC / TP exports after parser upgrades.

Archives are immutable and local. Re-import by the exact archived path retains
SHA-256 provenance and does not require users to upload files again.
"""
from __future__ import annotations

from pathlib import Path

from ntf_insight.ingestion.artifacts import SourceType
from ntf_insight.ingestion.qec_primary import active_qec_lists
from ntf_insight.ingestion.source_detection import detect_source_type
from ntf_insight.ingestion.service import SourceImportService
from ntf_insight.storage.source_knowledge_store import SourceKnowledgeStore


def recover_archived_qec_tp(raw_dir: Path, database_path: Path) -> int:
    """One-time repair when the primary QEC list or TP CSV was not processed.

    Existing imported cases are never dropped. Previously indexed TP data
    are not rewritten merely because the application was restarted.
    """
    source = SourceImportService(raw_dir, database_path)
    archived = source.list_artifacts()
    primaries = active_qec_lists(archived)
    if len(primaries) != 1:
        # Ambiguous legacy cohorts must be resolved by a person, not guessed.
        return 0

    from ntf_insight.ingestion.batch_import import LocalBatchImporter
    from ntf_insight.ingestion.real_source_parsers import QECWorkbookParser

    primary = primaries[0]
    cases = QECWorkbookParser(primary.sha256).parse(
        Path(primary.archived_path)
    ).cases
    if not cases:
        return 0
    known_cases = {case.case_id for case in source.store.load_cases()}
    expected_cases = {case.case_id for case in cases}
    pending: list[Path] = []
    if (
        not expected_cases.issubset(known_cases)
        or primary.source_type != SourceType.VEHICLE_CASE_LIST
    ):
        pending.append(Path(primary.archived_path))

    indexed_tp = {
        document["source_sha256"]
        for document in SourceKnowledgeStore(source.store).documents()
        if document["source_kind"] == "autoexport_rows"
        and document["metadata"].get("source_type") == SourceType.TP_DASHBOARD
    }
    for artifact in archived:
        path = Path(artifact.archived_path)
        if (
            path.suffix.casefold() == ".csv"
            and path.is_file()
            and detect_source_type(path) == SourceType.TP_DASHBOARD
            and (
                artifact.source_type != SourceType.TP_DASHBOARD
                or artifact.sha256 not in indexed_tp
            )
        ):
            pending.append(path)

    if pending:
        LocalBatchImporter(source).import_paths(pending)
    return len(pending)
