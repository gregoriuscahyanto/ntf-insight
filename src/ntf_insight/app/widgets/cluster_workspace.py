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
    QPushButton, QScrollArea, QSlider, QSpinBox,
    QTableView, QVBoxLayout, QWidget,
)

from ntf_insight.analysis.case_clustering import _component_key
from ntf_insight.analysis.cluster_workspace_engine import (
    BY_METHOD, METHODS, ClusterParameters, UnifiedClusterResult,
    calculate_clusters, compare_cluster_runs,
)
from ntf_insight.analysis.hdbscan_clustering import cluster_hdbscan_cases
from ntf_insight.app.models.simple_table_model import SimpleTableModel
from ntf_insight.app.widgets.cluster_projection_plot import ClusterProjectionPlot
from ntf_insight.domain.case import NTFCase


# Keep QThreads alive even if CasePage is rebuilt during import/reload.
# Never let an in-flight QThread be destroyed by deleteLater() on a page.
_ACTIVE_TASKS: set[QThread] = set()


class _ClusterTask(QThread):
    calculated = Signal(object)
    problem = Signal(str)

    def __init__(
        self,
        cases: list[NTFCase],
        parameters: ClusterParameters,
        methods: tuple[str, ...],
    ) -> None:
        super().__init__()
        self.cases = cases
        self.parameters = parameters
        self.methods = methods

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
            results = [
                calculate_clusters(
                    self.cases, replace(p, method=method), reference=base,
                )
                for method in self.methods
            ]
            self.calculated.emit(results)
        except (ValueError, RuntimeError) as exc:
            self.problem.emit(str(exc))
        except Exception:
            # Real FIN/QEC identifiers, local paths or raw exception contents
            # may be present in unexpected third-party failures.
            self.problem.emit(
                "Clusterberechnung fehlgeschlagen. Bitte Diagnosedaten und "
                "lokale Programmprotokolle prüfen."
            )


