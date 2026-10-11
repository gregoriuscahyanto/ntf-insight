"""Eine FIN-basierte Clusteranalyse, ergänzt aus AutoExport und QEC.

Ein sichtbarer Startknopf, dieselben Verfahren HDBSCAN Leaf/EOM und
konservatives Complete-Link. Originaldaten bleiben lokal. Die Darstellung
ist eine 2D/3D-Punktwolke und NIE die Berechnungsgrundlage.
"""
from __future__ import annotations

from dataclasses import replace
from collections import defaultdict
from time import perf_counter

from PySide6.QtCore import QModelIndex, QThread, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QFrame, QHBoxLayout,
    QLabel, QLineEdit, QMenu, QPlainTextEdit, QPushButton, QScrollArea,
    QSpinBox, QTableView, QToolButton, QVBoxLayout, QWidget,
)

from ntf_insight.analysis.autoexport_fin_patterns import (
    METHOD_TITLES, FinPatternResult, cluster_fin_methods,
)
from ntf_insight.analysis.combined_fin_evidence import (
    QECFinEvidence, merge_fin_evidence, qec_fin_evidence,
)
from ntf_insight.app.models.simple_table_model import SimpleTableModel
from ntf_insight.app.widgets.fin_cluster_projection_plot import FinClusterProjectionPlot
from ntf_insight.app.widgets.fin_coverage_donut import FinCoverageDonut
from ntf_insight.analysis.qec_end_finding_filter import (
    finding_counts, part_numbers, qec_pump_cases, selected_qec_cases,
    source_coverage,
)
from ntf_insight.app.widgets.fin_status_donut import (
    FIN_COLORS, FIN_LABELS, FinStatusDonut,
)
from ntf_insight.analysis.dtc_review_priority import (
    GroupDtcPriority, review_priority,
)
from ntf_insight.storage.dtc_review_store import DtcReviewStore
from ntf_insight.domain.case import NTFCase
from ntf_insight.storage.source_knowledge_store import SourceKnowledgeStore


_ACTIVE_FIN_TASKS: set[QThread] = set()


class _FinClusterTask(QThread):
    calculated = Signal(object)
    failed = Signal(str)
    phase = Signal(str)

    def __init__(
        self,
        source: SourceKnowledgeStore | None,
        qec_evidence: QECFinEvidence,
        *,
        only_qec: bool,
        qec_cases: tuple[NTFCase, ...],
        part_number: str,
        quicktest_fins: tuple[str, ...],
        min_cluster_size: int,
        min_samples: int,
        minimum_similarity: float,
    ) -> None:
        super().__init__()
        self.source = source
        self.qec_evidence = qec_evidence
        self.only_qec = only_qec
        self.qec_cases = qec_cases
        self.part_number = part_number
        self.quicktest_fins = quicktest_fins
        self.min_cluster_size = min_cluster_size
        self.min_samples = min_samples
        self.minimum_similarity = minimum_similarity

    def run(self) -> None:
        started = perf_counter()
        try:
            self.phase.emit("Lese AutoExport und QEC als eindeutige FINs …")
            if self.source is not None:
                fins, auto_faults, labels = self.source.autoexport_fin_dtc_signatures(
                    pump_swap_dates=self.qec_evidence.pump_swap_dates,
                    include_all_fins=True,
                    fin_filter=(
                        tuple(self.qec_evidence.case_links)
                        if self.only_qec else None
                    ),
                )
                tips_fins = self.source.autoexport_source_fins("autoexport_tips")
                raw_dtc_fins = self.source.autoexport_source_fins("autoexport_dtc")
            else:
                fins, auto_faults, labels = (), {}, {}
                tips_fins = frozenset()
                raw_dtc_fins = frozenset()
            combined = merge_fin_evidence(
                fins, auto_faults, labels, self.qec_evidence,
                only_qec=self.only_qec,
            )
            cover = source_coverage(
                combined.fins, self.qec_cases,
                part_number=self.part_number,
                tips_fins=tips_fins, quicktest_fins=self.quicktest_fins,
            )
            part_fins: dict[str, set[str]] = defaultdict(set)
            for case in self.qec_cases:
                number = str(getattr(case, "qec_part_number", "") or "").strip()
                if number and case.vin.strip().upper() in combined.fins:
                    part_fins[number].add(case.vin.strip().upper())
            observed = set(raw_dtc_fins) | {
                case.vin.strip().upper()
                for case in self.qec_cases if case.diagnostics
            }
            no_records = sum(
                fin not in observed
                for fin in combined.fins if not combined.faults[fin]
            )
            unsuitable = sum(not combined.faults[fin] for fin in combined.fins)
            coverage_counts = {
                "total": cover.total_fins,
                "part": cover.part_number_fins,
                "qec": cover.qec_fins,
                "tips": cover.tips_fins,
                "quicktest": cover.quicktest_fins,
                "qec_cases": cover.qec_case_count,
            }
            results = cluster_fin_methods(
                combined.fins, combined.faults,
                combined.labels, combined.case_links,
                min_cluster_size=self.min_cluster_size,
                min_samples=self.min_samples,
                minimum_similarity=self.minimum_similarity,
                include_qec_anchors=True,
                progress=self.phase.emit,
            )
            enriched = {
                key: replace(
                    result,
                    sources_by_fin=combined.sources,
                    autoexport_fin_count=combined.autoexport_fin_count,
                    qec_fin_count=combined.qec_fin_count,
                    overlap_fin_count=combined.overlap_fin_count,
                    qec_only_fin_count=combined.qec_only_fin_count,
                    pre_swap_fins=len(self.qec_evidence.pump_swap_dates),
                    runtime_seconds=round(perf_counter() - started, 2),
                    dtc_keys_by_fin=combined.faults,
                    source_coverage_counts=coverage_counts,
                    qec_part_number_counts={
                        number: len(members)
                        for number, members in part_fins.items()
                    },
                    no_dtc_without_records=no_records,
                    no_dtc_with_records_excluded=unsuitable - no_records,
                )
                for key, result in results.items()
            }
            self.calculated.emit(enriched)
        except ValueError as exc:
            self.failed.emit(str(exc))
        except Exception:
            # SQL drivers may expose FINs and local file paths in exceptions;
            # never send untrusted exception text to GUI, CI or a chat export.
            self.failed.emit(
                "Analyse nicht abgeschlossen. Bitte lokale "
                "AutoExport-Datenbank und Importzuordnung prüfen."
            )


