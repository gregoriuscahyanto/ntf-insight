"""Single Mercedes-Benz-inspired cluster analysis workspace for local QEC cases.

One tab owns all method selection, configuration, side-by-side comparison,
2D/3D MDS visualization, group drilldown, real FIN/case details and legacy
expert tools. No method creates a new tab. Clustering runs off the GUI thread.
"""
from __future__ import annotations

import csv
from collections import Counter
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDoubleSpinBox,
    QFileDialog, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QPushButton, QScrollArea, QSlider, QSpinBox,
    QTableView, QVBoxLayout, QWidget,
)

from ntf_insight.analysis.case_clustering import _component_key
from ntf_insight.analysis.cluster_workspace_engine import (
    BY_METHOD, METHODS, ClusterParameters, UnifiedClusterResult, UnifiedCluster,
    _project_3d, calculate_clusters, compare_cluster_runs,
)
from ntf_insight.analysis.cluster_core_review import (
    CoreGroupLink, link_core_review_groups, write_core_review_template,
)
from ntf_insight.analysis.hdbscan_clustering import cluster_hdbscan_cases
from ntf_insight.analysis.cluster_explanation import explain_cluster
from ntf_insight.analysis.cluster_stability import build_stability_report, sensitivity_scenarios
from ntf_insight.app.models.simple_table_model import SimpleTableModel
from ntf_insight.app.widgets.cluster_projection_plot import ClusterProjectionPlot
from ntf_insight.domain.case import NTFCase


# Keep QThreads alive even if CasePage is rebuilt during import/reload.
# Never let an in-flight QThread be destroyed by deleteLater() on a page.
_ACTIVE_TASKS: set[QThread] = set()


class _ClusterTask(QThread):
    calculated = Signal(object)
    problem = Signal(str)
    progress = Signal(str)

    def __init__(
        self,
        cases: list[NTFCase],
        parameters: ClusterParameters,
        methods: tuple[str, ...],
        core_threshold: float = 0.45,
        include_stability: bool = False,
    ) -> None:
        super().__init__()
        self.cases = cases
        self.parameters = parameters
        self.methods = methods
        self.core_threshold = core_threshold
        self.include_stability = include_stability

    def run(self) -> None:
        try:
            p = self.parameters
            base = cluster_hdbscan_cases(
                self.cases,
                min_cluster_size=p.min_cluster_size,
                min_samples=p.min_samples,
                selection_method="leaf",
                dtc_source=p.dtc_source,
                lookback_days=p.lookback_days,
                common_dtc_cutoff=p.common_dtc_cutoff,
            )
            self.progress.emit("Berechne alle Clustermethoden auf gleicher Diagnosebasis …")
            shared_projection = _project_3d(base)
            results = [
                calculate_clusters(
                    self.cases, replace(p, method=method),
                    reference=base, projection=shared_projection,
                )
                for method in self.methods
            ]
            strict_params = replace(
                p, method="complete_cosine",
                minimum_similarity=self.core_threshold,
            )
            core = next(
                (item for item in results if item.parameters == strict_params),
                None,
            )
            if core is None:
                core = calculate_clusters(
                    self.cases, strict_params, reference=base,
                    projection=shared_projection,
                )
            report = None
            if self.include_stability:
                reference = next(
                    result for result in results
                    if result.parameters.method == p.method
                )
                comparisons = [
                    ("Verfahren", BY_METHOD[item.parameters.method].title, item)
                    for item in results if item.parameters.method != p.method
                ]
                scenarios = sensitivity_scenarios(p)
                for index, (label, variant) in enumerate(scenarios, start=1):
                    self.progress.emit(
                        f"Robustheitsprüfung {index}/{len(scenarios)}: {label}"
                    )
                    # Independently re-evaluate eligible cases per scenario.
                    run = calculate_clusters(
                        self.cases, variant, include_projection=False,
                    )
                    comparisons.append(("Daten/Parameter", label, run))
                self.progress.emit("Fasse Fallpaar-Stabilität zusammen …")
                report = build_stability_report(reference, tuple(comparisons))
            self.calculated.emit((results, core, report))
        except (ValueError, RuntimeError) as exc:
            self.problem.emit(str(exc))
        except Exception:
            # Real FIN/QEC identifiers, local paths or raw exception contents
            # may be present in unexpected third-party failures.
            self.problem.emit(
                "Clusterberechnung fehlgeschlagen. Bitte Diagnosedaten und "
                "lokale Programmprotokolle prüfen."
            )


class _ClusterTableModel(SimpleTableModel):
    """Compact text on screen, with complete local evidence on hover."""

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.ToolTipRole and index.isValid():
            value = self.rows[index.row()][index.column()]
            return str(value) if value is not None else ""
        return super().data(index, role)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.ToolTipRole:
            return super().headerData(
                section, orientation, Qt.ItemDataRole.DisplayRole,
            )
        return super().headerData(section, orientation, role)


def _table(
    model: SimpleTableModel,
    height: int = 190,
    widths: tuple[int, ...] = (),
) -> QTableView:
    """Readable even with 336 cases and long CPC3/SSL text columns."""
    table = QTableView()
    table.setModel(model)
    table.setMinimumHeight(height)
    table.setAlternatingRowColors(True)
    table.setWordWrap(False)
    table.setTextElideMode(Qt.TextElideMode.ElideRight)
    table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
    table.setSortingEnabled(False)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.verticalHeader().setVisible(False)
    table.verticalHeader().setDefaultSectionSize(27)
    header = table.horizontalHeader()
    header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    header.setDefaultSectionSize(136)
    header.setMinimumSectionSize(65)
    header.setStretchLastSection(False)
    for column, width in enumerate(widths):
        table.setColumnWidth(column, width)
    return table


