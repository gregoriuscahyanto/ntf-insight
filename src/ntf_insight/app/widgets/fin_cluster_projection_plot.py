"""Schnelle 2D/3D-Punktwolke aller FINs, ohne 11.000 QGraphicsItems.

QPainter rendert gruppenweise die Projektionspunkte in einem einzigen
Widget. 3D wird per gedrueckter linker Maustaste gedreht und geneigt.
Die Koordinaten werden NICHT als HDBSCAN-Eingabe verwendet.
"""
from __future__ import annotations

from math import cos, radians, sin

import numpy as np
from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import QFrame, QToolTip

from ntf_insight.analysis.autoexport_fin_patterns import FinPatternResult
from ntf_insight.app.widgets.case_scatter_plot import color_for_cluster


class FinClusterProjectionPlot(QFrame):
    fin_picked = Signal(str)
    rotation_changed = Signal(int, int)

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumHeight(400)
        self.setMouseTracking(True)
        self.setObjectName("Card")
        self._result: FinPatternResult | None = None
        self.mode = "2d"
        self.yaw = 32
        self.elevation = 24
        self.zoom = 1.0
        self._fins: tuple[str, ...] = ()
        self._positions = np.zeros((0, 3), dtype=float)
        self._screen = np.zeros((0, 2), dtype=float)
        self._by_group: dict[int | None, np.ndarray] = {}
        self._group_for_fin: dict[str, int] = {}
        self._highlight: int | None = None
        self._selected_fin: str | None = None
        self._drag_origin: QPointF | None = None
        self._last_drag: QPointF | None = None
        self._dragged = False

    def set_result(self, result: FinPatternResult | None) -> None:
        self._result = result
        self._fins = tuple(item[0] for item in result.positions) if result else ()
        self._positions = (
            np.asarray([item[1:] for item in result.positions], dtype=float)
            if self._fins else np.zeros((0, 3), dtype=float)
        )
        self._group_for_fin = {}
        if result is not None:
            for group in result.groups:
                for fin, _ in group.members:
                    self._group_for_fin[fin] = group.group_id
        grouped: dict[int | None, list[int]] = {}
        for index, fin in enumerate(self._fins):
            group = self._group_for_fin.get(fin)
            grouped.setdefault(group, []).append(index)
        self._by_group = {
            key: np.asarray(indices, dtype=int)
            for key, indices in grouped.items()
        }
        self._highlight = None
        self._selected_fin = None
        self._project()

    def set_mode(self, mode: str) -> None:
        if mode not in {"2d", "3d"}:
            raise ValueError("Punktwolke nur in 2D oder 3D.")
        self.mode = mode
        self._project()

    def set_rotation(self, yaw: int, elevation: int) -> None:
        self.yaw = int(yaw) % 360
        self.elevation = max(-75, min(75, int(elevation)))
        if self.mode == "3d":
            self._project()

    def set_highlight(
        self, group_id: int | None, fin: str | None = None,
    ) -> None:
        self._highlight = group_id
        if fin is not None:
            self._selected_fin = fin
        self.update()

    def reset_view(self) -> None:
        self.zoom = 1.0
        self.set_rotation(32, 24)
        self._project()

    def _project(self) -> None:
        if not len(self._positions):
            self._screen = np.zeros((0, 2), dtype=float)
            self.update()
            return
        src = self._positions
        if self.mode == "3d":
            az, el = radians(self.yaw), radians(self.elevation)
            x = src[:, 0] * cos(az) + src[:, 2] * sin(az)
            z = -src[:, 0] * sin(az) + src[:, 2] * cos(az)
            y = src[:, 1] * cos(el) - z * sin(el)
        else:
            x, y = src[:, 0], src[:, 1]
        width = max(180.0, float(self.width()))
        height = max(180.0, float(self.height()))
        span_x = max(float(np.ptp(x)), 1e-6)
        span_y = max(float(np.ptp(y)), 1e-6)
        size = min((width - 68) / span_x, (height - 82) / span_y)
        scale = size * self.zoom
        center_x = (float(np.max(x)) + float(np.min(x))) / 2
        center_y = (float(np.max(y)) + float(np.min(y))) / 2
        coords = np.column_stack((
            width / 2 + (x - center_x) * scale,
            height / 2 - (y - center_y) * scale,
        ))
        # Slight, deterministic VISUAL-only jitter so coincident FINs are
        # visible. HDBSCAN never reads this 2D/3D position.
        indices = np.arange(len(x), dtype=float)
        coords[:, 0] += np.sin(indices * 2.39996323) * 2.3
        coords[:, 1] += np.cos(indices * 2.39996323) * 2.3
        self._screen = coords
        self.update()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._project()

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), QColor("#111A23"))
        painter.setPen(QPen(QColor("#34424F"), 1, Qt.PenStyle.DotLine))
        for fraction in (0.25, 0.5, 0.75):
            x = int(self.width() * fraction)
            y = int(self.height() * fraction)
            painter.drawLine(x, 22, x, self.height() - 32)
            painter.drawLine(22, y, self.width() - 22, y)
        if not self._fins:
            painter.setPen(QColor("#BBC5CE"))
            painter.drawText(
                self.rect(), Qt.AlignmentFlag.AlignCenter,
                "Clusteranalyse starten, um die FIN-Punktwolke zu sehen.",
            )
            return

        # Grouped drawPoints() calls avoid thousands of QGraphics scene items.
        for group_id, indices in self._by_group.items():
            color = color_for_cluster(group_id)
            if self._highlight is not None and group_id != self._highlight:
                color.setAlpha(60)
            pen = QPen(color, 4.2 if group_id is not None else 2.6)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.drawPoints([
                QPointF(float(self._screen[i, 0]), float(self._screen[i, 1]))
                for i in indices
            ])
        if self._result is not None:
            painter.setPen(QPen(QColor("#FFFFFF"), 1.4))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            by_fin = {fin: i for i, fin in enumerate(self._fins)}
            for group in self._result.groups:
                if self._highlight not in (None, group.group_id):
                    continue
                index = by_fin.get(group.representative_fin)
                if index is not None:
                    x, y = self._screen[index]
                    painter.drawEllipse(QPointF(float(x), float(y)), 6.8, 6.8)
        if self._selected_fin in self._fins:
            index = self._fins.index(self._selected_fin)
            x, y = self._screen[index]
            painter.setPen(QPen(QColor("#FFFFFF"), 2.2))
            painter.drawEllipse(QPointF(float(x), float(y)), 9, 9)

        painter.setPen(QColor("#BBC5CE"))
        text = (
            "3D · Linke Maustaste halten + ziehen: drehen und neigen"
            if self.mode == "3d" else
            "2D · Projektion der gemeinsamen Diagnosemerkmale"
        )
        painter.drawText(24, self.height() - 10, text)

    def _fin_at(self, pos: QPointF) -> str | None:
        if not len(self._screen):
            return None
        delta = self._screen - np.array([pos.x(), pos.y()])
        d2 = np.einsum("ij,ij->i", delta, delta)
        near = int(np.argmin(d2))
        return self._fins[near] if d2[near] <= 100.0 else None

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_origin = event.position()
            self._last_drag = event.position()
            self._dragged = False
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if (
            self.mode == "3d"
            and self._drag_origin is not None
            and event.buttons() & Qt.MouseButton.LeftButton
        ):
            delta = event.position() - self._drag_origin
            if not self._dragged and abs(delta.x()) + abs(delta.y()) < 5:
                event.accept()
                return
            self._dragged = True
            previous = self._last_drag or event.position()
            step = event.position() - previous
            self._last_drag = event.position()
            self.set_rotation(
                self.yaw + round(step.x()),
                self.elevation - round(step.y()),
            )
            self.rotation_changed.emit(self.yaw, self.elevation)
            event.accept()
            return
        if self._drag_origin is None:
            fin = self._fin_at(event.position())
            if fin is not None:
                group = self._group_for_fin.get(fin)
                QToolTip.showText(
                    event.globalPosition().toPoint(),
                    f"FIN {fin}\n"
                    f"{'Cluster ' + str(group) if group is not None else 'Ohne Cluster'}\n"
                    "Klick: Fahrzeug auswählen",
                    self,
                )
            else:
                QToolTip.hideText()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self._drag_origin is not None:
            if not self._dragged:
                fin = self._fin_at(event.position())
                if fin is not None:
                    self._selected_fin = fin
                    self.fin_picked.emit(fin)
                    self.update()
            self._drag_origin = None
            self._last_drag = None
            self._dragged = False
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event) -> None:  # noqa: N802
        if event.angleDelta().y():
            multiplier = 1.12 if event.angleDelta().y() > 0 else 1 / 1.12
            self.zoom = max(0.7, min(8, self.zoom * multiplier))
            self._project()
            event.accept()
            return
        super().wheelEvent(event)
