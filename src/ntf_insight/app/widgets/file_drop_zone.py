"""Reusable local-file drag-and-drop zone."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QMimeData, Signal
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout


class FileDropZone(QFrame):
    files_dropped = Signal(list)

    def __init__(self) -> None:
        super().__init__(objectName="DropZone")
        self.setAcceptDrops(True)
        self.setMinimumHeight(112)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(4)

        title = QLabel("Dateien hierher ziehen", objectName="DropZoneTitle")
        hint = QLabel(
            "Mehrere Dateien sind möglich. Die ausgewählte Quellenart wird verwendet; "
            ".smr-d wird automatisch als SMR-D erkannt.",
            objectName="DropZoneHint",
        )
        hint.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(hint)

    @staticmethod
    def local_files(mime_data: QMimeData) -> list[Path]:
        if not mime_data.hasUrls():
            return []
        files: list[Path] = []
        for url in mime_data.urls():
            if not url.isLocalFile():
                continue
            path = Path(url.toLocalFile())
            if path.is_file():
                files.append(path)
        return files

    def _set_drag_active(self, active: bool) -> None:
        self.setProperty("dragActive", active)
        style = self.style()
        style.unpolish(self)
        style.polish(self)

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if self.local_files(event.mimeData()):
            event.acceptProposedAction()
            self._set_drag_active(True)
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if self.local_files(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self._set_drag_active(False)
        event.accept()

    def dropEvent(self, event) -> None:  # noqa: N802
        files = self.local_files(event.mimeData())
        self._set_drag_active(False)
        if not files:
            event.ignore()
            return
        event.acceptProposedAction()
        self.files_dropped.emit(files)
