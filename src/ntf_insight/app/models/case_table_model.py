"""Qt model for FIN/case combinations."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt


@dataclass(frozen=True, slots=True)
class CaseRow:
    case_id: str
    vin: str
    component: str
    dtc_count: int
    replacement: str | None
    recurrence: str
    assessment: str | None


class CaseTableModel(QAbstractTableModel):
    HEADERS = (
        "Fall",
        "FIN / VIN",
        "Bauteil",
        "DTCs",
        "Tausch",
        "Wiederauftreten",
        "Bewertung",
    )

    def __init__(self, rows: list[CaseRow] | None = None) -> None:
        super().__init__()
        self._rows = rows or []

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self.HEADERS)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        values = (
            "Nur QuickTests (kein Fall)"
            if row.case_id.startswith("FIN-QUICKTEST:")
            else row.case_id,
            row.vin,
            row.component,
            row.dtc_count,
            row.replacement or "—",
            row.recurrence,
            row.assessment or "—",
        )
        if role == Qt.ItemDataRole.DisplayRole:
            return values[index.column()]
        if role == Qt.ItemDataRole.UserRole:
            return row.case_id
        return None

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

    def case_id_at(self, row: int) -> str | None:
        if 0 <= row < len(self._rows):
            return self._rows[row].case_id
        return None
