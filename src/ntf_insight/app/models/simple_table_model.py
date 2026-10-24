"""Reusable read-only table model for compact engineering views."""

from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QColor, QBrush

ROW_COLORS = {
    "success": QColor(32, 151, 99, 32),
    "warning": QColor(224, 162, 38, 35),
    "error": QColor(199, 62, 62, 31),
    "muted": QColor(127, 137, 149, 24),
    "info": QColor(21, 114, 163, 28),
}



class SimpleTableModel(QAbstractTableModel):
    def __init__(
        self,
        headers: tuple[str, ...],
        rows: list[tuple[object, ...]] | None = None,
    ) -> None:
        super().__init__()
        self.headers = headers
        self.rows = rows or []
        self._row_states: list[str] = []

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self.headers)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        if role == Qt.ItemDataRole.BackgroundRole:
            state = (
                self._row_states[index.row()]
                if index.row() < len(self._row_states) else ""
            )
            color = ROW_COLORS.get(state)
            return QBrush(color) if color is not None else None
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        value = self.rows[index.row()][index.column()]
        return "—" if value is None or value == "" else str(value)

    def headerData(  # noqa: N802
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return self.headers[section]
        return section + 1

    def set_rows(
        self, rows: list[tuple[object, ...]],
        *, row_states: list[str] | None = None,
    ) -> None:
        if row_states is not None and len(row_states) != len(rows):
            raise ValueError("Eine Statusfarbe pro Tabellenzeile erforderlich.")
        self.beginResetModel()
        self.rows = rows
        self._row_states = list(row_states or [])
        self.endResetModel()
