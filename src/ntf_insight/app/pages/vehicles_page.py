"""Vehicle explorer page."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)


class VehiclesPage(QWidget):
    """Placeholder vehicle/FIN explorer ready for a real table model."""

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

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["FIN / VIN", "Component", "DTCs", "Replacement", "Recurrence", "Assessment"]
        )
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table, 1)
