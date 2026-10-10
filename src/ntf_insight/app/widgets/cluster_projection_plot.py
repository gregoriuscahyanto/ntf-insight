"""Reusable interactive Qt 2D/3D projection for ANY clustering method.

3D is a rotatable classical-MDS point cloud drawn with QGraphicsScene:
no OpenGL driver, web engine, external telemetry or third-party GPU required.
All coordinates come from the ORIGINAL pre-swap diagnostic distances, and
never feed back into the clustering algorithm.
"""
from __future__ import annotations

from math import cos, radians, sin

from PySide6.QtCore import QPoint, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPen
from PySide6.QtWidgets import QApplication, QFrame, QGraphicsScene, QGraphicsView

from ntf_insight.analysis.cluster_workspace_engine import UnifiedClusterResult
from ntf_insight.app.widgets.case_scatter_plot import color_for_cluster
from ntf_insight.domain.case import NTFCase


class ClusterProjectionPlot(QGraphicsView):
    case_picked = Signal(str)
    rotation_changed = Signal(int, int)

    def __init__(self) -> None:
        super().__init__()
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setMinimumHeight(365)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self._zoom = 1.0
        self._mode = "2d"
        self.yaw = 32
        self.elevation = 24
        self._drag_position: QPoint | None = None
        self._drag_origin: QPoint | None = None
        self._drag_button: Qt.MouseButton | None = None
        self._dragged = False
        self._pressed_case_id: str | None = None
        self._result: UnifiedClusterResult | None = None
        self._cases: dict[str, NTFCase] = {}
        self._selected_group: int | None = None
        self._selected_case: str | None = None
        self._emphasis_case_ids: frozenset[str] | None = None
        self.items_by_case = {}
        self._scene.setSceneRect(QRectF(0, 0, 760, 400))

    @property
    def mode(self) -> str:
        return self._mode

    def set_result(
        self,
        result: UnifiedClusterResult | None,
        cases: list[NTFCase],
        highlighted_cluster: int | None = None,
    ) -> None:
        self._result = result
        self._cases = {case.case_id: case for case in cases}
        self._selected_group = highlighted_cluster
        self._selected_case = None
        self._draw()

    def set_mode(self, mode: str) -> None:
        if mode not in {"2d", "3d"}:
            raise ValueError("Darstellung muss 2D oder 3D sein.")
        self._mode = mode
        self._drag_position = None
        self._drag_origin = None
        self._drag_button = None
        self._pressed_case_id = None
        self._dragged = False
        if mode == "3d":
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        else:
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
            self.unsetCursor()
        self._draw()

    def set_highlight(self, cluster_id: int | None, case_id: str | None = None) -> None:
        self._selected_group = cluster_id
        if case_id is not None:
            self._selected_case = case_id
        self._draw()

    def set_emphasis_cases(self, case_ids: tuple[str, ...] | None) -> None:
        """Highlight strict core group members across different algorithms."""
        selected = frozenset(case_ids) if case_ids is not None else None
        if self._emphasis_case_ids != selected:
            self._emphasis_case_ids = selected
            self._draw()

    def set_rotation(self, yaw: int, elevation: int) -> None:
        self.yaw = int(yaw) % 360
        self.elevation = max(-75, min(75, int(elevation)))
        if self._mode == "3d":
            self._draw()

    def _screen_positions(self) -> dict[str, tuple[float, float, float]]:
        if self._result is None:
            return {}
        raw: dict[str, tuple[float, float, float]] = {}
        az, el = radians(self.yaw), radians(self.elevation)
        for case_id, x, y, z in self._result.positions:
            if self._mode == "2d":
                px, py, depth = x, y, 0.0
            else:
                # Rotation about vertical and horizontal axes, orthographic.
                rx = x * cos(az) + z * sin(az)
                rz = -x * sin(az) + z * cos(az)
                px = rx
                py = y * cos(el) - rz * sin(el)
                depth = y * sin(el) + rz * cos(el)
            raw[case_id] = (px, py, depth)
        if not raw:
            return {}
        xmin = min(x for x, _, _ in raw.values())
        xmax = max(x for x, _, _ in raw.values())
        ymin = min(y for _, y, _ in raw.values())
        ymax = max(y for _, y, _ in raw.values())
        xspan = max(xmax - xmin, 1e-9)
        yspan = max(ymax - ymin, 1e-9)
        return {
            cid: (
                38 + (x - xmin) / xspan * 670,
                35 + (1 - (y - ymin) / yspan) * 310,
                depth,
            )
            for cid, (x, y, depth) in raw.items()
        }

    def _draw(self) -> None:
        self._scene.clear()
        self.items_by_case.clear()
        self._scene.setSceneRect(QRectF(0, 0, 760, 400))
        coords = self._screen_positions()
        if not coords:
            info = self._scene.addText(
                "Keine Fälle mit belegtem ECU:DTC vor dem Bauteiltausch."
            )
            info.setDefaultTextColor(QColor("#8793A3"))
            info.setPos(30, 180)
            self._refit_preserving_zoom()
            return
        groups = {}
        representatives = {}
        if self._result is not None:
            for group in self._result.groups:
                representatives[group.representative_case_id] = group.cluster_id
                for member in group.members:
                    groups[member.case_id] = (group.cluster_id, member.similarity)
        background = QPen(QColor("#3B4654"))
        background.setStyle(Qt.PenStyle.DotLine)
        for fraction in (0.25, 0.5, 0.75):
            self._scene.addLine(
                38, 35 + fraction * 310, 708, 35 + fraction * 310,
                background,
            ).setOpacity(0.32)
            self._scene.addLine(
                38 + fraction * 670, 35, 38 + fraction * 670, 345,
                background,
            ).setOpacity(0.32)

        # Draw low-depth points first, so nearer items are easier to select.
        for case_id in sorted(coords, key=lambda cid: (coords[cid][2], cid)):
            x, y, depth = coords[case_id]
            info = groups.get(case_id)
            group_id = info[0] if info is not None else None
            is_rep = case_id in representatives
            selected = case_id == self._selected_case
            emphasized = group_id is not None and (
                self._selected_group is None or group_id == self._selected_group
            )
            radius = 9.5 if selected else 8 if is_rep else 5.4
            border = QColor("#101820") if (selected or is_rep) else QColor("#FFFFFF")
            fill = color_for_cluster(group_id)
            if self._emphasis_case_ids is not None:
                if case_id not in self._emphasis_case_ids:
                    fill.setAlpha(54)
                else:
                    radius += 1.6
            elif self._selected_group is not None and not emphasized:
                fill.setAlpha(72)
            edge = QPen(border, 2.6 if selected else 2.1 if is_rep else 0.9)
            item = self._scene.addEllipse(
                x - radius, y - radius, radius * 2, radius * 2,
                edge, QBrush(fill),
            )
            item.setData(0, case_id)
            # Selected case must win when multiple MDS points overlap.
            item.setZValue(
                50 if selected else 30 if (
                    self._emphasis_case_ids is not None
                    and case_id in self._emphasis_case_ids
                ) else 15 if is_rep else 1 + depth * 0.1
            )
            case = self._cases.get(case_id)
            vin = case.vin if case is not None else "unbekannt"
            if info is not None:
                membership = (
                    f"Cluster {group_id}, Index zum Medoid {info[1]:.1%}"
                )
            else:
                membership = "Nicht zugeordnet (ML-Ausreißer)"
            item.setToolTip(
                f"QEC {case_id}\nFIN {vin}\n{membership}\n"
                "Diagnostische Nähe ist kein Ursachennachweis."
            )
            self.items_by_case[case_id] = item
            if is_rep:
                label = self._scene.addText(f"C{group_id}")
                label.setDefaultTextColor(QColor("#AAB8C8"))
                label.setPos(x + 9, y - 19)
                label.setZValue(6)
        label = self._scene.addText(
            "3D-MDS · Linke Maustaste halten und ziehen: drehen und neigen"
            if self._mode == "3d" else "2D-MDS · Originaldiagnose, nur Projektion"
        )
        label.setDefaultTextColor(QColor("#8394A6"))
        label.setPos(37, 358)
        self._refit_preserving_zoom()

    def _refit_preserving_zoom(self) -> None:
        # Selection, core-group highlighting or 3D rotation must not throw
        # away the user's current zoom level.
        zoom = self._zoom
        self.resetTransform()
        self.fitInView(
            self._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio,
        )
        if zoom != 1.0:
            self.scale(zoom, zoom)

    def reset_zoom(self) -> None:
        self._zoom = 1.0
        self._refit_preserving_zoom()

    def _case_at(self, position: QPoint) -> str | None:
        """Find an actual ellipse also when a text label overlaps the point."""
        item = self.itemAt(position)
        case_id = item.data(0) if item is not None else None
        if not isinstance(case_id, str):
            candidates = self._scene.items(self.mapToScene(position))
            case_id = next(
                (candidate.data(0) for candidate in candidates
                 if isinstance(candidate.data(0), str)), None,
            )
        return case_id if isinstance(case_id, str) else None

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if (
            self._mode == "3d"
            and event.button() in (
                Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton,
            )
        ):
            self._drag_origin = event.pos()
            self._drag_position = event.pos()
            self._drag_button = event.button()
            self._dragged = False
            self._pressed_case_id = (
                self._case_at(event.pos())
                if event.button() == Qt.MouseButton.LeftButton else None
            )
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            case_id = self._case_at(event.pos())
            if case_id is not None:
                self._selected_case = case_id
                self.case_picked.emit(case_id)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if (
            self._mode == "3d"
            and self._drag_position is not None
            and self._drag_origin is not None
            and self._drag_button is not None
            and event.buttons() & self._drag_button
        ):
            displacement = event.pos() - self._drag_origin
            if (
                not self._dragged
                and displacement.manhattanLength() < QApplication.startDragDistance()
            ):
                event.accept()
                return
            self._dragged = True
            delta = event.pos() - self._drag_position
            self._drag_position = event.pos()
            if delta.x() or delta.y():
                # Horizontal movement rotates the view; vertical movement
                # tilts it. No diagnostic distances or cluster IDs change.
                self.set_rotation(
                    self.yaw + delta.x(), self.elevation - delta.y(),
                )
                self.rotation_changed.emit(self.yaw, self.elevation)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if (
            self._mode == "3d"
            and event.button() == self._drag_button
        ):
            case_id = (
                self._pressed_case_id
                if event.button() == Qt.MouseButton.LeftButton
                and not self._dragged else None
            )
            self._drag_position = None
            self._drag_origin = None
            self._drag_button = None
            self._dragged = False
            self._pressed_case_id = None
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            if case_id is not None:
                self._selected_case = case_id
                self.case_picked.emit(case_id)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event) -> None:  # noqa: N802
        amount = event.angleDelta().y()
        if not amount:
            event.ignore()
            return
        zoom = max(0.55, min(7.0, self._zoom * (
            1.15 if amount > 0 else 1 / 1.15
        )))
        self.scale(zoom / self._zoom, zoom / self._zoom)
        self._zoom = zoom
        event.accept()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self._zoom == 1.0:
            self.fitInView(
                self._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio
            )
