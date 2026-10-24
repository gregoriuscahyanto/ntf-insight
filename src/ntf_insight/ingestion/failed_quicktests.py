"""Gezielte Wiederholung zuvor fehlgeschlagener QuickTest-PDF-Importe.

Die Auswahl basiert AUSSCHLIESSLICH auf vorhandenen Parser-Laufprotokollen
und dem lokalen SHA-Archiv. Es werden weder quicktests/<FIN>/ durchsucht
noch erfolgreich persistierte v2-Berichte fuer v3 vorgemerkt.
"""
from __future__ import annotations

from pathlib import Path

from ntf_insight.ingestion.artifacts import ParseRun, ParseStatus, SourceArtifact, SourceType
from ntf_insight.ingestion.real_source_parsers import QuickTestPdfParser
from ntf_insight.ingestion.service import SourceImportService
from ntf_insight.storage.quicktest_store import QuickTestStore


def find_failed_quicktest_artifacts(
    sources: SourceImportService,
) -> list[SourceArtifact]:
    """Return only previously attempted, still-problematic QuickTest PDFs.

    - A successful and already stored v2/v3 result is never selected merely
      because the current parser has a newer version.
    - Failed/partial attempts and missing persistence are recoverable, also
      after a restart or when the old source type was OTHER.
    - Never select a merely downloaded, not-yet-imported PDF.
    - Source paths must point to existing regular files under the raw archive.
    """
    artifacts = sources.list_artifacts()
    if not artifacts:
        return []
    known = {a.sha256: a for a in artifacts if a.original_name.lower().endswith(".pdf")}
    if not known:
        return []

    latest: dict[str, ParseRun] = {}
    successful: set[str] = set()
    for run in sources.store.load_parse_runs():
        if run.parser_name != QuickTestPdfParser.name or run.artifact_sha256 not in known:
            continue
        if run.status == ParseStatus.SUCCESS:
            successful.add(run.artifact_sha256)
        old = latest.get(run.artifact_sha256)
        if old is None or (run.completed_at or run.started_at) >= (
            old.completed_at or old.started_at
        ):
            latest[run.artifact_sha256] = run
    if not latest:
        return []

    # QuickTestStore creates the tables even when this is the first retry.
    QuickTestStore(sources.store)
    with sources.store.connect() as con:
        persisted = {
            row[0] for row in con.execute(
                "SELECT artifact_sha256 FROM quicktest_sources"
            ).fetchall()
        }

    root = sources.archive.root.resolve()
    selected: list[SourceArtifact] = []
    for sha, run in latest.items():
        artifact = known[sha]
        if artifact.source_type not in {SourceType.SHORT_TEST, SourceType.OTHER}:
            continue
        # A successful v2 result that is already safely stored must not be
        # reprocessed here. PARTIAL remains an explicit parser problem.
        if sha in persisted and (sha in successful or run.status != ParseStatus.PARTIAL):
            continue
        # Missing persistence also needs repair even if a parser run was
        # marked successful before the storage transaction failed.
        path = Path(artifact.archived_path).absolute()
        if (
            not path.is_symlink()
            and path.is_file()
            and path.suffix.casefold() == ".pdf"
            and path.resolve().is_relative_to(root)
        ):
            selected.append(artifact)
    return sorted(selected, key=lambda a: a.sha256)
