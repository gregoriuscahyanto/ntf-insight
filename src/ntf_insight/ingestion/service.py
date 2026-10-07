"""High-level local source ingestion service.

This service archives and registers original files. Parsing is deliberately separate so
unsupported formats can still be preserved with full provenance.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from ntf_insight.ingestion.artifacts import RawArchive, SourceArtifact, SourceType
from ntf_insight.storage.duckdb_store import DuckDBStore


class SourceImportService:
    def __init__(self, raw_dir: Path, database_path: Path) -> None:
        self.archive = RawArchive(raw_dir)
        self.store = DuckDBStore(database_path)

    def import_raw(
        self,
        path: Path,
        source_type: SourceType,
        *,
        source_system: str | None = None,
        vin_hint: str | None = None,
        case_id_hint: str | None = None,
        remote_ref: str | None = None,
        report_date: datetime | None = None,
    ) -> SourceArtifact:
        artifact = self.archive.archive(
            path,
            source_type=source_type,
            source_system=source_system,
            vin_hint=vin_hint,
            case_id_hint=case_id_hint,
            remote_ref=remote_ref,
            report_date=report_date,
        )
        self.store.save_artifact(artifact)
        return artifact

    def list_artifacts(self) -> list[SourceArtifact]:
        return self.store.load_artifacts()
