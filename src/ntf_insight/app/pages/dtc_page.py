"""DTC explorer page linking field observations to trigger and release knowledge."""

from __future__ import annotations

from collections import defaultdict

from PySide6.QtCore import QSortFilterProxyModel, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ntf_insight.app.models.simple_table_model import SimpleTableModel
from ntf_insight.storage.reference_repositories import ReferenceRepository
from ntf_insight.storage.repositories import CaseRepository


class DTCExplorerPage(QWidget):
    def __init__(self, cases: CaseRepository, references: ReferenceRepository) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(14)

        layout.addWidget(QLabel("DTC Explorer", objectName="PageTitle"))
        subtitle = QLabel(
            "Observed DTCs linked to synthetic trigger definitions and HW/SW change history. "
            "Real SMR-D content will replace the demo catalog later.",
            objectName="PageSubtitle",
        )
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        search = QLineEdit()
        search.setPlaceholderText("Search ECU, DTC, text, trigger, tag …")
        search.setClearButtonEnabled(True)
        layout.addWidget(search)

        groups: dict[tuple[str, str], dict[str, object]] = defaultdict(
            lambda: {"vehicles": set(), "events": 0, "text": None}
        )
        for case in cases.list_cases():
            for event in case.diagnostics:
                key = event.fault_key
                groups[key]["vehicles"].add(case.vin)
                groups[key]["events"] += 1
                if not groups[key]["text"] and event.dtc_text:
                    groups[key]["text"] = event.dtc_text

        rows: list[tuple[object, ...]] = []
        for (ecu, dtc), data in sorted(groups.items()):
            trigger = references.find_trigger(ecu, dtc)
            changes = references.find_changes_for_dtc(ecu, dtc)
            rows.append(
                (
                    ecu,
                    dtc,
                    data["text"],
                    len(data["vehicles"]),
                    data["events"],
                    "Yes" if trigger else "No",
                    ", ".join(trigger.semantic_tags) if trigger else None,
                    trigger.trigger_text if trigger else None,
                    len(changes),
                )
            )

        self.model = SimpleTableModel(
            (
                "ECU",
                "DTC",
                "DTC text",
                "Vehicles",
                "Events",
                "Trigger",
                "Tags",
                "Trigger summary",
                "HW/SW changes",
            ),
            rows,
        )
        self.proxy = QSortFilterProxyModel(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.proxy.setFilterKeyColumn(-1)
        search.textChanged.connect(self.proxy.setFilterFixedString)

        table = QTableView()
        table.setModel(self.proxy)
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSortingEnabled(True)
        table.verticalHeader().setVisible(False)
        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setStretchLastSection(True)
        layout.addWidget(table, 1)
