"""German probabilistic diagnosis view with explicit expert-confirmation workflow."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QFormLayout, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMessageBox, QPushButton, QTableView, QVBoxLayout, QWidget,
)

from ntf_insight.analysis.root_cause_ml import train_root_cause_model
from ntf_insight.app.models.simple_table_model import SimpleTableModel
from ntf_insight.domain.enums import RootCauseCategory
from ntf_insight.storage.ml_feedback import MLFeedbackStore
from ntf_insight.storage.repositories import CaseRepository


CAUSE_DE = {
    RootCauseCategory.COMPONENT_SUPPLIER: "Bauteil / Lieferant",
    RootCauseCategory.ELECTRICAL_SUPPLY: "Spannungsversorgung",
    RootCauseCategory.WIRING_CONNECTOR: "Leitung / Steckverbindung",
    RootCauseCategory.ECU_SOFTWARE: "Steuergerät / Software",
    RootCauseCategory.VEHICLE_SYSTEM: "Fahrzeugsystem",
    RootCauseCategory.WORKSHOP_PROCESS: "Werkstatt / Prozess",
}


class PredictionPage(QWidget):
    def __init__(self, repository: CaseRepository, database_path: str, mode: str) -> None:
        super().__init__()
        self.repository = repository
        self.feedback = MLFeedbackStore(database_path)
        self.mode = mode

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(12)
        layout.addWidget(QLabel("KI-Ursachenprognose", objectName="PageTitle"))
        self.status = QLabel(objectName="PageSubtitle")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        self.table = QTableView()
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table, 1)

        layout.addWidget(QLabel("Fachlich bestätigte Ursache erfassen", objectName="PageTitle"))
        form = QFormLayout()
        self.case_selector = QComboBox()
        for case in repository.list_cases():
            if case.component_type.casefold() == "coolant pump":
                self.case_selector.addItem(case.case_id, case.case_id)
        self.cause_selector = QComboBox()
        for cause, name in CAUSE_DE.items():
            self.cause_selector.addItem(name, cause.value)
        self.reviewer = QLineEdit()
        self.reviewer.setPlaceholderText("Name / fachliche Kennung")
        self.evidence = QLineEdit()
        self.evidence.setPlaceholderText("Befundungsbericht / 8D-Fall / Prüfreferenz")
        form.addRow("Fall", self.case_selector)
        form.addRow("Bestätigte Ursache", self.cause_selector)
        form.addRow("Prüfer", self.reviewer)
        form.addRow("Evidenzquelle", self.evidence)
        layout.addLayout(form)

        buttons = QHBoxLayout()
        self.confirm_button = QPushButton("Bestätigung speichern und Modell prüfen")
        self.confirm_button.clicked.connect(self._confirm)
        buttons.addWidget(self.confirm_button)
        self.refresh_button = QPushButton("Prognosen aktualisieren")
        self.refresh_button.clicked.connect(self.refresh)
        buttons.addWidget(self.refresh_button)
        layout.addLayout(buttons)
        self.refresh()

    def _confirm(self) -> None:
        if self.case_selector.currentData() is None:
            QMessageBox.warning(self, "Kein Fall", "Bitte zuerst einen Fall auswählen.")
            return
        if not self.reviewer.text().strip() or not self.evidence.text().strip():
            QMessageBox.warning(self, "Unvollständig", "Prüfer und Evidenzquelle sind erforderlich.")
            return
        answer = QMessageBox.question(
            self, "Ursache bestätigen",
            "Ist diese Ursache durch eine unabhängige fachliche Prüfung tatsächlich bestätigt? "
            "Bloße Hypothesen dürfen nicht als Trainingslabel gespeichert werden.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.feedback.confirm(
            str(self.case_selector.currentData()),
            RootCauseCategory(self.cause_selector.currentData()),
            self.reviewer.text().strip(),
            self.evidence.text().strip(),
        )
        self.refresh()

    def refresh(self) -> None:
        labels = self.feedback.list_confirmed()
        result = train_root_cause_model(self.repository.list_cases(), labels)
        if self.mode == "demo":
            self.status.setText(
                "DEMO / SYNTHETISCHE DATEN. Keine produktiv gültigen Ursachenwahrscheinlichkeiten. "
                f"Bestätigte Trainingsfälle: {result.eligible_count}. {result.message}"
            )
        elif result.model is None:
            self.status.setText(
                f"Modell noch nicht bereit. Bestätigte Fälle: {result.eligible_count}. "
                + result.message
            )
        else:
            m = result.model.metrics
            self.status.setText(
                f"Retrospektive ML-Prognose · {result.eligible_count} bestätigte Fälle · "
                f"Test: {m.test_count} Fälle / {m.test_groups} Fahrzeuge · "
                f"Trefferquote: {m.accuracy:.0%} · Brier: {m.brier_score:.3f}. "
                "Wahrscheinlichkeiten sind Hypothesen, kein Verursachernachweis. "
                "Nicht trainierte Klassen sind nicht bewertbar."
            )

        headings = ("Fall", "Top-Ursache", "Top-Prognose", "Prüfung", *CAUSE_DE.values(), "Hinweise")
        rows = []
        if result.model is not None and self.mode != "demo":
            for prediction in result.model.predict_many(self.repository.list_cases()):
                probs = dict(prediction.probabilities)
                rows.append((
                    prediction.case_id,
                    CAUSE_DE.get(prediction.top_cause, prediction.top_cause.value),
                    f"{prediction.top_probability:.1%}",
                    "Erforderlich" if prediction.review_required else "Empfohlen",
                    *(f"{probs[cause]:.1%}" if cause in probs else "nicht trainiert"
                      for cause in CAUSE_DE),
                    "; ".join((*prediction.review_notes, *prediction.supporting_model_features)),
                ))
        self.model = SimpleTableModel(headings, rows)
        self.table.setModel(self.model)
