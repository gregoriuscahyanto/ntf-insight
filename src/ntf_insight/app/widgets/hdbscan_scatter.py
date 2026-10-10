"""HDBSCAN 2D MDS visualisation: clusters, representatives and noise."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPen
from PySide6.QtWidgets import QFrame, QGraphicsScene, QGraphicsView

from ntf_insight.analysis.hdbscan_clustering import MLClusterResult
from ntf_insight.app.widgets.case_scatter_plot import color_for_cluster
from ntf_insight.domain.case import NTFCase


class HDBSCANScatter(QGraphicsView):
    """All plotted locations come from the HDBSCAN input distance, not labels."""

    case_picked = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setMinimumHeight(365)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self._zoom = 1.0
        self.items_by_case = {}
        self.connector_count = 0

    def set_result(
        self,
        result: MLClusterResult,
        cases: list[NTFCase],
        highlighted_cluster: int | None = None,
    ) -> None:
        self._scene.clear()
        self.items_by_case = {}
        self.connector_count = 0
        coords = {
            cid: (x, y) for cid, x, y in result.coordinates
        }
        if not coords:
            self._scene.addText("Keine Vor-Tausch-ECU:DTC-Fälle für HDBSCAN.")
            self._scene.setSceneRect(QRectF(0, 0, 740, 355))
            self.reset_zoom()
            return
        by_id = {case.case_id: case for case in cases}
        by_group = {
            member.case_id: (
                group.cluster_id, group.representative_case_id,
                member.membership_strength, member.similarity_to_representative,
            )
            for group in result.clusters
            for member in group.members
        }
        xx = [x for x, _ in coords.values()]
        yy = [y for _, y in coords.values()]
        low_x, low_y = min(xx), min(yy)
        span_x = max(max(xx)-low_x, 1e-6)
        span_y = max(max(yy)-low_y, 1e-6)

        def pos(case_id: str) -> tuple[float, float]:
            x, y = coords[case_id]
            return (33 + (x-low_x)/span_x*665,
                    32 + (1-(y-low_y)/span_y)*305)

        # Avoid the misleading "100-case star" on EOM broad groups.
        # Only draw selected *small* groups, and never link weak pairs.
        self.connector_count = 0
        for group in result.clusters:
            if (
                highlighted_cluster != group.cluster_id
                or group.case_count > 12
            ):
                continue
            center = group.representative_case_id
            if center not in coords:
                continue
            center_x, center_y = pos(center)
            pen = QPen(color_for_cluster(group.cluster_id), 0.8)
            pen.setStyle(Qt.PenStyle.DashLine)
            for member in group.members:
                if (
                    member.case_id == center
                    or member.similarity_to_representative < 0.45
                ):
                    continue
                mx, my = pos(member.case_id)
                line = self._scene.addLine(center_x, center_y, mx, my, pen)
                line.setOpacity(0.37)
                line.setZValue(0)
                self.connector_count += 1

        for case_id in sorted(coords):
            meta = by_group.get(case_id)
            group_id = meta[0] if meta else None
            is_rep = bool(meta and case_id == meta[1])
            radius = 8.3 if is_rep else 5.5
            x, y = pos(case_id)
            if is_rep:
                stroke = QColor("#162134")
            elif group_id is not None and group_id == highlighted_cluster:
                stroke = QColor("#15202c")
            else:
                stroke = QColor("#ffffff")
            item = self._scene.addEllipse(
                x-radius, y-radius, 2*radius, 2*radius,
                QPen(stroke, 2.4 if is_rep else 1.2),
                QBrush(color_for_cluster(group_id)),
            )
            item.setZValue(2 if is_rep else 1)
            item.setData(0, case_id)
            item.setToolTip(
                f"{case_id} · FIN {by_id[case_id].vin}\n"
                + (
                    f"ML-Gruppe H{group_id} · repräsentativer Fall {meta[1]}\n"
                    f"HDBSCAN-Zugehörigkeitsstärke: {meta[2]:.1%}\n"
                    f"Cosinus zum Medoid: {meta[3]:.1%}\n"
                    "Keine bestätigte gleiche technische Ursache"
                    if meta else
                    "HDBSCAN-Ausreißer / Rauschen: kein zugeordneter Cluster"
                )
            )
            self.items_by_case[case_id] = item
            if is_rep:
                label = self._scene.addText(f"H{group_id}")
                label.setDefaultTextColor(QColor("#17202e"))
                label.setPos(x+9, y-22)
                label.setZValue(3)
        self._scene.setSceneRect(QRectF(0, 0, 740, 365))
        self.reset_zoom()

    def reset_zoom(self) -> None:
        self._zoom = 1.0
        self.resetTransform()
        self.fitInView(
            self._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio
        )

    def mousePressEvent(self, event) -> None:  # noqa: N802
        clicked = self.itemAt(event.pos())
        case_id = clicked.data(0) if clicked is not None else None
        if isinstance(case_id, str):
            self.case_picked.emit(case_id)
        super().mousePressEvent(event)

    def wheelEvent(self, event) -> None:  # noqa: N802
        amount = event.angleDelta().y()
        if amount == 0:
            event.ignore()
            return
        zoom = max(0.55, min(7.0, self._zoom * (
            1.15 if amount > 0 else 1/1.15
        )))
        factor = zoom/self._zoom
        self.scale(factor, factor)
        self._zoom = zoom
        event.accept()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self._zoom == 1.0:
            self.fitInView(
                self._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio
            )
