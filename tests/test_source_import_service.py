from ntf_insight.ingestion.artifacts import SourceType
from ntf_insight.ingestion.service import SourceImportService


def test_source_import_service_archives_and_registers_file(tmp_path) -> None:
    source = tmp_path / "input.smr-d"
    source.write_text("synthetic", encoding="utf-8")
    service = SourceImportService(tmp_path / "raw", tmp_path / "ntf.duckdb")

    artifact = service.import_raw(source, SourceType.SMR_D)
    loaded = service.list_artifacts()

    assert artifact.sha256
    assert len(loaded) == 1
    assert loaded[0].sha256 == artifact.sha256
    assert loaded[0].source_type == SourceType.SMR_D
