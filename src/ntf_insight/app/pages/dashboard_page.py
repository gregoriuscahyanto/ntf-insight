"""Dashboard page."""

from __future__ import annotations

from PySide6.QtWidgets import QGridLayout, QLabel, QVBoxLayout, QWidget

from ntf_insight.app.widgets.status_card import StatusCard


class DashboardPage(QWidget):
    """Initial overview page for NTF Insight."""

    def __init__(self) -> None:
        super().__init__()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(18)

        title = QLabel("Overview", objectName="PageTitle")
        subtitle = QLabel(
            "Vehicle-centred NTF analysis across components, diagnostics and field history.",
            objectName="PageSubtitle",
        )
        layout.addWidget(title)
        layout.addWidget(subtitle)

        cards = QGridLayout()
        cards.setHorizontalSpacing(14)
        cards.setVerticalSpacing(14)
        cards.addWidget(StatusCard("Vehicles", "—", "Imported cases"), 0, 0)
        cards.addWidget(StatusCard("NTF cases", "—", "Current analysis scope"), 0, 1)
        cards.addWidget(StatusCard("Recurrences", "—", "Fault after replacement"), 0, 2)
        cards.addWidget(StatusCard("Unresolved", "—", "Needs expert review"), 0, 3)
        layout.addLayout(cards)

        next_title = QLabel("First milestone", objectName="PageTitle")
        next_title.setStyleSheet("font-size: 18px;")
        layout.addWidget(next_title)

        next_steps = QLabel(
            "Import short-test results and replacement events, normalize DTCs, then build a "
            "vehicle timeline around the component replacement. Root-cause rules and clustering "
            "come after the data pipeline is trustworthy.",
            objectName="PageSubtitle",
        )
        next_steps.setWordWrap(True)
        layout.addWidget(next_steps)
        layout.addStretch(1)
