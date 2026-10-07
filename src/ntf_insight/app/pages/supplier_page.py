"""Supplier analytics page."""

from __future__ import annotations

from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QLabel, QTableView, QVBoxLayout, QWidget

from ntf_insight.analysis.supplier_metrics import build_supplier_summaries
from ntf_insight.app.models.simple_table_model import SimpleTableModel
from ntf_insight.storage.repositories import CaseRepository


class SupplierPage(QWidget):
    def __init__(self, repository: CaseRepository) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(14)

        layout.addWidget(QLabel("Suppliers", objectName="PageTitle"))
        subtitle = QLabel(
            "Raw case counts are shown separately from normalized rates. A supplier rate remains "
            "blank until installed-population denominator data is available.",
            objectName="PageSubtitle",
        )
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        rows = []
        for item in build_supplier_summaries(repository.list_cases()):
            rows.append(
                (
                    item.component_type,
                    item.supplier,
                    item.case_count,
                    item.return_ntf_count,
                    item.return_fault_found_count,
                    item.recurrence_count,
                    item.installed_units,
                    (
                        f"{item.ntf_per_1000_installed:.3f}"
                        if item.ntf_per_1000_installed is not None
                        else None
                    ),
                )
            )

        model = SimpleTableModel(
            (
                "Component",
                "Supplier",
                "Cases",
                "Return NTF",
                "Fault found",
                "Recurrences",
                "Installed units",
                "NTF / 1000",
            ),
            rows,
        )
        table = QTableView()
        table.setModel(model)
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(table, 1)
        self.model = model
