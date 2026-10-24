"""Einheitlicher modaler Dialog für sichere lokale NTF-Exporte.

Der Dialog enthält bewusst keine Netzwerkfunktion und öffnet nach erfolgreichem
Schreiben nur den lokalen Zielordner. Restzeiten sind Schätzungen auf Basis
gemeldeter Arbeitseinheiten und bleiben bei unbekannter Gesamtmenge offen.
"""
from __future__ import annotations

import re
import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QHBoxLayout, QLabel, QProgressBar,
    QPushButton, QVBoxLayout, QWidget,
)


class ExportOperationDialog(QDialog):
    """Dieselbe schwebende Oberfläche für ZIP, Projekttransfer und ChatGPT."""

    start_requested = Signal(dict)

    def __init__(
        self, title: str, message: str, *,
        options: tuple[tuple[str, str, bool], ...] = (),
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("NTFExportOperationDialog")
        self.setWindowTitle(title)
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setWindowFlags(
            Qt.WindowType.Dialog | Qt.WindowType.CustomizeWindowHint
            | Qt.WindowType.WindowTitleHint
        )
        self.setMinimumWidth(540)
        self.resize(660, 275)
        self.setStyleSheet(
            "QDialog#NTFExportOperationDialog {"
            "background: #f5f7fa; border: 1px solid #aab7c2;"
            "border-radius: 12px; }"
            "QLabel#ExportDialogTitle { color: #0c243d;"
            "font-weight: bold; font-size: 17px; }"
            "QProgressBar { min-height: 15px; border-radius: 5px; }"
            "QCheckBox { spacing: 8px; }"
        )
        self._running = False
        self._started_at = 0.0
        self._units: tuple[int, int] | None = None
        self._destination: Path | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 20)
        layout.setSpacing(12)
        title_label = QLabel(title, objectName="ExportDialogTitle")
        layout.addWidget(title_label)
        self.status = QLabel(message)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.checkboxes: dict[str, QCheckBox] = {}
        for key, label, checked in options:
            checkbox = QCheckBox(label)
            checkbox.setObjectName("ExportOption_" + key)
            checkbox.setChecked(checked)
            checkbox.setToolTip(
                "Vertrauliche Originale/Freitexte sind nicht anonymisiert. "
                "Nur nach Unternehmensfreigabe weitergeben."
            )
            self.checkboxes[key] = checkbox
            layout.addWidget(checkbox)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        layout.addWidget(self.progress)
        self.time_label = QLabel("")
        self.time_label.setWordWrap(True)
        self.time_label.hide()
        layout.addWidget(self.time_label)
        self.destination_label = QLabel("")
        self.destination_label.setWordWrap(True)
        self.destination_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.destination_label.hide()
        layout.addWidget(self.destination_label)
        row = QHBoxLayout()
        row.addStretch()
        self.start_button = QPushButton("Datei wählen und Export starten")
        self.start_button.setObjectName("ExportStartAction")
        self.start_button.clicked.connect(self._request_start)
        self.start_button.setVisible(bool(options))
        row.addWidget(self.start_button)
        self.folder_button = QPushButton("Dateiordner öffnen")
        self.folder_button.setObjectName("ExportFolderAction")
        self.folder_button.hide()
        self.folder_button.clicked.connect(self.open_destination)
        row.addWidget(self.folder_button)
        self.close_button = QPushButton("Schließen")
        self.close_button.clicked.connect(self.reject)
        self.close_button.setVisible(bool(options))
        row.addWidget(self.close_button)
        layout.addLayout(row)
        self.clock = QTimer(self)
        self.clock.setInterval(1000)
        self.clock.timeout.connect(self._tick)

    def _request_start(self) -> None:
        self.start_requested.emit({
            key: checkbox.isChecked()
            for key, checkbox in self.checkboxes.items()
        })

    def begin(self, message: str = "") -> None:
        self._running = True
        self._started_at = time.monotonic()
        self._units = None
        self._destination = None
        self.start_button.hide()
        self.close_button.hide()
        self.folder_button.hide()
        for checkbox in self.checkboxes.values():
            checkbox.hide()
        self.progress.setRange(0, 0)
        self.progress.show()
        self.time_label.show()
        if message:
            self.status.setText(message)
        self._tick()
        self.clock.start()

    def _tick(self) -> None:
        if not self._running:
            return
        elapsed = max(0, int(time.monotonic() - self._started_at))
        estimate = "Restzeit noch nicht abschätzbar"
        if self._units is not None:
            done, total = self._units
            if 0 < done < total and elapsed >= 2:
                remaining = round(elapsed * (total - done) / done)
                estimate = f"geschätzt noch {remaining // 60} min {remaining % 60:02d} s"
            elif done == total:
                estimate = "Schreibvorgang wird abgeschlossen …"
        self.time_label.setText(
            f"Bisher {elapsed // 60} min {elapsed % 60:02d} s · {estimate}"
        )

    def setLabelText(self, message: str) -> None:  # noqa: N802
        self.status.setText(message)

    def labelText(self) -> str:  # noqa: N802
        return self.status.text()

    def setRange(self, low: int, high: int) -> None:  # noqa: N802
        self.progress.setRange(low, high)

    def setValue(self, value: int) -> None:  # noqa: N802
        self.progress.setValue(value)
        if self.progress.maximum() > 0:
            self._units = (value, self.progress.maximum())
        self._tick()

    def maximum(self) -> int:
        return self.progress.maximum()

    def value(self) -> int:
        return self.progress.value()

    def update_message(self, message: str) -> None:
        self.setLabelText(message)
        match = re.search(r"(\d+)\s*/\s*(\d+)", message)
        if match and int(match.group(2)) > 0:
            done, total = map(int, match.groups())
            self.setRange(0, total)
            self.setValue(min(done, total))
        elif self._units is None:
            # Ein nachgelagerter Text ohne Zählung darf die bereits bekannte
            # Gesamtmenge nicht wieder auf den Endlos-Spinner zurücksetzen.
            self.setRange(0, 0)
        self._tick()

    def _done(self) -> None:
        self._running = False
        self.clock.stop()
        self.progress.hide()
        self.time_label.hide()
        self.close_button.show()

    def complete(
        self, destination: Path | None, *,
        details: str = "",
    ) -> None:
        self._done()
        if destination is not None:
            destination = Path(destination)
            if not destination.is_file() or destination.stat().st_size <= 0:
                self.fail("Die exportierte Datei fehlt oder ist leer.")
                return
            self._destination = destination
            self.folder_button.show()
            self.destination_label.setText(
                f"Speicherort: {destination}\n"
                f"Dateigröße: {destination.stat().st_size:,} Byte"
            )
            self.destination_label.show()
        self.status.setText(
            "Vorgang erfolgreich abgeschlossen."
            + ("\n" + details if details else "")
        )

    def complete_directory(self, directory: Path, *, details: str = "") -> None:
        """Mehrere FIN-ZIPs: Ordner statt fiktiver einzelner ZIP-Datei öffnen."""
        directory = Path(directory)
        if not directory.is_dir():
            self.fail("Der Exportordner konnte nicht gefunden werden.")
            return
        self._done()
        self._destination = directory / "FIN-Exporte"
        self.folder_button.show()
        self.destination_label.setText(f"Speicherordner: {directory}")
        self.destination_label.show()
        self.status.setText(
            "Vorgang erfolgreich abgeschlossen."
            + ("\n" + details if details else "")
        )

    def fail(self, message: str) -> None:
        self._done()
        self._destination = None
        self.folder_button.hide()
        self.destination_label.hide()
        self.status.setText("Vorgang fehlgeschlagen:\n" + message)

    def open_destination(self) -> bool:
        if self._destination is None:
            return False
        return QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(self._destination.parent))
        )

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._running:
            event.ignore()
            return
        self.clock.stop()
        super().closeEvent(event)

    def reject(self) -> None:
        if not self._running:
            super().reject()
