"""DTC-Explorer: alle lokalen ECU:DTCs ansehen und fachlich markieren.

Manuelle Markierungen sind lokale Pruefhinweise, keine technischen
Ursachenfeststellungen. Sie beeinflussen NIE HDBSCAN oder Complete-Link.
"""
from __future__ import annotations

from collections import defaultdict

from PySide6.QtCore import QSortFilterProxyModel, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QPushButton, QTableView, QVBoxLayout, QWidget,
)

from ntf_insight.analysis.diagnostic_observations import (
    dtc_description_catalog, unique_diagnostic_observations,
)
from ntf_insight.app.models.simple_table_model import SimpleTableModel
from ntf_insight.storage.dtc_review_store import DtcReviewMark, DtcReviewStore
from ntf_insight.storage.reference_repositories import ReferenceRepository
from ntf_insight.storage.repositories import CaseRepository
from ntf_insight.storage.source_knowledge_store import SourceKnowledgeStore

FaultKey = tuple[str, str]


class _DtcExplorerModel(SimpleTableModel):
    """Show manually marked ECU:DTC rows without altering source data."""

    def __init__(
        self,
        headers: tuple[str, ...],
        rows: list[tuple[object, ...]],
        marked_keys: set[FaultKey],
    ) -> None:
        super().__init__(headers, rows)
        self.marked_keys = marked_keys

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        key = (str(self.rows[index.row()][1]), str(self.rows[index.row()][2]))
        if role == Qt.ItemDataRole.BackgroundRole and key in self.marked_keys:
            return QColor("#F0E5D2")
        if role == Qt.ItemDataRole.ForegroundRole and key in self.marked_keys:
            return QColor("#172639")
        return super().data(index, role)


