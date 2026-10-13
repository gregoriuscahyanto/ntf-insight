"""Deutsche QEC-Download-Seite; Edge/PING-ID in separatem Playwright-Thread."""

from __future__ import annotations

from pathlib import Path
from threading import Event

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ntf_insight.acquisition.qec_tool import QecDownloader, parse_qec_targets
from ntf_insight.acquisition.credentials import (
    QEC_SERVICE_NAME, LoginCredentials, clear_saved_credentials,
    load_saved_credentials, save_credentials,
)


class QecDownloadWorker(QThread):
    progress = Signal(str)
    completed = Signal(object)
    failed = Signal(str)

    def __init__(
        self, targets, folder: Path, profile: Path, pump_only: bool,
        login: LoginCredentials | None = None,
    ):
        super().__init__()
        self.targets = targets
        self.folder = Path(folder)
        self.profile = Path(profile)
        self.pump_only = pump_only
        self.login = login
        self.cancel = Event()

    def run(self) -> None:
        try:
            results = QecDownloader(
                self.folder, self.profile, pump_only=self.pump_only,
                user_id=self.login.user_id if self.login else "",
                password=self.login.password if self.login else "",
            ).run(self.targets, progress=self.progress.emit, cancel=self.cancel)
            self.completed.emit(results)
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            self.login = None


