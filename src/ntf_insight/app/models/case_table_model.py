"""Qt model for FIN/case combinations, QuickTest retrieval and batch selection."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Mapping

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal
from PySide6.QtGui import QBrush, QFont, QPalette
from PySide6.QtWidgets import QApplication

from ntf_insight.acquisition.diagnosis_viewer import format_last_attempt


@dataclass(frozen=True, slots=True)
class CaseRow:
    case_id: str
    vin: str
    component: str
    dtc_count: int
    replacement: str | None
    recurrence: str
    assessment: str | None
    quicktest_last_attempt: str = ""
    quicktest_folder: Path | None = None
    quicktest_pdf_count: int = 0


class CaseTableModel(QAbstractTableModel):
    """Checkbox state is identified by stable case IDs, not sorting or proxy rows."""

    selection_changed = Signal()

    CHECK_COLUMN = 0
    QUICKTEST_DATE_COLUMN = 8
    HEADERS = (
        "Auswahl",
        "Fall",
        "FIN / VIN",
        "Bauteil",
        "DTCs",
        "Tausch",
        "Wiederauftreten",
        "Bewertung",
        "QuickTest-Abruf-Datum",
    )

    def __init__(self, rows: list[CaseRow] | None = None) -> None:
        super().__init__()
        self._rows = rows or []
        self._checked_case_ids: set[str] = set()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self.HEADERS)

    def _has_folder(self, row: CaseRow) -> bool:
        return row.quicktest_folder is not None and row.quicktest_folder.is_dir()

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return None
        row = self._rows[index.row()]
        column = index.column()
        if role == Qt.ItemDataRole.CheckStateRole and column == self.CHECK_COLUMN:
            return (
                Qt.CheckState.Checked
                if row.case_id in self._checked_case_ids
                else Qt.CheckState.Unchecked
            )
        if role == Qt.ItemDataRole.UserRole:
            return row.case_id
        if column == self.QUICKTEST_DATE_COLUMN:
            if role == Qt.ItemDataRole.DisplayRole:
                if row.quicktest_last_attempt:
                    return format_last_attempt(row.quicktest_last_attempt)
                return "n.a."
            if role == Qt.ItemDataRole.ToolTipRole:
                if self._has_folder(row):
                    return (
                        f"QuickTest-Ordner öffnen:\n{row.quicktest_folder}\n"
                        f"{row.quicktest_pdf_count} PDF(s) vorhanden."
                    )
                return "Noch kein QuickTest-Abruf im lokalen Download-Ordner."
            if self._has_folder(row):
                if role == Qt.ItemDataRole.ForegroundRole:
                    return QBrush(QApplication.palette().color(QPalette.ColorRole.Link))
                if role == Qt.ItemDataRole.FontRole:
                    font = QFont()
                    font.setUnderline(True)
                    return font
        if role == Qt.ItemDataRole.DisplayRole:
            values = (
                "",
                "Nur QuickTests (kein Fall)"
                if row.case_id.startswith("FIN-QUICKTEST:") else row.case_id,
                row.vin,
                row.component,
                row.dtc_count,
                row.replacement or "—",
                row.recurrence,
                row.assessment or "—",
            )
            if column < len(values):
                return values[column]
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlags:
        basic = super().flags(index)
        if index.isValid() and index.column() == self.CHECK_COLUMN:
            return basic | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled
        return basic

    def setData(  # noqa: N802
        self, index: QModelIndex, value, role: int = Qt.ItemDataRole.EditRole
    ) -> bool:
        if (
            not index.isValid()
            or index.column() != self.CHECK_COLUMN
            or role != Qt.ItemDataRole.CheckStateRole
        ):
            return False
        case_id = self.case_id_at(index.row())
        if case_id is None:
            return False
        if value in (Qt.CheckState.Checked, Qt.CheckState.Checked.value):
            self._checked_case_ids.add(case_id)
        else:
            self._checked_case_ids.discard(case_id)
        self.dataChanged.emit(index, index, [Qt.ItemDataRole.CheckStateRole])
        self.selection_changed.emit()
        return True

    def checked_case_ids(self) -> set[str]:
        return self._checked_case_ids.copy()

    def selected_fins(self) -> list[str]:
        """Deduplicate FINs across several QEC cases of the same vehicle."""
        return sorted({
            row.vin for row in self._rows if row.case_id in self._checked_case_ids
        })

    def all_fins(self) -> list[str]:
        return sorted({row.vin for row in self._rows})

    def folder_at(self, source_row: int) -> Path | None:
        if not 0 <= source_row < len(self._rows):
            return None
        row = self._rows[source_row]
        return row.quicktest_folder if self._has_folder(row) else None

    def set_quicktest_history(
        self,
        history: Mapping[str, tuple[str, Path | None, int]],
    ) -> None:
        """Update only the date column while preserving checkboxes and sorted rows."""
        if not self._rows:
            return
        changed = False
        for index, row in enumerate(self._rows):
            timestamp, folder, count = history.get(row.vin, ("", None, 0))
            replacement = replace(
                row,
                quicktest_last_attempt=timestamp,
                quicktest_folder=folder,
                quicktest_pdf_count=count,
            )
            if replacement != row:
                self._rows[index] = replacement
                changed = True
        if changed:
            self.dataChanged.emit(
                self.index(0, self.QUICKTEST_DATE_COLUMN),
                self.index(len(self._rows) - 1, self.QUICKTEST_DATE_COLUMN),
                [
                    Qt.ItemDataRole.DisplayRole,
                    Qt.ItemDataRole.ToolTipRole,
                    Qt.ItemDataRole.FontRole,
                    Qt.ItemDataRole.ForegroundRole,
                ],
            )

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
