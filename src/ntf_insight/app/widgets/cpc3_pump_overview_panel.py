"""Compact, FIN-searchable all-pump-case CPC3 SW overview.

All work uses the local knowledge store. No remote FIN transmission.
No guessed software flash dates or causal software success indicators.
"""
from __future__ import annotations

from collections import Counter

from PySide6.QtCore import QSortFilterProxyModel, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QFileDialog, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPushButton, QTableView, QVBoxLayout, QWidget,
)

from ntf_insight.analysis.cpc3_pump_overview import (
    CPC3PumpOverviewReport, build_cpc3_pump_overview,
    ecu_software_frequencies,
)
from ntf_insight.app.models.simple_table_model import SimpleTableModel
from ntf_insight.app.widgets.ecu_software_donut import ECUOverviewDonutCard
from ntf_insight.domain.case import NTFCase
from ntf_insight.reporting.cpc3_pump_excel import export_cpc3_pump_overview
from ntf_insight.storage.source_knowledge_store import SourceKnowledgeStore


_RUNNING_CPC3_TASKS: set[QThread] = set()


class _CPC3OverviewTask(QThread):
    completed = Signal(object, object)
    failed = Signal(str)

    def __init__(
        self,
        cases: tuple[NTFCase, ...],
        source_knowledge: SourceKnowledgeStore | None,
        ecu: str,
    ) -> None:
        super().__init__()
        self.cases = cases
        self.source_knowledge = source_knowledge
        self.ecu = ecu

    def run(self) -> None:
        try:
            names = {"CPC3", self.ecu}
            for case in self.cases:
                names.update(
                    state.ecu.strip().upper() for state in case.ecu_states
                    if state.ecu and state.ecu.strip()
                )
                names.update(
                    event.ecu.strip().upper() for event in case.diagnostics
                    if event.ecu and event.ecu.strip()
                )
            if self.source_knowledge is not None:
                names.update(self.source_knowledge.autoexport_ecu_names())
            report = build_cpc3_pump_overview(
                self.cases,
                ecu=self.ecu,
                load_ecu_history=(
                    self.source_knowledge.ecu_software_rows_for_fins
                    if self.source_knowledge is not None else None
                ),
            )
            self.completed.emit(report, tuple(sorted(names)))
        except Exception as exc:
            # Never echo FIN, absolute paths or customer texts into the GUI.
            self.failed.emit(type(exc).__name__)


class _CPC3OverviewFilter(QSortFilterProxyModel):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.source_cases = ()
        self.status_group = "all"
        self.dtc_group = "all"

    def filterAcceptsRow(self, source_row, source_parent):  # noqa: N802
        if not super().filterAcceptsRow(source_row, source_parent):
            return False
        if source_row >= len(self.source_cases):
            return False
        row = self.source_cases[source_row]
        if self.status_group != "all" and row.update_group != self.status_group:
            return False
        if self.dtc_group == "returned" and not row.returned_dtcs:
            return False
        observed = (
            row.pre_complete_tests > 0
            and row.post_complete_tests > 0
            and bool(row.pre_cpc3_dtcs)
        )
        if self.dtc_group == "not_seen" and (
            not observed or row.returned_dtcs
        ):
            return False
        if self.dtc_group == "unknown" and observed:
            return False
        return True


