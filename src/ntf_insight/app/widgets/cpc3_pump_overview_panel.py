"""Compact, FIN-searchable all-pump-case CPC3 SW overview.

All work uses the local knowledge store. No remote FIN transmission.
No guessed software flash dates or causal software success indicators.
"""
from __future__ import annotations

from PySide6.QtCore import QSortFilterProxyModel, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QFileDialog, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPushButton, QTableView, QVBoxLayout, QWidget,
)

from ntf_insight.analysis.cpc3_pump_overview import (
    CPC3PumpOverviewReport, build_cpc3_pump_overview,
)
from ntf_insight.app.models.simple_table_model import SimpleTableModel
from ntf_insight.domain.case import NTFCase
from ntf_insight.reporting.cpc3_pump_excel import export_cpc3_pump_overview
from ntf_insight.storage.source_knowledge_store import SourceKnowledgeStore


_RUNNING_CPC3_TASKS: set[QThread] = set()


class _CPC3OverviewTask(QThread):
    completed = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        cases: tuple[NTFCase, ...],
        source_knowledge: SourceKnowledgeStore | None,
    ) -> None:
        super().__init__()
        self.cases = cases
        self.source_knowledge = source_knowledge

    def run(self) -> None:
        try:
            report = build_cpc3_pump_overview(
                self.cases,
                load_autoexport=(
                    self.source_knowledge.cpc3_software_rows_for_fin
                    if self.source_knowledge is not None else None
                ),
            )
            self.completed.emit(report)
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

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(10)
        layout.addWidget(QLabel(
            "CPC3 · Software- und Pumpentauschübersicht",
            objectName="PageTitle",
        ))
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
        self.reload_button = QPushButton("Alle Pumpenfälle auswerten")
        self.reload_button.clicked.connect(self.run_analysis)
        top.addWidget(self.reload_button)
        self.export_button = QPushButton("Sichtbare Fälle als Excel …")
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self.export_visible)
        top.addWidget(self.export_button)
        top.addStretch(1)
        layout.addLayout(top)

        self.summary = QLabel(
            "Auswertung noch nicht gestartet.", objectName="PageSubtitle",
        )
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.summary)
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
            ("CPC3-DTC erneut gesehen", "returned"),
            ("CPC3-DTC nicht erneut gesehen", "not_seen"),
            ("DTC-Verlauf nicht beurteilbar", "unknown"),
        ):
            self.dtc_filter.addItem(title, value)
        controls.addWidget(self.dtc_filter)
        layout.addLayout(controls)

        self.model = SimpleTableModel((
            "QEC-/Fall-ID", "FIN", "Komponente", "Pumpentauschdatum",
            "CPC3-SW vor Tausch", "CPC3-SW nach Tausch",
            "SW-Maßnahme / Standabweichung", "Beobachtungsintervall",
            "CPC3-DTCs vor", "CPC3-DTCs nach", "DTC-Verlauf",
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
            160, 175, 135, 115, 135, 135, 285, 195, 170,
            170, 270, 320, 125, 125, 175, 350, 300,
        )):
            self.table.setColumnWidth(column, width)
        self.table.doubleClicked.connect(self._open_case)
        layout.addWidget(self.table, 1)
        self.details = QLabel(
            "Doppelklick auf eine Fallzeile öffnet die zugehörige FIN/Fallanalyse.",
            objectName="PageSubtitle",
        )
        self.details.setWordWrap(True)
        layout.addWidget(self.details)

    def _set_filters(self, *_args) -> None:
        self.proxy.status_group = self.update_filter.currentData() or "all"
        self.proxy.dtc_group = self.dtc_filter.currentData() or "all"
        self.proxy.invalidateFilter()
        self._update_visible_count()

    def _update_visible_count(self) -> None:
        if self.report is not None:
            self.details.setText(
                f"{self.proxy.rowCount()} von {self.report.total_pump_cases} "
                "Pumpenfällen sichtbar. Doppelklick öffnet die FIN/Fallanalyse. "
                "Excel enthält nur die aktuell sichtbaren Fälle."
            )

    def ensure_loaded(self) -> None:
        if self.report is None and self._task is None:
            self.run_analysis()

    def run_analysis(self) -> None:
        if self._task is not None:
            return
        self.reload_button.setEnabled(False)
        self.export_button.setEnabled(False)
        self.summary.setText(
            "CPC3-SW-Verlauf und vollständige QuickTest-Belege "
            "aller Pumpenfälle werden lokal ausgewertet …"
        )
        job = _CPC3OverviewTask(self.cases, self.source_knowledge)
        self._task = job
        _RUNNING_CPC3_TASKS.add(job)
        job.completed.connect(self.set_report)
        job.failed.connect(self._failed)
        job.finished.connect(self._task_finished)
        job.finished.connect(lambda: _RUNNING_CPC3_TASKS.discard(job))
        job.start()

    def _task_finished(self) -> None:
        self._task = None
        self.reload_button.setEnabled(True)
        self.export_button.setEnabled(self.report is not None)

    def _failed(self, category: str) -> None:
        self.summary.setText(
            f"Lokale Analyse nicht möglich ({category}). "
            "Bitte lokale Datenbank und Zugriffsrechte prüfen. "
            "Es wurden keine Quelldaten verändert."
        )

    def set_report(self, report: CPC3PumpOverviewReport) -> None:
        """Also supports direct synchronous synthetic GUI tests."""
        self.report = report
        self.proxy.source_cases = report.cases
        self.model.set_rows([
            (
                item.case_id, item.fin, item.component,
                item.swap_day.isoformat() if item.swap_day else "Unbekannt",
                item.before_sw or "Nicht belegt",
                item.after_sw or "Nicht belegt",
                item.update_status, item.interval_description or "—",
                ", ".join(item.pre_cpc3_dtcs) or "Keine belegt",
                ", ".join(item.post_cpc3_dtcs) or "Keine belegt",
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
            f"CPC3-DTC nach Tausch erneut: {report.dtc_returned}; "
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
        chosen = tuple(
            self.report.cases[
                self.proxy.mapToSource(self.proxy.index(row, 0)).row()
            ]
            for row in range(self.proxy.rowCount())
        )
        if not chosen:
            QMessageBox.information(
                self, "CPC3-Excel", "Keine sichtbaren Fälle zum Exportieren."
            )
            return
        filename, _ = QFileDialog.getSaveFileName(
            self, "CPC3-Fallübersicht lokal als Excel speichern",
            "NTF_CPC3_SW_Pumpentausch_Uebersicht.xlsx",
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
                self, "CPC3-Excel",
                "Der Excel-Export ist fehlgeschlagen. Bitte lokalen "
                "Dateipfad und Schreibberechtigung prüfen.",
            )
            return
        self.details.setText(
            f"{exported} aktuell sichtbare Fälle lokal exportiert. "
            "Die Datei enthält FINs und gehört nur in eine freigegebene Ablage."
        )
