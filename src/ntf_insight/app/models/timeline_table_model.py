"""Qt model for a case timeline."""

from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt

from ntf_insight.analysis.timeline import TimelineEntry


class TimelineTableModel(QAbstractTableModel):
    HEADERS = ("Zeit", "Kilometerstand", "Typ", "Ereignis", "Details", "Quelle")

    def __init__(self, entries: list[TimelineEntry] | None = None) -> None:
        super().__init__()
        self._entries = entries or []

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._entries)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self.HEADERS)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or role != Qt.ItemDataRole.DisplayRole:
            return None

        entry = self._entries[index.row()]
        values = (
            entry.occurred_at.strftime("%Y-%m-%d %H:%M"),
            f"{entry.mileage_km:,} km" if entry.mileage_km is not None else "—",
            self._kind_label(entry.kind),
            entry.title,
            entry.detail or "—",
            entry.source_ref or "—",
        )
        return values[index.column()]

    def headerData(  # noqa: N802
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return self.HEADERS[section]
        return section + 1

    @staticmethod
    def _kind_label(kind: str) -> str:
        labels = {
            "diagnostic_session": "Diagnosesitzung",
            "diagnostic": "DTC",
            "ecu_state": "ECU-Stand",
            "replacement": "Tausch",
            "repair": "Werkstatt",
            "software": "Software",
            "supplier": "Lieferant",
        }
        return labels.get(kind, kind.replace("_", " ").title())

    def set_entries(self, entries: list[TimelineEntry]) -> None:
        self.beginResetModel()
        self._entries = entries
        self.endResetModel()