class _SelectableText(QPlainTextEdit):
    """Read-only, scrollable complete ECU:DTC explanation, test-compatible."""

    def __init__(self) -> None:
        super().__init__()
        self.setReadOnly(True)
        self.setMinimumHeight(175)
        self.setMaximumHeight(245)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.setPlaceholderText(
            "Cluster auswählen, um die gemeinsamen Diagnosen zu verstehen."
        )

    def text(self) -> str:
        return self.toPlainText()

    def setText(self, text: str) -> None:  # noqa: N802
        self.setPlainText(text)


def _table(
    headers: tuple[str, ...], widths: tuple[int, ...],
    height: int,
) -> tuple[QTableView, SimpleTableModel]:
    model = SimpleTableModel(headers, [])
    view = QTableView()
    view.setModel(model)
    view.setMinimumHeight(height)
    view.setAlternatingRowColors(True)
    view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    view.verticalHeader().setVisible(False)
    for index, width in enumerate(widths):
        view.setColumnWidth(index, width)
    view.horizontalHeader().setStretchLastSection(True)
    return view, model


class AutoExportFinWorkspace(QWidget):
    """Single user-facing Clusteranalyse: one FIN, one point, three methods."""

    fin_requested = Signal(str)
    case_requested = Signal(str)

    def __init__(
        self,
        source: SourceKnowledgeStore | None,
        cases: list[NTFCase],
        population_metrics: dict[str, int] | None = None,
        *,
        review_store: DtcReviewStore | None = None,
    ) -> None:
        super().__init__()
        self.source = source
        self.review_store = review_store
        self._review_marks = (
            review_store.list_marks() if review_store is not None else {}
        )
        self._review_levels: dict[int, GroupDtcPriority] = {}
        self._case_vins = {case.case_id: case.vin for case in cases}
        self.by_id = {case.case_id: case for case in cases}
        self._focused_case_id: str | None = None
        self._qec_evidence = qec_fin_evidence(cases)
        self._linked = self._qec_evidence.case_links
        self._pump_swap_dates = self._qec_evidence.pump_swap_dates
        self.population_metrics = population_metrics or {}
        self._task: _FinClusterTask | None = None
        self._run_results: dict[str, FinPatternResult] = {}
        self.result: FinPatternResult | None = None
        self._selected_fin: str | None = None
        self._shown_members: list[str] = []
        self._group_rows: tuple[int, ...] = ()
        self._analysis_scoped_to_pump = False
        self._normal_method = "leaf"

        shell = QVBoxLayout(self)
        shell.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        shell.addWidget(scroll)
        content = QWidget()
        scroll.setWidget(content)
        body = QVBoxLayout(content)
        body.setContentsMargins(22, 18, 22, 25)
        body.setSpacing(12)

        body.addWidget(QLabel("Clusteranalyse", objectName="PageTitle"))
        intro = QLabel(
            "AutoExport und QEC werden über die FIN zusammengeführt. "
            "Ein Fahrzeug zählt genau einmal. Die Cluster zeigen "
            "ähnliche Diagnosen – nicht bestätigte Pumpenfehler.",
            objectName="PageSubtitle",
        )
        intro.setWordWrap(True)
        body.addWidget(intro)

        total_auto = self.population_metrics.get("autoexport_unique_fins", 0)
        self.population_note = QLabel(
            (
                f"AutoExport: {total_auto:,} FINs importiert · "
                f"QEC-Pumpenfälle: {len(self._linked):,} FINs · "
                "Gesamte eindeutige FIN-Zahl nach gemeinsamer Analyse."
            ).replace(",", "."),
            objectName="PageSubtitle",
        )
        self.population_note.setWordWrap(True)
        body.addWidget(self.population_note)

        # Small everyday parameter row, one actual calculation button.
        settings = QHBoxLayout()
        settings.addWidget(QLabel("Mindestgröße"))
        self.min_cluster_size = QSpinBox()
        self.min_cluster_size.setRange(2, 100)
        self.min_cluster_size.setValue(5)
        self.min_cluster_size.setToolTip(
            "Kleinste Anzahl unterschiedlicher FINs, die eine Gruppe bilden."
        )
        settings.addWidget(self.min_cluster_size)
        settings.addWidget(QLabel("MinSamples"))
        self.min_samples = QSpinBox()
        self.min_samples.setRange(1, 100)
        self.min_samples.setValue(2)
        settings.addWidget(self.min_samples)
        settings.addStretch(1)
        body.addLayout(settings)

        self.only_pump_swap = QCheckBox(
            "Nur FINs mit QEC-Pumpentauschdatum"
        )
        self.only_pump_swap.setToolTip(
            "Ohne Haken: AutoExport und QEC gemeinsam; FINs ohne "
            "Pumpentausch bleiben Teil der allgemeinen Diagnosemustersuche. "
            "Mit Haken: nur nachgewiesen vorherige Diagnosen "
            "mit dem Tauschdatum aus QEC Rep.-Datum."
        )
        body.addWidget(self.only_pump_swap)

        self.qec_anchor_mode = QCheckBox(
            "QEC-Fälle als Anker für die Clusterbildung verwenden"
        )
        self.qec_anchor_mode.setToolTip(
            "Optionales eigenes Zuordnungsverfahren (KEIN HDBSCAN): "
            "Jede geeignete QEC-FIN ist ein Diagnose-Anker; "
            "AutoExport-FINs kommen nur bei mindestens 45 % "
            "ECU:DTC-Cosinusähnlichkeit zu ihrem nächsten Anker dazu. "
            "Gruppen benötigen die eingestellte Mindestgröße. "
            "Ohne Haken: bisherige HDBSCAN-/Complete-Link-Methoden."
        )
        body.addWidget(self.qec_anchor_mode)

        actions = QHBoxLayout()
        self.start_button = QPushButton("Clusteranalyse starten")
        self.start_button.setObjectName("ClusterStartButton")
        self.start_button.clicked.connect(self.run_analysis)
        actions.addWidget(self.start_button)
        actions.addStretch(1)
        body.addLayout(actions)
        self.status = QLabel(
            "Bereit. Nur lokal importierte AutoExport- und QEC-Daten "
            "werden ausgewertet.",
            objectName="PageSubtitle",
        )
        self.status.setWordWrap(True)
        body.addWidget(self.status)

        # Clear overview: one cluster count, one FIN donut with three
        # mutually exclusive categories. No chart library, no data upload.
        self.number_labels: dict[str, QLabel] = {}
        overview = QHBoxLayout()
        overview.setSpacing(10)

        count_card = QFrame()
        count_card.setObjectName("Card")
        count_card.setMinimumWidth(210)
        cluster_stack = QVBoxLayout(count_card)
        cluster_stack.setContentsMargins(17, 15, 17, 15)
        cluster_stack.addWidget(QLabel(
            "Gefundene Cluster", objectName="CardTitle",
        ))
        number = QLabel("–", objectName="CardValue")
        number.setStyleSheet("font-size: 31px; font-weight: 700;")
        self.number_labels["groups"] = number
        cluster_stack.addWidget(number)
        cluster_stack.addStretch(1)
        overview.addWidget(count_card, 1)

        distribution_card = QFrame()
        distribution_card.setObjectName("Card")
        distribution_box = QHBoxLayout(distribution_card)
        distribution_box.setContentsMargins(15, 12, 19, 12)
        distribution_box.setSpacing(15)
        self.donut = FinStatusDonut()
        distribution_box.addWidget(self.donut, 0)
        legend = QVBoxLayout()
        headline = QHBoxLayout()
        headline.addWidget(QLabel(
            "Verteilung der FINs", objectName="CardTitle",
        ))
        headline.addStretch(1)
        headline.addWidget(QLabel("FINs gesamt:"))
        total = QLabel("–", objectName="CardValue")
        self.number_labels["total"] = total
        headline.addWidget(total)
        legend.addLayout(headline)
        self.percent_labels: dict[str, QLabel] = {}
        for index, key in enumerate(("assigned", "unassigned", "missing")):
            line = QHBoxLayout()
            square = QLabel("●")
            square.setStyleSheet(
                f"color: {FIN_COLORS[index]}; font-size: 15px;"
            )
            square.setFixedWidth(18)
            line.addWidget(square)
            group_label = QLabel(FIN_LABELS[index])
            group_label.setMinimumWidth(175)
            line.addWidget(group_label)
            percent = QLabel("–")
            percent.setObjectName("PageSubtitle")
            self.percent_labels[key] = percent
            line.addWidget(percent)
            line.addStretch(1)
            count = QLabel("–", objectName="CardValue")
            self.number_labels[key] = count
            line.addWidget(count)
            legend.addLayout(line)
        legend.addStretch(1)
        distribution_box.addLayout(legend, 1)
        overview.addWidget(distribution_card, 3)
        body.addLayout(overview)
        # Compatibility: number of FINs with suitable DTCs; also in caption.
        self.number_labels["dtc"] = QLabel("–")

        self.summary_note = QLabel(
            "Alle eindeutigen FINs werden gezählt. FINs ohne geeignete "
            "DTC-Daten erhalten keine künstliche Clusterzuordnung.",
            objectName="PageSubtitle",
        )
        self.summary_note.setWordWrap(True)
        body.addWidget(self.summary_note)
        self.priority_note = QLabel(
            "Fachliche Prüfpriorität: markiere wichtige ECU:DTCs "
            "im DTC-Explorer. Dies verändert keine Cluster.",
            objectName="PageSubtitle",
        )
        self.priority_note.setWordWrap(True)
        body.addWidget(self.priority_note)

        plot_header = QHBoxLayout()
        plot_header.addWidget(QLabel(
            "FIN-Punktwolke · Diagnoseähnlichkeit", objectName="CardTitle",
        ))
        plot_header.addStretch(1)
        plot_header.addWidget(QLabel("Verfahren"))
        self.method_combo = QComboBox()
        for key in ("leaf", "eom", "complete_cosine"):
            self.method_combo.addItem(METHOD_TITLES[key], key)
        self.method_combo.setMinimumWidth(208)
        self.method_combo.currentIndexChanged.connect(self._method_changed)
        self.qec_anchor_mode.toggled.connect(self._anchor_mode_changed)
        plot_header.addWidget(self.method_combo)
        self.dimension = QComboBox()
        self.dimension.addItem("2D", "2d")
        self.dimension.addItem("3D · drehbar", "3d")
        self.dimension.currentIndexChanged.connect(self._dimension_changed)
        plot_header.addWidget(self.dimension)
        reset = QPushButton("Ansicht zurücksetzen")
        reset.clicked.connect(self._reset_view)
        plot_header.addWidget(reset)
        body.addLayout(plot_header)
        self.plot = FinClusterProjectionPlot()
        self.plot.fin_picked.connect(self._point_picked)
        self.chart = self.plot
        body.addWidget(self.plot)

        self.group_table, self.group_model = _table(
            (
                "Cluster", "Prüfpriorität", "Markierte FINs",
                "FINs", "Mit QEC", "Repräsentative FIN",
                "Rep. QEC?", "DTC-Kern", "Diagnoseähnlichkeit",
            ),
            (76, 145, 115, 75, 85, 185, 94, 92, 166),
            235,
        )
        self.group_table.selectionModel().currentRowChanged.connect(
            self._group_changed
        )
        body.addWidget(QLabel(
            "Cluster auswählen", objectName="CardTitle",
        ))
        body.addWidget(self.group_table)

        self.why_heading = QLabel(
            "Warum gehören diese FINs zusammen?", objectName="CardTitle",
        )
        self.why_heading.setWordWrap(True)
        body.addWidget(self.why_heading)
        self.explanation = _SelectableText()
        body.addWidget(self.explanation)

        find = QHBoxLayout()
        find.addWidget(QLabel("FIN suchen"))
        self.fin_search = QLineEdit()
        self.fin_search.setPlaceholderText(
            "Auch FINs ohne Cluster oder ohne QEC finden"
        )
        self.fin_search.returnPressed.connect(self.find_fin)
        find.addWidget(self.fin_search, 1)
        self.find_button = QPushButton("FIN finden")
        self.find_button.clicked.connect(self.find_fin)
        find.addWidget(self.find_button)
        body.addLayout(find)
        self.fin_status = QLabel(objectName="PageSubtitle")
        self.fin_status.setWordWrap(True)
        body.addWidget(self.fin_status)

        body.addWidget(QLabel(
            "FINs im ausgewählten Cluster", objectName="CardTitle",
        ))
        self.fin_table, self.fin_model = _table(
            (
                "FIN", "ECU:DTC", "Ähnlichkeit zum Repräsentanten",
                "QEC-Fälle", "QEC-Fallkennungen", "Datenherkunft",
            ),
            (185, 90, 205, 90, 200, 160),
            280,
        )
        self.fin_table.selectionModel().currentRowChanged.connect(
            self._fin_changed
        )
        self.fin_table.doubleClicked.connect(self.open_fin)
        body.addWidget(self.fin_table)
        self.open_button = QPushButton(
            "Ausgewählte FIN und vorhandene QEC-Fälle öffnen"
        )
        self.open_button.setEnabled(False)
        self.open_button.clicked.connect(self.open_fin)
        body.addWidget(self.open_button)

        for control in (self.min_cluster_size, self.min_samples):
            control.valueChanged.connect(self._invalidate)
        self.only_pump_swap.toggled.connect(self._invalidate)
        # Keep one static plot and cached results for fast method switching.
        self._show_empty()

    def _show_empty(self) -> None:
        self.plot.set_result(None)
        self.group_model.set_rows([])
        self.fin_model.set_rows([])
        self.explanation.setText(
            "Clusteranalyse starten und danach einen Cluster auswählen."
        )
        for label in self.number_labels.values():
            label.setText("–")
        self.donut.set_values(None)
        for label in self.percent_labels.values():
            label.setText("–")
        self._review_levels = {}
        self.priority_note.setText(
            "DTC-Markierungen aus dem Explorer bestimmen nur die "
            "Prüfpriorität, nicht die Clusterbildung."
        )

    def _invalidate(self, *_args) -> None:
        if self._task is not None:
            return
        if self._run_results:
            self._run_results = {}
            self.result = None
            self._show_empty()
            self.status.setText(
                "Parameter geändert. Clusteranalyse bitte erneut starten."
            )

    def run_analysis(self) -> None:
        if self._task is not None:
            return
        self._run_results = {}
        self.result = None
        self._show_empty()
        self._analysis_scoped_to_pump = self.only_pump_swap.isChecked()
        self.start_button.setEnabled(False)
        self.only_pump_swap.setEnabled(False)
        self.qec_anchor_mode.setEnabled(False)
        self.min_cluster_size.setEnabled(False)
        self.min_samples.setEnabled(False)
        task = _FinClusterTask(
            self.source, self._qec_evidence,
            only_pump_swap=self._analysis_scoped_to_pump,
            min_cluster_size=self.min_cluster_size.value(),
            min_samples=self.min_samples.value(),
            minimum_similarity=0.45,
        )
        self._task = task
        _ACTIVE_FIN_TASKS.add(task)
        task.calculated.connect(self._receive)
        task.failed.connect(self._failed)
        task.phase.connect(self.status.setText)
        task.finished.connect(lambda: _ACTIVE_FIN_TASKS.discard(task))
        task.finished.connect(task.deleteLater)
        task.start()

    def _enable_controls(self) -> None:
        self._task = None
        self.start_button.setEnabled(True)
        self.only_pump_swap.setEnabled(True)
        self.qec_anchor_mode.setEnabled(True)
        self.min_cluster_size.setEnabled(True)
        self.min_samples.setEnabled(not self.qec_anchor_mode.isChecked())

    def _receive(self, results: dict[str, FinPatternResult]) -> None:
        self._enable_controls()
        self._run_results = results
        key = self.method_combo.currentData()
        self._show_result(results.get(key) or results["leaf"])

    def _failed(self, message: str) -> None:
        self._enable_controls()
        self.status.setText("Clusteranalyse nicht möglich: " + message)

    def _anchor_mode_changed(self, checked: bool) -> None:
        """Instantly compare QEC-seeded and HDBSCAN on the cached FIN set."""
        self.method_combo.blockSignals(True)
        try:
            if checked:
                selected = self.method_combo.currentData()
                if selected in ("leaf", "eom", "complete_cosine"):
                    self._normal_method = selected
                if self.method_combo.findData("qec_anchor") < 0:
                    self.method_combo.addItem(
                        METHOD_TITLES["qec_anchor"], "qec_anchor",
                    )
                self.method_combo.setCurrentIndex(
                    self.method_combo.findData("qec_anchor")
                )
            else:
                index = self.method_combo.findData("qec_anchor")
                if index >= 0:
                    self.method_combo.removeItem(index)
                self.method_combo.setCurrentIndex(
                    self.method_combo.findData(self._normal_method)
                )
        finally:
            self.method_combo.blockSignals(False)
        self.method_combo.setEnabled(not checked)
        if self._task is None:
            self.min_samples.setEnabled(not checked)
            method = self.method_combo.currentData()
            if method in self._run_results:
                self._show_result(self._run_results[method])
            elif self._run_results:
                # Never display an old HDBSCAN result under the label of
                # another, not-yet-calculated cluster procedure.
                self.result = None
                self._show_empty()
                self.status.setText(
                    "QEC-Ankergruppen noch nicht berechnet. "
                    "Bitte Clusteranalyse erneut starten."
                )
            else:
                self.status.setText(
                    "QEC-Ankerverfahren: mindestens 45 % Cosinusähnlichkeit "
                    "zur QEC-FIN. Bitte Clusteranalyse starten."
                    if checked else
                    "HDBSCAN / Complete-Link ausgewählt. "
                    "Bitte Clusteranalyse starten."
                )

    def _method_changed(self, *_args) -> None:
        if self.qec_anchor_mode.isChecked():
            return
        key = self.method_combo.currentData()
        if key in ("leaf", "eom", "complete_cosine"):
            self._normal_method = key
        if key in self._run_results:
            self._show_result(self._run_results[key])

    def _dimension_changed(self, *_args) -> None:
        self.plot.set_mode(self.dimension.currentData() or "2d")

    def _reset_view(self) -> None:
        self.plot.reset_view()

    def _show_result(self, result: FinPatternResult) -> None:
        self.result = result
        summary = {
            "total": result.total_fins,
            "dtc": result.dtc_fins,
            "groups": len(result.groups),
            "assigned": result.assigned_fins,
            "unassigned": len(result.unassigned_fins),
            "missing": len(result.no_dtc_fins),
        }
        if (
            summary["assigned"] + summary["unassigned"] + summary["missing"]
            != summary["total"]
        ):
            raise ValueError("FIN-Clusterzahlen passen nicht zum importierten Bestand.")
        for key, number in summary.items():
            self.number_labels[key].setText(f"{number:,}".replace(",", "."))
        self.donut.set_values((
            summary["assigned"], summary["unassigned"], summary["missing"],
        ))
        for key in ("assigned", "unassigned", "missing"):
            self.percent_labels[key].setText(
                (f"{summary[key] / summary['total'] * 100:.1f} %"
                 if summary["total"] else "0,0 %").replace(".", ",")
            )
        self.population_note.setText(
            (
                f"Gemeinsamer FIN-Bestand: {result.total_fins:,} eindeutige FINs. "
                f"AutoExport: {result.autoexport_fin_count:,} · "
                f"QEC: {result.qec_fin_count:,} FINs, davon "
                f"{result.overlap_fin_count:,} bereits im AutoExport · "
                f"QEC zusätzlich: {result.qec_only_fin_count:,}. "
                "Kein Fahrzeug doppelt gezählt."
            ).replace(",", ".")
        )
        self.summary_note.setText(
            (
                f"{result.dtc_fins:,} FINs mit DTC-Daten. "
                f"{len(result.no_dtc_fins):,} FINs ohne geeignete "
                "DTC-Daten sind nicht geclustert. "
                "Bei FINs mit dokumentiertem Pumpentausch werden nur "
                "Diagnosemerkmale vor diesem Tausch verwendet."
            ).replace(",", ".")
        )
        time_label = (
            f"{result.runtime_seconds:.1f} s"
            if result.runtime_seconds is not None else "nicht gemessen"
        )
        self.status.setText(
            (
                f"{METHOD_TITLES[result.method]}: "
                f"{len(result.groups)} Cluster · {result.assigned_fins:,} "
                f"FINs gruppiert · Laufzeit insgesamt: {time_label}. "
                "Methodenwechsel und 2D/3D benötigen keine Neuberechnung."
            ).replace(",", ".")
        )
        self._refresh_review_table()
        self.plot.set_result(result)
        self.plot.set_mode(self.dimension.currentData() or "2d")
        self._selected_fin = None
        self.fin_model.set_rows([])
        self._shown_members = []
        self.open_button.setEnabled(False)
        self.explanation.setText(
            "Wähle einen Cluster in der Tabelle oder klicke "
            "auf einen Punkt in der FIN-Punktwolke."
        )
        self.why_heading.setText(
            "Warum gehören diese FINs zusammen?"
        )
        if result.groups:
            self.group_table.selectRow(0)
            # Model resets may preserve the same current row and skip
            # Qt's currentRowChanged signal. Always show real evidence.
            self._group_changed(self.group_model.index(0, 0), QModelIndex())
        else:
            self.explanation.setText(
                (
                    "Keine QEC-Ankergruppe hat die Mindestgröße und "
                    "die erforderliche Diagnoseähnlichkeit erreicht. "
                    "FINs ohne passenden QEC-Anker bleiben unzugeordnet."
                    if result.method == "qec_anchor" else
                    "Das Verfahren hat bei diesen Einstellungen keine "
                    "geeigneten Cluster gebildet. Das beweist nicht, "
                    "dass keine Kühlmittelpumpenstörung vorliegt."
                )
            )

    def refresh_review_priorities(self) -> None:
        """Read local manual annotations; NEVER trigger cluster recalculation."""
        if self.review_store is None:
            return
        current = self.review_store.list_marks()
        if current == self._review_marks:
            return
        self._review_marks = current
        if self.result is not None:
            selected = None
            index = self.group_table.currentIndex()
            if index.isValid() and index.row() < len(self._group_rows):
                selected = self._group_rows[index.row()]
            self._refresh_review_table()
            if selected is not None:
                self.select_group(selected)
                row = self._group_rows.index(selected)
                self._group_changed(self.group_model.index(row, 0), QModelIndex())
            elif self._group_rows:
                self.group_table.selectRow(0)
                self._group_changed(self.group_model.index(0, 0), QModelIndex())

    def _refresh_review_table(self) -> None:
        if self.result is None:
            return
        keys = set(self._review_marks)
        faults = self.result.dtc_keys_by_fin or {}
        groups = self.result.groups
        self._review_levels = {
            group.group_id: review_priority(group, faults, keys)
            for group in groups
        }
        rank = {"hoch": 0, "hinweis": 1, "keine": 2}
        ranked = sorted(
            groups,
            key=lambda group: (
                rank[self._review_levels[group.group_id].level],
                -self._review_levels[group.group_id].ratio,
                -group.fin_count,
                group.group_id,
            ),
        )
        self._group_rows = tuple(g.group_id for g in ranked)
        self.group_model.set_rows([
            (
                f"C{group.group_id}",
                self._review_levels[group.group_id].label,
                (
                    f"{self._review_levels[group.group_id].affected_fins}"
                    f"/{group.fin_count}"
                ),
                group.fin_count,
                group.qec_fin_count,
                group.representative_fin,
                "Ja" if group.representative_has_qec else "Nein",
                group.shared_fault_count,
                f"{group.median_similarity:.1%}",
            )
            for group in ranked
        ])
        high = sum(
            score.level == "hoch" for score in self._review_levels.values()
        )
        hints = sum(
            score.level == "hinweis" for score in self._review_levels.values()
        )
        self.priority_note.setText(
            f"Fachliche Prüfpriorität: {high} Cluster hoch · "
            f"{hints} mit Prüfhinweis · "
            f"{len(self._review_marks)} markierte ECU:DTCs. "
            "Markierungen dienen der Nachprüfung, nicht der Ursachenzuweisung."
        )

    def select_group(self, group_id: int) -> None:
        if self.result is None:
            return
        for row, candidate in enumerate(self._group_rows):
            if candidate == group_id:
                self.group_table.selectRow(row)
                return

    def _group_changed(self, index, _previous) -> None:
        if self.result is None or not index.isValid():
            return
        if index.row() >= len(self._group_rows):
            return
        group_id = self._group_rows[index.row()]
        group = next(
            (item for item in self.result.groups if item.group_id == group_id),
            None,
        )
        if group is None:
            return
        self.plot.set_highlight(group.group_id)
        self._shown_members = [fin for fin, _ in group.members]
        self.fin_model.set_rows([
            (
                fin,
                self.result.code_counts.get(fin, 0),
                f"{similarity:.1%}",
                len(self.result.qec_links.get(fin, ())),
                ", ".join(self.result.qec_links.get(fin, ())) or "–",
                (self.result.sources_by_fin or {}).get(fin, "–"),
            )
            for fin, similarity in group.members
        ])
        self._selected_fin = None
        self.open_button.setEnabled(False)
        self.why_heading.setText(
            f"Warum gehören diese {group.fin_count} FINs zu Cluster "
            f"C{group.group_id}?"
        )
        priority = self._review_levels.get(group.group_id)
        if priority is None:
            priority = review_priority(
                group, self.result.dtc_keys_by_fin or {},
                set(self._review_marks),
            )
        if group.representative_is_fixed_anchor:
            representative_note = (
                "Diese QEC-FIN ist der feste Diagnose-Anker dieser Gruppe. "
                "Andere FINs wurden wegen ihrer Ähnlichkeit zu genau "
                "diesem Originalfall aufgenommen. Der Anker muss nicht "
                "der statistisch zentralste Fall seiner Gruppe sein."
            )
        elif group.representative_has_qec:
            representative_note = (
                "Eine FIN mit QEC-Fall wurde als Repräsentant bevorzugt. "
                "Ihr mittlerer Diagnose-Cosinuswert zum Cluster erreicht "
                f"{group.representative_centrality_ratio:.0%} des besten "
                "möglichen Werts und ist damit ausreichend typisch."
            )
        elif group.qec_fin_count:
            representative_note = (
                "Dieses Cluster enthält FINs mit QEC-Fällen. Diese sind "
                "jedoch diagnostisch weniger typisch (unter 90 % des "
                "höchsten mittleren Cosinuswerts). Deshalb wurde die "
                "zentralere FIN ohne QEC-Fall als Repräsentant gewählt."
            )
        else:
            representative_note = (
                "Im Cluster gibt es keine FIN mit QEC-Fall. "
                "Repräsentant ist die FIN mit der höchsten mittleren "
                "Diagnoseähnlichkeit zur Gruppe."
            )
        lines = [
            (
                f"Repräsentant: {group.representative_fin}. "
                + representative_note
            ),
            "",
            (
                f"Prüfpriorität: {priority.label}. "
                f"{priority.affected_fins} von {priority.total_fins} FINs "
                "enthalten mindestens einen manuell markierten Pumpen-DTC. "
                "Das ist kein Defektnachweis."
            ),
            *(
                [
                    "Markierte ECU:DTCs in diesem Cluster:",
                    *[
                        f"★ {ecu}:{dtc} – {count} von {group.fin_count} FINs"
                        for ecu, dtc, count in priority.marked_faults
                    ],
                ]
                if priority.marked_faults else []
            ),
            "",
            "1. Gemeinsame Diagnosemerkmale",
            f"Die {group.fin_count} Fahrzeuge teilen wiederkehrende "
            "Steuergerät-Fehlercode-Kombinationen (ECU:DTC). "
            "Zu jeder Kombination steht die Anzahl betroffener FINs. "
            "Ein Klartext erscheint nur, wenn er in den Daten vorliegt. "
            "Ein Klartext kann aus einem anderen Diagnosezeitpunkt "
            "stammen und war kein eigenes Clustering-Merkmal.",
        ]
        if group.common_faults:
            for ecu, dtc, count, description in group.common_faults:
                label = f" — {description}" if description else ""
                star = "★ " if (ecu, dtc) in self._review_marks else "• "
                lines.append(
                    f"{star}{ecu}:{dtc}{label} – bei {count} "
                    f"von {group.fin_count} FINs"
                )
        else:
            lines.append(
                "Kein ECU:DTC ist in mehr als einer FIN dieser Gruppe "
                "gemeinsam. Das Muster ist besonders kritisch zu prüfen."
            )
        lines.extend([
            "",
            "2. Wie wurde gruppiert?",
            (
                "HDBSCAN findet ähnliche Diagnosemuster mithilfe einer "
                "effizienten 16-dimensionalen Modellprojektion der "
                "ECU:DTC-TF-IDF-Merkmale."
                if self.result.method in ("leaf", "eom") else
                "QEC-Ankerverfahren: Alle hier gruppierten FINs besitzen "
                "mindestens 45 % ursprüngliche Cosinusähnlichkeit zur "
                "repräsentativen QEC-FIN. Nicht alle Fallpaare müssen "
                "untereinander ähnlich sein."
                if self.result.method == "qec_anchor" else
                "Complete-Link prüft innerhalb begrenzter Leaf-Teilgruppen, "
                "ob jede Paarähnlichkeit mindestens 45 % beträgt."
            ),
            self.result.notes,
            "",
            "3. Wie sicher ist die Ähnlichkeit?",
            (
                f"Es wurden {group.checked_pair_count} Diagnosepaare "
                "stichprobenartig oder vollständig geprüft. "
                f"Bei {group.pair_weak_count} Paaren lag die "
                "Cosinus-Ähnlichkeit unter 45 %. "
                "Das bedeutet diagnostische Uneinheitlichkeit, "
                "nicht eine Defektwahrscheinlichkeit."
            ),
            f"{group.qec_fin_count} der FINs haben einen QEC-Bezug. "
            "DTCs nach dem Pumpentausch sind keine Clustering-Merkmale. "
            "Bei FINs ohne Tauschanker ist eine allgemeine "
            "Diagnosehistorie mit den vorhandenen DTCs ausgewertet.",
            "Wichtig: Diese Cluster erklären Diagnoseähnlichkeit. "
            "Sie beweisen weder die Ursache in der Kühlmittelpumpe "
            "noch eine Verantwortung des Lieferanten.",
        ])
        self.explanation.setText("\n".join(lines))

    def _point_picked(self, fin: str) -> None:
        if self.result is None:
            return
        group = self.result.group_for(fin)
        if group is not None:
            self.select_group(group.group_id)
            self._select_fin_in_group(fin)
        else:
            self._selected_fin = fin
            self.open_button.setEnabled(True)
            self.fin_status.setText(
                "FIN hat DTCs, gehört aber zu keinem Cluster "
                "dieses Verfahrens."
            )

    def _fin_changed(self, index, _previous) -> None:
        if not index.isValid() or index.row() >= len(self._shown_members):
            return
        self._selected_fin = self._shown_members[index.row()]
        self.open_button.setEnabled(True)
        if self.result is not None:
            group = self.result.group_for(self._selected_fin)
            self.plot.set_highlight(
                group.group_id if group is not None else None,
                self._selected_fin,
            )

    def _select_fin_in_group(self, fin: str) -> None:
        for row, existing in enumerate(self._shown_members):
            if existing == fin:
                self.fin_table.selectRow(row)
                self.fin_table.scrollTo(self.fin_model.index(row, 0))
                break

    def find_fin(self) -> bool:
        if self.result is None:
            self.fin_status.setText("Bitte zuerst die Clusteranalyse starten.")
            return False
        fin = self.fin_search.text().strip().upper()
        if not fin:
            self.fin_status.setText("Bitte eine FIN eingeben.")
            return False
        group = self.result.group_for(fin)
        if group is not None:
            self.select_group(group.group_id)
            self._select_fin_in_group(fin)
            self.fin_status.setText(
                f"FIN liegt in Cluster C{group.group_id}."
            )
            return True
        if fin in self.result.no_dtc_fins:
            self.fin_status.setText(
                "FIN vorhanden, aber ohne geeignete DTC-Merkmale "
                "für diese Clusteranalyse."
            )
        elif fin in self.result.unassigned_fins:
            self.fin_status.setText(
                "FIN hat Diagnosemerkmale, wurde aber keinem "
                "Cluster zugeordnet."
            )
        else:
            self.fin_status.setText(
                "FIN nicht in der ausgewählten Datenbasis vorhanden."
            )
            return False
        self._selected_fin = fin
        self.open_button.setEnabled(True)
        return True

    def focus_case(self, case_id: str) -> bool:
        """Keep existing QEC case-navigation API on the single FIN view."""
        fin = self._case_vins.get(case_id)
        if not fin:
            return False
        self._focused_case_id = case_id
        self.fin_search.setText(fin)
        if self.result is not None:
            self.find_fin()
        else:
            self.fin_status.setText(
                "QEC-Fahrzeug ausgewählt. Clusteranalyse starten, um dessen "
                "Einordnung im gesamten AutoExport+QEC-Bestand zu sehen."
            )
        return True

    def clear_focus(self) -> None:
        self._focused_case_id = None
        self._selected_fin = None
        self.plot.set_highlight(None)
        self.fin_status.setText("")

    def open_fin(self, *_args) -> None:
        if self._selected_fin:
            self.fin_requested.emit(self._selected_fin)
