"""Similarity baseline shown before ML clustering is introduced."""

from __future__ import annotations

from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QLabel, QTableView, QVBoxLayout, QWidget

from ntf_insight.analysis.similarity import all_pairwise_similarities
from ntf_insight.app.models.simple_table_model import SimpleTableModel
from ntf_insight.storage.repositories import CaseRepository


class SimilarityPage(QWidget):
    def __init__(self, repository: CaseRepository) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(14)

        layout.addWidget(QLabel("Similarity / Clusters", objectName="PageTitle"))
        subtitle = QLabel(
            "This is an explainable baseline similarity, not yet HDBSCAN clustering. "
            "It is useful for validating feature behaviour before real data and ML are added.",
            objectName="PageSubtitle",
        )
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        rows = []
        for result in all_pairwise_similarities(repository.list_cases()):
            shared_faults = ", ".join(f"{ecu}:{dtc}" for ecu, dtc in result.shared_faults)
            rows.append(
                (
                    result.left_case_id,
                    result.right_case_id,
                    f"{result.score:.0%}",
                    shared_faults or None,
                    ", ".join(result.shared_ecus) or None,
                    "Yes" if result.same_recurrence_pattern else "No",
                )
            )

        model = SimpleTableModel(
            ("Case A", "Case B", "Similarity", "Shared DTCs", "Shared ECUs", "Same recurrence"),
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