class DTCExplorerPage(QWidget):
    def __init__(
        self,
        cases: CaseRepository,
        references: ReferenceRepository,
        *,
        source_knowledge: SourceKnowledgeStore | None = None,
        review_store: DtcReviewStore | None = None,
    ) -> None:
        super().__init__()
        self.review_store = review_store
        self._marks: dict[FaultKey, DtcReviewMark] = (
            review_store.list_marks() if review_store is not None else {}
        )
        self._selected_key: FaultKey | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(12)
        layout.addWidget(QLabel("DTC-Explorer", objectName="PageTitle"))
        subtitle = QLabel(
            "ECU:DTCs aus QEC/QuickTests und importiertem AutoExport. "
            "Markiere hier Codes, die du bei der Kühlmittelpumpen-Prüfung "
            "besonders beachten möchtest. Die Markierung erzeugt "
            "eine Prüfpriorität, verändert aber keine Cluster.",
            objectName="PageSubtitle",
        )
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        search = QLineEdit()
        search.setPlaceholderText(
            "Steuergerät, DTC, Klartext oder vorhandene Fachmarkierung suchen …"
        )
        search.setClearButtonEnabled(True)
        self.search_input = search
        layout.addWidget(search)

        all_cases = cases.list_cases()
        descriptions = dtc_description_catalog(all_cases)
        groups: dict[FaultKey, dict[str, object]] = defaultdict(
            lambda: {"vehicles": set(), "events": 0}
        )
        for case in all_cases:
            for observation in unique_diagnostic_observations(case.diagnostics):
                event = observation.event
                key = event.fault_key
                groups[key]["vehicles"].add(case.vin)
                groups[key]["events"] += 1

        # Unlike the older QEC-only table, expose EVERY imported AutoExport
        # ECU:DTC, including keys occurring exclusively on non-QEC FINs.
        # Keep source populations SEPARATE to avoid double-counting overlapping
        # FINs (one source overview is already aggregated).
        auto = (
            source_knowledge.autoexport_dtc_overview()
            if source_knowledge is not None else {}
        )
        rows: list[tuple[object, ...]] = []
        for ecu, dtc in sorted(set(groups) | set(auto)):
            key = ecu, dtc
            data = groups.get(key)
            auto_fin, auto_events, auto_text = auto.get(key, (0, 0, ""))
            triggers = references.find_triggers(ecu, dtc)
            trigger = triggers[0] if triggers else None
            changes = references.find_changes_for_dtc(ecu, dtc)
            tags = sorted({tag for item in triggers for tag in item.semantic_tags})
            rows.append((
                "★" if key in self._marks else "",
                ecu,
                dtc,
                descriptions.get(key) or auto_text or None,
                len(data["vehicles"]) if data else 0,
                auto_fin,
                data["events"] if data else 0,
                auto_events,
                len(triggers),
                ", ".join(tags) if tags else None,
                trigger.trigger_text if trigger else None,
                len(changes),
            ))

        self.model = _DtcExplorerModel(
            (
                "Pumpenprüfung", "ECU", "DTC", "DTC-Text",
                "QEC-FINs", "AutoExport-FINs", "QEC-Ereignisse",
                "AutoExport-DTC-Zeilen", "Triggerdefinitionen",
                "Tags", "Trigger-Zusammenfassung", "HW-/SW-Änderungen",
            ),
            rows,
            set(self._marks),
        )
        self.proxy = QSortFilterProxyModel(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.proxy.setFilterKeyColumn(-1)
        search.textChanged.connect(self.proxy.setFilterFixedString)

        table = QTableView()
        self.table = table
        table.setModel(self.proxy)
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSortingEnabled(True)
        table.verticalHeader().setVisible(False)
        header = table.horizontalHeader()
        # Thousands of AutoExport DTCs: do not scan every text cell at
        # window creation just to determine column widths.
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        for column, width in enumerate((105, 105, 145, 300, 88, 112, 108, 130,
                                        132, 145, 250, 130)):
            table.setColumnWidth(column, width)
        header.setStretchLastSection(True)
        layout.addWidget(table, 1)

        editor = QHBoxLayout()
        self.review_button = QPushButton("★ Für Pumpenprüfung markieren")
        self.review_button.setEnabled(False)
        self.review_button.clicked.connect(self._toggle_mark)
        editor.addWidget(self.review_button)
        self.note_input = QLineEdit()
        self.note_input.setPlaceholderText(
            "Optionale fachliche Notiz (z. B. Pumpenkommunikation)"
        )
        self.note_input.setMaxLength(500)
        editor.addWidget(self.note_input, 1)
        self.save_note_button = QPushButton("Notiz speichern")
        self.save_note_button.setEnabled(False)
        self.save_note_button.clicked.connect(self._save_note)
        editor.addWidget(self.save_note_button)
        layout.addLayout(editor)
        self.review_note = QLabel(
            "ECU:DTC auswählen. Eine Markierung gilt exakt für diese "
            "Steuergerät-DTC-Kombination und ist kein bestätigter Pumpendefekt.",
            objectName="PageSubtitle",
        )
        self.review_note.setWordWrap(True)
        layout.addWidget(self.review_note)
        table.selectionModel().currentRowChanged.connect(self._selection_changed)

    def _selection_changed(self, index, _old) -> None:
        if not index.isValid():
            self._selected_key = None
        else:
            source_index = self.proxy.mapToSource(index)
            row = self.model.rows[source_index.row()]
            self._selected_key = str(row[1]), str(row[2])
        self._refresh_editor()

    def _refresh_editor(self) -> None:
        key = self._selected_key
        self.review_button.setEnabled(
            key is not None and self.review_store is not None
        )
        marked = key in self._marks if key is not None else False
        self.review_button.setText(
            "★ Pumpenmarkierung entfernen" if marked
            else "★ Für Pumpenprüfung markieren"
        )
        self.note_input.setEnabled(
            key is not None and self.review_store is not None
        )
        note = self._marks[key].note if marked and key is not None else ""
        self.note_input.setText(note)
        self.save_note_button.setEnabled(
            marked and self.review_store is not None
        )
        self.review_note.setText(
            (
                f"{key[0]}:{key[1]} ist für die Pumpenprüfung markiert. "
                "Fachliche Notiz und Markierung bleiben lokal gespeichert. "
                "Clusterprioritäten werden beim nächsten Öffnen aktualisiert."
                if marked else
                "Ausgewählte ECU:DTC-Kombination kann fachlich markiert werden. "
                "Eine Markierung ist nur ein Prüfhinweis, kein Defektnachweis."
            )
        )

    def _save_note(self) -> None:
        if self._selected_key is None or self.review_store is None:
            return
        if self._selected_key not in self._marks:
            return
        self.review_store.mark(
            *self._selected_key, relevant=True,
            note=self.note_input.text(),
        )
        self._marks = self.review_store.list_marks()
        self.review_note.setText(
            "Fachliche Notiz lokal gespeichert. "
            "Die HDBSCAN-Cluster bleiben unverändert."
        )

    def _toggle_mark(self) -> None:
        if self._selected_key is None or self.review_store is None:
            return
        key = self._selected_key
        already_marked = key in self._marks
        self.review_store.mark(
            *key, relevant=not already_marked,
            note=self.note_input.text() if not already_marked else "",
        )
        self._marks = self.review_store.list_marks()
        self.model.marked_keys = set(self._marks)
        for row_number, row in enumerate(self.model.rows):
            if (row[1], row[2]) == key:
                updated = list(row)
                updated[0] = "★" if key in self._marks else ""
                self.model.rows[row_number] = tuple(updated)
                top = self.model.index(row_number, 0)
                bottom = self.model.index(row_number, len(row) - 1)
                self.model.dataChanged.emit(top, bottom)
                break
        self._refresh_editor()
