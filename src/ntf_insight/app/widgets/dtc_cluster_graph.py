"""Interactive Qt visualization for descriptive DTC clusters."""

from __future__ import annotations

from collections import defaultdict
from math import ceil, cos, pi, sin, sqrt

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QGraphicsScene, QGraphicsView

from ntf_insight.analysis.dtc_clusters import DTCNetwork, DTCNode, FaultKey


class DTCClusterGraph(QGraphicsView):
    def __init__(self) -> None:
        super().__init__(objectName="ClusterGraph")
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHints(
            QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing
        )
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setMinimumHeight(420)
        self._has_content = False

    def set_network(
        self,
        network: DTCNetwork,
        *,
        min_cases: int = 1,
        max_nodes: int = 30,
    ) -> tuple[int, int, int]:
        self._scene.clear()

        selected_nodes = [node for node in network.nodes if node.case_count >= min_cases]
        selected_nodes = selected_nodes[:max_nodes]
        selected_keys = {node.key for node in selected_nodes}
        selected_edges = [
            edge
            for edge in network.edges
            if edge.left in selected_keys and edge.right in selected_keys
        ]

        if not selected_nodes:
            message = self._scene.addText("Keine DTCs für die aktuelle Filterung.")
            message.setDefaultTextColor(QColor("#6b7280"))
            message.setPos(24, 24)
            self._scene.setSceneRect(QRectF(0, 0, 520, 180))
            self._has_content = False
            return 0, 0, 0

        cluster_by_fault = network.cluster_by_fault()
        grouped: dict[int, list[DTCNode]] = defaultdict(list)
        for node in selected_nodes:
            grouped[cluster_by_fault[node.key]].append(node)

        cluster_ids = sorted(grouped)
        columns = max(1, min(3, ceil(sqrt(len(cluster_ids)))))
        cell_width = 430.0
        cell_height = 330.0
        positions: dict[FaultKey, tuple[float, float, float]] = {}

        for index, cluster_id in enumerate(cluster_ids):
            row = index // columns
            column = index % columns
            origin_x = column * cell_width
            origin_y = row * cell_height
            center_x = origin_x + cell_width / 2
            center_y = origin_y + cell_height / 2 + 8
            nodes = sorted(
                grouped[cluster_id],
                key=lambda node: (-node.case_count, -node.event_count, node.key),
            )

            header = self._scene.addRect(
                origin_x + 12,
                origin_y + 12,
                136,
                30,
                QPen(QColor("#9ca3af")),
                QColor("#e5e7eb"),
            )
            header.setToolTip("Deskriptiver Cluster aus DTC-Koauftreten im selben Fall")
            header_text = self._scene.addText(f"Cluster {cluster_id}")
            header_text.setDefaultTextColor(QColor("#111827"))
            header_text.setFont(QFont("Arial", 9, QFont.Weight.DemiBold))
            header_text.setPos(origin_x + 24, origin_y + 16)

            if len(nodes) == 1:
                angles = [0.0]
                orbit = 0.0
            else:
                angles = [2 * pi * i / len(nodes) - pi / 2 for i in range(len(nodes))]
                orbit = min(115.0, 72.0 + 7.0 * len(nodes))

            for node, angle in zip(nodes, angles):
                radius = min(48.0, 31.0 + 3.0 * node.case_count)
                x = center_x + orbit * cos(angle)
                y = center_y + orbit * sin(angle)
                positions[node.key] = (x, y, radius)

        for edge in selected_edges:
            left = positions.get(edge.left)
            right = positions.get(edge.right)
            if left is None or right is None:
                continue
            width = min(5.0, 1.2 + 0.8 * edge.case_count)
            line = self._scene.addLine(
                left[0],
                left[1],
                right[0],
                right[1],
                QPen(QColor("#9ca3af"), width),
            )
            line.setZValue(-2)
            line.setToolTip(
                f"{edge.left[0]}:{edge.left[1]} ↔ {edge.right[0]}:{edge.right[1]}\n"
                f"Gemeinsam in {edge.case_count} Fall/Fällen"
            )

        for node in selected_nodes:
            x, y, radius = positions[node.key]
            item = self._scene.addEllipse(
                x - radius,
                y - radius,
                radius * 2,
                radius * 2,
                QPen(QColor("#4b5563"), 1.4),
                QColor("#f3f4f6"),
            )
            item.setZValue(1)
            item.setToolTip(
                f"{node.ecu}:{node.dtc_code}\n"
                f"{node.case_count} Fall/Fälle · {node.event_count} Ereignis(se)\n"
                f"Fälle: {', '.join(node.case_ids)}"
            )

            text = self._scene.addText(f"{node.ecu}\n{node.dtc_code}")
            text.setDefaultTextColor(QColor("#111827"))
            text.setFont(QFont("Arial", 8, QFont.Weight.DemiBold))
            bounds = text.boundingRect()
            text.setPos(x - bounds.width() / 2, y - bounds.height() / 2)
            text.setZValue(2)

        rows = ceil(len(cluster_ids) / columns)
        scene_width = columns * cell_width
        scene_height = rows * cell_height
        self._scene.setSceneRect(QRectF(0, 0, scene_width, scene_height))
        self._has_content = True
        self.resetTransform()
        self.fitInView(self._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
        return len(selected_nodes), len(selected_edges), len(cluster_ids)

    def wheelEvent(self, event) -> None:  # noqa: N802
        if not self._has_content:
            super().wheelEvent(event)
            return
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)
        event.accept()
