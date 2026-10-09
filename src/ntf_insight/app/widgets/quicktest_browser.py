"""Read-only FIN-centred QuickTest explorer (independent of QEC/NTF cases)."""
from __future__ import annotations

import json

from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QSpinBox,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ntf_insight.app.models.simple_table_model import SimpleTableModel
from ntf_insight.app.models.ecu_version_table_model import ECUVersionTableModel
from ntf_insight.analysis.ecu_version_changes import detect_ecu_version_changes
from ntf_insight.ingestion.quicktest_detailed import _identifier
from ntf_insight.storage.quicktest_store import QuickTestStore


def _table(model: SimpleTableModel, min_height: int = 130) -> QTableView:
    table = QTableView()
    table.setModel(model)
    table.setMinimumHeight(min_height)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setAlternatingRowColors(True)
    table.verticalHeader().setVisible(False)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    table.horizontalHeader().setStretchLastSection(True)
    return table


class QuickTestBrowser(QWidget):
    """Show FIN, date, all ECUs and DTC parameters from the local DuckDB."""

    def __init__(self, store: QuickTestStore) -> None:
        super().__init__()
        self.store = store
        self._reports: list[dict] = []
        self._ecus: list[dict] = []
        self._dtcs: list[dict] = []
        self._report_id: str | None = None
        self._version_flags: dict[str, frozenset[str]] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(10)
        layout.addWidget(QLabel("QuickTests nach FIN", objectName="PageTitle"))

        caption = QLabel(
            "Alle QuickTests werden dauerhaft unter der im PDF erkannten FIN gespeichert "
            "– auch ohne QEC-Schadteilfall. Der Diagnosezeitpunkt ist ein "
            "Beobachtungszeitpunkt, nicht der sichere Fehlerbeginn.",
            objectName="PageSubtitle",
        )
        caption.setWordWrap(True)
        layout.addWidget(caption)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("FIN:"))
        self.fin_selector = QComboBox()
        self.fin_selector.setMinimumWidth(220)
        self.fin_selector.addItems(self.store.list_fins())
        controls.addWidget(self.fin_selector, 1)
        self.summary = QLabel(objectName="PageSubtitle")
        controls.addWidget(self.summary, 2)
        layout.addLayout(controls)

        layout.addWidget(QLabel("Diagnosesitzungen", objectName="CardTitle"))
        self.report_model = SimpleTableModel(
            ("Diagnosezeit", "FIN", "Kilometerstand", "Steuergeräte", "DTCs")
        )
        self.report_table = _table(self.report_model)
        self.report_table.setMaximumHeight(185)
        layout.addWidget(self.report_table)

        layout.addWidget(QLabel("Steuergeräte / HW-/SW-Stände", objectName="CardTitle"))
        self.ecu_model = ECUVersionTableModel()
        self.ecu_table = _table(self.ecu_model)
        self.ecu_table.setMaximumHeight(190)
        layout.addWidget(self.ecu_table)

        self.version_hint = QLabel(objectName="PageSubtitle")
        self.version_hint.setWordWrap(True)
        self.version_hint.setText(
            "Farbig markiert: HW-/SW-Stand weicht vom letzten vergleichbaren "
            "QuickTest dieser FIN ab. Markiert ist der erste beobachtete "
            "neue Stand, nicht das Datum eines bestätigten Updates."
        )
        layout.addWidget(self.version_hint)

        controls_dtc = QHBoxLayout()
        controls_dtc.addWidget(QLabel("DTC-Beobachtungen", objectName="CardTitle"))
        controls_dtc.addStretch(1)
        controls_dtc.addWidget(QLabel("Filter ECU:"))
        self.ecu_filter = QComboBox()
        self.ecu_filter.addItem("Alle Steuergeräte", None)
        controls_dtc.addWidget(self.ecu_filter)
        layout.addLayout(controls_dtc)

        self.dtc_model = SimpleTableModel(
            ("ECU", "DTC", "Art", "Beschreibung", "Status",
             "Häufigkeit", "Erste km", "Letzte km")
        )
        self.dtc_table = _table(self.dtc_model, min_height=150)
        self.dtc_table.setMaximumHeight(220)
        layout.addWidget(self.dtc_table)

        detail = QGridLayout()
        detail.setHorizontalSpacing(14)
        self.parameter_model = SimpleTableModel(
            ("Snapshot-Parameter", "Erster Wert", "Letzter Wert", "PDF-Seite")
        )
        self.parameter_table = _table(self.parameter_model)
        detail.addWidget(QLabel("DTC-Snapshot / Freeze-Frame", objectName="CardTitle"), 0, 0)
        detail.addWidget(self.parameter_table, 1, 0)

        self.metadata_text = QPlainTextEdit()
        self.metadata_text.setReadOnly(True)
        self.metadata_text.setPlaceholderText(
            "ECU oder DTC auswählen, um Metadaten und den Rohtext zu sehen."
        )
        detail.addWidget(QLabel("Quelltext / Metadaten", objectName="CardTitle"), 0, 1)
        detail.addWidget(self.metadata_text, 1, 1)
        detail.setColumnStretch(0, 2)
        detail.setColumnStretch(1, 3)
        layout.addLayout(detail)

        bottom = QHBoxLayout()
        bottom.addWidget(QLabel("Original-PDF-Seitentext", objectName="CardTitle"))
        bottom.addStretch(1)
        bottom.addWidget(QLabel("Seite"))
        self.page_selector = QSpinBox()
        self.page_selector.setMinimum(1)
        self.page_selector.setMaximum(1)
        bottom.addWidget(self.page_selector)
        layout.addLayout(bottom)

        self.page_text = QPlainTextEdit()
        self.page_text.setReadOnly(True)
        self.page_text.setMaximumHeight(180)
        layout.addWidget(self.page_text)

        self.fin_selector.currentIndexChanged.connect(self._load_fin)
        self.report_table.clicked.connect(self._report_clicked)
        self.ecu_table.clicked.connect(self._ecu_clicked)
        self.ecu_filter.currentIndexChanged.connect(self._show_dtcs)
        self.dtc_table.clicked.connect(self._dtc_clicked)
        self.page_selector.valueChanged.connect(self._load_page)
        self._load_fin()

    def select_fin(self, fin: str) -> None:
        """Select a FIN even if it currently has no uploaded QuickTest PDF.

        Showing an explicit 0-report FIN avoids silently leaving the browser
        on a different vehicle when navigating from a QEC case.
        """
        index = self.fin_selector.findText(fin)
        if index < 0 and fin:
            self.fin_selector.addItem(fin)
            index = self.fin_selector.findText(fin)
        if index >= 0:
            self.fin_selector.setCurrentIndex(index)

    def _load_fin(self) -> None:
        fin = self.fin_selector.currentText()
        self._reports = self.store.list_reports(fin) if fin else []
        # Across *all* QuickTests of this FIN, independent from a QEC case.
        # Calculate once on FIN switch; the selected report is then highlighted.
        all_states = []
        for report in self._reports:
            _, _, states = self.store.case_projection(report["report_id"])
            all_states.extend(states)
        changed: dict[str, set[str]] = {}
        for change in detect_ecu_version_changes(all_states):
            changed.setdefault(change.current.event_id, set()).add(change.kind)
        self._version_flags = {
            event_id: frozenset(kinds)
            for event_id, kinds in changed.items()
        }
        self.report_model.set_rows([
            (
                report["diagnosed_at"].strftime("%d.%m.%Y %H:%M"),
                report["fin"],
                report["mileage_km"],
                report["ecu_count"],
                report["dtc_count"],
            )
            for report in self._reports
        ])
        self.summary.setText(
            f"{len(self._reports)} Kurztest(s) für diese FIN" if fin
            else "Noch keine QuickTest-PDFs importiert"
        )
        if self._reports:
            self.report_table.selectRow(0)
            self._select_report(0)
        else:
            self._report_id = None
            self._ecus = []
            self._dtcs = []
            self.ecu_model.set_rows_with_flags([], [])
            self.dtc_model.set_rows([])
            self.parameter_model.set_rows([])
            self.metadata_text.clear()
            self.page_text.clear()

    def _report_clicked(self, index) -> None:
        if index.isValid():
            self._select_report(index.row())

    def _select_report(self, row: int) -> None:
        if not 0 <= row < len(self._reports):
            return
        report = self._reports[row]
        self._report_id = report["report_id"]
        self._ecus = self.store.list_ecus(self._report_id)
        self._dtcs = self.store.list_dtcs(self._report_id)
        flags = [
            self._version_flags.get(
                _identifier(self._report_id, f"ecu:{ecu['ecu_index']}:state"),
                frozenset(),
            )
            for ecu in self._ecus
        ]
        self.ecu_model.set_rows_with_flags(
            [
                (
                    ecu["ecu_code"], ecu["name"],
                    ecu["metadata"].get("ecu_variant"),
                    ecu["metadata"].get("hardware_version"),
                    ecu["metadata"].get("software_version"),
                    (
                        "HW + SW abweichend"
                        if {"hw", "sw"} <= changed
                        else "HW abweichend" if "hw" in changed
                        else "SW abweichend" if "sw" in changed
                        else "Keine belegte Abweichung"
                    ),
                    ecu["dtc_count"],
                )
                for ecu, changed in zip(self._ecus, flags)
            ],
            flags,
        )
        hw = sum("hw" in changed for changed in flags)
        sw = sum("sw" in changed for changed in flags)
        self.version_hint.setText(
            f"Dieses QuickTest: {hw} abweichende HW- und {sw} abweichende "
            "SW-Stände gegenüber dem letzten vergleichbaren Stand. "
            "Farbig hervorgehoben sind nur beobachtete Versionsunterschiede; "
            "ein physischer Steuergerätetausch oder Flash-Zeitpunkt "
            "ist dadurch nicht bewiesen."
        )

        self.ecu_filter.blockSignals(True)
        self.ecu_filter.clear()
        self.ecu_filter.addItem("Alle Steuergeräte", None)
        for ecu in self._ecus:
            self.ecu_filter.addItem(
                f'{ecu["ecu_code"]} ({ecu["ecu_index"]})', ecu["ecu_index"]
            )
        self.ecu_filter.blockSignals(False)
        self._show_dtcs()
        self.metadata_text.setPlainText(
            json.dumps(report["header"], indent=2, ensure_ascii=False)
        )
        with self.store.store.connect() as con:
            pages = con.execute(
                "SELECT COUNT(*) FROM quicktest_pages WHERE report_id = ?",
                [self._report_id],
            ).fetchone()[0]
        self.page_selector.blockSignals(True)
        self.page_selector.setMaximum(max(1, pages))
        self.page_selector.setValue(1)
        self.page_selector.blockSignals(False)
        self._load_page()

    def _ecu_clicked(self, index) -> None:
        if not index.isValid() or not 0 <= index.row() < len(self._ecus):
            return
        ecu = self._ecus[index.row()]
        self.metadata_text.setPlainText(
            json.dumps(ecu["metadata"], indent=2, ensure_ascii=False)
            + "\n\n--- ECU-Rohtext ---\n"
            + ecu["raw_block_text"]
        )
        self.ecu_filter.setCurrentIndex(
            self.ecu_filter.findData(ecu["ecu_index"])
        )

    def _show_dtcs(self) -> None:
        chosen_ecu = self.ecu_filter.currentData()
        self._visible_dtcs = [
            dtc for dtc in self._dtcs
            if chosen_ecu is None or dtc["ecu_index"] == chosen_ecu
        ]
        self.dtc_model.set_rows([
            (
                dtc["ecu_code"], dtc["dtc_code"], dtc["kind"],
                dtc["description"], dtc["status"],
                dtc["frequency_counter"], dtc["original_odometer_km"],
                dtc["most_recent_odometer_km"],
            )
            for dtc in self._visible_dtcs
        ])
        self.parameter_model.set_rows([])

    def _dtc_clicked(self, index) -> None:
        if not index.isValid() or not 0 <= index.row() < len(self._visible_dtcs):
            return
        dtc = self._visible_dtcs[index.row()]
        self.parameter_model.set_rows([
            (
                item["name"], item["first_value"], item["last_value"], item["page"],
            )
            for item in self.store.list_parameters(
                self._report_id, dtc["ecu_index"], dtc["dtc_index"]
            )
        ])
        self.metadata_text.setPlainText(dtc["raw_block_text"])
        if dtc["page_start"]:
            self.page_selector.setValue(dtc["page_start"])

    def _load_page(self) -> None:
        self.page_text.setPlainText(
            self.store.page_text(self._report_id, self.page_selector.value()) or ""
            if self._report_id else ""
        )
