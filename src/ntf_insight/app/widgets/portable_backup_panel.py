"""Lokales Ein-Datei-Backup für einen bereits analysierten NTF-Insight-Stand."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QVBoxLayout, QWidget,
)

from ntf_insight.ingestion.portable_backup import (
    BACKUP_EXTENSION, export_portable_backup, restore_portable_backup,
)


class PortableTransferWorker(QThread):
    progress = Signal(str)
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, action: str, data_dir: Path, package: Path) -> None:
        super().__init__()
        self.action = action
        self.data_dir = Path(data_dir)
        self.package = Path(package)

    def run(self) -> None:
        try:
            if self.action == "export":
                result = export_portable_backup(
                    self.data_dir, self.package, progress=self.progress.emit,
                )
            elif self.action == "restore":
                result = restore_portable_backup(
                    self.package, self.data_dir,
                    replace_existing=True, progress=self.progress.emit,
                )
            else:
                raise ValueError("Ungültiger Datentransfer.")
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")
        else:
            self.completed.emit(result)


class PortableBackupPanel(QWidget):
    """Single-file export/import without re-parsing any source document."""

    restored = Signal(object)
    transfer_busy = Signal(bool)

    def __init__(self, data_dir: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.data_dir = Path(data_dir)
        self.worker: PortableTransferWorker | None = None
        self._guard: Callable[[], bool] | None = None
        self._pending_restore = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 8)
        layout.setSpacing(8)
        layout.addWidget(QLabel(
            "Gesamtdatenstand zwischen PCs übertragen", objectName="CardTitle",
        ))
        explanation = QLabel(
            "Eine .ntfbackup-Datei enthält die bereits ausgewertete DuckDB, "
            "Rohquellen, QuickTests, QEC- und TIPS-Dateien. "
            "Auf dem Ziel-PC werden keine Quellen erneut geparst. "
            "Vorhandene Daten werden nur nach Bestätigung ersetzt.",
            objectName="PageSubtitle",
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)

        row = QHBoxLayout()
        self.export_button = QPushButton("Gesamtstand als eine Datei exportieren")
        self.export_button.setToolTip(
            "Sichert Fallzuordnungen, QuickTest-Auswertung, manuelle Bewertungen "
            "und lokale Originaldateien zusammen."
        )
        self.export_button.clicked.connect(self._export)
        row.addWidget(self.export_button)

        self.restore_button = QPushButton("Gesamtstand aus Datei wiederherstellen")
        self.restore_button.setToolTip(
            "Übernimmt den ausgewerteten Bestand ohne erneutes PDF-/QEC-Parsen. "
            "Der vorhandene lokale Datenstand wird ersetzt."
        )
        self.restore_button.clicked.connect(self._restore)
        row.addWidget(self.restore_button)
        layout.addLayout(row)

        self.status = QLabel(
            "Das Paket ist nicht verschlüsselt. Nur über freigegebene, "
            "geschützte Unternehmensspeicher übertragen. "
            "SSO-Kennwörter und Edge-Browserprofile sind ausgeschlossen.",
            objectName="PageSubtitle",
        )
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

    def set_guard(self, guard: Callable[[], bool]) -> None:
        self._guard = guard

    def _can_start(self) -> bool:
        if self.worker is not None:
            return False
        if self._guard is not None and not self._guard():
            QMessageBox.warning(
                self, "Datentransfer nicht möglich",
                "Bitte zuerst alle QuickTest-/QEC-Downloads, "
                "FIN-ZIP-Exporte und Quellenimporte abschließen.",
            )
            return False
        return True

    def _export(self) -> None:
        if not self._can_start():
            return
        proposed = Path.home() / (
            "NTF-Insight-Gesamtstand-"
            + datetime.now().strftime("%Y%m%d-%H%M")
            + BACKUP_EXTENSION
        )
        filename, _ = QFileDialog.getSaveFileName(
            self, "Gesamtdatenstand als eine Datei sichern",
            str(proposed), "NTF-Insight-Datenpaket (*.ntfbackup)",
        )
        if not filename:
            return
        package = Path(filename)
        if package.suffix.lower() != BACKUP_EXTENSION:
            package = package.with_suffix(BACKUP_EXTENSION)
        self._start("export", package)

    def _restore(self) -> None:
        if not self._can_start():
            return
        filename, _ = QFileDialog.getOpenFileName(
            self, "Gesamtdatenstand von einem anderen PC auswählen",
            str(Path.home()), "NTF-Insight-Datenpaket (*.ntfbackup)",
        )
        if not filename:
            return
        answer = QMessageBox.question(
            self, "Gesamten NTF-Insight-Datenstand ersetzen?",
            "Die Datei enthält bereits ausgewertete Fahrzeug- und Befunddaten.\n\n"
            "Beim Wiederherstellen werden die bisherige lokale Datenbank "
            "und die vorhandenen QuickTest-/QEC-/TIPS-/Rohdatenordner vollständig "
            "durch den Inhalt des Pakets ersetzt. Es erfolgt kein Zusammenführen.\n\n"
            "Bitte einen bestehenden Datenstand vorher selbst als Paket sichern. "
            "Nur ein selbst erzeugtes, vertrauenswürdiges Paket verwenden.\n\n"
            "Wiederherstellung wirklich starten?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._start("restore", Path(filename))

    def _start(self, action: str, package: Path) -> None:
        self._pending_restore = None
        self.worker = PortableTransferWorker(action, self.data_dir, package)
        self.worker.progress.connect(self.status.setText)
        self.worker.completed.connect(self._completed)
        self.worker.failed.connect(self._failed)
        self.worker.finished.connect(self._finished)
        self.export_button.setEnabled(False)
        self.restore_button.setEnabled(False)
        self.status.setText(
            "Ausgewerteten Bestand sichern …" if action == "export"
            else "Paket prüfen und Daten wiederherstellen …"
        )
        self.transfer_busy.emit(True)
        self.worker.start()

    def _completed(self, result: object) -> None:
        if isinstance(result, object) and hasattr(result, "path"):
            self.status.setText(
                "Gesamtstand in einer Datei gesichert: "
                + result.path.name
                + ". Keine Browserprofile oder Anmeldedaten enthalten."
            )
        else:
            self._pending_restore = result
            self.status.setText(
                "Gesamtdatenstand vollständig wiederhergestellt. "
                "Die App lädt den Bestand jetzt ohne Neuparsen."
            )

    def _failed(self, message: str) -> None:
        self.status.setText(
            "Transfer fehlgeschlagen: " + message
            + " · Der bisherige Datenstand bleibt bei Prüfungsfehlern unverändert."
        )

    def _finished(self) -> None:
        worker, self.worker = self.worker, None
        if worker is not None:
            worker.deleteLater()
        self.export_button.setEnabled(True)
        self.restore_button.setEnabled(True)
        self.transfer_busy.emit(False)
        if self._pending_restore is not None:
            result, self._pending_restore = self._pending_restore, None
            self.restored.emit(result)