class QecDownloadPage(QWidget):
    """Separate QEC-Datenquelle, nutzbar neben dem Diagnosis-Viewer-QuickTest-Abruf."""

    import_requested = Signal(object)

    def __init__(self, data_dir: Path, cases=None, mode: str = "local") -> None:
        super().__init__()
        self.data_dir = Path(data_dir)
        self.cases = cases
        self.mode = mode
        self.worker: QecDownloadWorker | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(14)
        layout.addWidget(QLabel("QEC-Befundungsberichte herunterladen", objectName="PageTitle"))
        description = QLabel(
            "QEC-Tool · Microsoft Edge · Unternehmens-SSO. Je FIN werden passende "
            "Kühlmittelpumpen-Schadteile, alle fünf Informationsreiter und die "
            "Dateianhänge der Lieferantenstellungnahme gesichert. "
            "Benutzer-ID/Passwort werden bei Bedarf auf der Mercedes-SSO-Seite eingetragen; "
            "PING ID bleibt eine manuelle Freigabe im Smartphone.",
            objectName="PageSubtitle",
        )
        description.setWordWrap(True)
        layout.addWidget(description)

        layout.addWidget(QLabel("SSO-Anmeldung (optional)", objectName="CardTitle"))
        login_row = QHBoxLayout()
        self.user_id = QLineEdit()
        self.user_id.setPlaceholderText("Benutzer-ID")
        self.user_id.setMaxLength(20)
        login_row.addWidget(self.user_id)
        self.password = QLineEdit()
        self.password.setPlaceholderText("Passwort (gespeichertes Passwort: leer lassen)")
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        login_row.addWidget(self.password)
        layout.addLayout(login_row)
        remember_row = QHBoxLayout()
        self.remember_login = QCheckBox(
            "QEC-Zugangsdaten im Windows-Anmeldeinformationsmanager speichern"
        )
        self.remember_login.setChecked(False)
        remember_row.addWidget(self.remember_login)
        self.forget_login = QPushButton("QEC-Zugangsdaten loeschen")
        self.forget_login.clicked.connect(self._forget_login)
        remember_row.addWidget(self.forget_login)
        layout.addLayout(remember_row)
        try:
            saved = load_saved_credentials(service_name=QEC_SERVICE_NAME)
        except RuntimeError:
            saved = None
        if saved:
            self.user_id.setText(saved.user_id)

        layout.addWidget(QLabel("FIN-Liste / optionale Sachnummer", objectName="CardTitle"))
        self.fins = QPlainTextEdit()
        self.fins.setPlaceholderText(
            "Eine 17-stellige FIN pro Zeile\n"
            "Optional: FIN;A 000 000 00 00 (nur diese Sachnummer abrufen)"
        )
        self.fins.setMaximumHeight(130)
        layout.addWidget(self.fins)

        source_row = QHBoxLayout()
        load = QPushButton("FIN-Liste laden …")
        load.clicked.connect(self._load_fins)
        source_row.addWidget(load)
        cases_button = QPushButton("FINs aus Fällen uebernehmen")
        cases_button.setEnabled(cases is not None and mode != "demo")
        cases_button.clicked.connect(self._from_cases)
        source_row.addWidget(cases_button)
        source_row.addStretch()
        layout.addLayout(source_row)

        self.pump_only = QCheckBox("Nur Kühlmittel-/Umwälzpumpen anhand der QEC-Bezeichnung")
        self.pump_only.setChecked(True)
        layout.addWidget(self.pump_only)
        self.archive = QCheckBox("Heruntergeladene Anhänge lokal in Datenquellen archivieren")
        self.archive.setChecked(True)
        layout.addWidget(self.archive)

        layout.addWidget(QLabel("Speicherort", objectName="CardTitle"))
        folder_row = QHBoxLayout()
        self.folder = QLabel(str(self.data_dir / "qec"), objectName="PageSubtitle")
        self.folder.setWordWrap(True)
        folder_row.addWidget(self.folder, 1)
        choose = QPushButton("Ordner ändern …")
        choose.clicked.connect(self._choose_folder)
        folder_row.addWidget(choose)
        layout.addLayout(folder_row)

        actions = QHBoxLayout()
        self.start = QPushButton("QEC-Daten und Berichte abrufen")
        self.start.clicked.connect(self._start)
        actions.addWidget(self.start)
        self.stop = QPushButton("Abbrechen")
        self.stop.setEnabled(False)
        self.stop.clicked.connect(self._stop)
        actions.addWidget(self.stop)
        actions.addStretch()
        layout.addLayout(actions)

        self.status = QLabel("Bereit", objectName="PageSubtitle")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        layout.addWidget(QLabel("Ablaufprotokoll", objectName="CardTitle"))
        self.activity = QPlainTextEdit()
        self.activity.setReadOnly(True)
        self.activity.setMaximumHeight(125)
        self.activity.setPlaceholderText(
            "Der QEC-Status wird hier mitgeschrieben. Keine Passwoerter oder Cookies enthalten."
        )
        layout.addWidget(self.activity)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ("FIN", "Status", "Schadteile", "Anhänge", "Hinweise / Fehler")
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table, 1)

    def _progress(self, message: str) -> None:
        self.status.setText(message)
        self.activity.appendPlainText(message)

    def _error(self, message: str) -> None:
        self._progress("Fehler: " + message)

    def _forget_login(self) -> None:
        try:
            clear_saved_credentials(service_name=QEC_SERVICE_NAME)
            self.user_id.clear()
            self.password.clear()
            self.status.setText("Gespeicherte QEC-Anmeldedaten aus dem System-Tresor geloescht.")
        except RuntimeError as exc:
            QMessageBox.warning(self, "QEC-Anmeldedaten", str(exc))

    def _resolve_login(self) -> LoginCredentials | None:
        user_id = self.user_id.text().strip()
        password = self.password.text()
        if password and not user_id:
            raise ValueError("Zum Passwort gehoert eine Benutzer-ID.")
        if user_id and password:
            if self.remember_login.isChecked():
                try:
                    save_credentials(user_id, password, service_name=QEC_SERVICE_NAME)
                except RuntimeError as exc:
                    reply = QMessageBox.question(
                        self, "Sicheres Speichern nicht verfuegbar",
                        str(exc) + "\n\nOhne Speichern nur fuer diesen Abruf fortfahren?",
                    )
                    if reply != QMessageBox.StandardButton.Yes:
                        raise ValueError("Abruf abgebrochen.")
            return LoginCredentials(user_id=user_id, password=password)
        if user_id:
            try:
                saved = load_saved_credentials(service_name=QEC_SERVICE_NAME)
            except RuntimeError:
                saved = None
            if saved and saved.user_id == user_id:
                return saved
            raise ValueError(
                "Fuer diese Benutzer-ID ist kein QEC-Passwort sicher gespeichert. "
                "Bitte Passwort eingeben oder beide Felder leer lassen und in Edge anmelden."
            )
        return None

    def _load_fins(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self, "FIN-Liste laden", "", "Textdateien (*.txt *.csv);;Alle Dateien (*)"
        )
        if filename:
            try:
                raw = Path(filename).read_text(encoding="utf-8-sig")
                targets = parse_qec_targets(raw)
                self.fins.setPlainText("\n".join(
                    f"{target.fin};{target.part_number}" if target.part_number else target.fin
                    for target in targets
                ))
            except Exception as exc:
                QMessageBox.warning(self, "FIN-Liste", str(exc))

    def _from_cases(self) -> None:
        if self.cases is None or self.mode == "demo":
            return
        try:
            previous = self.fins.toPlainText().strip()
            vins = [case.vin for case in self.cases.list_cases() if case.vin]
            merged = "\n".join(filter(None, (previous, *vins)))
            targets = parse_qec_targets(merged)
            self.fins.setPlainText("\n".join(
                f"{target.fin};{target.part_number}" if target.part_number else target.fin
                for target in targets
            ))
        except ValueError as exc:
            QMessageBox.warning(self, "FINs aus Fällen", str(exc))

    def _choose_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Speicherort", self.folder.text())
        if folder:
            self.folder.setText(folder)

    def _start(self) -> None:
        if self.worker is not None:
            return
        try:
            targets = parse_qec_targets(self.fins.toPlainText())
            login = self._resolve_login()
        except ValueError as exc:
            QMessageBox.warning(self, "FIN / Anmeldung pruefen", str(exc))
            return
        self.table.setRowCount(0)
        self.activity.clear()
        self.worker = QecDownloadWorker(
            targets, Path(self.folder.text()), self.data_dir / "edge-qec-profile",
            self.pump_only.isChecked(), login=login,
        )
        self.password.clear()  # Passwort nicht nach dem Start in der GUI halten.
        self.worker.progress.connect(self._progress)
        self.worker.completed.connect(self._completed)
        self.worker.failed.connect(self._error)
        self.worker.finished.connect(self._finished)
        self.start.setEnabled(False)
        self.stop.setEnabled(True)
        self._progress(f"QEC-Edge startet · {len(targets)} FIN(s)")
        self.worker.start()

    def _stop(self) -> None:
        if self.worker is not None:
            self.worker.cancel.set()
            self.stop.setEnabled(False)
            self.status.setText("Abbruch angefordert …")

    def _completed(self, results) -> None:
        self.table.setRowCount(len(results))
        for row, result in enumerate(results):
            fields = (
                result.fin, result.status, str(len(result.references)),
                str(len(result.files)), "; ".join((result.errors + result.warnings)[:3]),
            )
            for column, value in enumerate(fields):
                self.table.setItem(row, column, QTableWidgetItem(value))
        files = list(dict.fromkeys(path for result in results for path in result.files))
        pages = sum(len(result.snapshots) for result in results)
        self._progress(
            f"QEC abgeschlossen: {len(results)} FIN(s), {pages} Reiter-Snapshots, "
            f"{len(files)} Anhaenge. Ablage: {self.folder.text()}"
        )
        if files and self.archive.isChecked():
            self.import_requested.emit(files)

    def _finished(self) -> None:
        self.start.setEnabled(True)
        self.stop.setEnabled(False)
        if self.worker is not None:
            self.worker.deleteLater()
            self.worker = None
