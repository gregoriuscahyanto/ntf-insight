"""QuickTest-Abruf-Auswahl und verlinkte FIN-Ordner in der Falltabelle."""

from pathlib import Path

from PySide6.QtCore import Qt

from ntf_insight.app.models.case_table_model import CaseRow, CaseTableModel


FIN_1 = "WDD12345678901234"
FIN_2 = "WDD12345678901235"


def _row(case: str, fin: str):
    return CaseRow(
        case_id=case, vin=fin, component="Kühlmittelpumpe", dtc_count=1,
        replacement=None, recurrence="Unbekannt", assessment=None,
    )


def test_checkbox_selection_is_by_case_and_fins_are_unique():
    model = CaseTableModel([
        _row("C1", FIN_1), _row("C2", FIN_1), _row("C3", FIN_2),
    ])
    assert model.HEADERS[0] == "Auswahl"
    assert model.HEADERS[-1] == "QuickTest-Abruf-Datum"
    assert model.all_fins() == [FIN_1, FIN_2]
    assert model.selected_fins() == []
    changed = []
    model.selection_changed.connect(lambda: changed.append(True))
    for row in (0, 1):
        index = model.index(row, model.CHECK_COLUMN)
        assert model.flags(index) & Qt.ItemFlag.ItemIsUserCheckable
        assert model.setData(index, Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole)
        assert model.data(index, Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Checked
    assert model.checked_case_ids() == {"C1", "C2"}
    assert model.selected_fins() == [FIN_1]  # Two QEC cases: only one download.
    assert len(changed) == 2
    assert model.setData(
        model.index(1, model.CHECK_COLUMN), Qt.CheckState.Unchecked,
        Qt.ItemDataRole.CheckStateRole
    )
    assert model.checked_case_ids() == {"C1"}
    assert not model.setData(model.index(0, 1), Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole)


def test_quicktest_date_is_link_when_folder_exists_and_na_otherwise(tmp_path: Path):
    model = CaseTableModel([_row("C1", FIN_1), _row("C2", FIN_2)])
    index = model.index(0, model.QUICKTEST_DATE_COLUMN)
    other = model.index(1, model.QUICKTEST_DATE_COLUMN)
    assert model.data(index, Qt.ItemDataRole.DisplayRole) == "n.a."
    assert model.folder_at(0) is None
    folder = tmp_path / FIN_1
    folder.mkdir()
    model.set_quicktest_history({
        FIN_1: ("2026-10-13T10:30:00+00:00", folder, 3)
    })
    assert model.folder_at(0) == folder
    assert model.folder_at(1) is None
    assert "3 PDF(s)" in model.data(index, Qt.ItemDataRole.ToolTipRole)
    assert model.data(index, Qt.ItemDataRole.FontRole).underline()
    assert model.data(index, Qt.ItemDataRole.ForegroundRole) is not None
    assert model.data(other, Qt.ItemDataRole.DisplayRole) == "n.a."
    assert model.data(index, Qt.ItemDataRole.DisplayRole) not in ("n.a.", "—")
    # Date refresh must retain checkbox selection state.
    model.setData(
        model.index(0, 0), Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole
    )
    model.set_quicktest_history({})
    assert model.checked_case_ids() == {"C1"}
    assert model.folder_at(0) is None
