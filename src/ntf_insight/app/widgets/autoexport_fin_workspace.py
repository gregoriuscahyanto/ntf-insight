"""Eine FIN-basierte Clusteranalyse, ergänzt aus AutoExport und QEC.

Ein sichtbarer Startknopf, dieselben Verfahren HDBSCAN Leaf/EOM und
konservatives Complete-Link. Originaldaten bleiben lokal. Die Darstellung
ist eine 2D/3D-Punktwolke und NIE die Berechnungsgrundlage.
"""
from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QFrame, QHBoxLayout,
    QLabel, QLineEdit, QPlainTextEdit, QPushButton, QScrollArea,
    QSpinBox, QTableView, QVBoxLayout, QWidget,
)

from ntf_insight.analysis.autoexport_fin_patterns import (
    METHOD_TITLES, FinPatternResult, cluster_fin_methods,
)
from ntf_insight.analysis.combined_fin_evidence import (
    QECFinEvidence, merge_fin_evidence, qec_fin_evidence,
)
from ntf_insight.app.models.simple_table_model import SimpleTableModel
from ntf_insight.app.widgets.fin_cluster_projection_plot import FinClusterProjectionPlot
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
        only_pump_swap: bool,
        min_cluster_size: int,
        min_samples: int,
        minimum_similarity: float,
    ) -> None:
        super().__init__()
        self.source = source
        self.qec_evidence = qec_evidence
        self.only_pump_swap = only_pump_swap
        self.min_cluster_size = min_cluster_size
        self.min_samples = min_samples
        self.minimum_similarity = minimum_similarity

    def run(self) -> None:
        try:
            self.phase.emit("Lese AutoExport und QEC als eindeutige FINs …")
            if self.source is not None:
                fins, auto_faults, labels = self.source.autoexport_fin_dtc_signatures(
                    pump_swap_dates=self.qec_evidence.pump_swap_dates,
                    include_all_fins=not self.only_pump_swap,
                )
            else:
                fins, auto_faults, labels = (), {}, {}
            combined = merge_fin_evidence(
                fins, auto_faults, labels, self.qec_evidence,
                only_pump_swap=self.only_pump_swap,
            )
            results = cluster_fin_methods(
                combined.fins, combined.faults,
                combined.labels, combined.case_links,
                min_cluster_size=self.min_cluster_size,
                min_samples=self.min_samples,
                minimum_similarity=self.minimum_similarity,
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
    ) -> None:
        super().__init__()
        self.source = source
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

        self.number_labels: dict[str, QLabel] = {}
        summary = QHBoxLayout()
        summary.setSpacing(9)
        for key, title in (
            ("total", "FINs insgesamt"),
            ("groups", "Gefundene Cluster"),
            ("assigned", "FINs in Clustern"),
            ("unassigned", "Mit DTC, ohne Cluster"),
            ("missing", "Ohne geeignete DTC"),
        ):
            card = QFrame()
            card.setObjectName("Card")
            inner = QVBoxLayout(card)
            inner.setContentsMargins(10, 9, 10, 9)
            heading = QLabel(title, objectName="CardTitle")
            heading.setWordWrap(True)
            inner.addWidget(heading)
            value = QLabel("–", objectName="CardValue")
            inner.addWidget(value)
            self.number_labels[key] = value
            summary.addWidget(card, 1)
        # Kept as a counted field for detailed tests and optional summaries.
        self.number_labels["dtc"] = QLabel("–")
        body.addLayout(summary)
        self.summary_note = QLabel(
            "FINs ohne geeignete DTC werden nicht geclustert, bleiben "
            "aber in der Gesamtanzahl sichtbar.",
            objectName="PageSubtitle",
        )
        self.summary_note.setWordWrap(True)
        body.addWidget(self.summary_note)

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
                "Cluster", "FINs", "Mit QEC", "Repräsentative FIN",
                "DTC-Kern", "Diagnoseähnlichkeit",
            ),
            (77, 75, 90, 190, 100, 170),
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
        self.min_cluster_size.setEnabled(True)
        self.min_samples.setEnabled(True)

    def _receive(self, results: dict[str, FinPatternResult]) -> None:
        self._enable_controls()
        self._run_results = results
        key = self.method_combo.currentData()
        self._show_result(results.get(key) or results["leaf"])

    def _failed(self, message: str) -> None:
        self._enable_controls()
        self.status.setText("Clusteranalyse nicht möglich: " + message)

    def _method_changed(self, *_args) -> None:
        key = self.method_combo.currentData()
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
            f"{result.dtc_fins:,} FINs mit DTC-Daten. "
            f"{len(result.no_dtc_fins):,} FINs ohne geeignete "
            "DTC-Daten sind nicht geclustert. "
            "Bei FINs mit dokumentiertem Pumpentausch werden nur "
            "Diagnosemerkmale vor diesem Tausch verwendet."
            .replace(",", ".")
        )
        self.status.setText(
            f"{METHOD_TITLES[result.method]}: "
            f"{len(result.groups)} Cluster · {result.assigned_fins:,} "
            f"FINs gruppiert. Methodenwechsel und 2D/3D benötigen "
            "keine Neuberechnung."
        )
        self.group_model.set_rows([
            (
                f"C{group.group_id}",
                group.fin_count,
                group.qec_fin_count,
                group.representative_fin,
                group.shared_fault_count,
                f"{group.median_similarity:.1%}",
            )
            for group in result.groups
        ])
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
        else:
            self.explanation.setText(
                "Das Verfahren hat bei diesen Einstellungen keine "
                "geeigneten Cluster gebildet. Das beweist nicht, "
                "dass keine Kühlmittelpumpenstörung vorliegt."
            )

    def select_group(self, group_id: int) -> None:
        if self.result is None:
            return
        for row, group in enumerate(self.result.groups):
            if group.group_id == group_id:
                self.group_table.selectRow(row)
                return

    def _group_changed(self, index, _previous) -> None:
        if self.result is None or not index.isValid():
            return
        if index.row() >= len(self.result.groups):
            return
        group = self.result.groups[index.row()]
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
        lines = [
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
                lines.append(
                    f"• {ecu}:{dtc}{label} – bei {count} "
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
                if result.method in ("leaf", "eom") else
                "Complete-Link prüft innerhalb begrenzter Leaf-Teilgruppen, "
                "ob jede Paarähnlichkeit mindestens 45 % beträgt."
            ),
            result.notes,
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
