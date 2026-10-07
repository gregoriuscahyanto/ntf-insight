"""Case detail and timeline page."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QGridLayout,
    QHeaderView,
    QLabel,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ntf_insight.analysis.recurrence import analyze_recurrence, format_faults
from ntf_insight.analysis.timeline import build_timeline
from ntf_insight.app.models.timeline_table_model import TimelineTableModel
from ntf_insight.storage.repositories import CaseRepository


class CasePage(QWidget):
    """Inspect one case, its assessment and the pre/post replacement timeline."""

    def __init__(self, repository: CaseRepository) -> None:
        super().__init__()
        self.repository = repository

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(14)

        layout.addWidget(QLabel("Cases", objectName="PageTitle"))
        layout.addWidget(
            QLabel(
                "Synthetic examples are shown until the real short-test and replacement files are connected.",
                objectName="PageSubtitle",
            )
        )

        self.selector = QComboBox()
        for case in repository.list_cases():
            self.selector.addItem(f"{case.case_id} · {case.vin}", case.case_id)
        self.selector.currentIndexChanged.connect(self._refresh)
        layout.addWidget(self.selector)

        summary = QGridLayout()
        summary.setHorizontalSpacing(24)
        summary.setVerticalSpacing(6)

        self.component_value = QLabel("—")
        self.replacement_value = QLabel("—")
        self.root_cause_value = QLabel("—")
        self.supplier_value = QLabel("—")
        self.confidence_value = QLabel("—")
        self.recurrence_value = QLabel("—")

        fields = (
            ("Component", self.component_value),
            ("Replacement", self.replacement_value),
            ("Root cause", self.root_cause_value),
            ("Supplier involvement", self.supplier_value),
            ("Confidence", self.confidence_value),
            ("Same fault after swap", self.recurrence_value),
        )
        for index, (title, value) in enumerate(fields):
            label = QLabel(title, objectName="CardTitle")
            value.setStyleSheet("font-weight: 600;")
            summary.addWidget(label, index // 3 * 2, index % 3)
            summary.addWidget(value, index // 3 * 2 + 1, index % 3)
        layout.addLayout(summary)

        self.assessment_text = QLabel("—", objectName="PageSubtitle")
        self.assessment_text.setWordWrap(True)
        layout.addWidget(self.assessment_text)

        self.recurrence_text = QLabel("—", objectName="PageSubtitle")
        self.recurrence_text.setWordWrap(True)
        layout.addWidget(self.recurrence_text)

        layout.addWidget(QLabel("Timeline", objectName="CardTitle"))
        self.timeline_model = TimelineTableModel()
        self.timeline = QTableView()
        self.timeline.setModel(self.timeline_model)
        self.timeline.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.timeline.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.timeline.setAlternatingRowColors(True)
        self.timeline.verticalHeader().setVisible(False)
        header = self.timeline.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setStretchLastSection(True)
        layout.addWidget(self.timeline, 1)

        if self.selector.count():
            self._refresh()

    def _refresh(self) -> None:
        case_id = self.selector.currentData()
        case = self.repository.get_case(case_id) if case_id else None
        if case is None:
            return

        replacement = case.investigated_replacement()
        recurrence = analyze_recurrence(case)
        assessment = case.assessment

        self.component_value.setText(case.component_type)
        self.replacement_value.setText(
            replacement.occurred_at.strftime("%Y-%m-%d") if replacement else "Missing"
        )
        self.root_cause_value.setText(str(assessment.root_cause) if assessment else "Not assessed")
        self.supplier_value.setText(
            str(assessment.supplier_involvement) if assessment else "Unknown"
        )
        self.confidence_value.setText(str(assessment.confidence) if assessment else "—")

        if not recurrence.assessable:
            recurrence_label = "Insufficient data"
        else:
            recurrence_label = "Yes" if recurrence.has_recurrence else "No"
        self.recurrence_value.setText(recurrence_label)

        self.assessment_text.setText(
            assessment.summary if assessment and assessment.summary else "No assessment available."
        )

        if recurrence.replacement is None:
            recurrence_summary = "No investigated component replacement is available."
        elif not recurrence.assessable:
            missing = []
            if not recurrence.has_pre_test:
                missing.append("pre-replacement short test")
            if not recurrence.has_post_test:
                missing.append("post-replacement short test")
            recurrence_summary = "Recurrence cannot be assessed reliably; missing " + " and ".join(missing) + "."
        else:
            elapsed = (
                f"{recurrence.first_recurrence_after.days} d"
                if recurrence.first_recurrence_after is not None
                else "—"
            )
            distance = (
                f"{recurrence.distance_to_recurrence_km} km"
                if recurrence.distance_to_recurrence_km is not None
                else "—"
            )
            recurrence_summary = (
                f"Same: {format_faults(recurrence.same_faults)}  |  "
                f"Disappeared: {format_faults(recurrence.disappeared_faults)}  |  "
                f"New: {format_faults(recurrence.new_faults)}  |  "
                f"First recurrence: {elapsed} / {distance}"
            )
        self.recurrence_text.setText(recurrence_summary)
        self.timeline_model.set_entries(build_timeline(case))
