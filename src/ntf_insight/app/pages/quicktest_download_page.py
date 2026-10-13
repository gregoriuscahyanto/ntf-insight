"""FIN-basiertes Herunterladen von QuickTests aus dem Diagnosis Viewer."""

from pathlib import Path
from threading import Event

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ntf_insight.acquisition.diagnosis_viewer import DiagnosisViewerDownloader, parse_fins


class DownloadWorker(QThread):
    progress = Signal(str)
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, fins: list[str], folder: Path, profile: Path):
        super().__init__()
        self.fins, self.folder, self.profile = fins, folder, profile
        self.cancel = Event()

    def run(self):
        try:
            results = DiagnosisViewerDownloader(self.folder, self.profile).run(
                self.fins, progress=self.progress.emit, cancel=self.cancel
            )
            self.completed.emit(results)
        except Exception as exc:
            self.failed.emit(str(exc))


class QuickTestDownloadPage(QWidget):
    """Modernes, deutschsprachiges PySide6-Bedienfeld mit Edge-SSO."""

    import_requested = Signal(object)

    def __init__(self, data_dir: Path, cases=None, mode: str = "local"):
        super().__init__()
        self.data_dir = Path(data_dir)
        self.cases = cases
        self.mode = mode
        self.worker = None
        self.auto_import_files = True

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(14)
        layout.addWidget(QLabel("QuickTests herunterladen", objectName="PageTitle"))
        subtitle = QLabel(
            "Diagnosis Viewer · Microsoft Edge · SSO / PING ID. "
            "Beim ersten Start Anmeldung in Edge und PING-ID-Freigabe am Handy durchführen. "
            "Pro FIN wird ein eigener Ordner angelegt.",
            objectName="PageSubtitle",
        )
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)
        layout.addWidget(QLabel("FIN-Liste", objectName="CardTitle"))
        self.fins = QPlainTextEdit()
        self.fins.setPlaceholderText("17-stellige FINs, jeweils eine pro Zeile")
        self.fins.setMaximumHeight(130)
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
        run_row.addStretch()
        layout.addLayout(run_row)

        self.status = QLabel("Bereit", objectName="PageSubtitle")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(("FIN", "Status", "PDFs", "Fehler"))
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table, 1)

    def _load_fins(self):
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

    def _from_cases(self):
        if self.cases is not None and self.mode != "demo":
            existing = self.fins.toPlainText().strip()
            vins = [case.vin for case in self.cases.list_cases()]
            self.fins.setPlainText("\n".join(filter(None, [existing, *vins])))

    def _choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Speicherort", self.folder.text())
        if folder:
            self.folder.setText(folder)

    def _start(self):
        if self.worker is not None:
            return
        try:
            fins = parse_fins(self.fins.toPlainText())
        except ValueError as exc:
            QMessageBox.warning(self, "FIN prüfen", str(exc))
            return
        self.table.setRowCount(0)
        self.worker = DownloadWorker(
            fins, Path(self.folder.text()), self.data_dir / "edge-diagnosis-viewer-profile"
        )
        self.worker.progress.connect(self.status.setText)
        self.worker.completed.connect(self._completed)
        self.worker.failed.connect(lambda error: self.status.setText("Fehler: " + error))
        self.worker.finished.connect(self._finished)
        self.start.setEnabled(False)
        self.stop.setEnabled(True)
        self.status.setText(f"Microsoft Edge wird gestartet · {len(fins)} FIN(s)")
        self.worker.start()

    def _stop(self):
        if self.worker is not None:
            self.worker.cancel.set()
            self.stop.setEnabled(False)
            self.status.setText("Abbruch angefordert …")

    def _completed(self, results):
        self.table.setRowCount(len(results))
        for i, result in enumerate(results):
            for j, text in enumerate((
                result.fin, result.status, str(len(result.files)), "; ".join(result.errors[:2])
            )):
                self.table.setItem(i, j, QTableWidgetItem(text))
        files = list(dict.fromkeys(file for result in results for file in result.files))
        self.status.setText(
            f"Fertig: {len(results)} FIN(s), {len(files)} PDF(s). Ordner: {self.folder.text()}"
        )
        if files:
            self.import_requested.emit(files)

    def _finished(self):
        self.start.setEnabled(True)
        self.stop.setEnabled(False)
        if self.worker is not None:
            self.worker.deleteLater()
            self.worker = None
