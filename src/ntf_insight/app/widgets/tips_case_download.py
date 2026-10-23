"""TIPS-Writer-Abruf direkt in FIN-/Fallanalyse; gemeinsame FIN-Checkboxen und SSO."""

from __future__ import annotations

from pathlib import Path
from threading import Event
from typing import Callable

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit, QPushButton,
    QVBoxLayout, QWidget,
)

from ntf_insight.acquisition.credentials import LoginCredentials
from ntf_insight.acquisition.tips_writer import TipsWriterDownloader


class TipsCaseWorker(QThread):
    progress = Signal(str)
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, fins: list[str], data_dir: Path,
                 login: LoginCredentials | None) -> None:
        super().__init__()
        self.fins = list(fins)
        self.data_dir = Path(data_dir)
        self.login = login
        self.cancel = Event()

    def run(self) -> None:
        try:
            downloader = TipsWriterDownloader(
                self.data_dir / "tips",
                self.data_dir / "edge-tips-writer-profile",
                user_id=self.login.user_id if self.login else "",
                password=self.login.password if self.login else "",
                click_delay_seconds=0.85,
            )
            self.completed.emit(
                downloader.run(
                    self.fins, progress=self.progress.emit, cancel=self.cancel,
                )
            )
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            self.login = None


class TipsCaseDownloadPanel(QWidget):
    """Gleiches Layout wie QEC, keine zweite FIN-Auswahl und keine zweite SSO-Maske."""

    downloads_completed = Signal(object)

    def __init__(
        self,
        data_dir: Path,
        all_fins: Callable[[], list[str]],
        selected_fins: Callable[[], list[str]],
        login_resolver: Callable[[], LoginCredentials | None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.data_dir = Path(data_dir)
        self.all_fins = all_fins
        self.selected_fins = selected_fins
        self.login_resolver = login_resolver
        self.worker: TipsCaseWorker | None = None
        self._all_count = 0
        self._selected_count = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 8)
        layout.setSpacing(8)
        layout.addWidget(QLabel("TIPS-Writer-Fälle für Fälle / FIN", objectName="CardTitle"))
        controls = QHBoxLayout()

        self.all_button = QPushButton("Alle TIPS-Fälle herunterladen/aktualisieren")
        self.all_button.clicked.connect(self._start_all)
        self.all_button.setToolTip(
            "Für jede FIN alle zugehörigen TIPS-Fälle und die vorhandenen Anhänge "
            "im eigenen Microsoft-Edge-Fenster abrufen."
        )
        controls.addWidget(self.all_button)

        self.selected_button = QPushButton(
            "TIPS-Fälle für ausgewählte FINs herunterladen/aktualisieren"
        )
        self.selected_button.setToolTip(
            "Benutzt genau die Fall-Checkboxen von QuickTest, QEC und ZIP-Export."
        )
        self.selected_button.clicked.connect(self._start_selected)
        controls.addWidget(self.selected_button)

        self.cancel_button = QPushButton("Abbrechen")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._cancel)
        controls.addWidget(self.cancel_button)
        layout.addLayout(controls)

        self.status = QLabel(
            "Pilotfunktion: Live-Navigation und Anhangsformate müssen im "
            "berechtigten Unternehmensnetz validiert werden. "
            "TIPS Writer nutzt Mercedes-SSO mit manueller PING-ID in Edge. "
            "Daten bleiben lokal unter tips/<FIN>/fall_<Nummer>/.",
            objectName="PageSubtitle",
        )
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(100)
        self.log.setPlaceholderText("TIPS-Ablaufprotokoll (ohne Zugangsdaten und Cookies)")
        layout.addWidget(self.log)
        self.set_selection_count(0, 0)

    def set_selection_count(self, total: int, checked: int) -> None:
        self._all_count = total
        self._selected_count = checked
        idle = self.worker is None
        self.all_button.setEnabled(idle and total > 0)
        self.selected_button.setEnabled(idle and checked > 0)
        self.selected_button.setToolTip(
            f"{checked} eindeutige FIN(s) angekreuzt; dieselben Fall-Checkboxen "
            "wie bei QuickTest/QEC."
        )

    def _start_all(self) -> None:
        self._start(self.all_fins(), bulk=True)

    def _start_selected(self) -> None:
        self._start(self.selected_fins(), bulk=False)

    def _start(self, fins: list[str], *, bulk: bool) -> None:
        if self.worker is not None or not fins:
            return
        if bulk and len(fins) > 5:
            answer = QMessageBox.question(
                self, "TIPS-Sammelabruf",
                f"{len(fins)} FINs aus TIPS Writer abrufen? "
                "Bitte Berechtigungen und Systemlast beachten.",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        try:
            login = self.login_resolver()
        except ValueError as exc:
            QMessageBox.warning(self, "Mercedes-SSO / TIPS Writer", str(exc))
            return
        self.worker = TipsCaseWorker(fins, self.data_dir, login)
        self.worker.progress.connect(self._progress)
        self.worker.completed.connect(self._completed)
        self.worker.failed.connect(self._failed)
        self.worker.finished.connect(self._finished)
        self.log.clear()
        self.set_selection_count(self._all_count, self._selected_count)
        self.cancel_button.setEnabled(True)
        self._progress(f"TIPS-Edge wird gestartet · {len(fins)} FIN(s)")
        self.worker.start()

    def _cancel(self) -> None:
        if self.worker is not None:
            self.worker.cancel.set()
            self.cancel_button.setEnabled(False)
            self._progress("TIPS-Abbruch angefordert …")

    def _progress(self, message: str) -> None:
        self.status.setText(message)
        self.log.appendPlainText(message)

    def _completed(self, results) -> None:
        count = sum(len(result.cases) for result in results)
        reports = sum(len(result.reports) for result in results)
        files = sum(len(result.files) for result in results)
        errors = sum(len(result.errors) for result in results)
        self._progress(
            f"TIPS-Abruf beendet: {len(results)} FIN(s), {count} TIPS-Fall/Fälle, "
            f"{reports} JSON(s), {files} Anhangdateien, {errors} Fehler. "
            "Die Daten werden beim nächsten FIN-ZIP-Export berücksichtigt."
        )
        self.downloads_completed.emit(results)

    def _failed(self, message: str) -> None:
        self._progress("TIPS-Fehler: " + message)

    def _finished(self) -> None:
        worker, self.worker = self.worker, None
        if worker is not None:
            worker.deleteLater()
        self.cancel_button.setEnabled(False)
        self.set_selection_count(self._all_count, self._selected_count)
