"""Gemeinsamer lokaler Clusterfilter: Steuergeräte, ECU:DTC und SSL-Endbefund.

Jeder Fachbereich besitzt eigene Unterreiter für Ein- und Ausschlüsse.
Die Suchtabellen bleiben bei vielen tausend DTC-Zeilen scrollbar.
"""
from __future__ import annotations

from collections import Counter
from typing import Mapping

from PySide6.QtCore import Qt, QSortFilterProxyModel
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QTabWidget, QTableView, QVBoxLayout, QWidget,
)

from ntf_insight.analysis.cluster_dtc_filters import ClusterDtcFilter
from ntf_insight.app.models.simple_table_model import SimpleTableModel


class ClusterDtcFilterDialog(QDialog):
    """Drei Fachbereiche mit jeweils Ein- und Ausschluss-Unterreitern."""

    _SECTIONS = (
        ("Steuergeräte", "ecus", ("Steuergerät", "DTC-Arten")),
        ("ECU:DTC", "faults", ("Steuergerät", "DTC", "FINs", "Beschreibung")),
        ("SSL-Endbefund", "findings", ("Endbefund", "QEC-Fälle", "SSL-Code")),
    )

    def __init__(
        self,
        catalog: Mapping[tuple[str, str], tuple[int, int, str]],
        rules: ClusterDtcFilter,
        parent=None,
        *,
        findings: Mapping[str, tuple[int, str]] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Filter · Clusteranalyse")
        self.resize(940, 650)
        self.setMinimumSize(640, 450)
        self._sets: dict[str, set] = {
            name: set(getattr(rules, name))
            for name in (
                "include_ecus", "exclude_ecus",
                "include_faults", "exclude_faults",
                "include_findings", "exclude_findings",
            )
        }
        self._views: dict[str, tuple[QTableView, QSortFilterProxyModel, SimpleTableModel, QLabel]] = {}
        self._source_rows: dict[str, list[tuple[object, ...]]] = {}
        self._source_keys: dict[str, list[str | tuple[str, str]]] = {}
        self._searches: dict[str, QLineEdit] = {}
        self._subtabs: dict[str, QTabWidget] = {}

        outer = QVBoxLayout(self)
        outer.setSpacing(10)
        introduction = QLabel(
            "Einschließen begrenzt die Auswahl, Ausschließen entfernt Treffer. "
            "Ausschlüsse haben immer Vorrang. Ohne Einschluss sind alle "
            "Einträge zugelassen. SSL-Endbefunde wählen QEC-Fälle aus; "
            "Steuergeräte und ECU:DTCs bestimmen die Diagnosemerkmale. "
            "Originaldaten bleiben unverändert."
        )
        introduction.setWordWrap(True)
        outer.addWidget(introduction)

        count_ecus: Counter[str] = Counter(ecu for ecu, _ in catalog)
        datasets = {
            "ecus": [
                (ecu, count)
                for ecu, count in sorted(count_ecus.items())
            ],
            "faults": [
                (ecu, dtc, values[0], values[2])
                for (ecu, dtc), values in sorted(catalog.items())
            ],
            "findings": [
                (finding, count, codes)
                for finding, (count, codes) in sorted(
                    (findings or {}).items(),
                    key=lambda row: (-row[1][0], row[0].casefold()),
                )
            ],
        }

        self.tabs = QTabWidget(self)
        outer.addWidget(self.tabs, 1)
        for title, kind, headers in self._SECTIONS:
            section = QWidget()
            section_layout = QVBoxLayout(section)
            nested = QTabWidget()
            self._subtabs[kind] = nested
            section_layout.addWidget(nested)
            for action, tab_title in (
                ("include", "Einschließen"),
                ("exclude", "Ausschließen"),
            ):
                key = f"{action}_{kind}"
                self._add_rule_tab(
                    nested, key, tab_title, headers, datasets[kind], kind
                )
            self.tabs.addTab(section, title)

        footer = QHBoxLayout()
        footer.addStretch()
        reset = QPushButton("Alle Filter zurücksetzen")
        reset.clicked.connect(self._reset)
        footer.addWidget(reset)
        cancel = QPushButton("Abbrechen")
        cancel.clicked.connect(self.reject)
        footer.addWidget(cancel)
        apply = QPushButton("Filter übernehmen")
        apply.setDefault(True)
        apply.clicked.connect(self.accept)
        footer.addWidget(apply)
        outer.addLayout(footer)

    def _add_rule_tab(
        self,
        nested: QTabWidget,
        name: str,
        title: str,
        headers: tuple[str, ...],
        data: list[tuple[object, ...]],
        kind: str,
    ) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        search = QLineEdit()
        search.setObjectName(f"Suche_{name}")
        search.setPlaceholderText(
            "Suchen nach Endbefund oder SSL-Code …"
            if kind == "findings"
            else "Suchen nach Steuergerät, DTC oder Beschreibung …"
        )
        search.setClearButtonEnabled(True)
        layout.addWidget(search)
        self._searches[name] = search
        self._source_rows[name] = list(data)
        self._source_keys[name] = [
            (str(row[0]).strip().upper(), str(row[1]).strip().upper())
            if kind == "faults"
            else " ".join(str(row[0]).split()).casefold()
            if kind == "findings"
            else str(row[0]).strip().upper()
            for row in data
        ]
        model = SimpleTableModel(("Gewählt", *headers), [])
        proxy = QSortFilterProxyModel(self)
        proxy.setSourceModel(model)
        proxy.setFilterKeyColumn(-1)
        proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        search.textChanged.connect(proxy.setFilterFixedString)
        view = QTableView()
        view.setModel(proxy)
        view.setObjectName(f"Tabelle_{name}")
        view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        view.setAlternatingRowColors(True)
        view.setSortingEnabled(True)
        view.verticalHeader().setVisible(False)
        view.setColumnWidth(0, 70)
        view.setColumnWidth(1, 250 if kind == "findings" else 160)
        view.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(view, 1)
        commands = QHBoxLayout()
        add = QPushButton("Markierte hinzufügen")
        all_matches = QPushButton("Alle Suchtreffer hinzufügen")
        all_matches.setEnabled(False)
        all_matches.setToolTip(
            "Alle Einträge des aktuellen Suchtreffers als Filterregel "
            "speichern, nicht nur die markierten Zeilen. "
            "Ohne Suchtext ist diese Aktion gesperrt."
        )
        search.textChanged.connect(
            lambda value, button=all_matches: button.setEnabled(bool(value.strip()))
        )
        remove = QPushButton("Markierte entfernen")
        clear = QPushButton("Auswahl dieser Liste leeren")
        commands.addWidget(add)
        commands.addWidget(all_matches)
        commands.addWidget(remove)
        commands.addWidget(clear)
        commands.addStretch(1)
        layout.addLayout(commands)
        status = QLabel()
        status.setWordWrap(True)
        layout.addWidget(status)
        self._views[name] = (view, proxy, model, status)
        add.clicked.connect(lambda _checked=False, k=name: self._change(k, True))
        all_matches.clicked.connect(lambda _checked=False, k=name: self._add_matches(k))
        remove.clicked.connect(lambda _checked=False, k=name: self._change(k, False))
        clear.clicked.connect(lambda _checked=False, k=name: self._clear(k))
        nested.addTab(page, title)
        self._update_count(name)

    def _change(self, name: str, add: bool) -> None:
        view, proxy, _model, _status = self._views[name]
        selected_keys = [
            self._source_keys[name][proxy.mapToSource(index).row()]
            for index in view.selectionModel().selectedRows()
        ]
        for key in selected_keys:
            if add:
                self._sets[name].add(key)
            else:
                self._sets[name].discard(key)
        self._update_count(name)

    def _add_matches(self, name: str) -> None:
        if not self._searches[name].text().strip():
            return
        _view, proxy, _model, _status = self._views[name]
        self._sets[name].update(
            self._source_keys[name][proxy.mapToSource(proxy.index(row, 0)).row()]
            for row in range(proxy.rowCount())
        )
        self._update_count(name)

    def _clear(self, name: str) -> None:
        self._sets[name].clear()
        self._update_count(name)

    def _reset(self) -> None:
        for name in self._sets:
            self._clear(name)

    def _update_count(self, name: str) -> None:
        _view, _proxy, model, status = self._views[name]
        keys = self._source_keys[name]
        model.set_rows([
            ("✓" if key in self._sets[name] else "", *row)
            for key, row in zip(keys, self._source_rows[name], strict=True)
        ])
        selected = len(self._sets[name])
        status.setText(
            f"{selected} Einträge gewählt · {len(keys)} im Katalog. "
            "Die Spalte „Gewählt“ zeigt die dauerhaft übernommene Auswahl."
        )

    def selected_rules(self) -> ClusterDtcFilter:
        return ClusterDtcFilter(**{
            name: frozenset(values)
            for name, values in self._sets.items()
        })
