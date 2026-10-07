"""Versioned parser execution with persisted provenance."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel

from ntf_insight.ingestion.artifacts import ParseRun, ParseStatus, SourceArtifact
from ntf_insight.storage.duckdb_store import DuckDBStore


class VersionedParser(Protocol):
    name: str
    version: str
    def parse(self, path: Path) -> BaseModel: ...


def _count_emitted_records(result: BaseModel) -> int:
    count = 0
    for field_name in type(result).model_fields:
        if field_name == "issues":
            continue
        value: Any = getattr(result, field_name)
        if isinstance(value, list):
            count += len(value)
    return count


class ParserExecutionService:
    def __init__(self, store: DuckDBStore) -> None:
        self.store = store

    def execute(
        self,
        artifact: SourceArtifact,
        parser: VersionedParser,
    ) -> tuple[BaseModel, ParseRun]:
        started = datetime.now(timezone.utc)
        try:
            result = parser.parse(Path(artifact.archived_path))
        except Exception as exc:
            run = ParseRun(
                artifact_sha256=artifact.sha256,
                parser_name=parser.name,
                parser_version=parser.version,
                status=ParseStatus.FAILED,
                started_at=started,
                completed_at=datetime.now(timezone.utc),
                error_message=str(exc),
            )
            self.store.save_parse_run(run)
            raise

        issues = getattr(result, "issues", [])
        status = ParseStatus.PARTIAL if issues else ParseStatus.SUCCESS
        run = ParseRun(
            artifact_sha256=artifact.sha256,
            parser_name=parser.name,
            parser_version=parser.version,
            status=status,
            started_at=started,
            completed_at=datetime.now(timezone.utc),
            records_emitted=_count_emitted_records(result),
            issue_count=len(issues),
        )
        self.store.save_parse_run(run)
        return result, run
