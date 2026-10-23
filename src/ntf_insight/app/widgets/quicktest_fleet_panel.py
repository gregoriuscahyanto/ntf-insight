"""Fahrzeugübergreifender QuickTest-Bestand mit CPC3-, DTC- und FIN-Filtern."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QTabWidget,
    QTableView, QHeaderView, QVBoxLayout, QWidget,
    QAbstractItemView,
)

from ntf_insight.analysis.quicktest_fleet import analyze_quicktest_fleet
from ntf_insight.app.models.simple_table_model import SimpleTableModel
from ntf_insight.storage.quicktest_store import QuickTestStore


class QuickTestFleetPanel(QWidget):
    fin_requested = Signal(str)

    def __init__(self, store: QuickTestStore) -> None:
        super().__init__()
        self.store = store
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(10)
        layout.addWidget(QLabel("QuickTest-Gesamtauswertung", objectName="PageTitle"))
        explanation = QLabel(
            "Alle lokal importierten QuickTests, unabhängig von QEC-Fällen. "
            "Zähler beschreiben Diagnosebeobachtungen, keine Ausfallraten oder "
            "Ursachennachweise. CPC3 ist bei der Kühlmittelpumpe besonders relevant.",
            objectName="PageSubtitle",
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Steuergerät"))
        self.ecu_filter = QLineEdit("CPC3")
        self.ecu_filter.setPlaceholderText("z. B. CPC3; leer = alle")
        controls.addWidget(self.ecu_filter)
        controls.addWidget(QLabel("DTC"))
        self.dtc_filter = QLineEdit()
        self.dtc_filter.setPlaceholderText("DTC-Code filtern")
        controls.addWidget(self.dtc_filter)
        self.refresh_button = QPushButton("Alle QuickTests auswerten")
        self.refresh_button.clicked.connect(self.refresh)
        controls.addWidget(self.refresh_button)
        layout.addLayout(controls)

        self.summary = QLabel(objectName="CardTitle")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        self.fin_model = SimpleTableModel((
            "FIN", "QuickTests", "Erster Test", "Letzter Test",
            "DTC-Beobachtungen", "QuickTests ohne DTC",
        ))
        self.dtc_model = SimpleTableModel((
            "ECU", "DTC", "Beobachtungen", "FINs", "QuickTests",
            "Erstmals beobachtet", "Zuletzt beobachtet",
        ))
        self.ecu_model = SimpleTableModel((
            "ECU", "FINs", "QuickTests", "DTC-Beobachtungen",
        ))
        self.software_model = SimpleTableModel((
            "ECU", "Softwarestand", "FINs", "QuickTests",
        ))
        self.fin_table = None
        for label, model in (
            ("Fahrzeuge / FIN", self.fin_model),
            ("DTC-Muster", self.dtc_model),
            ("Steuergeräte", self.ecu_model),
            ("Softwarestände", self.software_model),
        ):
            table = QTableView()
            table.setModel(model)
            table.setSortingEnabled(True)
            table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            table.setAlternatingRowColors(True)
            table.verticalHeader().setVisible(False)
            table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
            table.horizontalHeader().setStretchLastSection(True)
            self.tabs.addTab(table, label)
            if label == "Fahrzeuge / FIN":
                self.fin_table = table
        self.fin_table.doubleClicked.connect(self._open_fin)
        self.refresh()

    def refresh(self) -> None:
        result = analyze_quicktest_fleet(
            self.store, ecu_filter=self.ecu_filter.text(),
            dtc_filter=self.dtc_filter.text(),
        )
        self.summary.setText(
            f"{result.fins} FINs · {result.reports} QuickTests · "
            f"{result.ecus} ECU-Blöcke · {result.dtc_observations} DTC-Beobachtungen · "
            f"{result.clean_reports} QuickTests ohne DTC"
        )
        self.fin_model.set_rows([
            (fin, n, str(start), str(end), count, clean)
            for fin, n, start, end, count, clean in result.report_rows
        ])
        self.dtc_model.set_rows([
            (ecu, dtc, n, fins, tests, str(first), str(last))
            for ecu, dtc, n, fins, tests, first, last in result.dtc_rows
        ])
        self.ecu_model.set_rows(result.ecu_rows)
        self.software_model.set_rows(result.software_rows)

    def _open_fin(self, index) -> None:
        if not index.isValid():
            return
        # Qt sorting changes view rows. Use the model index of the clicked cell.
        fin_index = index.siblingAtColumn(0)
        fin = fin_index.data()
        if fin:
            self.fin_requested.emit(str(fin))
