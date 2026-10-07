"""Reusable read-only table model for compact engineering views."""

from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt


class SimpleTableModel(QAbstractTableModel):
    def __init__(
        self,
        headers: tuple[str, ...],
        rows: list[tuple[object, ...]] | None = None,
    ) -> None:
        super().__init__()
        self.headers = headers
        self.rows = rows or []

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self.headers)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or role != Qt.ItemDataRole.DisplayRole:
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

    def set_rows(self, rows: list[tuple[object, ...]]) -> None:
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()
