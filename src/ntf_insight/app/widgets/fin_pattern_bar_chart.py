"""Clickable, bounded Qt bar overview for large AutoExport FIN pattern groups."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPen
from PySide6.QtWidgets import QFrame, QGraphicsScene, QGraphicsView

from ntf_insight.analysis.autoexport_fin_patterns import FinPatternGroup


class FinPatternBarChart(QGraphicsView):
    group_picked = Signal(int)

    def __init__(self) -> None:
        super().__init__()
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setMinimumHeight(355)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._selected: int | None = None
        self._groups: tuple[FinPatternGroup, ...] = ()
        self._draw()

    def set_groups(
        self, groups: tuple[FinPatternGroup, ...],
        selected: int | None = None,
    ) -> None:
        self._groups = groups
        self._selected = selected
        self._draw()

    def set_selected(self, group_id: int | None) -> None:
        if self._selected != group_id:
            self._selected = group_id
            self._draw()

    def _draw(self) -> None:
        self._scene.clear()
        shown = self._groups[:14]
        self._scene.setSceneRect(QRectF(0, 0, 730, 355))
        if not shown:
            info = self._scene.addText(
                "Noch keine AutoExport-Fahrzeugmuster berechnet."
            )
            info.setDefaultTextColor(QColor("#697481"))
            info.setPos(20, 145)
            return
        largest = max(g.fin_count for g in shown)
        for i, group in enumerate(shown):
            y = 16 + i * 24
            selected = group.group_id == self._selected
            pen = QPen(QColor("#101820"), 1.3 if selected else 0)
            width = 480 * group.fin_count / largest
            rect = self._scene.addRect(
                101, y, width, 16,
                pen, QBrush(QColor("#176BA0" if selected else "#8398A8")),
            )
            rect.setData(0, group.group_id)
            label = self._scene.addText(f"G{group.group_id}")
            label.setDefaultTextColor(QColor("#263543"))
            label.setPos(50, y - 5)
            label.setData(0, group.group_id)
            amount = self._scene.addText(f"{group.fin_count:,} FINs".replace(",", "."))
            amount.setDefaultTextColor(QColor("#263543"))
            amount.setPos(110 + width, y - 5)
            amount.setData(0, group.group_id)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            item = self.itemAt(event.pos())
            group_id = item.data(0) if item is not None else None
            if isinstance(group_id, int):
                self.group_picked.emit(group_id)
                event.accept()
                return
        super().mousePressEvent(event)
