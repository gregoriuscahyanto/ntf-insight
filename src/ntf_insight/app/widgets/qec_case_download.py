"""QEC-Abruf in der vorhandenen FIN-/Fallanalyse mit derselben Checkbox-Auswahl wie QuickTest."""

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
    """QuickTest-ähnliche QEC-Download-Zeile; keine zweite Auswahl oder SSO-Maske."""

    import_requested = Signal(object)
    downloads_completed = Signal(object)

    def __init__(
        self,
        data_dir: Path,
        all_targets: Callable[[], list[QecTarget]],
        selected_targets: Callable[[], list[QecTarget]],
        login_resolver: Callable[[], LoginCredentials | None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.data_dir = Path(data_dir)
        self.all_targets = all_targets
        self.selected_targets = selected_targets
        self.login_resolver = login_resolver
        self.worker: QecCaseWorker | None = None
        self._pending_import: list[Path] = []
        self._all_count = 0
        self._selected_count = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 8)
        layout.setSpacing(8)
        layout.addWidget(QLabel("QEC-Befundungsberichte für Fälle / FIN", objectName="CardTitle"))

        download_row = QHBoxLayout()
        self.all_button = QPushButton("Alle QEC-Berichte herunterladen/aktualisieren")
        self.all_button.clicked.connect(self._start_all)
        self.all_button.setToolTip(
            "Alle in der Fallanalyse bekannten FIN-/Schadteilfälle abrufen; "
            "bestehende Dateien bleiben lokal erhalten."
        )
        download_row.addWidget(self.all_button)
        self.selected_button = QPushButton(
            "QEC-Berichte für ausgewählte Fälle herunterladen/aktualisieren"
        )
        self.selected_button.clicked.connect(self._start_selected)
        self.selected_button.setToolTip(
            "Dieselben Checkboxen links in der Falltabelle wie beim QuickTest-Abruf. "
            "Bekannte QEC-Referenzen werden exakt geprüft."
        )
        download_row.addWidget(self.selected_button)
        self.cancel_button = QPushButton("Abbrechen")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._cancel)
        download_row.addWidget(self.cancel_button)
        layout.addLayout(download_row)

        self.status = QLabel(
            "Fälle über die Checkbox links auswählen. "
            "Blau unterstrichene QEC-Abrufdaten öffnen den lokalen Schadteilfallordner.",
            objectName="PageSubtitle",
        )
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(96)
        self.log.setPlaceholderText("QEC-Ablaufprotokoll · keine Passwörter oder Cookies")
        layout.addWidget(self.log)
        self.set_selection_count(0, 0)

    def set_selection_count(self, all_count: int, selected_count: int) -> None:
        """Reuse the model's persistent checkbox set, even across sorting/filtering."""
        self._all_count = all_count
        self._selected_count = selected_count
        ready = self.worker is None
        self.all_button.setEnabled(ready and all_count > 0)
        self.selected_button.setEnabled(ready and selected_count > 0)
        self.selected_button.setToolTip(
            f"{selected_count} ausgewählte(r) gültige(r) FIN-/QEC-Fallabruf(e) · "
            "dieselben Fall-Checkboxen wie bei QuickTest."
        )

    def _start_all(self) -> None:
        self._start(self.all_targets(), bulk=True)

    def _start_selected(self) -> None:
        self._start(self.selected_targets(), bulk=False)

    def _start(self, targets: list[QecTarget], *, bulk: bool) -> None:
        if self.worker is not None:
            return
        if not targets:
            QMessageBox.information(
                self, "QEC-Abruf",
                "Keine gültigen FIN-/Fallzeilen ausgewählt. "
                "Bitte die Checkbox links in der Falltabelle verwenden.",
            )
            return
        if bulk and len(targets) > 5:
            answer = QMessageBox.question(
                self, "QEC-Sammelabruf",
                f"{len(targets)} FIN-/Fallabrufe starten? "
                "Bitte QEC-Berechtigung und Systemlast beachten.",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        try:
            login = self.login_resolver()
        except ValueError as exc:
            QMessageBox.warning(self, "Mercedes-SSO", str(exc))
            return

        self.log.clear()
        self._pending_import = []
        self.worker = QecCaseWorker(targets, self.data_dir, login)
        self.worker.progress.connect(self._progress)
        self.worker.completed.connect(self._completed)
        self.worker.failed.connect(self._failed)
        self.worker.finished.connect(self._finished)
        self.set_selection_count(self._all_count, self._selected_count)
        self.cancel_button.setEnabled(True)
        self._progress(f"QEC-Edge wird gestartet · {len(targets)} Fallabruf(e)")
        self.worker.start()

    def _cancel(self) -> None:
        if self.worker is not None:
            self.worker.cancel.set()
            self.cancel_button.setEnabled(False)
            self._progress("Abruf wird angehalten …")

    def _progress(self, message: str) -> None:
        self.status.setText(message)
        self.log.appendPlainText(message)

    def _completed(self, results) -> None:
        reports = list(dict.fromkeys(
            path for entry in results for path in entry.snapshots if path.is_file()
        ))
        attachments = list(dict.fromkeys(
            path for entry in results for path in entry.files if path.is_file()
        ))
        count_errors = sum(len(entry.errors) for entry in results)
        self._progress(
            f"QEC-Abruf beendet: {len(results)} Fallabruf(e), "
            f"{len(reports)} Fall-JSON, {len(attachments)} Anhänge, "
            f"{count_errors} Fehler."
        )
        self.downloads_completed.emit(results)
        # Import only after QThread is finished: the importer may rebuild CasePage.
        self._pending_import = [*reports, *attachments]

    def _failed(self, message: str) -> None:
        self._progress("QEC-Abruf fehlgeschlagen: " + message)

    def _finished(self) -> None:
        worker = self.worker
        self.worker = None
        if worker is not None:
            worker.deleteLater()
        self.cancel_button.setEnabled(False)
        self.set_selection_count(self._all_count, self._selected_count)
        files, self._pending_import = self._pending_import, []
        if files:
            self.import_requested.emit(files)