class CPC3PumpOverviewPanel(QWidget):
    """One row per investigated pump case, including missing evidence."""

    case_requested = Signal(str)

    def __init__(
        self, cases: list[NTFCase],
        source_knowledge: SourceKnowledgeStore | None,
    ) -> None:
        super().__init__()
        self.cases = tuple(cases)
        self.source_knowledge = source_knowledge
        self.report: CPC3PumpOverviewReport | None = None
        self._task: _CPC3OverviewTask | None = None
        self._updating_choices = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(10)
        self.heading = QLabel(
            "ECU · Software- und Pumpentauschübersicht",
            objectName="PageTitle",
        )
        layout.addWidget(self.heading)
        intro = QLabel(
            "Eine Zeile je Kühlmittelpumpenfall (auch mehrere Fälle derselben FIN). "
            "Dokumentierte SW-Maßnahmen und beobachtete Versionsabweichungen "
            "werden getrennt. Kein DTC im Nachtest beweist nicht, dass ein "
            "Softwareupdate den Fehler behoben hat.",
            objectName="PageSubtitle",
        )
        intro.setWordWrap(True)
        intro.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(intro)

        top = QHBoxLayout()
        top.addWidget(QLabel("Steuergerät:"))
        self.ecu_selector = QComboBox()
        self.ecu_selector.setEditable(True)
        self.ecu_selector.setInsertPolicy(
            QComboBox.InsertPolicy.NoInsert
        )
        self.ecu_selector.setMinimumWidth(145)
        self.ecu_selector.addItem("CPC3")
        self.ecu_selector.activated.connect(self._ecu_changed)
        self.ecu_selector.lineEdit().returnPressed.connect(self._ecu_changed)
        top.addWidget(self.ecu_selector)
        self.reload_button = QPushButton("Alle Pumpenfälle auswerten")
        self.reload_button.clicked.connect(self.run_analysis)
        top.addWidget(self.reload_button)
        self.export_button = QPushButton("Sichtbare Fälle als Excel …")
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self.export_visible)
        top.addWidget(self.export_button)
        self.toggle_charts = QPushButton("Kennzahlen ausblenden")
        self.toggle_charts.setCheckable(True)
        self.toggle_charts.setChecked(True)
        self.toggle_charts.toggled.connect(self._toggle_charts)
        top.addWidget(self.toggle_charts)
        top.addStretch(1)
        layout.addLayout(top)

        self.summary = QLabel(
            "Auswertung noch nicht gestartet.", objectName="PageSubtitle",
        )
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.summary)

        # Independent, mutually exclusive per-case counters. Absence of a
        # full ECU scan is explicitly unknown, NEVER classified as healed.
        self.chart_row = QHBoxLayout()
        self.donut_pre = ECUOverviewDonutCard("ECU-DTC vor Tausch")
        self.donut_sw = ECUOverviewDonutCard("Häufigste SW vor Tausch")
        self.donut_post = ECUOverviewDonutCard("ECU-DTC nach Tausch")
        for chart in (self.donut_pre, self.donut_sw, self.donut_post):
            self.chart_row.addWidget(chart, 1)
        layout.addLayout(self.chart_row)
        self.donut_pre.set_counts(())
        self.donut_sw.set_counts(())
        self.donut_post.set_counts(())

        # These are RETURNED-PUMP case concentrations, not installed-fleet
        # failure probabilities; rate only if >=5 valid complete QT pairs.
        self.sw_frequency_heading = QLabel(
            "Auffällige SW-Stände unter Pumpenfällen "
            "(keine Ausfallquote der Fahrzeugflotte)",
            objectName="CardTitle",
        )
        layout.addWidget(self.sw_frequency_heading)
        self.sw_frequency_model = SimpleTableModel((
            "SW-Stand vor Tausch", "Pumpenfälle", "FINs",
            "Fälle mit ECU-DTC vor Tausch",
            "Auswertbare QT-Vor/Nach-Paare",
            "Gleicher DTC erneut", "Wiederkehrrate (mind. 5 Paare)",
        ))
        self.sw_frequency_table = QTableView()
        self.sw_frequency_table.setModel(self.sw_frequency_model)
        self.sw_frequency_table.setMaximumHeight(130)
        self.sw_frequency_table.setMinimumHeight(60)
        self.sw_frequency_table.setAlternatingRowColors(True)
        self.sw_frequency_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        layout.addWidget(self.sw_frequency_table)
        controls = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText(
            "FIN, Fall, SW-Version, DTC oder Status suchen …"
        )
        self.search.setClearButtonEnabled(True)
        controls.addWidget(self.search, 1)
        self.update_filter = QComboBox()
        for title, value in (
            ("Alle SW-Befunde", "all"),
            ("SW-Maßnahme am Tauschtag", "documented_same_day"),
            ("SW-Maßnahme zeitnah (±14 Tage)", "documented_nearby"),
            ("SW-Stand vor/nach verschieden", "observed_change"),
            ("SW-Stand gleich beobachtet", "observed_same"),
            ("SW-Angaben unvollständig", "unknown"),
            ("Ohne Pumpentauschdatum", "no_swap"),
        ):
            self.update_filter.addItem(title, value)
        controls.addWidget(self.update_filter)
        self.dtc_filter = QComboBox()
        for title, value in (
            ("Alle DTC-Verläufe", "all"),
            ("Gleicher ECU-DTC erneut gesehen", "returned"),
            ("Gleicher ECU-DTC im Nachtest nicht gesehen", "not_seen"),
            ("DTC-Verlauf nicht beurteilbar", "unknown"),
        ):
            self.dtc_filter.addItem(title, value)
        controls.addWidget(self.dtc_filter)
        layout.addLayout(controls)

        self.model = SimpleTableModel((
            "QEC-/Fall-ID", "FIN", "Komponente", "Pumpentauschdatum",
            "ECU", "SW vor Tausch", "SW nach Tausch",
            "Alle SW-Stände dieser FIN", "Chronologischer SW-Verlauf",
            "Anzahl SW-Stände", "SW-Maßnahme / Standabweichung",
            "Beobachtungsintervall", "ECU-DTC vor: Evidenz",
            "ECU-DTC nach: Evidenz", "ECU-DTCs vor",
            "ECU-DTCs nach", "DTC-Verlauf",
            "SW-Wirkung / Zuordnung", "Vollständige QT vor/nach Tausch",
            "Vollständige QT vor/nach SW", "DTC erneut nach SW",
            "Quellen / dokumentierte SW-Maßnahme", "Datenlücken",
        ))
        self.proxy = _CPC3OverviewFilter(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setFilterCaseSensitivity(
            Qt.CaseSensitivity.CaseInsensitive
        )
        self.proxy.setFilterKeyColumn(-1)
        self.search.textChanged.connect(self.proxy.setFilterFixedString)
        self.search.textChanged.connect(self._update_visible_count)
        self.update_filter.currentIndexChanged.connect(self._set_filters)
        self.dtc_filter.currentIndexChanged.connect(self._set_filters)
        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.setWordWrap(False)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        for column, width in enumerate((
            160, 175, 135, 115, 85, 135, 135, 300, 390, 95,
            280, 195, 175, 175, 170, 170, 270, 320,
            125, 125, 175, 350, 300,
        )):
            self.table.setColumnWidth(column, width)
        self.table.doubleClicked.connect(self._open_case)
        self.table.clicked.connect(self._show_selected_history)
        layout.addWidget(self.table, 1)
        self.sw_detail_label = QLabel(
            "Chronologische SW-Messungen der ausgewählten Fall-FIN",
            objectName="CardTitle",
        )
        layout.addWidget(self.sw_detail_label)
        self.sw_detail_model = SimpleTableModel((
            "Diagnosezeit", "SW aus EcuSwVersionTxt",
            "Bezug zum Pumpentausch", "Originalquelle",
        ))
        self.sw_detail_table = QTableView()
        self.sw_detail_table.setModel(self.sw_detail_model)
        self.sw_detail_table.setMaximumHeight(135)
        self.sw_detail_table.setMinimumHeight(55)
        self.sw_detail_table.setAlternatingRowColors(True)
        self.sw_detail_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        layout.addWidget(self.sw_detail_table)
        self.details = QLabel(
            "Doppelklick auf eine Fallzeile öffnet die zugehörige FIN/Fallanalyse.",
            objectName="PageSubtitle",
        )
        self.details.setWordWrap(True)
        layout.addWidget(self.details)

    def _ecu_changed(self, *_args) -> None:
        ecu = self.ecu_selector.currentText().strip().upper()
        if (
            not self._updating_choices and ecu and self._task is None
            and (self.report is None or ecu != self.report.ecu)
        ):
            self.report = None
            self.run_analysis()

    def _toggle_charts(self, visible: bool) -> None:
        for widget in (
            self.donut_pre, self.donut_sw, self.donut_post,
            self.sw_frequency_heading, self.sw_frequency_table,
        ):
            widget.setVisible(visible)
        self.toggle_charts.setText(
            "Kennzahlen ausblenden" if visible else "Kennzahlen anzeigen"
        )

    def _set_filters(self, *_args) -> None:
        self.proxy.status_group = self.update_filter.currentData() or "all"
        self.proxy.dtc_group = self.dtc_filter.currentData() or "all"
        self.proxy.invalidateFilter()
        self._update_visible_count()

    def _visible_cases(self) -> tuple:
        if self.report is None:
            return ()
        return tuple(
            self.report.cases[
                self.proxy.mapToSource(self.proxy.index(row, 0)).row()
            ]
            for row in range(self.proxy.rowCount())
        )

    def _update_visible_count(self, *_args) -> None:
        if self.report is None:
            return
        visible = self._visible_cases()
        self.details.setText(
            f"{len(visible)} von {self.report.total_pump_cases} "
            "Pumpenfällen sichtbar. Doppelklick öffnet die FIN/Fallanalyse. "
            "Excel enthält nur die aktuell sichtbaren Fälle."
        )
        before = Counter(row.pre_dtc_evidence for row in visible)
        after = Counter(row.post_dtc_evidence for row in visible)
        self.donut_pre.set_counts((
            ("ECU-DTC gesehen", before["present"]),
            ("QT ohne ECU-DTC", before["tested_none"]),
            ("Keine genügenden Belege", before["unknown"]),
        ))
        self.donut_post.set_counts((
            ("ECU-DTC gesehen", after["present"]),
            ("QT ohne ECU-DTC", after["tested_none"]),
            ("Keine genügenden Belege", after["unknown"]),
        ))
        common = Counter(
            row.before_sw for row in visible
            if row.before_sw and not row.truncated
        )
        top = common.most_common(5)
        used = sum(n for _, n in top)
        remainder = sum(common.values()) - used
        no_sw = len(visible) - sum(common.values())
        self.donut_sw.set_counts(tuple([
            *((str(sw), int(n)) for sw, n in top),
            ("Weitere SW", remainder),
            ("Ohne SW-Beleg", no_sw),
        ]))
        frequencies = ecu_software_frequencies(visible)
        self.sw_frequency_model.set_rows([
            (
                freq.version, freq.cases, freq.fins,
                freq.with_pre_dtc, freq.with_pre_complete_comparison,
                freq.same_dtc_returned,
                (
                    f"{freq.recurrence_percent:.1f} %"
                    if freq.recurrence_percent is not None
                    else "— (weniger als 5 QT-Paare)"
                ),
            )
            for freq in frequencies[:25]
        ])
        if self.proxy.rowCount():
            self._show_selected_history(self.proxy.index(0, 0))
        else:
            self.sw_detail_model.set_rows([])

    def _show_selected_history(self, index) -> None:
        if self.report is None or not index.isValid():
            self.sw_detail_model.set_rows([])
            return
        row = self.proxy.mapToSource(index).row()
        if row >= len(self.report.cases):
            return
        item = self.report.cases[row]
        self.sw_detail_label.setText(
            f"SW-Messhistorie · ECU {item.ecu} · Fall {item.case_id}"
        )
        self.sw_detail_model.set_rows([
            (when, version, context, source)
            for when, version, context, source in item.sw_observations
        ])

    def ensure_loaded(self) -> None:
        if self.report is None and self._task is None:
            self.run_analysis()

    def run_analysis(self) -> None:
        if self._task is not None:
            return
        self.reload_button.setEnabled(False)
        self.ecu_selector.setEnabled(False)
        self.export_button.setEnabled(False)
        ecu = self.ecu_selector.currentText().strip().upper() or "CPC3"
        self.heading.setText(f"{ecu} · Software- und Pumpentauschübersicht")
        self.summary.setText(
            f"{ecu}-SW-Verlauf und vorhandene Diagnosebelege "
            "aller Pumpenfälle werden lokal ausgewertet …"
        )
        job = _CPC3OverviewTask(
            self.cases, self.source_knowledge, ecu,
        )
        self._task = job
        _RUNNING_CPC3_TASKS.add(job)
        job.completed.connect(self._received_report)
        job.failed.connect(self._failed)
        job.finished.connect(self._task_finished)
        job.finished.connect(lambda: _RUNNING_CPC3_TASKS.discard(job))
        job.start()

    def _task_finished(self) -> None:
        self._task = None
        self.reload_button.setEnabled(True)
        self.ecu_selector.setEnabled(True)
        self.export_button.setEnabled(self.report is not None)

    def _failed(self, category: str) -> None:
        self.summary.setText(
            f"Lokale Analyse nicht möglich ({category}). "
            "Bitte lokale Datenbank und Zugriffsrechte prüfen. "
            "Es wurden keine Quelldaten verändert."
        )

    def _received_report(
        self, report: CPC3PumpOverviewReport,
        ecu_names: tuple[str, ...],
    ) -> None:
        self._updating_choices = True
        current = report.ecu
        self.ecu_selector.clear()
        self.ecu_selector.addItems(
            [current, *(name for name in ecu_names if name != current)]
        )
        self.ecu_selector.setCurrentText(current)
        self._updating_choices = False
        self.set_report(report)

    def set_report(self, report: CPC3PumpOverviewReport) -> None:
        """Also supports direct synchronous synthetic GUI tests."""
        self.report = report
        self.proxy.source_cases = report.cases
        self.model.set_rows([
            (
                item.case_id, item.fin, item.component,
                item.swap_day.isoformat() if item.swap_day else "Unbekannt",
                item.ecu,
                item.before_sw or "Nicht belegt",
                item.after_sw or "Nicht belegt",
                "; ".join(item.sw_versions) or "Nicht belegt",
                " → ".join(item.sw_history) or "Nicht belegt",
                len(item.sw_versions),
                item.update_status, item.interval_description or "—",
                {
                    "present": "ECU-DTC gesehen",
                    "tested_none": "Vollständiger QT ohne DTC",
                    "unknown": "Nicht beurteilbar",
                }[item.pre_dtc_evidence],
                {
                    "present": "ECU-DTC gesehen",
                    "tested_none": "Vollständiger QT ohne DTC",
                    "unknown": "Nicht beurteilbar",
                }[item.post_dtc_evidence],
                ", ".join(item.pre_dtc_observed) or "Keine belegt",
                ", ".join(item.post_dtc_observed) or "Keine belegt",
                item.dtc_status, item.sw_effect,
                f"{item.pre_complete_tests} / {item.post_complete_tests}",
                f"{item.sw_pre_complete_tests} / {item.sw_post_complete_tests}",
                ", ".join(item.sw_post_returned_dtcs) or "Keine belegt",
                " | ".join(item.update_events) or (
                    f"Vor: {item.before_source or '—'}; "
                    f"Nach: {item.after_source or '—'}"
                ),
                item.note,
            )
            for item in report.cases
        ])
        self.proxy.invalidateFilter()
        self.heading.setText(
            f"{report.ecu} · Software- und Pumpentauschübersicht"
        )
        self.summary.setText(
            f"{report.total_pump_cases} Pumpenfälle · "
            f"{report.unique_fins} unterschiedliche FINs · "
            f"{report.documented_swap_day_updates} SW-Maßnahmen "
            f"am Tauschtag dokumentiert · "
            f"{report.documented_nearby_updates} zeitnah (±14 Tage) · "
            f"{report.changed_sw_observed} SW-Standabweichungen ohne "
            f"belegten Updatezeitpunkt · "
            f"{report.unchanged_sw_observed} gleicher Stand beobachtet · "
            f"{report.not_assessable} ohne vergleichbare SW-/Tauschdaten. "
            f"{report.ecu}-DTC nach Tausch erneut: {report.dtc_returned}; "
            f"in Nachtests nicht erneut gesehen: {report.dtc_not_seen} "
            "(keine SW-Kausalitätsbestätigung)."
        )
        self.export_button.setEnabled(True)
        self._update_visible_count()

    def _open_case(self, index) -> None:
        if not index.isValid() or self.report is None:
            return
        row = self.proxy.mapToSource(index).row()
        if 0 <= row < len(self.report.cases):
            self.case_requested.emit(self.report.cases[row].case_id)

    def export_visible(self) -> None:
        if self.report is None:
            return
        chosen = self._visible_cases()
        if not chosen:
            QMessageBox.information(
                self, "ECU-Excel", "Keine sichtbaren Fälle zum Exportieren."
            )
            return
        filename, _ = QFileDialog.getSaveFileName(
            self, "ECU-Fallübersicht lokal als Excel speichern",
            f"NTF_{self.report.ecu}_SW_Pumpentausch_Uebersicht.xlsx",
            "Excel (*.xlsx)",
        )
        if not filename:
            return
        if not filename.lower().endswith(".xlsx"):
            filename += ".xlsx"
        try:
            exported = export_cpc3_pump_overview(filename, chosen)
        except (OSError, ValueError, PermissionError):
            QMessageBox.warning(
                self, "ECU-Excel",
                "Der Excel-Export ist fehlgeschlagen. Bitte lokalen "
                "Dateipfad und Schreibberechtigung prüfen.",
            )
            return
        self.details.setText(
            f"{exported} aktuell sichtbare Fälle lokal exportiert. "
            "Die Datei enthält FINs und gehört nur in eine freigegebene Ablage."
        )
