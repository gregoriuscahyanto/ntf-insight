"""Provider interface for external report systems."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from ntf_insight.acquisition.models import DownloadedSource


class ReportProvider(Protocol):
    """Implemented later for each actual report source/API/browser workflow."""

    name: str

    def download_for_vin(self, vin: str, work_dir: Path) -> list[DownloadedSource]: ...
