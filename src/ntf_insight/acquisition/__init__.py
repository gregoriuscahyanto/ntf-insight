"""Report acquisition abstractions for external diagnostic/field systems."""

from ntf_insight.acquisition.base import ReportProvider
from ntf_insight.acquisition.models import AcquisitionIssue, AcquisitionResult, DownloadedSource
from ntf_insight.acquisition.service import BatchAcquisitionService

__all__ = [
    "AcquisitionIssue",
    "AcquisitionResult",
    "BatchAcquisitionService",
    "DownloadedSource",
    "ReportProvider",
]
