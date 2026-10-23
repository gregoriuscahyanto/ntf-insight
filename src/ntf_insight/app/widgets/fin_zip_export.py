"""ZIP-Export pro FIN: nutzt die bestehenden Checkboxen der Falltabelle."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from ntf_insight.reporting.fin_zip_export import FinZipResult, export_fin_zip


class FinZipExportWorker(QThread):
    progress = Signal(str)
    completed = Signal(object)

    def __init__(self, fins: list[str], data_dir: Path, destination: Path) -> None:
        super().__init__()
        self.fins = list(fins)
        self.data_dir = Path(data_dir)
        self.destination = Path(destination)

    def run(self) -> None:
        results: list[FinZipResult] = []
        for index, fin in enumerate(self.fins, 1):
            self.progress.emit(f"FIN-Export {index}/{len(self.fins)}: {fin} …")
            try:
                outcome = export_fin_zip(fin, self.data_dir, self.destination)
            except (OSError, RuntimeError, ValueError) as exc:
                # Continue the batch without publishing an incomplete ZIP.
                outcome = FinZipResult(fin, None, warnings=(f"Export fehlgeschlagen: {exc}",))
            results.append(outcome)
        self.completed.emit(results)


class FinZipExportPanel(QWidget):
    """One ZIP per unique FIN; selection is shared with QEC/QuickTest."""

    def __init__(
        self,
        data_dir: Path,
        all_fins: Callable[[], list[str]],
        selected_fins: Callable[[], list[str]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.data_dir = Path(data_dir)
        self.all_fins = all_fins
        self.selected_fins = selected_fins
        self.worker: FinZipExportWorker | None = None
        self._all_count = 0
        self._selected_count = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 8)
        layout.setSpacing(8)
        layout.addWidget(QLabel("ZIP-Export pro FIN", objectName="CardTitle"))

        controls = QHBoxLayout()
        self.all_button = QPushButton("Alle FINs als ZIP exportieren")
        self.all_button.setToolTip(
            "Erstellt für jede eindeutige FIN ein ZIP mit lokalen QuickTest-PDFs, "
            "QEC-Fall-JSONs und QEC-Befundungs-PDFs. Vorhandene TIPS-Dateien "
            "werden aus tips/<FIN>/ ergänzt."
        )
        self.all_button.clicked.connect(self._start_all)
        controls.addWidget(self.all_button)

        self.selected_button = QPushButton("Ausgewählte FINs als ZIP exportieren")
        self.selected_button.setToolTip(
            "Dieselben Fall-Checkboxen wie für QuickTest und QEC verwenden. "
            "Mehrere Fälle derselben FIN erzeugen nur eine ZIP-Datei."
        )
        self.selected_button.clicked.connect(self._start_selected)
        controls.addWidget(self.selected_button)
        controls.addStretch(1)
        layout.addLayout(controls)

        self.status = QLabel(
            "Jedes ZIP enthält nur lokal verfügbare Daten dieser FIN; "
            "fehlende Quellen werden im Export-Manifest ausgewiesen.",
            objectName="PageSubtitle",
        )
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.set_selection_count(0, 0)

    def set_selection_count(self, all_count: int, selected_count: int) -> None:
        self._all_count = all_count
        self._selected_count = selected_count
        idle = self.worker is None
        self.all_button.setEnabled(idle and all_count > 0)
        self.selected_button.setEnabled(idle and selected_count > 0)
        self.selected_button.setToolTip(
            f"{selected_count} ausgewählte eindeutige FIN(s) · "
            "Checkboxen bleiben beim Filtern und Sortieren erhalten."
        )

    def _start_all(self) -> None:
        self._start(self.all_fins())

    def _start_selected(self) -> None:
        self._start(self.selected_fins())

    def _start(self, fins: list[str]) -> None:
        if self.worker is not None or not fins:
            return
        default = Path.home() / "Documents"
        if not default.is_dir():
            default = Path.home()
        target = QFileDialog.getExistingDirectory(
            self, "Zielordner für FIN-ZIP-Export auswählen", str(default),
        )
        if not target:
            return
        # There must never be one combined all-FIN archive.
        self.worker = FinZipExportWorker(sorted(set(fins)), self.data_dir, Path(target))
        self.worker.progress.connect(self.status.setText)
        self.worker.completed.connect(self._completed)
        self.worker.finished.connect(self._finished)
        self.set_selection_count(self._all_count, self._selected_count)
        self.worker.start()

    def _completed(self, results: list[FinZipResult]) -> None:
        succeeded = [item for item in results if item.zip_path is not None]
        no_data = [item for item in results
                   if item.zip_path is None and any(
                       "Keine lokalen Quelldateien" in warning for warning in item.warnings
                   )]
        failed = len(results) - len(succeeded) - len(no_data)
        files = sum(item.file_count for item in succeeded)
        location = str(self.worker.destination) if self.worker else ""
        self.status.setText(
            f"FIN-ZIP-Export abgeschlossen: {len(succeeded)} ZIP(s) mit "
            f"{files} Quelldateien, {len(no_data)} FIN(s) ohne lokale Dateien, "
            f"{failed} Fehler. Speicherort: {location}"
        )
        self.status.setToolTip(
            "\n".join(
                f"{item.fin}: {item.zip_path.name if item.zip_path else 'kein ZIP'}"
                + (" · " + "; ".join(item.warnings) if item.warnings else "")
                for item in results
            )
        )

    def _finished(self) -> None:
        if self.worker is not None:
            self.worker.deleteLater()
            self.worker = None
        self.set_selection_count(self._all_count, self._selected_count)
