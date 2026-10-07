"""Data-source readiness, raw archive and provenance view."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ntf_insight.app.models.simple_table_model import SimpleTableModel
from ntf_insight.ingestion.artifacts import SourceType
from ntf_insight.ingestion.service import SourceImportService
from ntf_insight.storage.reference_repositories import ReferenceRepository
from ntf_insight.storage.repositories import CaseRepository


class SourcesPage(QWidget):
    def __init__(
        self,
        cases: CaseRepository,
        references: ReferenceRepository,
        mode: str = "demo",
        data_dir: str | None = None,
        raw_dir: str | None = None,
        database_path: str | None = None,
    ) -> None:
        super().__init__()
        self.import_service = (
            SourceImportService(Path(raw_dir), Path(database_path))
            if raw_dir and database_path
            else None
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(14)

        layout.addWidget(QLabel("Data Sources", objectName="PageTitle"))
        location = f" Local data directory: {data_dir}." if data_dir else ""
        subtitle = QLabel(
            "Original files are archived unchanged with SHA-256 provenance before parsing. "
            "Concrete parsers stay format-neutral until representative source files are available. "
            f"Mode: {mode}.{location}",
            objectName="PageSubtitle",
        )
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        case_count = len(cases.list_cases())
        trigger_count = len(references.list_triggers())
        change_count = len(references.list_changes())
        readiness_rows = [
            ("Case / FIN list", "Case scope and vehicle identity", "Canonical model ready", f"{case_count} loaded cases"),
            ("Short tests", "Diagnostic sessions, DTCs, ECU states", "Contract ready; concrete format pending", "Awaiting original sample"),
            ("Replacement list", "Pre/post anchor, part metadata", "Contract ready; concrete format pending", "Awaiting original sample"),
            ("Supplier findings", "Returned-part result / NTF evidence", "Contract ready; concrete format pending", "Awaiting original sample"),
            ("SMR-D", "DTC trigger / enable / healing logic", "Contract ready; concrete format pending", f"{trigger_count} loaded definitions"),
            ("HW/SW change history", "Release changes and affected DTCs/functions", "Contract ready; concrete format pending", f"{change_count} loaded changes"),
            ("Vehicle HW/SW state", "Actual ECU state per VIN / short test", "Canonical model ready", "Awaiting original sample"),
            ("Workshop / claim history", "Complaint, diagnosis and actions", "Contract ready; concrete format pending", "Awaiting original sample"),
            ("Installed population", "Denominators for supplier/part rates", "Canonical model ready", "Awaiting original sample"),
        ]

        readiness_model = SimpleTableModel(
            ("Source", "Purpose", "Implementation", "Current data"), readiness_rows
        )
        readiness_table = QTableView()
        readiness_table.setModel(readiness_model)
        readiness_table.setMaximumHeight(275)
        readiness_table.setAlternatingRowColors(True)
        readiness_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        readiness_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        readiness_table.verticalHeader().setVisible(False)
        readiness_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(readiness_table)
        self.readiness_model = readiness_model

        layout.addWidget(QLabel("Raw source archive", objectName="CardTitle"))
        controls = QHBoxLayout()
        self.source_type = QComboBox()
        labels = {
            SourceType.VEHICLE_CASE_LIST: "Case / FIN list",
            SourceType.SHORT_TEST: "Short test",
            SourceType.REPLACEMENT_LIST: "Replacement list",
            SourceType.SUPPLIER_FINDING: "Supplier finding",
            SourceType.WORKSHOP_HISTORY: "Workshop / claim history",
            SourceType.SMR_D: "SMR-D",
            SourceType.HW_SW_CHANGE_HISTORY: "HW/SW change history",
            SourceType.VEHICLE_SOFTWARE_HISTORY: "Vehicle software history",
            SourceType.INSTALLED_POPULATION: "Installed population",
            SourceType.COMPONENT_MASTER_DATA: "Component / supplier master data",
            SourceType.OTHER: "Other",
        }
        for source_type, label in labels.items():
            self.source_type.addItem(label, source_type)
        controls.addWidget(self.source_type)

        self.source_system = QLineEdit()
        self.source_system.setPlaceholderText("Source system (optional)")
        self.source_system.setMaximumWidth(190)
        controls.addWidget(self.source_system)

        self.vin_hint = QLineEdit()
        self.vin_hint.setPlaceholderText("FIN / VIN hint (optional)")
        self.vin_hint.setMaximumWidth(210)
        controls.addWidget(self.vin_hint)

        self.archive_button = QPushButton("Archive source file…")
        self.archive_button.setEnabled(self.import_service is not None)
        self.archive_button.clicked.connect(self._archive_file)
        controls.addWidget(self.archive_button)
        controls.addStretch(1)
        layout.addLayout(controls)

        self.import_status = QLabel(
            "Files can already be archived safely even before a parser exists.",
            objectName="PageSubtitle",
        )
        self.import_status.setWordWrap(True)
        layout.addWidget(self.import_status)

        self.artifact_model = SimpleTableModel(
            ("File", "Source type", "System", "FIN / VIN hint", "Size", "SHA-256", "Parse status", "Imported")
        )
        artifact_table = QTableView()
        artifact_table.setModel(self.artifact_model)
        artifact_table.setAlternatingRowColors(True)
        artifact_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        artifact_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        artifact_table.verticalHeader().setVisible(False)
        artifact_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(artifact_table, 1)
        self._refresh_artifacts()

    def _archive_file(self) -> None:
        if self.import_service is None:
            return
        filename, _ = QFileDialog.getOpenFileName(self, "Archive source file")
        if not filename:
            return
        source_type = self.source_type.currentData()
        try:
            artifact = self.import_service.import_raw(
                Path(filename),
                source_type,
                source_system=self.source_system.text().strip() or None,
                vin_hint=self.vin_hint.text().strip() or None,
            )
        except Exception as exc:  # GUI boundary: keep the app alive and surface the error.
            self.import_status.setText(f"Import failed: {exc}")
            return
        self.import_status.setText(
            f"Archived {artifact.original_name} · {artifact.sha256[:12]}… · "
            f"{artifact.size_bytes:,} bytes"
        )
        self._refresh_artifacts()

    def _refresh_artifacts(self) -> None:
        if self.import_service is None:
            self.artifact_model.set_rows([])
            return
        rows = []
        for artifact in self.import_service.list_artifacts():
            runs = self.import_service.store.load_parse_runs(artifact.sha256)
            latest = runs[-1] if runs else None
            parse_status = (
                f"{latest.status} · {latest.parser_name} {latest.parser_version}"
                if latest is not None
                else "Not parsed"
            )
            rows.append(
                (
                    artifact.original_name,
                    str(artifact.source_type),
                    artifact.source_system,
                    artifact.vin_hint,
                    f"{artifact.size_bytes:,} B",
                    artifact.sha256,
                    parse_status,
                    artifact.imported_at.astimezone().strftime("%Y-%m-%d %H:%M"),
                )
            )
        self.artifact_model.set_rows(rows)
