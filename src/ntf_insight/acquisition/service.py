"""Batch acquisition orchestrator independent from provider implementation."""

from __future__ import annotations

import tempfile
from pathlib import Path

from ntf_insight.acquisition.base import ReportProvider
from ntf_insight.acquisition.models import AcquisitionIssue, AcquisitionResult
from ntf_insight.ingestion.service import SourceImportService


class BatchAcquisitionService:
    def __init__(self, provider: ReportProvider, importer: SourceImportService) -> None:
        self.provider = provider
        self.importer = importer

    def acquire(self, vins: list[str]) -> AcquisitionResult:
        result = AcquisitionResult()
        with tempfile.TemporaryDirectory(prefix="ntf-insight-download-") as temp:
            work_dir = Path(temp)
            for vin in vins:
                try:
                    downloaded = self.provider.download_for_vin(vin, work_dir)
                    for item in downloaded:
                        artifact = self.importer.import_raw(
                            item.path,
                            source_type=item.source_type,
                            parser_name=None,
                            parser_version=None,
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
