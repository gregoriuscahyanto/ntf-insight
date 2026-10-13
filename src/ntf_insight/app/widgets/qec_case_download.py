"""QEC-Download-Aktionen direkt in Fälle / FIN -> FIN / Fallanalyse.

Die Auswahl kommt aus der Falltabelle; keine zweite QEC-Eingabeseite.
"""

from __future__ import annotations

from pathlib import Path
from threading import Event
from typing import Callable

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit, QPushButton,
    QVBoxLayout, QWidget,
)

from ntf_insight.acquisition.credentials import LoginCredentials, load_saved_credentials
from ntf_insight.acquisition.qec_tool import QecDownloader, QecTarget


class QecCaseWorker(QThread):
    progress = Signal(str)
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, targets: list[QecTarget], data_dir: Path,
                 login: LoginCredentials | None) -> None:
        super().__init__()
        self.targets = targets
        self.data_dir = Path(data_dir)
        self.login = login
        self.cancel = Event()

    def run(self) -> None:
        try:
            downloader = QecDownloader(
                self.data_dir / "qec",
                self.data_dir / "edge-qec-profile",
                user_id=self.login.user_id if self.login else "",
                password=self.login.password if self.login else "",
                click_delay_seconds=0.85,
            )
            results = downloader.run(
                self.targets, progress=self.progress.emit, cancel=self.cancel,
            )
            self.completed.emit(results)
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            self.login = None


class QecCaseDownloadPanel(QWidget):
    """Anschluss an den gemeinsamen QuickTest/SSO-Kennworttresor."""

    import_requested = Signal(object)
    downloads_completed = Signal(object)

    def __init__(
        self, data_dir: Path,
        all_targets: Callable[[], list[QecTarget]],
        selected_targets: Callable[[], list[QecTarget]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.data_dir = Path(data_dir)
        self.all_targets = all_targets
        self.selected_targets = selected_targets
        self.worker: QecCaseWorker | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 8)
        layout.setSpacing(8)
        controls = QHBoxLayout()
        controls.addWidget(QLabel("QEC-Befundungsberichte", objectName="CardTitle"))
        self.all_button = QPushButton("Alle QEC-Berichte herunterladen")
        self.all_button.setToolTip(
            "Ruft QEC für alle FIN-/Schadteilfälle der Falltabelle ab, "
            "auch wenn die Tabelle gefiltert ist."
        )
        self.all_button.clicked.connect(self._start_all)
        controls.addWidget(self.all_button)
        self.selected_button = QPushButton("Ausgewählte herunterladen")
        self.selected_button.setToolTip(
            "Nur markierte Tabellenzeilen. Referenznummern werden exakt geprüft."
        )
        self.selected_button.clicked.connect(self._start_selected)
        controls.addWidget(self.selected_button)
        self.cancel_button = QPushButton("QEC-Abbruch")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._cancel)
        controls.addWidget(self.cancel_button)
        controls.addStretch(1)
        layout.addLayout(controls)

        self.credentials_status = QLabel(objectName="PageSubtitle")
        self.credentials_status.setWordWrap(True)
        self.credentials_status.setToolTip(
            "Dieselben Zugangsdaten wie im QuickTest-Abruf. "
            "Gespeichert nur im Betriebssystem-Tresor, niemals in der Fall-Datei. "
            "PING ID bleibt manuell."
        )
        layout.addWidget(self.credentials_status)
        self.status = QLabel("QEC bereit. Download über die Falltabelle starten.",
                             objectName="PageSubtitle")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(100)
        self.log.setPlaceholderText("QEC-Ablaufprotokoll (ohne Passwort und Cookies)")
        layout.addWidget(self.log)
        self.refresh_credentials()

    def refresh_credentials(self) -> None:
        try:
            creds = load_saved_credentials()
        except RuntimeError:
            creds = None
        if creds is not None:
            self.credentials_status.setText(
                "✓ QuickTest-/QEC-Zugangsdaten sicher gespeichert · "
                "PING ID bei Bedarf am Smartphone bestätigen"
            )
            # Dezentes Statusgrün, passend zur hellen/dunklen NTF-Oberfläche.
            self.credentials_status.setStyleSheet("color: #268b52; font-weight: 600;")
        else:
            self.credentials_status.setText(
                "Keine gemeinsamen Zugangsdaten gespeichert. Im Menü QuickTest-Abruf "
                "speichern oder interaktiv im Edge-Fenster anmelden."
            )
            self.credentials_status.setStyleSheet("")

    def _start_all(self) -> None:
        self._start(self.all_targets(), bulk=True)

    def _start_selected(self) -> None:
        self._start(self.selected_targets(), bulk=False)

    def _start(self, targets: list[QecTarget], *, bulk: bool) -> None:
        if self.worker is not None:
            return
        if not targets:
            QMessageBox.information(
                self, "QEC-Abruf", "Keine geeigneten FIN-/Fallzeilen gewählt. "
                "Für den Abruf ist eine gültige FIN erforderlich.",
            )
            return
        if bulk and len(targets) > 5:
            reply = QMessageBox.question(
                self, "QEC-Sammelabruf",
                f"{len(targets)} FIN-/Fallabrufe starten? "
                "Bitte den berechtigten Zugang und die QEC-Systemlast beachten.",
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        try:
            login = load_saved_credentials()
        except RuntimeError:
            login = None  # Manuelle Mercedes-SSO/PING-ID bleibt möglich.
        self.log.clear()
        self.worker = QecCaseWorker(targets, self.data_dir, login)
        self.worker.progress.connect(self._progress)
        self.worker.completed.connect(self._completed)
        self.worker.failed.connect(self._failed)
        self.worker.finished.connect(self._finished)
        self.all_button.setEnabled(False)
        self.selected_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self._progress(f"QEC-Edge wird gestartet · {len(targets)} Fallabruf(e)")
        self.worker.start()

    def _cancel(self) -> None:
        if self.worker is not None:
            self.worker.cancel.set()
            self.cancel_button.setEnabled(False)
            self._progress("Abbruch angefordert …")

    def _progress(self, text: str) -> None:
        self.status.setText(text)
        self.log.appendPlainText(text)

    def _completed(self, results) -> None:
        reports = list(dict.fromkeys(
            path for item in results for path in item.snapshots
            if path.is_file()
        ))
        attachments = list(dict.fromkeys(
            path for item in results for path in item.files
            if path.is_file()
        ))
        errors = sum(len(item.errors) for item in results)
        self._progress(
            f"QEC beendet: {len(results)} Fallabruf(e), {len(reports)} Fall-JSON, "
            f"{len(attachments)} Anhaenge, {errors} Fehler."
        )
        self.downloads_completed.emit(results)
        if reports or attachments:
            self.import_requested.emit([*reports, *attachments])

    def _failed(self, message: str) -> None:
        self._progress("QEC-Fehler: " + message)

    def _finished(self) -> None:
        self.all_button.setEnabled(True)
        self.selected_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        if self.worker is not None:
            self.worker.deleteLater()
            self.worker = None
        self.refresh_credentials()
