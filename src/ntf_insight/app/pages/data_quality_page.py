"""Data-quality readiness view."""

from __future__ import annotations

from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QLabel, QTableView, QVBoxLayout, QWidget

from ntf_insight.analysis.data_quality import assess_data_quality
from ntf_insight.analysis.integrity import validate_case_integrity
from ntf_insight.app.models.simple_table_model import SimpleTableModel
from ntf_insight.storage.reference_repositories import ReferenceRepository
from ntf_insight.storage.repositories import CaseRepository


class DataQualityPage(QWidget):
    def __init__(self, cases: CaseRepository, references: ReferenceRepository) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(14)

        layout.addWidget(QLabel("Data Quality", objectName="PageTitle"))
        subtitle = QLabel(
            "Analysis readiness is checked explicitly so missing data is never silently interpreted "
            "as a negative finding.",
            objectName="PageSubtitle",
        )
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        rows: list[tuple[object, ...]] = []
        for case in cases.list_cases():
            report = assess_data_quality(case, references)
            integrity = validate_case_integrity(case)
            ratio = report.trigger_coverage_ratio
            rows.append(
                (
                    case.case_id,
                    case.vin,
                    report.status_for("replacement_anchor"),
                    report.status_for("pre_test"),
                    report.status_for("post_test"),
                    report.status_for("supplier_finding"),
                    report.status_for("software_history"),
                    f"{ratio:.0%}" if ratio is not None else None,
                    integrity.error_count,
                    report.issue_count,
                )
            )

        model = SimpleTableModel(
            (
                "Case",
                "FIN / VIN",
                "Replacement",
                "Pre test",
                "Post test",
                "Supplier finding",
                "SW history",
                "Trigger coverage",
                "Integrity errors",
                "Completeness issues",
            ),
            rows,
        )
        table = QTableView()
        table.setModel(model)
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSortingEnabled(True)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(table, 1)
        self.model = model
