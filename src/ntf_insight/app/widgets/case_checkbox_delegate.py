"""Make the entire checkbox column clickable, not just the small checkbox glyph."""

from __future__ import annotations

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import QStyledItemDelegate


class CaseCheckboxDelegate(QStyledItemDelegate):
    """Case/FIN multi-selection, independent of the active table row."""

    def editorEvent(self, event, model, option, index):  # noqa: N802
        if not index.isValid() or index.column() != 0:
            return super().editorEvent(event, model, option, index)

        click = (
            event.type() == QEvent.Type.MouseButtonRelease
            and event.button() == Qt.MouseButton.LeftButton
        )
        space = (
            event.type() == QEvent.Type.KeyPress
            and event.key() == Qt.Key.Key_Space
        )
        if click or space:
            current = model.data(index, Qt.ItemDataRole.CheckStateRole)
            checked = (
                current in (Qt.CheckState.Checked, Qt.CheckState.Checked.value)
            )
            next_state = Qt.CheckState.Unchecked if checked else Qt.CheckState.Checked
            return model.setData(index, next_state, Qt.ItemDataRole.CheckStateRole)
        return False
