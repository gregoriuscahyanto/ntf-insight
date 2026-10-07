"""High-level local source ingestion service.

This service only archives and registers the original file. Parsing is deliberately separate
so unsupported formats can still be preserved with full provenance.
"""

from __future__ import annotations

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
        parser_name: str | None = None,
        parser_version: str | None = None,
    ) -> SourceArtifact:
        artifact = self.archive.archive(
            path,
            source_type=source_type,
            parser_name=parser_name,
            parser_version=parser_version,
        )
        self.store.save_artifact(artifact)
        return artifact

    def list_artifacts(self) -> list[SourceArtifact]:
        return self.store.load_artifacts()
