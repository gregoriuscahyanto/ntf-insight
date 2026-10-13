"""QuickTest-Abruf mit Edge, sicherem SSO-Login und FIN-bezogener Historie."""

from __future__ import annotations

from pathlib import Path
from threading import Event

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPlainTextEdit, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ntf_insight.acquisition.credentials import (
    LoginCredentials, clear_saved_credentials, load_saved_credentials, save_credentials,
)
from ntf_insight.acquisition.diagnosis_viewer import (
    DiagnosisViewerDownloader, format_last_attempt, parse_fins, read_last_attempt,
)


class DownloadWorker(QThread):
    progress = Signal(str)
    completed = Signal(object)
    failed = Signal(str)

    def __init__(
        self, fins: list[str], folder: Path, profile: Path,
        login: LoginCredentials | None = None, retry_recent: bool = False,
    ) -> None:
        super().__init__()
        self.fins, self.folder, self.profile = fins, folder, profile
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
            results = downloader.run(self.fins, progress=self.progress.emit, cancel=self.cancel)
            self.completed.emit(results)
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            self.login = None


class QuickTestDownloadPage(QWidget):
    """Deutsches, CI-konformes PySide6-Bedienfeld mit PING-ID-Handyfreigabe."""

    import_requested = Signal(object)

    def __init__(self, data_dir: Path, cases=None, mode: str = "local"):
        super().__init__()
        self.data_dir = Path(data_dir)
        self.cases = cases
        self.mode = mode
        self.worker: DownloadWorker | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(14)
        layout.addWidget(QLabel("QuickTests herunterladen", objectName="PageTitle"))
        subtitle = QLabel(
            "Diagnosis Viewer · Microsoft Edge · Mercedes SSO. "
            "Benutzer-ID und Passwort können sicher im Windows-Anmeldeinformationsmanager "
            "gespeichert werden. PING ID muss weiterhin auf dem Smartphone bestätigt werden.",
            objectName="PageSubtitle",
        )
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        layout.addWidget(QLabel("SSO-Anmeldung", objectName="CardTitle"))
        login_row = QHBoxLayout()
        self.user_id = QLineEdit()
        self.user_id.setPlaceholderText("Benutzer-ID")
        self.user_id.setMaxLength(20)
        login_row.addWidget(self.user_id)
        self.password = QLineEdit()
        self.password.setPlaceholderText("Passwort (bei gespeichertem Passwort leer lassen)")
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        login_row.addWidget(self.password)
        layout.addLayout(login_row)
        security_row = QHBoxLayout()
        self.remember_login = QCheckBox(
            "Zugangsdaten im Windows-Anmeldeinformationsmanager speichern"
        )
        self.remember_login.setChecked(True)
        security_row.addWidget(self.remember_login)
        self.forget_login = QPushButton("Zugangsdaten löschen")
        self.forget_login.clicked.connect(self._forget_login)
        security_row.addWidget(self.forget_login)
        layout.addLayout(security_row)

        try:
            saved = load_saved_credentials()
        except RuntimeError:
            saved = None
        if saved:
            self.user_id.setText(saved.user_id)

        layout.addWidget(QLabel("FIN-Liste", objectName="CardTitle"))
        self.fins = QPlainTextEdit()
        self.fins.setPlaceholderText("17-stellige FINs, jeweils eine pro Zeile")
        self.fins.setMaximumHeight(120)
        layout.addWidget(self.fins)

        controls = QHBoxLayout()
        load = QPushButton("FIN-Liste laden …")
        load.clicked.connect(self._load_fins)
        controls.addWidget(load)
        from_cases = QPushButton("FINs aus Fällen übernehmen")
        from_cases.setEnabled(cases is not None and mode != "demo")
        from_cases.clicked.connect(self._from_cases)
        controls.addWidget(from_cases)
        controls.addStretch()
        layout.addLayout(controls)

        layout.addWidget(QLabel("Speicherort", objectName="CardTitle"))
        folder_row = QHBoxLayout()
        self.folder = QLabel(str(self.data_dir / "quicktests"), objectName="PageSubtitle")
        folder_row.addWidget(self.folder, 1)
        choose = QPushButton("Ordner ändern …")
        choose.clicked.connect(self._choose_folder)
        folder_row.addWidget(choose)
        layout.addLayout(folder_row)

        run_row = QHBoxLayout()
        self.start = QPushButton("QuickTests abrufen")
        self.start.clicked.connect(self._start)
        run_row.addWidget(self.start)
        self.stop = QPushButton("Abbrechen")
        self.stop.setEnabled(False)
        self.stop.clicked.connect(self._stop)
        run_row.addWidget(self.stop)
        self.retry_recent = QCheckBox("24-Stunden-Sperre einmalig übergehen")
        self.retry_recent.setToolTip(
            "Standard: Jede FIN mit einem Abrufversuch in den letzten 24 Stunden wird "
            "übersprungen, auch wenn dabei ein Fehler aufgetreten ist."
        )
        run_row.addWidget(self.retry_recent)
        run_row.addStretch()
        layout.addLayout(run_row)

        self.status = QLabel(
            "Bereit. Bei Bedarf SSO bestätigen, danach PING ID auf dem Smartphone freigeben.",
            objectName="PageSubtitle",
        )
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ("FIN", "Letzter Abruf", "Status", "PDFs", "Fehler")
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table, 1)

    def _forget_login(self) -> None:
        try:
            clear_saved_credentials()
            self.password.clear()
            self.user_id.clear()
            self.status.setText("Gespeicherte Zugangsdaten aus dem System-Tresor gelöscht.")
        except RuntimeError as exc:
            QMessageBox.warning(self, "Zugangsdaten", str(exc))

    def _load_fins(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self, "FIN-Liste laden", "", "Textdateien (*.txt *.csv);;Alle Dateien (*)"
        )
        if filename:
            try:
                text = Path(filename).read_text(encoding="utf-8-sig")
                fins = parse_fins(text)
                self.fins.setPlainText("\n".join(fins))
            except Exception as exc:
                QMessageBox.warning(self, "FIN-Liste", str(exc))

    def _from_cases(self) -> None:
        if self.cases is not None and self.mode != "demo":
            existing = self.fins.toPlainText().strip()
            vins = [case.vin for case in self.cases.list_cases()]
            self.fins.setPlainText("\n".join(filter(None, [existing, *vins])))

    def _choose_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Speicherort", self.folder.text())
        if folder:
            self.folder.setText(folder)

    def _resolve_login(self) -> LoginCredentials | None:
        user_id = self.user_id.text().strip()
        password = self.password.text()
        if password and not user_id:
            raise ValueError("Für das Passwort muss eine Benutzer-ID angegeben werden.")
        if user_id and password:
            if self.remember_login.isChecked():
                try:
                    save_credentials(user_id, password)
                except RuntimeError as exc:
                    answer = QMessageBox.question(
                        self, "Sicheres Speichern nicht verfügbar",
                        str(exc) + "\n\nOhne Speichern nur für diesen Abruf fortfahren?",
                    )
                    if answer != QMessageBox.StandardButton.Yes:
                        raise ValueError("Abruf abgebrochen.")
            return LoginCredentials(user_id=user_id, password=password)
        if user_id:
            try:
                existing = load_saved_credentials()
            except RuntimeError:
                existing = None
            if existing is not None and existing.user_id == user_id:
                return existing
            raise ValueError(
                "Für diese Benutzer-ID ist noch kein Passwort sicher gespeichert. "
                "Bitte einmal das Passwort eingeben. Alternativ beide Felder "
                "leer lassen und die Anmeldung manuell in Edge durchführen."
            )
        return None

    def _start(self) -> None:
        if self.worker is not None:
            return
        try:
            fins = parse_fins(self.fins.toPlainText())
            login = self._resolve_login()
        except ValueError as exc:
            QMessageBox.warning(self, "Eingabe prüfen", str(exc))
            return

        folder = Path(self.folder.text())
        self.table.setRowCount(len(fins))
        for i, fin in enumerate(fins):
            previous = read_last_attempt(folder, fin)
            for j, label in enumerate((
                fin,
                format_last_attempt(previous.last_attempt_at if previous else ""),
                "Wartend",
                str(len(previous.files)) if previous else "0",
                "",
            )):
                self.table.setItem(i, j, QTableWidgetItem(label))
        self.worker = DownloadWorker(
            fins, folder, self.data_dir / "edge-diagnosis-viewer-profile",
            login=login, retry_recent=self.retry_recent.isChecked(),
        )
        self.password.clear()  # Passwords must never remain in the GUI after start.
        self.worker.progress.connect(self.status.setText)
        self.worker.completed.connect(self._completed)
        self.worker.failed.connect(lambda error: self.status.setText("Fehler: " + error))
        self.worker.finished.connect(self._finished)
        self.start.setEnabled(False)
        self.stop.setEnabled(True)
        self.status.setText(f"Abruf startet · {len(fins)} FIN(s)")
        self.worker.start()

    def _stop(self) -> None:
        if self.worker is not None:
            self.worker.cancel.set()
            self.stop.setEnabled(False)
            self.status.setText("Abbruch angefordert …")

    def _completed(self, results) -> None:
        self.table.setRowCount(len(results))
        for i, result in enumerate(results):
            for j, label in enumerate((
                result.fin,
                format_last_attempt(result.last_attempt_at),
                result.status,
                str(len(result.files)),
                "; ".join(result.errors[:2]),
            )):
                self.table.setItem(i, j, QTableWidgetItem(label))
        files = list(dict.fromkeys(
            file for result in results if not result.status.startswith("Übersprungen")
            for file in result.files
        ))
        self.status.setText(
            f"Fertig: {len(results)} FIN(s), {len(files)} neue PDF(s). "
            f"Ordner: {self.folder.text()}"
        )
        if files:
            self.import_requested.emit(files)

    def _finished(self) -> None:
        self.start.setEnabled(True)
        self.stop.setEnabled(False)
        if self.worker is not None:
            self.worker.deleteLater()
            self.worker = None
