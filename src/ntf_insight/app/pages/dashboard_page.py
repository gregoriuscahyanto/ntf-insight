"""Dashboard page."""

from __future__ import annotations

from PySide6.QtWidgets import QGridLayout, QLabel, QVBoxLayout, QWidget

from ntf_insight.analysis.recurrence import analyze_recurrence
from ntf_insight.app.widgets.status_card import StatusCard
from ntf_insight.domain.enums import RootCauseCategory
from ntf_insight.storage.repositories import CaseRepository


class DashboardPage(QWidget):
    """Overview page backed by the current case repository."""

    def __init__(self, repository: CaseRepository, mode: str = "demo") -> None:
        super().__init__()

        cases = repository.list_cases()
        recurrence_results = [analyze_recurrence(case) for case in cases]
        recurrence_count = sum(
            result.assessable and result.has_recurrence for result in recurrence_results
        )
        unresolved_count = sum(
            case.assessment is None
            or case.assessment.root_cause == RootCauseCategory.UNKNOWN
            for case in cases
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(18)

        title = QLabel("Übersicht", objectName="PageTitle")
        subtitle_text = (
            "Aktuell werden fiktive Demo-Fälle angezeigt, bis echte Quelldateien importiert wurden."
            if mode == "demo"
            else "Aktuelle Werte werden aus dem lokalen NTF-Insight-Datenspeicher geladen."
        )
        subtitle = QLabel(
            subtitle_text,
            objectName="PageSubtitle",
        )
        layout.addWidget(title)
        layout.addWidget(subtitle)

        cards = QGridLayout()
        cards.setHorizontalSpacing(14)
        cards.setVerticalSpacing(14)
        cards.addWidget(StatusCard("Fahrzeuge", str(len({case.vin for case in cases})), "Geladene Fahrzeuge"), 0, 0)
        cards.addWidget(StatusCard("NTF-Fälle", str(len(cases)), "Aktueller Analyseumfang"), 0, 1)
        cards.addWidget(StatusCard("Wiederholungen", str(recurrence_count), "Gleicher DTC nach Tausch"), 0, 2)
        cards.addWidget(StatusCard("Ungeklärt", str(unresolved_count), "Weitere Evidenz erforderlich"), 0, 3)
        layout.addLayout(cards)

        next_title = QLabel("Pipeline-Status", objectName="PageTitle")
        next_title.setStyleSheet("font-size: 18px;")
        layout.addWidget(next_title)

        next_steps = QLabel(
            "Domänenmodell, Fall-Timeline und Vorher-/Nachher-Analyse sind in die Desktop-App integriert. "
            "Der nächste quellenabhängige Schritt ist der Kurztest-Parser. Sobald echte Dateien "
            "vorliegen, werden die Demo-Fälle schrittweise durch normalisierte reale Fälle ersetzt.",
            objectName="PageSubtitle",
        )
        next_steps.setWordWrap(True)
        layout.addWidget(next_steps)
        layout.addStretch(1)
