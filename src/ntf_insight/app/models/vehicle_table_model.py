"""Qt table model for the vehicle explorer."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt


@dataclass(frozen=True, slots=True)
class VehicleRow:
    vin: str
    component: str
    dtc_count: int | None = None
    replacement: str | None = None
    recurrence: str | None = None
    assessment: str | None = None


class VehicleTableModel(QAbstractTableModel):
    HEADERS = ("FIN / VIN", "Component", "DTCs", "Replacement", "Recurrence", "Assessment")

    def __init__(self, rows: list[VehicleRow] | None = None) -> None:
        super().__init__()
        self._rows = rows or []

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self.HEADERS)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or role != Qt.ItemDataRole.DisplayRole:
            return None

        row = self._rows[index.row()]
        values = (
            row.vin,
            row.component,
            row.dtc_count,
            row.replacement,
            row.recurrence,
            row.assessment,
        )
        value = values[index.column()]
        return "—" if value is None else str(value)

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

    def set_rows(self, rows: list[VehicleRow]) -> None:
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()
