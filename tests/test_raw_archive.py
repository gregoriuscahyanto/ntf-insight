from ntf_insight.ingestion.artifacts import RawArchive, SourceType, sha256_file


def test_raw_archive_is_content_addressed_and_idempotent(tmp_path) -> None:
    source = tmp_path / "sample.smr-d"
    source.write_text("synthetic source data", encoding="utf-8")
    archive = RawArchive(tmp_path / "raw")

    first = archive.archive(source, SourceType.SMR_D)
    second = archive.archive(source, SourceType.SMR_D)

    assert first.sha256 == sha256_file(source)
    assert first.archived_path == second.archived_path
    assert (tmp_path / "raw" / first.sha256[:2]).exists()
