"""Lokaler Suchdialog für tausende importierte Steuergeräte und ECU:DTCs."""
from __future__ import annotations

from collections import Counter

from PySide6.QtCore import Qt, QSortFilterProxyModel
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QTabWidget, QTableView, QVBoxLayout, QWidget,
)

from ntf_insight.analysis.cluster_dtc_filters import ClusterDtcFilter
from ntf_insight.app.models.simple_table_model import SimpleTableModel


class ClusterDtcFilterDialog(QDialog):
    """Vier Regellisten, editierbar durch Suche und Mehrfach-Zeilenauswahl."""

    def __init__(self, catalog: dict[tuple[str, str], tuple[int, int, str]],
                 rules: ClusterDtcFilter, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Steuergeräte und DTCs für Cluster auswählen")
        self.resize(910, 620)
        self._sets = {
            "include_ecus": set(rules.include_ecus),
            "exclude_ecus": set(rules.exclude_ecus),
            "include_faults": set(rules.include_faults),
            "exclude_faults": set(rules.exclude_faults),
        }
        outer = QVBoxLayout(self)
        note = QLabel(
            "Einschließen: nur gewählte Steuergeräte ODER ECU:DTCs verwenden. "
            "Ohne Einschluss gelten alle. Ausschlüsse haben immer Vorrang. "
            "Mehrere Zeilen mit Strg/Umschalt wählen; Suchfeld durchsucht "
            "Steuergerät, DTC und Beschreibung. Originaldaten bleiben erhalten."
        )
        note.setWordWrap(True)
        outer.addWidget(note)
        self.tabs = QTabWidget()
        outer.addWidget(self.tabs)
        ecu_counts: Counter[str] = Counter()
        for ecu, _dtc in catalog:
            ecu_counts[ecu] += 1
        ecus = [(ecu, str(count)) for ecu, count in sorted(ecu_counts.items())]
        faults = [
            (ecu, dtc, str(values[0]), values[2])
            for (ecu, dtc), values in sorted(catalog.items())
        ]
        self._views = {}
        for name, title, rows, headers in (
            ("include_ecus", "Steuergeräte einschließen", ecus, ("Steuergerät", "DTC-Arten")),
            ("exclude_ecus", "Steuergeräte ausschließen", ecus, ("Steuergerät", "DTC-Arten")),
            ("include_faults", "ECU:DTC einschließen", faults, ("Steuergerät", "DTC", "FINs", "Beschreibung")),
            ("exclude_faults", "ECU:DTC ausschließen", faults, ("Steuergerät", "DTC", "FINs", "Beschreibung")),
        ):
            page = QWidget()
            layout = QVBoxLayout(page)
            search = QLineEdit()
            search.setPlaceholderText("Suchen …")
            search.setClearButtonEnabled(True)
            layout.addWidget(search)
            model = SimpleTableModel(headers, rows)
            proxy = QSortFilterProxyModel(self)
            proxy.setSourceModel(model)
            proxy.setFilterKeyColumn(-1)
            proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            search.textChanged.connect(proxy.setFilterFixedString)
            view = QTableView()
            view.setModel(proxy)
            view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
            view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            view.setAlternatingRowColors(True)
            view.setSortingEnabled(True)
            view.horizontalHeader().setStretchLastSection(True)
            layout.addWidget(view)
            row = QHBoxLayout()
            add = QPushButton("Markierte hinzufügen")
            remove = QPushButton("Markierte entfernen")
            clear = QPushButton("Diese Regelliste leeren")
            row.addWidget(add)
            row.addWidget(remove)
            row.addWidget(clear)
            layout.addLayout(row)
            status = QLabel()
            layout.addWidget(status)
            self._views[name] = (view, proxy, model, status)
            add.clicked.connect(lambda _=False, n=name: self._change(n, True))
            remove.clicked.connect(lambda _=False, n=name: self._change(n, False))
            clear.clicked.connect(lambda _=False, n=name: self._clear(n))
            self.tabs.addTab(page, title)
            self._update_count(name)
        footer = QHBoxLayout()
        footer.addStretch()
        reset = QPushButton("Alle Filter zurücksetzen")
        reset.clicked.connect(self._reset)
        footer.addWidget(reset)
        cancel = QPushButton("Abbrechen")
        cancel.clicked.connect(self.reject)
        footer.addWidget(cancel)
        apply = QPushButton("Filter übernehmen")
        apply.clicked.connect(self.accept)
        apply.setDefault(True)
        footer.addWidget(apply)
        outer.addLayout(footer)

    def _change(self, name: str, add: bool) -> None:
        view, proxy, model, _status = self._views[name]
        rows = {index.row() for index in view.selectionModel().selectedRows()}
        for row in rows:
            original = proxy.mapToSource(proxy.index(row, 0)).row()
            values = model.rows[original]
            key = values[0] if name.endswith("ecus") else (values[0], values[1])
            if add:
                self._sets[name].add(key)
            else:
                self._sets[name].discard(key)
        self._update_count(name)

    def _clear(self, name: str) -> None:
        self._sets[name].clear()
        self._update_count(name)

    def _reset(self) -> None:
        for name in self._sets:
            self._clear(name)

    def _update_count(self, name: str) -> None:
        self._views[name][3].setText(
            f"{len(self._sets[name])} Regeln ausgewählt. "
            "Nicht markierte Zeilen bleiben unverändert."
        )

    def selected_rules(self) -> ClusterDtcFilter:
        return ClusterDtcFilter(**{
            name: frozenset(values) for name, values in self._sets.items()
        })
