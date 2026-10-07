from pathlib import Path

from ntf_insight.acquisition.models import DownloadedSource
from ntf_insight.acquisition.service import BatchAcquisitionService
from ntf_insight.ingestion.artifacts import SourceType
from ntf_insight.ingestion.service import SourceImportService


class FakeProvider:
    name = "fake"

    def download_for_vin(self, vin: str, work_dir: Path) -> list[DownloadedSource]:
        if vin == "FAIL":
            raise RuntimeError("synthetic failure")
        path = work_dir / f"{vin}.txt"
        path.write_text(f"report for {vin}", encoding="utf-8")
        return [DownloadedSource(path=path, source_type=SourceType.SHORT_TEST)]


def test_batch_acquisition_archives_successes_and_collects_failures(tmp_path) -> None:
    importer = SourceImportService(tmp_path / "raw", tmp_path / "ntf.duckdb")
    service = BatchAcquisitionService(FakeProvider(), importer)

    result = service.acquire(["VIN1", "FAIL", "VIN2"])

    assert len(result.artifacts) == 2
    assert len(result.issues) == 1
    assert result.issues[0].vin == "FAIL"
    assert len(importer.list_artifacts()) == 2
