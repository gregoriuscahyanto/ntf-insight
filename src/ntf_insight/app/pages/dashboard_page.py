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

        title = QLabel("Overview", objectName="PageTitle")
        subtitle_text = (
            "Current values come from fictional demo cases until real source files are imported."
            if mode == "demo"
            else "Current values are loaded from the local NTF Insight data store."
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
        cards.addWidget(StatusCard("Vehicles", str(len({case.vin for case in cases})), "Loaded vehicles"), 0, 0)
        cards.addWidget(StatusCard("NTF cases", str(len(cases)), "Current analysis scope"), 0, 1)
        cards.addWidget(StatusCard("Recurrences", str(recurrence_count), "Same DTC after replacement"), 0, 2)
        cards.addWidget(StatusCard("Unresolved", str(unresolved_count), "Needs more evidence"), 0, 3)
        layout.addLayout(cards)

        next_title = QLabel("Pipeline status", objectName="PageTitle")
        next_title.setStyleSheet("font-size: 18px;")
        layout.addWidget(next_title)

        next_steps = QLabel(
            "The domain model, case timeline and pre/post replacement analysis are now wired into "
            "the desktop app. The next source-dependent step is the short-test parser. When real "
            "files arrive, the synthetic repository will be replaced by normalized imported cases.",
            objectName="PageSubtitle",
        )
        next_steps.setWordWrap(True)
        layout.addWidget(next_steps)
        layout.addStretch(1)