def _table(model: SimpleTableModel, height: int = 190) -> QTableView:
    table = QTableView()
    table.setModel(model)
    table.setMinimumHeight(height)
    table.setAlternatingRowColors(True)
    table.setSortingEnabled(False)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.verticalHeader().setVisible(False)
    header = table.horizontalHeader()
    header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    header.setStretchLastSection(True)
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
        self._group_ids: list[int] = []
        self._member_ids: list[str] = []
        self._noise_ids: list[str] = []
        self._focused_case_id: str | None = None
        self._dialogs: list[QDialog] = []
        self._activated = False

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

        body.addWidget(QLabel("Methode und Datenbasis", objectName="CardTitle"))
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
        fields.addWidget(QLabel("Verfahren"), 0, 2)
        fields.addWidget(self.method, 0, 3)
        fields.addWidget(QLabel("DTC-Quellen"), 1, 0)
        fields.addWidget(self.source, 1, 1)
        fields.addWidget(QLabel("Vor-Tausch-Zeitraum"), 1, 2)
        fields.addWidget(self.lookback, 1, 3)
        fields.addWidget(QLabel("Min. Fälle je Cluster"), 2, 0)
        fields.addWidget(self.min_cluster_size, 2, 1)
        self.min_samples_label = QLabel("MinSamples")
        fields.addWidget(self.min_samples_label, 2, 2)
        fields.addWidget(self.min_samples, 2, 3)
        self.cosine_label = QLabel("Min. Paar-Cosinus")
        fields.addWidget(self.cosine_label, 3, 0)
        fields.addWidget(self.cosine_threshold, 3, 1)
        self.jaccard_label = QLabel("Min. DTC-Jaccard-Index")
        fields.addWidget(self.jaccard_label, 3, 2)
        fields.addWidget(self.jaccard_threshold, 3, 3)
        fields.addWidget(self.filter_common, 4, 0, 1, 4)
        body.addLayout(fields)
        self.method.currentIndexChanged.connect(self._update_parameters)
        self._update_parameters()

        buttons = QHBoxLayout()
        self.run_button = QPushButton("Cluster berechnen")
        self.run_button.clicked.connect(self.run_analysis)
        buttons.addWidget(self.run_button)
        self.compare_button = QPushButton("Methoden vergleichen")
        self.compare_button.clicked.connect(self.compare_methods)
        buttons.addWidget(self.compare_button)
        self.export_button = QPushButton("Clustertabelle lokal exportieren")
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self.export_csv)
        buttons.addWidget(self.export_button)
        buttons.addStretch(1)
        body.addLayout(buttons)

        self.status = QLabel("Noch keine Analyse ausgeführt.", objectName="PageSubtitle")
        self.status.setWordWrap(True)
        body.addWidget(self.status)
        self.kpi = QLabel(objectName="PageSubtitle")
        self.kpi.setWordWrap(True)
        body.addWidget(self.kpi)

        comparison_header = QHBoxLayout()
        comparison_header.addWidget(QLabel("Methodenvergleich", objectName="CardTitle"))
        comparison_header.addStretch(1)
        self.compare_side = QCheckBox("Zwei Verfahren nebeneinander")
        self.compare_side.setEnabled(False)
        self.compare_side.toggled.connect(self._draw_plots)
        comparison_header.addWidget(self.compare_side)
        body.addLayout(comparison_header)
        self.compare_model = SimpleTableModel((
            "Verfahren", "Cluster", "Clusterfälle", "Ausreißer",
            "Mit DTC-Kern", "Mit ≥2 FINs", "Paarübereinstimmung", "Distanzmaß",
        ))
        self.compare_table = _table(self.compare_model, 145)
        self.compare_table.setMaximumHeight(200)
        self.compare_table.doubleClicked.connect(self._compare_row_picked)
        body.addWidget(self.compare_table)
        info = QLabel(
            "Paarübereinstimmung vergleicht echte QEC-Fallpaare, niemals "
            "zufällige Clusternummern. Jaccard verwendet eine andere Metrik. "
            "Hohe Übereinstimmung bedeutet nicht gleiche technische Ursache.",
            objectName="PageSubtitle",
        )
        info.setWordWrap(True)
        body.addWidget(info)

        map_header = QHBoxLayout()
        map_header.addWidget(QLabel("Fallvisualisierung", objectName="CardTitle"))
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
            "2D/3D sind MDS-Projektionen der Originaldistanzen. "
            "Cluster entstehen NIE aus 2D/3D-Pixeln. "
            "Farbige Punkte = gruppiert, Grau = Rauschen, größere Punkte = Medoid. "
            "Fälle ohne gesicherte Vor-Tausch-Diagnose werden unten dokumentiert.",
            objectName="PageSubtitle",
        )
        plot_note.setWordWrap(True)
        body.addWidget(plot_note)

        body.addWidget(QLabel("Clustertabelle", objectName="CardTitle"))
        self.group_model = SimpleTableModel((
            "Cluster", "Repräsentativer QEC-Fall", "QEC-Fälle", "FINs",
            "Schwächstes Paar", "Median", "Schwache Paare",
            "Gemeinsame ECU:DTC", "Prüfhypothese",
        ))
        self.group_table = _table(self.group_model, 210)
        self.group_table.selectionModel().currentRowChanged.connect(
            self._group_changed
        )
        body.addWidget(self.group_table)

        body.addWidget(QLabel("Falltabelle – gewählter Cluster", objectName="CardTitle"))
        self.member_model = SimpleTableModel((
            "Rolle", "QEC-Fall", "FIN", "Index zum Medoid",
            "ML-Zugehörigkeit", "Gemeinsame ECU:DTC", "SSL-Endbefund (post hoc)",
        ))
        self.member_table = _table(self.member_model, 210)
        self.member_table.doubleClicked.connect(self._open_member_case)
        body.addWidget(self.member_table)
        open_row = QHBoxLayout()
        self.open_button = QPushButton("Ausgewählten Fall in FIN / Fallanalyse öffnen")
        self.open_button.clicked.connect(self.open_selected_case)
        self.open_button.setEnabled(False)
        open_row.addWidget(self.open_button)
        open_row.addStretch(1)
        body.addLayout(open_row)

        body.addWidget(QLabel(
            "Nicht zugeordnete und diagnostisch ausgeschlossene Fälle",
            objectName="CardTitle",
        ))
        self.noise_model = SimpleTableModel(("QEC-Fall", "FIN", "Begründung"))
        self.noise_table = _table(self.noise_model, 190)
        self.noise_table.doubleClicked.connect(self._open_noise_case)
        body.addWidget(self.noise_table)

        body.addWidget(QLabel(
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
        body.addLayout(footer)
        note = QLabel(
            "Fachbestätigungen, Pilot-Vergleichslisten, CPC3-Brücken, "
            "TIPS-Verknüpfungen und bewährte CSV-Exporte bleiben "
            "über diese Aktionen erreichbar – ohne zusätzliche Cluster-Tabs.",
            objectName="PageSubtitle",
        )
        note.setWordWrap(True)
        body.addWidget(note)
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
        self.method_hint.setText(spec.description)

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

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if not self._activated:
            self._activated = True
            self.run_analysis()

    def run_analysis(self) -> None:
        self._start_methods((self._parameters().method,))

    def compare_methods(self) -> None:
        selected = self._parameters().method
        options = (selected, *(x.key for x in METHODS if x.key != selected))
        self._start_methods(tuple(options))

    def _start_methods(self, methods: tuple[str, ...]) -> None:
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
        self.compare_button.setEnabled(False)
        self.export_button.setEnabled(False)
        self.status.setText(
            f"Berechne {len(methods)} Methode(n) für {len(cases)} QEC-Fälle …"
        )
        task = _ClusterTask(cases, params, methods)
        _ACTIVE_TASKS.add(task)
        self._task = task
        task.calculated.connect(self._receive_results)
        task.problem.connect(self._receive_error)
        task.finished.connect(lambda: _ACTIVE_TASKS.discard(task))
        task.finished.connect(task.deleteLater)
        task.start()

    def _receive_results(self, results: list[UnifiedClusterResult]) -> None:
        self._task = None
        self.run_button.setEnabled(True)
        self.compare_button.setEnabled(True)
        self._run_results = {r.parameters.method: r for r in results}
        self.result = results[0]
        self.export_button.setEnabled(True)
        self.status.setText(
            f"{len(results)} Methode(n) berechnet · "
            f"gemeinsame Basis: {len(results[0].eligible_case_ids)} "
            "QEC-Fälle mit geeigneter Vor-Tausch-Diagnose. "
            "Keine technisch bestätigten Fehlermechanismen."
        )
        self._refresh_comparison(results)
        self._show_result(results[0])

    def _receive_error(self, message: str) -> None:
        self._task = None
        self.run_button.setEnabled(True)
        self.compare_button.setEnabled(True)
        self.status.setText(f"Clusterberechnung nicht möglich: {message}")
        self._clear_results()

    def _clear_results(self) -> None:
        self.result = None
        self._run_results = {}
        self._group_ids = []
        self._member_ids = []
        self._noise_ids = []
        self.group_model.set_rows([])
        self.member_model.set_rows([])
        self.noise_model.set_rows([])
        self.compare_model.set_rows([])
        self.plot.set_result(None, [])
        self.other_plot.set_result(None, [])
        self.compare_side.setEnabled(False)
        self.compare_side.setChecked(False)
        self.export_button.setEnabled(False)
        self.open_button.setEnabled(False)

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
        elif self._focused_case_id is not None:
            self.focus_case(self._focused_case_id)
        self._draw_plots()

    def _group_changed(self, index, _previous) -> None:
        if self.result is None or not index.isValid():
            return
        if not 0 <= index.row() < len(self.result.groups):
            return
        group = self.result.groups[index.row()]
        self._member_ids = [m.case_id for m in group.members]
        rows = []
        for member in group.members:
            case = self.by_id[member.case_id]
            status = (
                "Repräsentant" if member.case_id == group.representative_case_id
                else "Clusterfall"
            )
            common = ", ".join(
                f"{ecu}:{dtc}" for ecu, dtc in group.common_faults[:7]
            ) or "Kein gemeinsamer Kern"
            ssl = getattr(case, "qec_ssl_end_finding", None) or "Nicht dokumentiert"
            rows.append((
                status, case.case_id, case.vin, f"{member.similarity:.1%}",
                f"{member.membership_strength:.1%}"
                if member.membership_strength is not None else "—",
                common, str(ssl),
            ))
        self.member_model.set_rows(rows)
        self.open_button.setEnabled(bool(rows))
        if rows:
            row = next(
                (i for i, m in enumerate(group.members)
                 if m.case_id == self._focused_case_id), 0,
            )
            self.member_table.selectRow(row)
        self._draw_plots()

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
        twin = self.compare_side.isChecked()
        self.other_plot.setVisible(twin)
        if twin:
            key = self.other_method.currentData()
            other = self._run_results.get(key)
            self.other_plot.set_result(other, self._subset(), group)
            if self._focused_case_id:
                self.other_plot.set_highlight(group, self._focused_case_id)
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
        for index, group in enumerate(self.result.groups):
            if case_id in group.case_ids:
                if self.group_table.currentIndex().row() != index:
                    self.group_table.selectRow(index)
                for row, member in enumerate(group.members):
                    if member.case_id == case_id:
                        self.member_table.selectRow(row)
                        break
                self._draw_plots()
                return True
        for row, cid in enumerate(self._noise_ids):
            if cid == case_id:
                self.noise_table.selectRow(row)
                break
        self._draw_plots()
        return True

    def clear_focus(self) -> None:
        self._focused_case_id = None
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
