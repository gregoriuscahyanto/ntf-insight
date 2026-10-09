"""Classical MDS diagnostic-distance map for selected *real* medoid clusters.

Unlike the older TruncatedSVD scatter, input distances use the same
pre-intervention diagnostic comparisons as representative assignment.
Two-dimensional distances are still approximations; numeric similarity in
the membership table remains authoritative.
"""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt, QRectF, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPen
from PySide6.QtWidgets import QFrame, QGraphicsScene, QGraphicsView

from ntf_insight.analysis.representative_clustering import RepresentativePlan
from ntf_insight.app.widgets.case_scatter_plot import color_for_cluster
from ntf_insight.domain.case import NTFCase


def representative_mds_coordinates(
    plan: RepresentativePlan,
) -> dict[str, tuple[float, float]]:
    """Deterministic classical MDS on the screened 1−similarity matrix."""
    ids = plan.eligible_cases
    if not ids:
        return {}
    if len(ids) == 1:
        return {ids[0]: (0.0, 0.0)}
    lookup = {pair.key: pair for pair in plan.pair_scores}
    n = len(ids)
    distances = np.ones((n, n), dtype=float)
    np.fill_diagonal(distances, 0)
    for i, a in enumerate(ids):
        for j in range(i + 1, n):
            b = ids[j]
            pair = lookup.get(frozenset((a, b)))
            distance = (
                1.0 - pair.similarity if pair is not None and pair.eligible
                else 1.0
            )
            distances[i, j] = distances[j, i] = max(0, distance)
    squared = distances ** 2
    centered = (
        squared - squared.mean(axis=0)[None, :]
        - squared.mean(axis=1)[:, None] + squared.mean()
    )
    eigenvalues, eigenvectors = np.linalg.eigh(-0.5 * centered)
    order = np.argsort(eigenvalues)[::-1][:2]
    result = np.zeros((n, 2))
    for axis, index in enumerate(order):
        if eigenvalues[index] <= 1e-12:
            continue
        coordinate = eigenvectors[:, index] * np.sqrt(eigenvalues[index])
        # Stable axis signs for reproducible diagnostic screenshots.
        if coordinate[np.argmax(np.abs(coordinate))] < 0:
            coordinate *= -1
        result[:, axis] = coordinate
    return {
        case_id: (float(result[i, 0]), float(result[i, 1]))
        for i, case_id in enumerate(ids)
    }


class RepresentativeScatter(QGraphicsView):
    """Medoids are numbered large points; grey means NOT assigned."""

    case_picked = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setMinimumHeight(340)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self._zoom = 1.0
        self.items_by_case = {}

    def set_plan(
        self,
        plan: RepresentativePlan,
        cases: list[NTFCase],
        selected_cluster: int | None = None,
    ) -> None:
        self._scene.clear()
        self.items_by_case = {}
        points = representative_mds_coordinates(plan)
        lookup = {case.case_id: case for case in cases}
        if not points:
            self._scene.addText("Keine Fälle mit Vorher-DTC und Tauschanker.")
            self.reset_zoom()
            return
        xs = [coord[0] for coord in points.values()]
        ys = [coord[1] for coord in points.values()]
        minimum_x, maximum_x = min(xs), max(xs)
        minimum_y, maximum_y = min(ys), max(ys)
        dx = max(maximum_x - minimum_x, 0.01)
        dy = max(maximum_y - minimum_y, 0.01)

        def xy(case_id: str) -> tuple[float, float]:
            px, py = points[case_id]
            return 35 + 660 * (px - minimum_x) / dx, 30 + 300 * (
                1 - (py - minimum_y) / dy
            )

        membership = {}
        for group in plan.clusters:
            for member in group.members:
                membership[member.case_id] = (
                    group.cluster_id, member.similarity,
                    group.representative_case_id,
                )
            if group.representative_case_id in points:
                x0, y0 = xy(group.representative_case_id)
                pen = QPen(color_for_cluster(group.cluster_id), 1.1)
                pen.setStyle(Qt.PenStyle.DashLine)
                for member in group.members:
                    if member.case_id == group.representative_case_id:
                        continue
                    x1, y1 = xy(member.case_id)
                    connector = self._scene.addLine(x0, y0, x1, y1, pen)
                    connector.setOpacity(
                        0.50 if selected_cluster == group.cluster_id else 0.20
                    )
                    connector.setZValue(0)

        self._scene.addText("MDS 2 · ausgewählte diagnostische Distanz").setPos(10, 0)
        for case_id in sorted(points):
            case = lookup[case_id]
            cluster_info = membership.get(case_id)
            group_id = cluster_info[0] if cluster_info else None
            is_rep = (
                cluster_info is not None
                and cluster_info[2] == case_id
            )
            x, y = xy(case_id)
            radius = 8.2 if is_rep else 5.2
            border = QColor("#14202f") if is_rep else QColor("#ffffff")
            if selected_cluster is not None and group_id == selected_cluster:
                border = QColor("#111827")
            item = self._scene.addEllipse(
                x - radius, y - radius, radius * 2, radius * 2,
                QPen(border, 2.4 if is_rep else 1.1),
                QBrush(color_for_cluster(group_id)),
            )
            item.setZValue(2 if is_rep else 1)
            item.setData(0, case_id)
            item.setToolTip(
                f"{case.case_id} · FIN {case.vin}\n"
                + (
                    f"R{group_id} · "
                    f"Medoid: {cluster_info[2]}\n"
                    f"Index zum Repräsentanten: {cluster_info[1]:.1%}"
                    if cluster_info else "Nicht zugeordnet – keine automatische Übertragung"
                )
            )
            self.items_by_case[case_id] = item
            if is_rep:
                label = self._scene.addText(f"R{group_id}")
                label.setDefaultTextColor(QColor("#17202e"))
                label.setPos(x + 7, y - 21)
                label.setZValue(3)
        self._scene.setSceneRect(QRectF(0, 0, 740, 355))
        self.reset_zoom()

    def reset_zoom(self) -> None:
        self._zoom = 1.0
        self.resetTransform()
        self.fitInView(
            self._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio
        )

    def mousePressEvent(self, event) -> None:  # noqa: N802
        hit = self.itemAt(event.pos())
        case_id = hit.data(0) if hit is not None else None
        if isinstance(case_id, str):
            self.case_picked.emit(case_id)
        super().mousePressEvent(event)

    def wheelEvent(self, event) -> None:  # noqa: N802
        delta = event.angleDelta().y()
        if delta == 0:
            event.ignore()
            return
        next_zoom = max(0.6, min(7.0, self._zoom * (
            1.15 if delta > 0 else 1 / 1.15
        )))
        factor = next_zoom / self._zoom
        self.scale(factor, factor)
        self._zoom = next_zoom
        event.accept()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self._zoom == 1.0:
            self.fitInView(
                self._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio
            )