class ClusterWorkspace(QWidget):
    """One extensible Clustering tab with local-only evidence drill-down."""

    case_requested = Signal(str)
    tips_linked = Signal(str)

    def __init__(
        self,
        cases: list[NTFCase], *, store=None, source_knowledge=None,
        population_metrics: dict | None = None,
    ) -> None:
        super().__init__()
        self.cases = sorted(cases, key=lambda c: c.case_id)
        self.by_id = {case.case_id: case for case in self.cases}
        self._store = store
        self._source_knowledge = source_knowledge
        self._population_metrics = population_metrics or {}
        self._task: _ClusterTask | None = None
        self._run_results: dict[str, UnifiedClusterResult] = {}
        self.result: UnifiedClusterResult | None = None
        self._core_result: UnifiedClusterResult | None = None
        self._stability_report = None
        self._core_links: tuple[CoreGroupLink, ...] = ()
        self._visible_core_links: list[CoreGroupLink] = []
        self._active_core_group: UnifiedCluster | None = None
        self._group_ids: list[int] = []
        self._member_ids: list[str] = []
        self._noise_ids: list[str] = []
        self._focused_case_id: str | None = None
        self._member_title_default = "4. Fälle im ausgewählten Cluster"
        self._dialogs: list[QDialog] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        layout.addWidget(scroll)
        content = QWidget()
        scroll.setWidget(content)
        body = QVBoxLayout(content)
        body.setContentsMargins(22, 18, 22, 26)
        body.setSpacing(11)

        headline = QHBoxLayout()
        headline.addWidget(QLabel("Clusteranalyse", objectName="PageTitle"))
        headline.addStretch(1)
        self.method_hint = QLabel("Diagnosegruppen · keine Ursachenbestätigung")
        self.method_hint.setObjectName("PageSubtitle")
        headline.addWidget(self.method_hint)
        body.addLayout(headline)
        lead = QLabel(
            "Eine Analysefläche für alle Clustermethoden. Gleiche Merkmale "
            "vor dem Pumpentausch, echte QEC-Repräsentanten, sichtbare "
            "Ausreißer und technisch getrennte Fachprüfung. "
            "SSL-Endbefunde fließen nicht in das Clustering ein.",
            objectName="PageSubtitle",
        )
        lead.setWordWrap(True)
        body.addWidget(lead)

        body.addWidget(QLabel("Datenbasis", objectName="CardTitle"))
        fields = QGridLayout()
        fields.setHorizontalSpacing(12)
        fields.setVerticalSpacing(8)
        self.family = QComboBox()
        fams = Counter(_component_key(c) for c in self.cases)
        for key, count in sorted(fams.items()):
            label = next(
                (c.component_type for c in self.cases if _component_key(c) == key),
                key,
            )
            self.family.addItem(f"{label} ({count})", key)
        if "coolant_pump" in fams:
            self.family.setCurrentIndex(self.family.findData("coolant_pump"))
        self.method = QComboBox()
        for item in METHODS:
            self.method.addItem(item.title, item.key)
            self.method.setItemData(
                self.method.count()-1, item.description,
                Qt.ItemDataRole.ToolTipRole,
            )
        self.method.setCurrentIndex(self.method.findData("leaf"))
        self.source = QComboBox()
        self.source.addItem("QuickTest + AutoExport", "all")
        self.source.addItem("QuickTest", "quicktest")
        self.source.addItem("AutoExport", "autoexport")
        self.lookback = QComboBox()
        self.lookback.addItem("Gesamte Vorher-Historie", None)
        for days in (30, 90, 180, 365):
            self.lookback.addItem(f"{days} Tage vor Tausch", days)
        self.min_cluster_size = QSpinBox()
        self.min_cluster_size.setRange(2, 100)
        self.min_cluster_size.setValue(3)
        self.min_samples = QSpinBox()
        self.min_samples.setRange(1, 100)
        self.min_samples.setValue(2)
        self.cosine_threshold = QDoubleSpinBox()
        self.cosine_threshold.setRange(0.05, 0.95)
        self.cosine_threshold.setDecimals(2)
        self.cosine_threshold.setSingleStep(0.05)
        self.cosine_threshold.setValue(0.45)
        self.jaccard_threshold = QDoubleSpinBox()
        self.jaccard_threshold.setRange(0.05, 1.00)
        self.jaccard_threshold.setDecimals(2)
        self.jaccard_threshold.setSingleStep(0.05)
        self.jaccard_threshold.setValue(0.60)
        self.filter_common = QCheckBox("Häufige DTCs ausschließen (ab 35 %)")
        self.filter_common.setChecked(False)
        self.filter_common.setToolTip(
            "Experimenteller Sensitivitätsfilter, keine Aussage über technische Relevanz."
        )

        fields.addWidget(QLabel("Bauteilfamilie"), 0, 0)
        fields.addWidget(self.family, 0, 1)
        fields.addWidget(QLabel("DTC-Quellen"), 0, 2)
        fields.addWidget(self.source, 0, 3)
        fields.addWidget(QLabel("Vor-Tausch-Zeitraum"), 1, 0)
        fields.addWidget(self.lookback, 1, 1)
        body.addLayout(fields)

        # Optional professional controls, not separate clustering actions.
        self.advanced_toggle = QCheckBox("Erweiterte Einstellungen anzeigen")
        body.addWidget(self.advanced_toggle)
        self.advanced_panel = QWidget()
        advanced_fields = QGridLayout(self.advanced_panel)
        advanced_fields.setContentsMargins(0, 0, 0, 0)
        advanced_fields.setHorizontalSpacing(12)
        advanced_fields.setVerticalSpacing(8)
        advanced_fields.addWidget(QLabel("Verfahren für Ergebnisansicht"), 0, 0)
        advanced_fields.addWidget(self.method, 0, 1)
        advanced_fields.addWidget(QLabel("Min. Fälle je Cluster"), 0, 2)
        advanced_fields.addWidget(self.min_cluster_size, 0, 3)
        self.min_samples_label = QLabel("MinSamples")
        advanced_fields.addWidget(self.min_samples_label, 1, 0)
        advanced_fields.addWidget(self.min_samples, 1, 1)
        self.cosine_label = QLabel("Min. Paar-Cosinus")
        advanced_fields.addWidget(self.cosine_label, 1, 2)
        advanced_fields.addWidget(self.cosine_threshold, 1, 3)
        self.jaccard_label = QLabel("Min. DTC-Jaccard-Index")
        advanced_fields.addWidget(self.jaccard_label, 2, 0)
        advanced_fields.addWidget(self.jaccard_threshold, 2, 1)
        advanced_fields.addWidget(self.filter_common, 3, 0, 1, 4)
        body.addWidget(self.advanced_panel)
        self.advanced_panel.hide()
        self.advanced_toggle.toggled.connect(self.advanced_panel.setVisible)
        self.method.currentIndexChanged.connect(self._method_changed)
        self._update_parameters()

        buttons = QHBoxLayout()
        self.run_button = QPushButton("Clusteranalyse starten")
        self.run_button.setObjectName("ClusterStartButton")
        self.run_button.setToolTip(
            "Alle zulässigen Verfahren, konservative Prüfgruppen und "
            "Stabilitätsanalysen ausschließlich mit lokalen Daten berechnen."
        )
        self.run_button.clicked.connect(self.run_analysis)
        buttons.addWidget(self.run_button)
        buttons.addStretch(1)
        body.addLayout(buttons)

        self.status = QLabel(
            "Bereit. 'Clusteranalyse starten' prüft alle Verfahren gemeinsam.",
            objectName="PageSubtitle",
        )
        self.status.setWordWrap(True)
        body.addWidget(self.status)

        # The three everyday KPIs and the separate missing-evidence figure.
        summary = QHBoxLayout()
        summary.setSpacing(10)
        self.summary_values = {}
        for key, title in (
            ("groups", "Gefundene Cluster"),
            ("assigned", "Fälle in Clustern"),
            ("noise", "Ohne Cluster"),
            ("missing", "Ohne Vor-Tausch-Diagnose"),
        ):
            card = QFrame()
            card.setObjectName("Card")
            stack = QVBoxLayout(card)
            stack.setContentsMargins(14, 10, 14, 10)
            label = QLabel(title, objectName="CardTitle")
            label.setWordWrap(True)
            value = QLabel("–", objectName="CardValue")
            value.setObjectName("CardValue")
            value.setAlignment(Qt.AlignmentFlag.AlignLeft)
            stack.addWidget(label)
            stack.addWidget(value)
            summary.addWidget(card, 1)
            self.summary_values[key] = value
        body.addLayout(summary)
        self.kpi = QLabel(objectName="PageSubtitle")
        self.kpi.setWordWrap(True)
        body.addWidget(self.kpi)

        map_header = QHBoxLayout()
        map_header.addWidget(QLabel("2. Cluster im Überblick", objectName="CardTitle"))
        map_header.addStretch(1)
        map_header.addWidget(QLabel("Darstellung"))
        self.dimension = QComboBox()
        self.dimension.addItem("2D", "2d")
        self.dimension.addItem("3D · drehbar", "3d")
        self.dimension.currentIndexChanged.connect(self._change_dimension)
        map_header.addWidget(self.dimension)
        self.other_method = QComboBox()
        self.other_method.currentIndexChanged.connect(self._draw_plots)
        self.other_method.setEnabled(False)
        map_header.addWidget(self.other_method)
        self.zoom_reset = QPushButton("Ansicht zurücksetzen")
        self.zoom_reset.clicked.connect(self._reset_zoom)
        map_header.addWidget(self.zoom_reset)
        body.addLayout(map_header)
        rotate = QHBoxLayout()
        self.rotation_label = QLabel("3D-Drehung")
        rotate.addWidget(self.rotation_label)
        self.yaw = QSlider(Qt.Orientation.Horizontal)
        self.yaw.setRange(0, 359)
        self.yaw.setValue(32)
        self.yaw.setToolTip("Azimut: 3D-Projektion horizontal drehen")
        rotate.addWidget(self.yaw, 1)
        rotate.addWidget(QLabel("Neigung"))
        self.elevation = QSlider(Qt.Orientation.Horizontal)
        self.elevation.setRange(-75, 75)
        self.elevation.setValue(24)
        self.elevation.setToolTip("Vertikale Neigung der 3D-Projektion")
        rotate.addWidget(self.elevation, 1)
        body.addLayout(rotate)
        self.yaw.valueChanged.connect(self._set_rotation)
        self.elevation.valueChanged.connect(self._set_rotation)
        self.plot_row = QHBoxLayout()
        self.plot = ClusterProjectionPlot()
        self.plot.case_picked.connect(self.focus_case)
        self.plot_row.addWidget(self.plot, 1)
        self.other_plot = ClusterProjectionPlot()
        self.other_plot.case_picked.connect(self.focus_case)
        self.other_plot.hide()
        self.plot_row.addWidget(self.other_plot, 1)
        body.addLayout(self.plot_row)
        plot_note = QLabel(
            "Jeder Punkt ist ein QEC-Fall. Farbe = Cluster, "
            "Grau = nicht zugeordnet, großer Punkt = repräsentativer Fall. "
            "Klick auf einen Punkt zeigt dessen Cluster. "
            "Die Grafik zeigt Ähnlichkeiten, keine bewiesenen Defekte.",
            objectName="PageSubtitle",
        )
        plot_note.setWordWrap(True)
        body.addWidget(plot_note)

        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("FIN oder QEC finden:"))
        self.case_finder = QLineEdit()
        self.case_finder.setPlaceholderText(
            "FIN / QEC lokal suchen – auch bei überlagerten 2D-/3D-Punkten"
        )
        self.case_finder.returnPressed.connect(self.find_case)
        search_row.addWidget(self.case_finder, 1)
        self.find_button = QPushButton("Fall markieren")
        self.find_button.clicked.connect(self.find_case)
        search_row.addWidget(self.find_button)
        body.addLayout(search_row)
        self.search_feedback = QLabel(objectName="PageSubtitle")
        self.search_feedback.setWordWrap(True)
        body.addWidget(self.search_feedback)

        body.addWidget(QLabel("3. Cluster auswählen – ein Klick zeigt die Fälle", objectName="CardTitle"))
        self.group_model = _ClusterTableModel((
            "Cluster", "Repräsentativer QEC-Fall", "QEC-Fälle", "FINs",
            "Schwächstes Paar", "Median", "Schwache Paare",
            "Gemeinsame ECU:DTC", "Prüfhypothese",
        ))
        self.group_table = _table(
            self.group_model, 210,
            (80, 170, 89, 74, 126, 92, 113, 320, 420),
        )
        self.group_table.selectionModel().currentRowChanged.connect(
            self._group_changed
        )
        # Keep technical columns in the model, but remove them from the
        # everyday view. The advanced details still explain algorithms below.
        for column in (1, 4, 5, 6, 8):
            self.group_table.setColumnHidden(column, True)
        self.group_table.setColumnWidth(7, 630)
        body.addWidget(self.group_table)

        self.why_box = QFrame()
        self.why_box.setObjectName("Card")
        why_layout = QVBoxLayout(self.why_box)
        why_layout.setContentsMargins(14, 12, 14, 12)
        self.why_heading = QLabel("Warum gehören diese Fälle zusammen?")
        self.why_heading.setObjectName("CardTitle")
        self.why_text = QLabel(
            "Bitte zuerst die Clusteranalyse starten und einen Cluster wählen."
        )
        self.why_text.setWordWrap(True)
        self.why_text.setTextFormat(Qt.TextFormat.PlainText)
        self.why_text.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        why_layout.addWidget(self.why_heading)
        why_layout.addWidget(self.why_text)
        body.addWidget(self.why_box)

        self.member_title = QLabel(
            self._member_title_default, objectName="CardTitle",
        )
        body.addWidget(self.member_title)
        self.member_model = _ClusterTableModel((
            "Rolle", "QEC-Fall", "FIN", "Index zum Medoid",
            "ML-Zugehörigkeit", "Gemeinsam mit Repräsentanten", "SSL-Endbefund (post hoc)",
        ))
        self.member_table = _table(
            self.member_model, 240,
            (165, 175, 185, 137, 115, 560, 480),
        )
        for column in (3, 4, 6):
            self.member_table.setColumnHidden(column, True)
        self.member_table.doubleClicked.connect(self._open_member_case)
        body.addWidget(self.member_table)
        open_row = QHBoxLayout()
        self.open_button = QPushButton("Ausgewählten Fall in FIN / Fallanalyse öffnen")
        self.open_button.clicked.connect(self.open_selected_case)
        self.open_button.setEnabled(False)
        open_row.addWidget(self.open_button)
        open_row.addStretch(1)
        body.addLayout(open_row)

        # The four everyday questions stay visible; detailed method diagnostics
        # and review/export tooling remain available, initially collapsed.
        self.expert_toggle = QCheckBox("Weitere Details für Experten anzeigen")
        body.addWidget(self.expert_toggle)
        self.expert_panel = QWidget()
        expert_body = QVBoxLayout(self.expert_panel)
        expert_body.setContentsMargins(0, 6, 0, 0)
        expert_body.setSpacing(10)
        export_row = QHBoxLayout()
        self.export_button = QPushButton("Clustertabelle lokal exportieren")
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self.export_csv)
        export_row.addWidget(self.export_button)
        export_row.addStretch(1)
        expert_body.addLayout(export_row)

        comparison_header = QHBoxLayout()
        comparison_header.addWidget(QLabel("Methodenvergleich", objectName="CardTitle"))
        comparison_header.addStretch(1)
        self.compare_side = QCheckBox("Zwei Verfahren nebeneinander")
        self.compare_side.setEnabled(False)
        self.compare_side.toggled.connect(self._draw_plots)
        comparison_header.addWidget(self.compare_side)
        expert_body.addLayout(comparison_header)
        self.compare_model = _ClusterTableModel((
            "Verfahren", "Cluster", "Clusterfälle", "Ausreißer",
            "Mit DTC-Kern", "Mit ≥2 FINs", "Paarübereinstimmung", "Distanzmaß",
        ))
        self.compare_table = _table(
            self.compare_model, 145,
            (205, 78, 104, 88, 110, 102, 151, 166),
        )
        self.compare_table.setMaximumHeight(200)
        self.compare_table.doubleClicked.connect(self._compare_row_picked)
        expert_body.addWidget(self.compare_table)
        info = QLabel(
            "Paarübereinstimmung vergleicht echte QEC-Fallpaare, niemals "
            "zufällige Clusternummern. Jaccard verwendet eine andere Metrik. "
            "Hohe Übereinstimmung bedeutet nicht gleiche technische Ursache.",
            objectName="PageSubtitle",
        )
        info.setWordWrap(True)
        expert_body.addWidget(info)
        expert_body.addWidget(QLabel(
            "Robustheitsprüfung · Methoden und Datenvarianten",
            objectName="CardTitle",
        ))
        self.stability_note = QLabel(
            "Noch keine Stabilitätsprüfung ausgeführt.",
            objectName="PageSubtitle",
        )
        self.stability_note.setWordWrap(True)
        expert_body.addWidget(self.stability_note)
        self.stability_model = _ClusterTableModel((
            "Vergleich", "Art", "Beidseitig geeignet",
            "Referenzfälle", "Paar-Jaccard", "Paarerhalt", "Hinweis",
        ))
        self.stability_table = _table(
            self.stability_model, 190,
            (245, 120, 145, 92, 115, 110, 400),
        )
        expert_body.addWidget(self.stability_table)
        self.stability_group_model = _ClusterTableModel((
            "Referenzcluster", "Prüfung", "Mitglieder", "Vergleichbar",
            "Referenzpaare", "Erhalten", "Erhaltquote", "Neue Verbindungen",
        ))
        self.stability_group_table = _table(
            self.stability_group_model, 155,
            (126, 210, 105, 100, 126, 100, 120, 160),
        )
        self.stability_group_table.setMaximumHeight(240)
        expert_body.addWidget(self.stability_group_table)
        self.stability_detail = QLabel(
            "Paarerhalt und Erhaltquote sind Diagnose-Stabilitätsmaße, "
            "keine Fehlerursachenwahrscheinlichkeiten.",
            objectName="PageSubtitle",
        )
        self.stability_detail.setWordWrap(True)
        expert_body.addWidget(self.stability_detail)

        core_header = QHBoxLayout()
        core_header.addWidget(QLabel(
            "Konservative Prüfgruppen · Complete-Link Cosinus",
            objectName="CardTitle",
        ))
        core_header.addStretch(1)
        core_header.addWidget(QLabel("Mindestpaarähnlichkeit"))
        self.core_threshold = QDoubleSpinBox()
        self.core_threshold.setRange(0.05, 0.95)
        self.core_threshold.setDecimals(2)
        self.core_threshold.setSingleStep(0.05)
        self.core_threshold.setValue(0.45)
        self.core_threshold.setToolTip(
            "Separater konservativer Prüfgruppenfilter, NICHT automatisch "
            "eine bestätigte Fehlerursache."
        )
        core_header.addWidget(self.core_threshold)
        self.core_only_group = QCheckBox("Nur passend zum gewählten Cluster")
        self.core_only_group.setChecked(False)
        self.core_only_group.toggled.connect(self._refresh_core_groups)
        core_header.addWidget(self.core_only_group)
        expert_body.addLayout(core_header)
        self.core_note = QLabel(
            "Prüfgruppen werden zusammen mit der Clustermethode berechnet. "
            "Gruppennummern verschiedener Methoden werden nicht gleichgesetzt.",
            objectName="PageSubtitle",
        )
        self.core_note.setWordWrap(True)
        expert_body.addWidget(self.core_note)
        self.core_model = _ClusterTableModel((
            "Prüfgruppe", "Fälle", "FINs", "Zugeordneter Cluster",
            "Überlappung", "Min. Cosinus", "Gemeinsamer ECU:DTC-Kern",
            "Fachlicher Hinweis",
        ))
        self.core_table = _table(
            self.core_model, 168,
            (103, 70, 72, 152, 98, 104, 326, 430),
        )
        self.core_table.selectionModel().currentRowChanged.connect(
            self._core_changed
        )
        expert_body.addWidget(self.core_table)
        core_actions = QHBoxLayout()
        self.core_export = QPushButton(
            "Prüfgruppen zur technischen Fachprüfung lokal exportieren"
        )
        self.core_export.setEnabled(False)
        self.core_export.clicked.connect(self.export_core_review)
        core_actions.addWidget(self.core_export)
        core_actions.addStretch(1)
        expert_body.addLayout(core_actions)

        expert_body.addWidget(QLabel(
            "Nicht zugeordnete und diagnostisch ausgeschlossene Fälle",
            objectName="CardTitle",
        ))
        self.noise_model = _ClusterTableModel(
            ("QEC-Fall", "FIN", "Begründung"),
        )
        self.noise_table = _table(
            self.noise_model, 190, (190, 230, 540),
        )
        self.noise_table.doubleClicked.connect(self._open_noise_case)
        expert_body.addWidget(self.noise_table)

        expert_body.addWidget(QLabel(
            "Fachprüfung und weiterführende Untersuchungen",
            objectName="CardTitle",
        ))
        footer = QHBoxLayout()
        self.expert_button = QPushButton("HDBSCAN-Fachprüfung und Exporte")
        self.expert_button.clicked.connect(self.open_expert_tools)
        footer.addWidget(self.expert_button)
        self.representative_button = QPushButton("Repräsentanten / TIPS prüfen")
        self.representative_button.clicked.connect(self.open_representative_tools)
        footer.addWidget(self.representative_button)
        self.old_scatter_button = QPushButton("Erweiterte Paaranalyse")
        self.old_scatter_button.clicked.connect(self.open_pair_tools)
        footer.addWidget(self.old_scatter_button)
        footer.addStretch(1)
        expert_body.addLayout(footer)
        note = QLabel(
            "Fachbestätigungen, Pilot-Vergleichslisten, CPC3-Brücken, "
            "TIPS-Verknüpfungen und bewährte CSV-Exporte bleiben "
            "über diese Aktionen erreichbar – ohne zusätzliche Cluster-Tabs.",
            objectName="PageSubtitle",
        )
        note.setWordWrap(True)
        expert_body.addWidget(note)

        body.addWidget(self.expert_panel)
        self.expert_panel.hide()
        self.expert_toggle.toggled.connect(self.expert_panel.setVisible)
        # New settings must never silently retain a previous grouping as
        # though it had been calculated with the changed parameters.
        for control in (
            self.family, self.source, self.lookback,
        ):
            control.currentIndexChanged.connect(self._invalidate_on_input)
        for control in (
            self.min_cluster_size, self.min_samples,
            self.cosine_threshold, self.jaccard_threshold,
        ):
            control.valueChanged.connect(self._invalidate_on_input)
        self.filter_common.toggled.connect(self._invalidate_on_input)
        self.core_threshold.valueChanged.connect(self._invalidate_on_input)
        self._change_dimension()

    def _update_parameters(self, *_args) -> None:
        spec = BY_METHOD.get(self.method.currentData(), METHODS[0])
        self.min_samples_label.setVisible(spec.supports_min_samples)
        self.min_samples.setVisible(spec.supports_min_samples)
        self.cosine_label.setVisible(spec.supports_cosine_cutoff)
        self.cosine_threshold.setVisible(spec.supports_cosine_cutoff)
        self.jaccard_label.setVisible(spec.supports_jaccard_cutoff)
        self.jaccard_threshold.setVisible(spec.supports_jaccard_cutoff)
        self.filter_common.setEnabled(not spec.supports_jaccard_cutoff)
        if spec.supports_jaccard_cutoff:
            self.filter_common.setChecked(False)
        self.method_hint.setText(
            f"Alle Verfahren · Ansicht: {spec.title} · Ursache unbestätigt"
        )

    def _method_changed(self, *_args) -> None:
        self._update_parameters()
        key = self.method.currentData()
        cached = self._run_results.get(key)
        if cached is not None and cached.parameters == self._parameters():
            self._show_result(cached)
        elif self.result is not None:
            self._clear_results()
            self.status.setText(
                "Anzeigeverfahren geändert. Bitte die Clusteranalyse neu starten."
            )

    def _invalidate_on_input(self, *_args) -> None:
        if self.result is None:
            return
        self._clear_results()
        self.status.setText(
            "Eingaben geändert. Die alten Cluster wurden ausgeblendet. "
            "Bitte die Clusteranalyse neu starten."
        )

    def _parameters(self) -> ClusterParameters:
        return ClusterParameters(
            method=self.method.currentData() or "leaf",
            min_cluster_size=self.min_cluster_size.value(),
            min_samples=self.min_samples.value(),
            minimum_similarity=self.cosine_threshold.value(),
            jaccard_threshold=self.jaccard_threshold.value(),
            common_dtc_cutoff=0.35 if self.filter_common.isChecked() else None,
            dtc_source=self.source.currentData() or "all",
            lookback_days=self.lookback.currentData(),
        )

    def _subset(self) -> list[NTFCase]:
        family = self.family.currentData()
        return [case for case in self.cases
                if _component_key(case) == family]

    def run_analysis(self) -> None:
        """The sole GUI analysis action computes every permissible method."""
        p = self._parameters()
        methods = (
            p.method,
            *(item.key for item in METHODS
              if item.key != p.method
              and (p.common_dtc_cutoff is None
                   or item.key != "complete_legacy")),
        )
        self._start_methods(tuple(methods), include_stability=True)

    # Internal legacy helpers remain callable, but are no longer UI actions.
    def compare_methods(self) -> None:
        self.run_analysis()

    def run_stability(self) -> None:
        self.run_analysis()

    def _start_methods(
        self, methods: tuple[str, ...], *, include_stability: bool = False,
    ) -> None:
        if self._task is not None and self._task.isRunning():
            self.status.setText("Eine Clusterberechnung läuft bereits.")
            return
        cases = self._subset()
        if not cases:
            self.status.setText("Keine Fälle für die gewählte Bauteilfamilie.")
            self._clear_results()
            return
        params = self._parameters()
        try:
            params.validate()
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        self.run_button.setEnabled(False)
        self.export_button.setEnabled(False)
        self.status.setText(
            f"Berechne {len(methods)} Methoden und die Stabilität "
            f"für {len(cases)} QEC-Fälle …"
        )
        self._running_params = params
        self._running_family = self.family.currentData()
        self._running_core_threshold = self.core_threshold.value()
        task = _ClusterTask(
            cases, params, methods, self._running_core_threshold,
            include_stability=include_stability,
        )
        _ACTIVE_TASKS.add(task)
        self._task = task
        task.calculated.connect(self._receive_results)
        task.progress.connect(self.status.setText)
        task.problem.connect(self._receive_error)
        task.finished.connect(lambda: _ACTIVE_TASKS.discard(task))
        task.finished.connect(task.deleteLater)
        task.start()

    def _receive_results(
        self,
        payload: tuple[list[UnifiedClusterResult], UnifiedClusterResult, object],
    ) -> None:
        results, core_result, stability_report = payload
        self._task = None
        self.run_button.setEnabled(True)
        if (
            self._running_params != self._parameters()
            or self._running_family != self.family.currentData()
            or self._running_core_threshold != self.core_threshold.value()
        ):
            self._clear_results()
            self.status.setText(
                "Parameter während der Berechnung geändert. "
                "Bitte die aktuelle Auswahl neu berechnen."
            )
            return
        self._run_results = {r.parameters.method: r for r in results}
        self._core_result = core_result
        self._show_stability(stability_report)
        self.result = results[0]
        self.export_button.setEnabled(True)
        self.status.setText(
            f"Analyse abgeschlossen: {len(results)} Verfahren und "
            f"{len(stability_report.comparisons) if stability_report else 0} "
            f"Stabilitätsvergleiche · {len(results[0].eligible_case_ids)} "
            "auswertbare QEC-Fälle. Keine Ursachenbestätigung."
        )
        self._refresh_comparison(results)
        self._show_result(results[0])

    def _receive_error(self, message: str) -> None:
        self._task = None
        self.run_button.setEnabled(True)
        self.status.setText(f"Clusterberechnung nicht möglich: {message}")
        self._clear_results()

    def _clear_results(self) -> None:
        self.result = None
        self._run_results = {}
        self._core_result = None
        self._show_stability(None)
        self._core_links = ()
        self._visible_core_links = []
        self._active_core_group = None
        self.core_model.set_rows([])
        self.core_note.setText(
            "Für die aktuelle Diagnosebasis noch keine konservativen "
            "Prüfgruppen berechnet."
        )
        self.core_export.setEnabled(False)
        self.member_title.setText(self._member_title_default)
        self._group_ids = []
        self._member_ids = []
        self._noise_ids = []
        self.group_model.set_rows([])
        self.member_model.set_rows([])
        self.noise_model.set_rows([])
        self.compare_model.set_rows([])
        self.plot.set_result(None, [])
        self.plot.set_emphasis_cases(None)
        self.other_plot.set_result(None, [])
        self.other_plot.set_emphasis_cases(None)
        self.compare_side.setEnabled(False)
        self.compare_side.setChecked(False)
        self.export_button.setEnabled(False)
        self.open_button.setEnabled(False)

    def _show_stability(self, report) -> None:
        self._stability_report = report
        if report is None:
            self.stability_model.set_rows([])
            self.stability_group_model.set_rows([])
            self.stability_note.setText(
                "Noch keine Robustheitsprüfung. 'Clusteranalyse starten' "
                "vergleicht vorhandene lokale Vor-Tausch-Diagnosen."
            )
            return
        self.stability_note.setText(
            f"{len(report.comparisons)} Vergleiche · "
            f"Referenz: {BY_METHOD[report.reference_method].title} · "
            f"{report.reference_eligible} geeignete Referenzfälle. "
            "Methoden = gleiche Diagnosebasis; Daten/Parameter = "
            "Ein-Faktor-Variationen. Kein Ursachen-Voting."
        )
        def percent(value):
            return f"{value:.1%}" if value is not None else "nicht bestimmbar"
        self.stability_model.set_rows([
            (
                c.label, c.category, c.shared_eligible,
                c.baseline_eligible, percent(c.pair_jaccard),
                percent(c.reference_pair_retention), c.warning,
            )
            for c in report.comparisons
        ])
        self.stability_group_model.set_rows([
            (
                f"C{g.group_number}", c.label, g.reference_members,
                g.comparable_members, g.reference_pairs,
                g.retained_pairs, percent(g.retention),
                g.newly_joined_external_pairs,
            )
            for c in report.comparisons for g in c.group_rows
        ])

    def _refresh_comparison(
        self, results: list[UnifiedClusterResult],
    ) -> None:
        self._comparison_order = [r.parameters.method for r in results]
        rows = compare_cluster_runs(results)
        values = []
        for item in rows:
            method = self._comparison_order[len(values)]
            label = item["methode"]
            if method == "complete_cosine":
                label += f" ({self.cosine_threshold.value():.0%})"
            if method == "complete_legacy":
                label += f" ({self.jaccard_threshold.value():.0%})"
            agreement = item["paaruebereinstimmung"]
            values.append((
                label, item["cluster"], item["faelle"],
                item["ausreisser"], item["gemeinsamer_dtc_kern"],
                item["mehrere_fin"],
                f"{agreement:.1%}" if agreement is not None else "—",
                item["metrik"],
            ))
        self.compare_model.set_rows(values)
        self.compare_side.setEnabled(len(results) > 1)
        self.other_method.blockSignals(True)
        self.other_method.clear()
        for result in results:
            self.other_method.addItem(
                BY_METHOD[result.parameters.method].title,
                result.parameters.method,
            )
        if len(results) > 1:
            self.other_method.setCurrentIndex(1)
        self.other_method.setEnabled(len(results) > 1)
        self.other_method.blockSignals(False)
        self._draw_plots()

    def _compare_row_picked(self, index) -> None:
        if not index.isValid() or index.row() >= len(self._comparison_order):
            return
        key = self._comparison_order[index.row()]
        if key not in self._run_results:
            return
        selected = self.method.findData(key)
        if selected >= 0:
            self.method.blockSignals(True)
            self.method.setCurrentIndex(selected)
            self.method.blockSignals(False)
            self._update_parameters()
        self._show_result(self._run_results[key])

    def _show_result(self, result: UnifiedClusterResult) -> None:
        self.result = result
        self._group_ids = [group.cluster_id for group in result.groups]
        self.kpi.setText(
            f"{len(self._subset())} QEC-Fälle · "
            f"{len(result.eligible_case_ids)} auswertbar · "
            f"{len(result.groups)} Cluster · "
            f"{result.clustered_count} zugeordnet · "
            f"{len(result.noise_case_ids)} Ausreißer · "
            f"{len(result.excluded_case_ids)} ohne geeignete Diagnose. "
            f"{result.note}"
        )
        self.group_model.set_rows([
            (
                f"C{g.cluster_id}", g.representative_case_id,
                g.case_count, g.vehicle_count,
                f"{g.minimum_pair_similarity:.1%}"
                if g.minimum_pair_similarity is not None else "—",
                f"{g.median_pair_similarity:.1%}"
                if g.median_pair_similarity is not None else "—",
                f"{g.weak_pair_count}/{g.internal_pair_count}"
                if g.weak_pair_count is not None else "andere Metrik",
                ", ".join(f"{ecu}:{dtc}" for ecu, dtc in g.common_faults[:7])
                or "Kein durchgängiger ECU:DTC",
                "; ".join(g.warnings) or "Technisch noch nicht bestätigt",
            ) for g in result.groups
        ])
        self._noise_ids = [
            *result.noise_case_ids, *result.excluded_case_ids
        ]
        self.noise_model.set_rows([
            (
                cid, self.by_id[cid].vin,
                "Keiner Diagnostikgruppe zugeordnet"
                if cid in result.noise_case_ids
                else "Kein eindeutiger Vor-Tausch-Diagnosenachweis",
            ) for cid in self._noise_ids
        ])
        self.member_model.set_rows([])
        self._member_ids = []
        self.open_button.setEnabled(False)
        if result.groups:
            selected_id = self._focused_case_id
            match = next(
                (i for i, group in enumerate(result.groups)
                 if selected_id in group.case_ids),
                0,
            )
            self.group_table.selectRow(match)
        else:
            self._refresh_core_groups()
            if self._focused_case_id is not None:
                self.focus_case(self._focused_case_id)
        self._draw_plots()

    def _fill_members(
        self, group: UnifiedCluster, *, core: bool,
    ) -> None:
        self.member_title.setText(
            f"Falltabelle – konservative Prüfgruppe K{group.cluster_id}"
            if core else self._member_title_default
        )
        self._member_ids = [member.case_id for member in group.members]
        rows = []
        # One QEC is not one independent vehicle. Only the first target
        # with a genuinely different FIN is eligible for that designation.
        seen_fins = {self.by_id[group.representative_case_id].vin}
        for member in group.members:
            case = self.by_id[member.case_id]
            if member.case_id == group.representative_case_id:
                role = "Repräsentant (Kern)" if core else "Repräsentant"
            elif core and case.vin in seen_fins:
                role = "Mehrfachfall derselben FIN – nicht unabhängig"
            elif core:
                role = "Prüffall mit anderer FIN – Mechanismus offen"
                seen_fins.add(case.vin)
            else:
                role = "Clusterfall"
            common = ", ".join(
                f"{ecu}:{dtc}" for ecu, dtc in group.common_faults[:7]
            ) or "Kein durchgängiger ECU:DTC"
            ssl = getattr(
                case, "qec_ssl_end_finding", None,
            ) or "Nicht dokumentiert"
            rows.append((
                role, case.case_id, case.vin, f"{member.similarity:.1%}",
                f"{member.membership_strength:.1%}"
                if member.membership_strength is not None else "—",
                common, str(ssl),
            ))
        self.member_model.set_rows(rows)
        self.open_button.setEnabled(bool(rows))
        if rows:
            target = next(
                (i for i, member in enumerate(group.members)
                 if member.case_id == self._focused_case_id),
                0,
            )
            self.member_table.selectRow(target)

    def _group_changed(self, index, _previous) -> None:
        if self.result is None or not index.isValid():
            return
        if not 0 <= index.row() < len(self.result.groups):
            return
        group = self.result.groups[index.row()]
        self._active_core_group = None
        self._fill_members(group, core=False)
        self._refresh_core_groups()
        self._draw_plots()

    def _refresh_core_groups(self, *_args) -> None:
        if self.result is None or self._core_result is None:
            self._core_links = ()
            self._visible_core_links = []
            self.core_model.set_rows([])
            self.core_export.setEnabled(False)
            return
        self._core_links = link_core_review_groups(
            self.result, self._core_result,
        )
        selected = self.group_table.currentIndex()
        group_id = (
            self.result.groups[selected.row()].cluster_id
            if selected.isValid() and selected.row() < len(self.result.groups)
            else None
        )
        self._visible_core_links = [
            link for link in self._core_links
            if (
                not self.core_only_group.isChecked()
                or group_id is None
                or group_id in link.active_group_ids
            )
        ]
        previously_selected = (
            self._active_core_group.cluster_id
            if self._active_core_group is not None else None
        )
        self.core_model.set_rows([
            (
                link.label,
                link.core.case_count,
                link.core.vehicle_count,
                ", ".join(f"C{cid}" for cid in link.active_group_ids)
                or "Keine",
                (
                    f"{link.dominant_overlap}/{link.core.case_count}"
                    if link.dominant_group_id is not None else "0"
                ),
                (
                    f"{link.core.minimum_pair_similarity:.1%}"
                    if link.core.minimum_pair_similarity is not None else "—"
                ),
                ", ".join(
                    f"{ecu}:{dtc}" for ecu, dtc in link.core.common_faults[:7]
                ) or "Kein durchgängiger ECU:DTC",
                link.note + " · Ursache nicht unabhängig bestätigt",
            ) for link in self._visible_core_links
        ])
        count = len(self._core_links)
        assigned = sum(link.core.case_count for link in self._core_links)
        self.core_note.setText(
            f"{count} konservative Prüfgruppen mit {assigned} QEC-Fällen; "
            f"{len(self._visible_core_links)} hier angezeigt. "
            f"Schwelle: {self.core_threshold.value():.0%}, "
            "gleiche originale Diagnoseabstände. "
            "C- und K-Nummern sind methodenabhängig. "
            "Klick auf eine K-Gruppe zeigt ihre Einzelfälle unten. "
            "Technischer Fehlermechanismus weiterhin unbestätigt."
        )
        self.core_export.setEnabled(bool(self._core_result.groups))
        if previously_selected is not None:
            new_row = next(
                (i for i, link in enumerate(self._visible_core_links)
                 if link.core.cluster_id == previously_selected),
                None,
            )
            if new_row is not None:
                self.core_table.selectRow(new_row)
            else:
                # A filtering action must never leave a stale strict case
                # subset in the detail table when it is no longer visible.
                self._active_core_group = None
                if group_id is not None and selected.isValid():
                    self._fill_members(
                        self.result.groups[selected.row()], core=False,
                    )
                self._draw_plots()

    def _core_changed(self, index, _previous) -> None:
        if (
            not index.isValid()
            or not 0 <= index.row() < len(self._visible_core_links)
        ):
            return
        link = self._visible_core_links[index.row()]
        self._active_core_group = link.core
        self._focused_case_id = link.core.representative_case_id
        self._fill_members(link.core, core=True)
        self.search_feedback.setText(
            f"{link.label}: {link.note}. "
            "Keine automatische Bestätigung von NTF oder Lieferantenursache."
        )
        self._draw_plots()

    def find_case(self) -> bool:
        """Search QEC/FIN locally, also for overlapping MDS points."""
        query = self.case_finder.text().strip().casefold()
        if not query:
            self.search_feedback.setText("Bitte FIN oder QEC-Fall eingeben.")
            return False
        matches = [
            case for case in self._subset()
            if query in case.case_id.casefold()
            or query in case.vin.casefold()
        ]
        if not matches:
            self.search_feedback.setText("Keine passende lokale QEC/FIN gefunden.")
            return False
        # Prefer exact FIN/QEC matches; when a FIN has multiple QEC records
        # the count is explicit and the user can select the next case in table.
        matches.sort(key=lambda case: (
            query not in {case.case_id.casefold(), case.vin.casefold()},
            case.case_id,
        ))
        picked = matches[0]
        self.focus_case(picked.case_id)
        self.search_feedback.setText(
            f"{len(matches)} lokale Treffer · ausgewählt: "
            f"{picked.case_id} / FIN {picked.vin}. "
            "Mehrere QECs derselben FIN sind nicht unabhängige Fahrzeuge."
        )
        return True

    def export_core_review(self) -> None:
        """Save only to a local file chosen by the user, never GitHub."""
        if self._core_result is None or not self._core_result.groups:
            return
        destination, _ = QFileDialog.getSaveFileName(
            self, "Lokale Complete-Link Fachprüfvorlage speichern",
            str(Path.home() / ".ntf-insight"
                / "Kernpruefgruppen_FIN_QEC_NICHT_HOCHLADEN.csv"),
            "CSV-Dateien (*.csv)",
        )
        if not destination:
            return
        target = Path(destination).resolve()
        # In editable installs never permit a confidential export into git.
        repository_root = Path(__file__).resolve().parents[4]
        if target == repository_root or repository_root in target.parents:
            self.status.setText(
                "Vertrauliche QEC-/FIN-Fachprüfung darf nicht ins Git-Repository."
            )
            return
        try:
            with target.open("w", encoding="utf-8-sig", newline="") as output:
                write_core_review_template(
                    output, self._subset(), self._core_result,
                )
        except OSError:
            self.status.setText(
                "Lokaler Fachprüf-Export nicht möglich. "
                "Speicherort und Schreibberechtigung prüfen."
            )
            return
        self.status.setText(
            "Kernprüfvorlage ausschließlich lokal gespeichert. "
            "Nur unabhängige Fachbelege können 'confirmed' begründen. "
            "NIEMALS in GitHub/Chat hochladen."
        )

    def _draw_plots(self, *_args) -> None:
        if self.result is None:
            return
        current = self.group_table.currentIndex()
        group = self.result.groups[current.row()].cluster_id if (
            current.isValid() and current.row() < len(self.result.groups)
        ) else None
        self.plot.set_result(self.result, self._subset(), group)
        if self._focused_case_id:
            self.plot.set_highlight(group, self._focused_case_id)
        strict_cases = (
            self._active_core_group.case_ids
            if self._active_core_group is not None else None
        )
        self.plot.set_emphasis_cases(strict_cases)
        twin = self.compare_side.isChecked()
        self.other_plot.setVisible(twin)
        if twin:
            key = self.other_method.currentData()
            other = self._run_results.get(key)
            # Group IDs are method-local and MUST NOT be treated as
            # matching IDs across different clustering algorithms.
            other_group = next(
                (g.cluster_id for g in other.groups
                 if self._focused_case_id in g.case_ids), None,
            ) if other is not None else None
            self.other_plot.set_result(other, self._subset(), other_group)
            if self._focused_case_id:
                self.other_plot.set_highlight(
                    other_group, self._focused_case_id,
                )
            self.other_plot.set_emphasis_cases(strict_cases)
        self._change_dimension()

    def _change_dimension(self, *_args) -> None:
        mode = self.dimension.currentData() or "2d"
        for plot in (self.plot, self.other_plot):
            plot.set_mode(mode)
        self.rotation_label.setVisible(mode == "3d")
        self.yaw.setVisible(mode == "3d")
        self.elevation.setVisible(mode == "3d")

    def _set_rotation(self, *_args) -> None:
        for plot in (self.plot, self.other_plot):
            plot.set_rotation(self.yaw.value(), self.elevation.value())

    def _reset_zoom(self) -> None:
        for plot in (self.plot, self.other_plot):
            plot.reset_zoom()

    def focus_case(self, case_id: str) -> bool:
        if case_id not in self.by_id:
            return False
        self._focused_case_id = case_id
        if self.result is None:
            return True

        # Keep the strict three-case drill-down active when one of its
        # independently comparable FINs is selected.
        if self._active_core_group is not None:
            if case_id in self._active_core_group.case_ids:
                for row, member in enumerate(self._active_core_group.members):
                    if member.case_id == case_id:
                        self.member_table.selectRow(row)
                        break
                self._draw_plots()
                return True
            self._active_core_group = None

        for index, group in enumerate(self.result.groups):
            if case_id in group.case_ids:
                if self.group_table.currentIndex().row() != index:
                    self.group_table.selectRow(index)
                else:
                    self._fill_members(group, core=False)
                for row, member in enumerate(group.members):
                    if member.case_id == case_id:
                        self.member_table.selectRow(row)
                        break
                self._draw_plots()
                return True

        # For eligible noise or excluded cases there is deliberately no
        # invented similarity or synthetic cluster group.
        selected = self.group_table.currentIndex()
        if selected.isValid() and selected.row() < len(self.result.groups):
            self._fill_members(self.result.groups[selected.row()], core=False)
        for row, cid in enumerate(self._noise_ids):
            if cid == case_id:
                self.noise_table.selectRow(row)
                break
        self._draw_plots()
        return True

    def clear_focus(self) -> None:
        self._focused_case_id = None
        self._active_core_group = None
        self._draw_plots()

    def _selected_member(self) -> str | None:
        idx = self.member_table.currentIndex()
        if idx.isValid() and 0 <= idx.row() < len(self._member_ids):
            return self._member_ids[idx.row()]
        return None

    def open_selected_case(self) -> None:
        cid = self._selected_member() or self._focused_case_id
        if isinstance(cid, str):
            self.case_requested.emit(cid)

    def _open_member_case(self, index) -> None:
        if index.isValid() and 0 <= index.row() < len(self._member_ids):
            self.case_requested.emit(self._member_ids[index.row()])

    def _open_noise_case(self, index) -> None:
        if index.isValid() and 0 <= index.row() < len(self._noise_ids):
            self.case_requested.emit(self._noise_ids[index.row()])

    def export_csv(self) -> None:
        if self.result is None:
            return
        destination, _ = QFileDialog.getSaveFileName(
            self, "Vertrauliche Clusterfälle lokal speichern",
            "NTF_Clusteranalyse_FIN_NICHT_HOCHLADEN.csv", "CSV (*.csv)",
        )
        if not destination:
            return
        with Path(destination).open("w", encoding="utf-8-sig", newline="") as target:
            writer = csv.writer(target, delimiter=";")
            writer.writerow((
                "Verfahren", "Cluster", "QEC-Fall", "FIN",
                "Repräsentant", "Index zum Medoid", "Kernevidenz ECU:DTC",
                "Technischer Mechanismus bestätigt",
            ))
            for group in self.result.groups:
                for member in group.members:
                    case = self.by_id[member.case_id]
                    def spreadsheet_safe(value: str) -> str:
                        return "'" + value if value.lstrip().startswith(
                            ("=", "+", "-", "@")
                        ) else value
                    writer.writerow((
                        self.result.parameters.method, group.cluster_id,
                        spreadsheet_safe(case.case_id), spreadsheet_safe(case.vin),
                        spreadsheet_safe(group.representative_case_id),
                        f"{member.similarity:.4f}",
                        spreadsheet_safe("; ".join(
                            f"{ecu}:{dtc}" for ecu, dtc in group.common_faults
                        )),
                        "Nein; technische Einzelprüfung erforderlich",
                    ))
        self.status.setText(
            "Vertrauliche Fallliste lokal gespeichert – NICHT in GitHub hochladen."
        )

    def _open_tool(self, title: str, widget: QWidget) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.resize(1200, 800)
        page = QVBoxLayout(dialog)
        page.addWidget(widget)
        if hasattr(widget, "case_requested"):
            widget.case_requested.connect(self.case_requested.emit)
        if hasattr(widget, "tips_linked"):
            widget.tips_linked.connect(self.tips_linked.emit)
        self._dialogs.append(dialog)
        dialog.finished.connect(lambda _code: self._dialogs.remove(dialog))
        dialog.show()

    def open_expert_tools(self) -> None:
        from ntf_insight.app.widgets.hdbscan_panel import HDBSCANPanel

        self._open_tool(
            "Clusteranalyse · Fachvalidierung / CPC3 / Exporte",
            HDBSCANPanel(self.cases, store=self._store),
        )

    def open_representative_tools(self) -> None:
        from ntf_insight.app.widgets.representative_case_panel import (
            RepresentativeCasePanel,
        )

        self._open_tool(
            "Clusteranalyse · Repräsentanten / TIPS",
            RepresentativeCasePanel(
                self.cases, source_knowledge=self._source_knowledge,
                store=self._store,
            ),
        )

    def open_pair_tools(self) -> None:
        from ntf_insight.app.widgets.case_scatter_plot import CaseScatterPanel

        panel = CaseScatterPanel(
            self.cases, population_metrics=self._population_metrics,
        )
        panel.case_focused.connect(self.focus_case)
        panel.quicktests_requested.connect(lambda _cid: None)
        self._open_tool("Clusteranalyse · Paarvergleich", panel)
