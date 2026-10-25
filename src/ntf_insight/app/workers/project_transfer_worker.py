"""Projekttransfer in eigenem Thread, ohne UI-Einfrieren."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal

from ntf_insight.ingestion.project_portable import export_project, import_project
from ntf_insight.ingestion.project_replacement import replace_existing_project


class ProjectTransferWorker(QThread):
    completed = Signal(object)
    failed = Signal(str)
    progress = Signal(int, str)

    def __init__(
        self, action: str, data_dir: Path, package: Path,
        *, profile: str = "", part_number: str = "",
        backup_path: Path | None = None,
    ) -> None:
        super().__init__()
        self.action = action
        self.data_dir = Path(data_dir)
        self.package = Path(package)
        self.profile = profile
        self.part_number = part_number
        self.backup_path = Path(backup_path) if backup_path is not None else None

    def run(self) -> None:
        try:
            if self.action == "export":
                result = export_project(
                    self.data_dir, self.package, self.profile, self.part_number,
                    progress=lambda percent, message: self.progress.emit(percent, message),
                )
            elif self.action == "import":
                result = import_project(
                    self.package, self.data_dir,
                    progress=lambda percent, message: self.progress.emit(percent, message),
                )
            elif self.action == "replace":
                if self.backup_path is None:
                    raise ValueError("Für den Projektersatz fehlt der Sicherungspfad.")
                result = replace_existing_project(
                    self.package, self.data_dir, self.backup_path,
                    progress=lambda percent, message: self.progress.emit(percent, message),
                )
            else:
                raise ValueError("Unbekannter Projekttransfer.")
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")
        else:
            self.completed.emit(result)
