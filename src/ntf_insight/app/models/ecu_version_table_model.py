"""Highlight newly observed ECU HW/SW versions without changing source data."""
from __future__ import annotations

from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import QApplication

from ntf_insight.app.models.simple_table_model import SimpleTableModel


class ECUVersionTableModel(SimpleTableModel):
    """Color only values that differ from the prior comparable QuickTest."""

    def __init__(self) -> None:
        super().__init__(
            ("ECU", "Beschreibung", "Variante", "HW", "SW", "Standvergleich", "DTCs")
        )
        self._flags: list[frozenset[str]] = []

    def set_rows_with_flags(
        self,
        rows: list[tuple[object, ...]],
        flags: list[frozenset[str]],
    ) -> None:
        if len(rows) != len(flags):
            raise ValueError("Versionskennzeichen passen nicht zu ECU-Zeilen.")
        self.beginResetModel()
        self.rows = rows
        self._flags = flags
        self.endResetModel()

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self._flags):
            return super().data(index, role)
        changed = self._flags[index.row()]
        column = index.column()
        hw_cell = column == 3 and "hw" in changed
        sw_cell = column == 4 and "sw" in changed
        status_cell = column == 5 and changed
        if hw_cell or sw_cell or status_cell:
            theme = (
                QApplication.instance().property("ntfTheme")
                if QApplication.instance() is not None else "light"
            )
            dark = theme == "dark"
            if role == Qt.ItemDataRole.BackgroundRole:
                return QBrush(QColor(
                    "#67481c" if dark else "#ffefce"
                    if hw_cell else "#184e58" if dark else "#ddf5f8"
                ))
            if role == Qt.ItemDataRole.ForegroundRole:
                return QBrush(QColor(
                    "#fff6d8" if dark else "#543b00"
                    if hw_cell else "#e3fdff" if dark else "#064955"
                ))
            if role == Qt.ItemDataRole.FontRole:
                font = QFont()
                font.setBold(True)
                return font
        return super().data(index, role)
