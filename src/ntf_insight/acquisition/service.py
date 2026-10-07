"""Batch acquisition orchestrator independent from provider implementation."""

from __future__ import annotations

import tempfile
from pathlib import Path

from ntf_insight.acquisition.base import ReportProvider
from ntf_insight.acquisition.models import AcquisitionIssue, AcquisitionResult
from ntf_insight.ingestion.service import SourceImportService


class BatchAcquisitionService:
    def __init__(
        self,
        provider: ReportProvider,
        importer: SourceImportService,
        work_root: Path | None = None,
    ) -> None:
        self.provider = provider
        self.importer = importer
        # Avoid the system TEMP directory on managed Windows clients where enterprise
        # policies may deny pytest/app access. Keep acquisition work beside the app data.
        self.work_root = work_root or (self.importer.archive.root.parent / "work")
        self.work_root.mkdir(parents=True, exist_ok=True)

    def acquire(self, vins: list[str]) -> AcquisitionResult:
        result = AcquisitionResult()
        with tempfile.TemporaryDirectory(
            prefix="ntf-insight-download-",
            dir=self.work_root,
        ) as temp:
            work_dir = Path(temp)
            for vin in vins:
                try:
                    downloaded = self.provider.download_for_vin(vin, work_dir)
                    for item in downloaded:
                        artifact = self.importer.import_raw(
                            item.path,
                            source_type=item.source_type,
                            source_system=self.provider.name,
                            vin_hint=vin,
                            remote_ref=item.remote_ref,
                        )
                        result.artifacts.append(artifact)
                except Exception as exc:
                    result.issues.append(
                        AcquisitionIssue(
                            vin=vin,
                            provider=self.provider.name,
                            message=str(exc),
                        )
                    )
        return result
