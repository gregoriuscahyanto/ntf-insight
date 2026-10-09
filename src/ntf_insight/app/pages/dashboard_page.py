"""Dashboard page."""

from __future__ import annotations

from PySide6.QtWidgets import QGridLayout, QLabel, QVBoxLayout, QWidget

from ntf_insight.analysis.recurrence import analyze_recurrence
from ntf_insight.app.widgets.status_card import StatusCard
from ntf_insight.domain.enums import RootCauseCategory
from ntf_insight.storage.repositories import CaseRepository
from ntf_insight.storage.quicktest_store import QuickTestStore


class DashboardPage(QWidget):
    """Overview page backed by the current case repository."""

    def __init__(
        self,
        repository: CaseRepository,
        mode: str = "demo",
        quicktests: QuickTestStore | None = None,
    ) -> None:
        super().__init__()

        cases = repository.list_cases()
        fin_ids = {case.vin for case in cases}
        fin_ids.update(quicktests.list_fins() if quicktests is not None else [])
        quicktest_total = (
            quicktests.statistics()["reports"] if quicktests is not None else 0
        )
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
        cards.addWidget(StatusCard("Fahrzeuge", str(len(fin_ids)), "FIN mit Diagnosen oder NTF-Fall"), 0, 0)
        cards.addWidget(StatusCard("NTF-Fälle", str(len(cases)), "Aktueller Analyseumfang"), 0, 1)
        cards.addWidget(StatusCard("Wiederholungen", str(recurrence_count), "Gleicher DTC nach Tausch"), 0, 2)
        cards.addWidget(StatusCard("Ungeklärt", str(unresolved_count), "Weitere Evidenz erforderlich"), 0, 3)
        cards.addWidget(
            StatusCard(
                "QuickTests", str(quicktest_total),
                "FIN-basierte Diagnoseberichte (auch ohne QEC-Fall)"
            ),
            1, 0,
        )
        layout.addLayout(cards)

        next_title = QLabel("Pipeline-Status", objectName="PageTitle")
        next_title.setStyleSheet("font-size: 18px;")
        layout.addWidget(next_title)

        next_steps = QLabel(
            "Domänenmodell, Fall-Timeline und Vorher-/Nachher-Analyse sind in die Desktop-App integriert. "
            "Der QuickTest-Parser liest FIN-Diagnosen auch ohne Schadteilfall. "
            "QEC-Fälle, Werkstattdaten und weitere Quellen ergänzen die "
            "Vorher-/Nachher-Analyse, sobald eine eindeutige Zuordnung vorliegt.",
            objectName="PageSubtitle",
        )
        next_steps.setWordWrap(True)
        layout.addWidget(next_steps)
        layout.addStretch(1)
