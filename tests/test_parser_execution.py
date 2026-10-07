from pathlib import Path

import pytest

from ntf_insight.domain.reference import DTCTriggerDefinition
from ntf_insight.ingestion.artifacts import ParseStatus, SourceType
from ntf_insight.ingestion.models import ParsedDTCTriggerCatalog
from ntf_insight.ingestion.parser_execution import ParserExecutionService
from ntf_insight.ingestion.service import SourceImportService
from ntf_insight.storage.duckdb_store import DuckDBStore


class FakeParser:
    name = "fake-smr-d"
    version = "1.0"

    def parse(self, path: Path) -> ParsedDTCTriggerCatalog:
        assert path.exists()
        return ParsedDTCTriggerCatalog(
            definitions=[
                DTCTriggerDefinition(
                    definition_id="demo", ecu="CPC3", dtc_code="P1"
                )
            ]
        )


class FailingParser:
    name = "failing"
    version = "1.0"

    def parse(self, path: Path):
        raise ValueError("synthetic parse failure")


def test_parser_execution_records_success(tmp_path) -> None:
    source = tmp_path / "source.smr-d"
    source.write_text("synthetic", encoding="utf-8")
    importer = SourceImportService(tmp_path / "raw", tmp_path / "ntf.duckdb")
    artifact = importer.import_raw(source, SourceType.SMR_D)
    store = DuckDBStore(tmp_path / "ntf.duckdb")

    result, run = ParserExecutionService(store).execute(artifact, FakeParser())

    assert result.definitions
    assert run.status == ParseStatus.SUCCESS
    assert run.records_emitted == 1
    assert store.load_parse_runs(artifact.sha256)[0].parser_version == "1.0"


def test_parser_execution_records_failure_before_reraising(tmp_path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("synthetic", encoding="utf-8")
    importer = SourceImportService(tmp_path / "raw", tmp_path / "ntf.duckdb")
    artifact = importer.import_raw(source, SourceType.OTHER)
    store = DuckDBStore(tmp_path / "ntf.duckdb")

    with pytest.raises(ValueError, match="synthetic parse failure"):
        ParserExecutionService(store).execute(artifact, FailingParser())

    runs = store.load_parse_runs(artifact.sha256)
    assert runs[0].status == ParseStatus.FAILED
    assert "synthetic parse failure" in (runs[0].error_message or "")
