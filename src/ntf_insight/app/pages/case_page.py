"""Case detail, evidence and timeline page."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSortFilterProxyModel, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ntf_insight.analysis.evidence_engine import generate_case_evidence
from ntf_insight.analysis.recurrence import analyze_recurrence, format_faults
from ntf_insight.analysis.timeline import build_timeline
from ntf_insight.app.models.case_table_model import CaseRow, CaseTableModel
from ntf_insight.app.models.simple_table_model import SimpleTableModel
from ntf_insight.app.models.timeline_table_model import TimelineTableModel
from ntf_insight.app.widgets.event_time_plot import EventTimePlot
from ntf_insight.reporting.markdown import save_case_report
from ntf_insight.storage.reference_repositories import ReferenceRepository
from ntf_insight.storage.repositories import CaseRepository


class CasePage(QWidget):
    """Inspect one case, its evidence and the pre/post replacement timeline."""

    def __init__(self, repository: CaseRepository, references: ReferenceRepository) -> None:
        super().__init__()
        self.repository = repository
        self.references = references

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        scroll.setWidget(content)
        outer_layout.addWidget(scroll)

        layout = QVBoxLayout(content)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(12)

        layout.addWidget(QLabel("Fälle / FIN", objectName="PageTitle"))
        intro = QLabel(
            "Die Analyseeinheit ist die Kombination aus FIN/VIN und Fall. "
            "Eine FIN kann mehrere Fälle oder Austausche enthalten.",
            objectName="PageSubtitle",
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.selector = QComboBox()
        self.selector.setVisible(False)
        for case in repository.list_cases():
            self.selector.addItem(f"{case.case_id} · {case.vin}", case.case_id)
        self.selector.currentIndexChanged.connect(self._refresh)

        selector_row = QHBoxLayout()
        search = QLineEdit()
        search.setPlaceholderText("Fall, FIN / VIN, Bauteil oder Bewertung suchen …")
        search.setClearButtonEnabled(True)
        selector_row.addWidget(search, 1)

        export_button = QPushButton("Markdown-Bericht exportieren…")
        export_button.clicked.connect(self._export_report)
        selector_row.addWidget(export_button)
        layout.addLayout(selector_row)

        case_rows: list[CaseRow] = []
        for case in repository.list_cases():
            replacement = case.investigated_replacement()
            recurrence = analyze_recurrence(case)
            if recurrence.assessable:
                recurrence_text = "Ja" if recurrence.has_recurrence else "Nein"
            else:
                recurrence_text = "Unbekannt"
            case_rows.append(
                CaseRow(
                    case_id=case.case_id,
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

        self.case_model = CaseTableModel(case_rows)
        self.case_proxy = QSortFilterProxyModel(self)
        self.case_proxy.setSourceModel(self.case_model)
        self.case_proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.case_proxy.setFilterKeyColumn(-1)
        search.textChanged.connect(self.case_proxy.setFilterFixedString)

        self.case_table = QTableView()
        self.case_table.setModel(self.case_proxy)
        self.case_table.setMaximumHeight(190)
        self.case_table.setAlternatingRowColors(True)
        self.case_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.case_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.case_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.case_table.setSortingEnabled(True)
        self.case_table.verticalHeader().setVisible(False)
        self.case_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.case_table.clicked.connect(self._case_clicked)
        layout.addWidget(self.case_table)

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
            ("Bauteil", self.component_value),
            ("Tausch", self.replacement_value),
            ("Aktuelle Bewertung", self.root_cause_value),
            ("Lieferantenbeteiligung", self.supplier_value),
            ("Konfidenz", self.confidence_value),
            ("Gleicher Fehler nach Tausch", self.recurrence_value),
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

        layout.addWidget(QLabel("Zeitliches Auftreten", objectName="CardTitle"))
        time_hint = QLabel(
            "DTCs und relevante Ereignisse über die Zeit; die gestrichelte Linie markiert den Bauteiltausch.",
            objectName="PageSubtitle",
        )
        time_hint.setWordWrap(True)
        layout.addWidget(time_hint)
        self.time_plot = EventTimePlot()
        layout.addWidget(self.time_plot)

        layout.addWidget(QLabel("Generierte Evidenz", objectName="CardTitle"))
        self.evidence_model = SimpleTableModel(
            ("Signal", "Kategoriehinweis", "Richtung", "Vorläufiges Gewicht", "Beschreibung")
        )
        self.evidence_table = QTableView()
        self.evidence_table.setModel(self.evidence_model)
        self.evidence_table.setMaximumHeight(190)
        self.evidence_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.evidence_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.evidence_table.setAlternatingRowColors(True)
        self.evidence_table.verticalHeader().setVisible(False)
        evidence_header = self.evidence_table.horizontalHeader()
        evidence_header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        evidence_header.setStretchLastSection(True)
        layout.addWidget(self.evidence_table)

        self.evidence_balance = QLabel("—", objectName="PageSubtitle")
        self.evidence_balance.setWordWrap(True)
        layout.addWidget(self.evidence_balance)

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
            self.case_table.selectRow(0)
            self._refresh()

    def _case_clicked(self, index) -> None:
        source_index = self.case_proxy.mapToSource(self.case_proxy.index(index.row(), 0))
        case_id = self.case_model.case_id_at(source_index.row())
        if case_id is None:
            return
        selector_index = self.selector.findData(case_id)
        if selector_index >= 0:
            self.selector.setCurrentIndex(selector_index)

    def _refresh(self) -> None:
        case_id = self.selector.currentData()
        case = self.repository.get_case(case_id) if case_id else None
        if case is None:
            return

        replacement = case.investigated_replacement()
        recurrence = analyze_recurrence(case)
        assessment = case.assessment
        generated = generate_case_evidence(case, self.references)
        timeline_entries = build_timeline(case)

        self.component_value.setText(case.component_type)
        self.replacement_value.setText(
            replacement.occurred_at.strftime("%Y-%m-%d") if replacement else "Fehlt"
        )
        self.root_cause_value.setText(str(assessment.root_cause) if assessment else "Nicht bewertet")
        self.supplier_value.setText(
            str(assessment.supplier_involvement) if assessment else "Unbekannt"
        )
        self.confidence_value.setText(str(assessment.confidence) if assessment else "—")

        if not recurrence.assessable:
            recurrence_label = "Unzureichende Daten"
        else:
            recurrence_label = "Ja" if recurrence.has_recurrence else "Nein"
        self.recurrence_value.setText(recurrence_label)

        self.assessment_text.setText(
            assessment.summary if assessment and assessment.summary else "Keine Bewertung verfügbar."
        )

        if recurrence.replacement is None:
            recurrence_summary = "Kein untersuchter Bauteiltausch verfügbar."
        elif not recurrence.assessable:
            missing = []
            if not recurrence.has_pre_test:
                missing.append("Kurztest vor dem Tausch")
            if not recurrence.has_post_test:
                missing.append("Kurztest nach dem Tausch")
            recurrence_summary = (
                "Wiederauftreten kann nicht zuverlässig bewertet werden; es fehlt: " + " und ".join(missing) + "."
            )
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
                f"Gleich: {format_faults(recurrence.same_faults)}  |  "
                f"Verschwunden: {format_faults(recurrence.disappeared_faults)}  |  "
                f"Neu: {format_faults(recurrence.new_faults)}  |  "
                f"Erstes Wiederauftreten: {elapsed} / {distance}"
            )
        self.recurrence_text.setText(recurrence_summary)

        evidence_rows = [
            (
                item.code,
                str(item.category_hint) if item.category_hint else None,
                str(item.direction),
                f"{item.weight:.2f}",
                item.description,
            )
            for item in generated.evidence
        ]
        self.evidence_model.set_rows(evidence_rows)
        balances = generated.balance_by_category()
        if balances:
            balance_text = ", ".join(
                f"{category}: {score:+.2f}"
                for category, score in sorted(
                    balances.items(), key=lambda item: abs(item[1]), reverse=True
                )
            )
            self.evidence_balance.setText(
                "Vorläufige Evidenzbilanz (kein finales Root-Cause-Urteil): " + balance_text
            )
        else:
            self.evidence_balance.setText(
                "Noch keine bewertete generische Evidenz; weitere Quelldaten oder bauteilspezifische Regeln sind erforderlich."
            )
        self.time_plot.set_entries(timeline_entries)
        self.timeline_model.set_entries(timeline_entries)


    def _export_report(self) -> None:
        case_id = self.selector.currentData()
        case = self.repository.get_case(case_id) if case_id else None
        if case is None:
            return
        suggested = f"{case.case_id}.md"
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "NTF-Fallbericht exportieren",
            suggested,
            "Markdown (*.md)",
        )
        if not filename:
            return
        path = filename if filename.lower().endswith(".md") else filename + ".md"
        save_case_report(Path(path), case, self.references)
