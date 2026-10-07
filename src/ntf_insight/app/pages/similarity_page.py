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

        layout.addWidget(QLabel("Ähnlichkeit / Cluster", objectName="PageTitle"))
        subtitle = QLabel(
            "Dies ist eine erklärbare Basis-Ähnlichkeit und noch kein HDBSCAN-Clustering. "
            "Damit lässt sich das Feature-Verhalten prüfen, bevor reale Daten und ML ergänzt werden.",
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
                    "Ja" if result.same_recurrence_pattern else "Nein",
                )
            )

        model = SimpleTableModel(
            ("Fall A", "Fall B", "Ähnlichkeit", "Gemeinsame DTCs", "Gemeinsame Steuergeräte", "Gleiches Wiederholungsmuster"),
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
