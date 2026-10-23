"""GUI für den lokalen, pseudonymisierten KI-Clusterexport."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox, QFileDialog, QHBoxLayout, QLabel, QMessageBox,
    QPushButton, QVBoxLayout, QWidget,
)

from ntf_insight.ingestion.service import SourceImportService
from ntf_insight.reporting.ki_analysepaket import export_ki_analysepaket


class KIAnalyseWorker(QThread):
    progress = Signal(str)
    completed = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        service: SourceImportService,
        path: Path,
        *,
        mit_freitext: bool,
    ) -> None:
        super().__init__()
        self.service = service
        self.path = Path(path)
        self.mit_freitext = mit_freitext

    def run(self) -> None:
        try:
            result = export_ki_analysepaket(
                self.service, self.path, mit_freitext=self.mit_freitext,
                progress=self.progress.emit,
            )
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")
            return
        self.completed.emit(result)


class KIAnalysepaketPanel(QWidget):
    """Safe-by-default analysis export, separate from the full .ntfbackup."""

    transfer_busy = Signal(bool)

    def __init__(
        self, service: SourceImportService, *, parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.worker: KIAnalyseWorker | None = None
        self._guard: Callable[[], bool] | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 8)
        layout.setSpacing(8)
        layout.addWidget(QLabel(
            "KI-Analysepaket · kompakter Export für Clusterung",
            objectName="CardTitle",
        ))
        description = QLabel(
            "Erstellt EINE ZIP mit verknüpften QEC-Befundmerkmalen, "
            "QuickTest-/CPC3-DTCs, TIPS-Abdeckung, Fall- und Zeitbezug, "
            "Datenlücken und einer Excel-Übersicht. Große Original-PDFs, "
            "QEC-/TIPS-Dateien und Anhänge werden NICHT beigefügt. "
            "Die echte FIN-/QEC-Zuordnung bleibt als separate "
            "NICHT-HOCHLADEN-Datei auf diesem Rechner.",
            objectName="PageSubtitle",
        )
        description.setWordWrap(True)
        layout.addWidget(description)

        self.include_text = QCheckBox(
            "QEC-/TIPS-Originalfreitext beifügen (vertraulich, nur nach Freigabe)",
        )
        self.include_text.setToolTip(
            "Nur nach interner Freigabe wählen. Freitext ist NICHT automatisch "
            "anonymisiert und kann FINs, Personen und geschützte Angaben enthalten."
        )
        self.include_text.setChecked(False)
        layout.addWidget(self.include_text)

        row = QHBoxLayout()
        self.export_button = QPushButton("Lightweight KI-Analysepaket als ZIP exportieren…")
        self.export_button.setToolTip(
            "Pseudonymisierte CSVs für Clusterung, Excel-Zusammenfassung "
            "und eine separate lokale Zuordnungstabelle. Niemals automatischer Upload."
        )
        self.export_button.clicked.connect(self._export)
        row.addWidget(self.export_button)
        row.addStretch(1)
        layout.addLayout(row)

        self.status = QLabel(
            "Standard ohne fachlichen Freitext, ohne reale FINs und "
            "ohne Originaldateien. Pseudonymisiert ist NICHT gleich anonym. "
            "Interne Informationsschutzfreigabe vor jedem externen Upload prüfen.",
            objectName="PageSubtitle",
        )
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

    def set_guard(self, guard: Callable[[], bool]) -> None:
        self._guard = guard

    def _export(self) -> None:
        if self.worker is not None:
            return
        if self._guard is not None and not self._guard():
            QMessageBox.warning(
                self, "Analyseexport derzeit nicht möglich",
                "Bitte zuvor laufende Downloads, Imports, ZIP-Exporte "
                "und vollständige Datentransfers abschließen.",
            )
            return
        with_text = self.include_text.isChecked()
        if with_text:
            reply = QMessageBox.warning(
                self, "Nicht anonymisierte QEC-/TIPS-Freitexte",
                "Diese Option exportiert Originalfreitexte aus QEC und TIPS. "
                "Darin können echte FINs, persönliche und vertrauliche "
                "Unternehmensdaten stehen. Eine vollständige Anonymisierung "
                "erfolgt NICHT. Vor Upload ist eine interne Freigabe "
                "und eigenständige Prüfung notwendig.\n\n"
                "Vertrauliche Texte wirklich lokal exportieren?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        path, _ = QFileDialog.getSaveFileName(
            self, "KI-Analysepaket für Fallclusterung erstellen",
            str(Path.home() / (
                "NTF-Insight-KI-Analyse-" + datetime.now().strftime("%Y%m%d-%H%M") + ".zip"
            )),
            "NTF KI-Analysepaket (*.zip)",
        )
        if not path:
            return
        destination = Path(path)
        if destination.suffix.lower() != ".zip":
            destination = destination.with_suffix(".zip")
        self.worker = KIAnalyseWorker(
            self.service, destination, mit_freitext=with_text,
        )
        self.worker.progress.connect(self.status.setText)
        self.worker.completed.connect(self._completed)
        self.worker.failed.connect(self._failed)
        self.worker.finished.connect(self._finished)
        self.export_button.setEnabled(False)
        self.include_text.setEnabled(False)
        self.status.setText("Strukturiertes KI-Analysepaket wird lokal erstellt …")
        self.transfer_busy.emit(True)
        self.worker.start()

    def _completed(self, result) -> None:
        self.status.setText(
            f"KI-Analysepaket bereit: {result.pfad.name} · "
            f"{result.faelle} Fälle, {result.fahrzeuge} Fahrzeuge, "
            f"{result.quicktests} QuickTests, {result.dtcs} DTC-Beobachtungen, "
            f"{result.qec_berichte} QEC-Berichte. "
            "Nur die ZIP zur freigegebenen Analyse verwenden. "
            f"Die daneben erstellte Datei {result.private_zuordnung.name} "
            "enthält die echten FIN-/Fall-Zuordnungen und darf NICHT hochgeladen werden."
        )

    def _failed(self, message: str) -> None:
        self.status.setText("KI-Analyseexport fehlgeschlagen: " + message)

    def _finished(self) -> None:
        worker, self.worker = self.worker, None
        if worker is not None:
            worker.deleteLater()
        self.export_button.setEnabled(True)
        self.include_text.setEnabled(True)
        self.transfer_busy.emit(False)
