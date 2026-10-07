"""Data-source readiness and ingestion overview."""

from __future__ import annotations

from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QLabel, QTableView, QVBoxLayout, QWidget

from ntf_insight.app.models.simple_table_model import SimpleTableModel
from ntf_insight.storage.reference_repositories import ReferenceRepository
from ntf_insight.storage.repositories import CaseRepository


class SourcesPage(QWidget):
    def __init__(
        self,
        cases: CaseRepository,
        references: ReferenceRepository,
        mode: str = "demo",
        data_dir: str | None = None,
    ) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(14)

        layout.addWidget(QLabel("Data Sources", objectName="PageTitle"))
        location = f" Local data directory: {data_dir}." if data_dir else ""
        subtitle = QLabel(
            "The ingestion contracts and raw-file archive are prepared. Concrete parsers stay "
            "format-neutral until representative original files are available. "
            f"Mode: {mode}.{location}",
            objectName="PageSubtitle",
        )
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        case_count = len(cases.list_cases())
        trigger_count = len(references.list_triggers())
        change_count = len(references.list_changes())
        rows = [
            ("Case / FIN list", "Case scope and vehicle identity", "Generic model ready", f"{case_count} synthetic cases"),
            ("Short tests", "Diagnostic sessions, DTCs, ECU states", "Contract ready; concrete format pending", "Awaiting original sample"),
            ("Replacement list", "Pre/post anchor, part metadata", "Canonical model ready", "Awaiting original sample"),
            ("Supplier findings", "Returned-part result / NTF evidence", "Canonical model ready", "Awaiting original sample"),
            ("SMR-D", "DTC trigger / enable / healing logic", "Contract ready; concrete format pending", f"{trigger_count} synthetic definitions"),
            ("HW/SW change history", "Release changes and affected DTCs/functions", "Contract ready; concrete format pending", f"{change_count} synthetic changes"),
            ("Vehicle HW/SW state", "Actual ECU state per VIN / short test", "Canonical model ready", "Awaiting original sample"),
            ("Workshop / claim history", "Complaint, diagnosis and actions", "Canonical model ready", "Awaiting original sample"),
        ]

        model = SimpleTableModel(("Source", "Purpose", "Implementation", "Current data"), rows)
        table = QTableView()
        table.setModel(model)
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(table, 1)
        self.model = model
