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

from ntf_insight.app.models.vehicle_table_model import VehicleTableModel


class VehiclesPage(QWidget):
    """Vehicle/FIN explorer backed by Qt's model/view architecture."""

    def __init__(self) -> None:
        super().__init__()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(14)

        layout.addWidget(QLabel("Vehicles", objectName="PageTitle"))
        layout.addWidget(
            QLabel(
                "Search and inspect vehicles once the first diagnostic data is imported.",
                objectName="PageSubtitle",
            )
        )

        search = QLineEdit()
        search.setPlaceholderText("Search FIN / VIN …")
        search.setClearButtonEnabled(True)
        layout.addWidget(search)

        self.model = VehicleTableModel()
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
