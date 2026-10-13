"""Sortierbares Qt-Modell fuer FIN/Faelle mit TIPS- und QEC-Abrufnachweis."""

from __future__ import annotations

from dataclasses import dataclass, replace

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QBrush, QFont
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QPalette


@dataclass(frozen=True, slots=True)
class CaseRow:
    case_id: str
    vin: str
    component: str
    dtc_count: int
    replacement: str | None
    recurrence: str
    assessment: str | None
    tips_status: str = "—"
    qec_date: str | None = None
    qec_folder: str | None = None


class CaseTableModel(QAbstractTableModel):
    HEADERS = (
        "Fall",
        "FIN / VIN",
        "Bauteil",
        "DTCs",
        "Tausch",
        "Wiederauftreten",
        "Bewertung",
        "TIPS-Fall",
        "QEC-Abrufdatum ↗",
    )
    TIPS_COLUMN = 7
    QEC_COLUMN = 8

    def __init__(self, rows: list[CaseRow] | None = None) -> None:
        super().__init__()
        self._rows = rows or []

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self.HEADERS)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._rows):
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
            row.tips_status,
            row.qec_date or "—",
        )
        if role == Qt.ItemDataRole.DisplayRole:
            return values[index.column()]
        if role == Qt.ItemDataRole.UserRole:
            return row.case_id
        if role == Qt.ItemDataRole.ToolTipRole:
            if index.column() == self.TIPS_COLUMN:
                return (
                    "TIPS-Vorgang dem konkreten Fall zugeordnet."
                    if row.tips_status == "Ja"
                    else "TIPS-Vorgang zur FIN vorhanden, aber keinem Schadteilfall sicher zugeordnet."
                    if row.tips_status == "FIN-Hinweis"
                    else "Kein TIPS-Fallbezug dokumentiert."
                )
            if index.column() == self.QEC_COLUMN:
                return (
                    f"QEC-Berichte vom {row.qec_date}: lokalen Fallordner öffnen."
                    if row.qec_folder
                    else "Kein QEC-Export mit passender FIN und Referenznummer."
                )
        if index.column() == self.QEC_COLUMN and row.qec_folder:
            if role == Qt.ItemDataRole.FontRole:
                font = QFont()
                font.setUnderline(True)
                return font
            if role == Qt.ItemDataRole.ForegroundRole:
                app = QApplication.instance()
                palette = app.palette() if app else QPalette()
                return QBrush(palette.color(QPalette.ColorRole.Link))
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

    def qec_folder_at(self, row: int) -> str | None:
        if 0 <= row < len(self._rows):
            return self._rows[row].qec_folder
        return None

    def update_qec_archives(self, by_case: dict[str, tuple[str, str] | None]) -> None:
        """Update only the linked date cells, preserving active table selections."""
        for i, row in enumerate(self._rows):
            entry = by_case.get(row.case_id)
            date, folder = entry if entry else (None, None)
            if (date, folder) == (row.qec_date, row.qec_folder):
                continue
            self._rows[i] = replace(row, qec_date=date, qec_folder=folder)
            idx = self.index(i, self.QEC_COLUMN)
            self.dataChanged.emit(idx, idx, [
                Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.FontRole,
                Qt.ItemDataRole.ForegroundRole, Qt.ItemDataRole.ToolTipRole,
            ])
