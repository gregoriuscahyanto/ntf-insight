"""QEC-Verfahrensübersicht: FIN-Kohorte, Befundungsberichte, Entscheidung."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QProgressBar, QVBoxLayout, QWidget,
)

from ntf_insight.storage.qec_workflow_store import QecWorkflowStore, VALID_DECISIONS


class QecWorkflowPanel(QWidget):
    def __init__(self, workflow: QecWorkflowStore, data_dir: Path) -> None:
        super().__init__()
        self.workflow = workflow
        self.qec_root = Path(data_dir) / "qec"
        body = QVBoxLayout(self)
        body.setContentsMargins(0, 4, 0, 6)
        body.setSpacing(10)
        body.addWidget(QLabel("QEC-Prüfworkflow", objectName="PageTitle"))
        self.source_label = QLabel(objectName="PageSubtitle")
        self.source_label.setWordWrap(True)
        body.addWidget(self.source_label)
        self.step1 = QLabel("01  QEC-generierte FIN-Liste", objectName="CardTitle")
        body.addWidget(self.step1)
        self.step2 = QLabel("02  QEC-Tool · Befundungsberichte", objectName="CardTitle")
        body.addWidget(self.step2)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        body.addWidget(self.progress)
        self.step3 = QLabel("03  Fachliche Schlussfolgerung", objectName="CardTitle")
        body.addWidget(self.step3)
        self.summary = QLabel(objectName="PageSubtitle")
        self.summary.setWordWrap(True)
        body.addWidget(self.summary)

        choice = QHBoxLayout()
        self.case_selector = QComboBox()
        self.case_selector.setMinimumWidth(270)
        self.case_selector.currentIndexChanged.connect(self._show_case)
        choice.addWidget(self.case_selector, 2)
        self.decision = QComboBox()
        for label in VALID_DECISIONS:
            self.decision.addItem(label, label)
        choice.addWidget(self.decision, 1)
        body.addLayout(choice)
        self.finding = QLabel(objectName="PageSubtitle")
        self.finding.setWordWrap(True)
        body.addWidget(self.finding)
        reason_row = QHBoxLayout()
        self.reason = QLineEdit()
        self.reason.setPlaceholderText("Begründung / Lieferantenbefund (optional)")
        reason_row.addWidget(self.reason, 1)
        self.save_button = QPushButton("Bewertung speichern")
        self.save_button.clicked.connect(self._save)
        reason_row.addWidget(self.save_button)
        body.addLayout(reason_row)
        actions = QHBoxLayout()
        self.export_button = QPushButton("FIN-Liste als CSV exportieren")
        self.export_button.clicked.connect(self._export)
        actions.addWidget(self.export_button)
        self.handoff_button = QPushButton("Bestätigte NTF-FINs zur Clusteranalyse übergeben")
        self.handoff_button.clicked.connect(self._handoff)
        actions.addWidget(self.handoff_button)
        body.addLayout(actions)
        self.handoff_note = QLabel(
            "Die Übergabe speichert nur die freigegebene FIN-Kohorte; "
            "die eigentliche Clusterbildung folgt separat.",
            objectName="PageSubtitle",
        )
        self.handoff_note.setWordWrap(True)
        body.addWidget(self.handoff_note)
        self.refresh()

    def refresh(self) -> None:
        source = self.workflow.active_source()
        rows = self.workflow.rows(self.qec_root)
        self._rows = rows
        self.source_label.setText(
            f"Aktuelle QEC-FIN-Liste: {source.original_name} · SHA-256 {source.sha256[:12]}…"
            if source else "Keine aktive QEC-generierte FIN-Liste. "
                           "Bitte eine QEC-Excel-Datei unter Datenquellen importieren."
        )
        stats = self.workflow.overview(self.qec_root)
        self.step1.setText(f"01  QEC-generierte FIN-Liste · {stats['fins']} FINs / {stats['cases']} Fälle")
        self.step2.setText(
            f"02  QEC-Tool Befundungsberichte · {stats['downloaded']} von {stats['fins']} FINs heruntergeladen"
        )
        self.progress.setValue(round(100 * stats["downloaded"] / max(stats["fins"], 1)))
        self.summary.setText(
            f"NTF: {stats['ntf']} · Kein NTF: {stats['not_ntf']} · "
            f"Offen: {stats['open']} (je QEC-Fall; keine automatische Lieferantenschuld-Zuordnung)"
        )
        old = self.case_selector.currentData()
        self.case_selector.blockSignals(True)
        self.case_selector.clear()
        for row in rows:
            self.case_selector.addItem(
                f"{row['case_id']} · {row['fin']}", row["case_id"]
            )
        index = self.case_selector.findData(old)
        if index >= 0:
            self.case_selector.setCurrentIndex(index)
        self.case_selector.blockSignals(False)
        enabled = bool(source and rows)
        for control in (self.case_selector, self.decision, self.reason,
                        self.save_button, self.export_button, self.handoff_button):
            control.setEnabled(enabled)
        self._show_case()

    def _show_case(self, *_args) -> None:
        selected = self.case_selector.currentData()
        row = next((r for r in self._rows if r["case_id"] == selected), None)
        self.finding.setText(
            f"SSL-Endbefund: {row['finding'] or 'Nicht vorhanden'}"
            if row else "Kein Fall ausgewählt."
        )
        index = self.decision.findData(row["decision"]) if row else 0
        self.decision.setCurrentIndex(max(index, 0))
        self.reason.setText(row["reason"] if row else "")

    def _save(self) -> None:
        source = self.workflow.active_source()
        if source is None or not self.case_selector.currentData():
            return
        try:
            self.workflow.set_decision(
                source.sha256, self.case_selector.currentData(),
                self.decision.currentData(), self.reason.text(),
            )
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "QEC-Bewertung", str(exc))
            return
        self.refresh()

    def _export(self) -> None:
        filename, _ = QFileDialog.getSaveFileName(
            self, "QEC-FIN-Liste exportieren", "QEC_FIN_Bewertung.csv", "CSV (*.csv)",
        )
        if not filename:
            return
        path = Path(filename)
        if path.suffix.lower() != ".csv":
            path = path.with_suffix(".csv")
        try:
            count = self.workflow.export_csv(path, self.qec_root)
        except (OSError, ValueError):
            QMessageBox.warning(self, "CSV-Export", "Die Datei konnte nicht gespeichert werden.")
            return
        QMessageBox.information(self, "CSV-Export", f"{count} QEC-Fälle lokal exportiert.")

    def _handoff(self) -> None:
        if QMessageBox.question(
            self, "NTF-FIN-Übergabe",
            "Nur FINs mit ausschließlich bestätigten NTF-Fällen "
            "für die spätere Clusteranalyse vormerken?",
        ) != QMessageBox.StandardButton.Yes:
            return
        count = self.workflow.handoff_ntf(self.qec_root)
        self.handoff_note.setText(
            f"{count} bestätigte NTF-FINs lokal vorgemerkt. "
            "Die Clusteranalyse wird in einem folgenden Schritt angebunden."
        )
