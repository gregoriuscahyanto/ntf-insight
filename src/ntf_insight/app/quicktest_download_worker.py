"""Non-blocking Edge QuickTest acquisition reused by the FIN/case analysis."""

from __future__ import annotations

from pathlib import Path
from threading import Event

from PySide6.QtCore import QThread, Signal

from ntf_insight.acquisition.credentials import LoginCredentials
from ntf_insight.acquisition.diagnosis_viewer import DiagnosisViewerDownloader


class DownloadWorker(QThread):
    progress = Signal(str)
    completed = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        fins: list[str],
        folder: Path,
        profile: Path,
        login: LoginCredentials | None = None,
        retry_recent: bool = False,
    ) -> None:
        super().__init__()
        self.fins = fins
        self.folder = folder
        self.profile = profile
        self.login = login
        self.retry_recent = retry_recent
        self.cancel = Event()

    def run(self) -> None:
        try:
            downloader = DiagnosisViewerDownloader(
                self.folder, self.profile,
                user_id=self.login.user_id if self.login else "",
                password=self.login.password if self.login else "",
                retry_recent=self.retry_recent,
            )
            results = downloader.run(
                self.fins, progress=self.progress.emit, cancel=self.cancel
            )
            self.completed.emit(results)
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            self.login = None
