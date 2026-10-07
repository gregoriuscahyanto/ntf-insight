"""Vehicle explorer page."""

from __future__ import annotations

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

from ntf_insight.analysis.recurrence import analyze_recurrence
from ntf_insight.app.models.vehicle_table_model import VehicleRow, VehicleTableModel
from ntf_insight.storage.repositories import CaseRepository


class VehiclesPage(QWidget):
    """Vehicle/FIN explorer backed by Qt's model/view architecture."""

    def __init__(self, repository: CaseRepository) -> None:
        super().__init__()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(14)

        layout.addWidget(QLabel("Vehicles", objectName="PageTitle"))
        layout.addWidget(
            QLabel(
                "Currently showing fictional demo vehicles; the same model will receive imported FINs later.",
                objectName="PageSubtitle",
            )
        )

        search = QLineEdit()
        search.setPlaceholderText("Search FIN / VIN …")
        search.setClearButtonEnabled(True)
        layout.addWidget(search)

        rows: list[VehicleRow] = []
        for case in repository.list_cases():
            replacement = case.investigated_replacement()
            recurrence = analyze_recurrence(case)
            if recurrence.assessable:
                recurrence_text = "Yes" if recurrence.has_recurrence else "No"
            else:
                recurrence_text = "Unknown"
            rows.append(
                VehicleRow(
                    vin=case.vin,
                    component=case.component_type,
                    dtc_count=len(case.diagnostics),
                    replacement=(
                        replacement.occurred_at.strftime("%Y-%m-%d")
                        if replacement is not None
                        else None
                    ),
                    recurrence=recurrence_text,
                    assessment=(
                        str(case.assessment.root_cause) if case.assessment is not None else None
                    ),
                )
            )

        self.model = VehicleTableModel(rows)
        self.proxy = QSortFilterProxyModel(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.proxy.setFilterKeyColumn(-1)
        search.textChanged.connect(self.proxy.setFilterFixedString)

        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSortingEnabled(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table, 1)
