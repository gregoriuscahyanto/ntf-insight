"""Interactive case scatter view; projection never determines cluster membership."""

from __future__ import annotations

from collections import Counter, defaultdict
from math import cos, pi, sin

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QComboBox,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ntf_insight.analysis.case_clustering import (
    CaseClusterResult,
    signature_for,
)
from ntf_insight.analysis.case_projection import CaseProjection, project_diagnostic_cases
from ntf_insight.analysis.qec_findings import qec_ssl_finding_label
from ntf_insight.domain.case import NTFCase


PALETTE = (
    "#2069b2", "#15816f", "#b66717", "#7752b7",
    "#b34d74", "#417e96", "#866b20", "#587f39",
)
UNASSIGNED = "#858e9b"


class CaseScatterPlot(QGraphicsView):
    """Click-ready Qt scatter chart without inventing new cluster IDs."""

    case_selected = Signal(str)

    def __init__(self) -> None:
        super().__init__(objectName="CaseScatterPlot")
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHints(
            QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing
        )
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setMinimumHeight(415)
        self._has_points = False
        self.items_by_case = {}

    def set_points(
        self,
        projection: CaseProjection,
        result: CaseClusterResult | None,
        by_id: dict[str, NTFCase],
        focus_id: str | None,
    ) -> None:
        scene = self._scene
        scene.clear()
        self.items_by_case = {}
        width, height = 850.0, 490.0
        left, right, top, bottom = 65.0, 35.0, 36.0, 64.0

        if not projection.points:
            item = scene.addText("Keine diagnostisch verwertbaren Fälle für das Streudiagramm.")
            item.setDefaultTextColor(QColor("#858e9b"))
            item.setPos(45, 45)
            scene.setSceneRect(QRectF(0, 0, width, 140))
            self._has_points = False
            self.resetTransform()
            self.fitInView(scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
            return

        xmin = min(p.x for p in projection.points)
        xmax = max(p.x for p in projection.points)
        ymin = min(p.y for p in projection.points)
        ymax = max(p.y for p in projection.points)
        xspan = max(xmax - xmin, 0.20)
        yspan = max(ymax - ymin, 0.20)
        midx, midy = (xmin + xmax) / 2, (ymin + ymax) / 2

        def xy(x: float, y: float) -> tuple[float, float]:
            return (
                left + (x - midx) / xspan * (width - left - right) * 0.84
                + (width - left - right) / 2,
                top + (height - top - bottom) / 2
                - (y - midy) / yspan * (height - top - bottom) * 0.84,
            )

        grid_pen = QPen(QColor("#b9c1cc"), 0.7)
        grid_pen.setStyle(Qt.PenStyle.DashLine)
        for fraction in (0.25, 0.5, 0.75):
            px = left + fraction * (width - left - right)
            py = top + fraction * (height - top - bottom)
            scene.addLine(px, top, px, height - bottom, grid_pen)
            scene.addLine(left, py, width - right, py, grid_pen)
        axis_pen = QPen(QColor("#65758a"), 1.0)
        scene.addLine(left, height - bottom, width - right, height - bottom, axis_pen)
        scene.addLine(left, top, left, height - bottom, axis_pen)

        x_label = scene.addText("SVD-Dimension 1")
        x_label.setDefaultTextColor(QColor("#5c6778"))
        x_label.setPos(width / 2 - 60, height - bottom + 22)
        y_label = scene.addText("SVD-Dimension 2")
        y_label.setDefaultTextColor(QColor("#5c6778"))
        y_label.setPos(left + 7, top - 30)

        # Identical projected coordinates can occur for identical signatures.
        # Small DISPLAY-ONLY offsets allow every underlying case to be clicked.
        coincident: dict[tuple[float, float], list[str]] = defaultdict(list)
        for point in projection.points:
            coincident[(point.x, point.y)].append(point.case_id)
        locations: dict[str, tuple[float, float]] = {}
        for point in projection.points:
            cases_at = coincident[(point.x, point.y)]
            x, y = xy(point.x, point.y)
            if len(cases_at) > 1:
                order = cases_at.index(point.case_id)
                theta = 2 * pi * order / len(cases_at)
                radius = min(26.0, 10.0 + len(cases_at) * 1.2)
                x += cos(theta) * radius
                y += sin(theta) * radius
            locations[point.case_id] = (x, y)

        for point in projection.points:
            case = by_id[point.case_id]
            cluster = result.cluster_for(point.case_id) if result else None
            color = QColor(PALETTE[(cluster - 1) % len(PALETTE)]) if cluster else QColor(UNASSIGNED)
            x, y = locations[point.case_id]
            radius = 9.5 if point.case_id == focus_id else 7.0
            outline = QColor("#172638") if point.case_id == focus_id else QColor("#ffffff")
            pen = QPen(outline, 3.0 if point.case_id == focus_id else 1.3)

            # Square markers explicitly flag cases without a replacement anchor.
            if point.has_replacement_anchor:
                item = scene.addEllipse(
                    x - radius, y - radius, 2 * radius, 2 * radius, pen, color
                )
            else:
                item = scene.addRect(
                    x - radius, y - radius, 2 * radius, 2 * radius, pen, color
                )
            item.setZValue(3 if point.case_id == focus_id else 2)
            item.setData(0, point.case_id)
            sig = signature_for(case)
            preview = ", ".join(f"{ecu}:{dtc}" for ecu, dtc in sorted(sig.faults)[:8])
            if len(sig.faults) > 8:
                preview += f" (+{len(sig.faults) - 8})"
            item.setToolTip(
                f"Fall {point.case_id} · FIN {case.vin}\n"
                f"{'Cluster ' + str(cluster) if cluster else 'Einzelfall / unzugeordnet'}\n"
                f"Diagnostische ECU:DTCs: {preview or 'Keine'}\n"
                f"Tauschanker: {'vorhanden' if point.has_replacement_anchor else 'fehlt'}\n"
                f"SSL-Endbefund (nicht im Score): {qec_ssl_finding_label(case)}\n"
                "Darstellungsabstand ist keine Ursachenwahrscheinlichkeit."
                + (
                    "\nPunkte mit identischen Koordinaten sind zur Auswahl leicht versetzt."
                    if len(coincident[(point.x, point.y)]) > 1 else ""
                )
            )
            self.items_by_case[point.case_id] = item

        scene.setSceneRect(QRectF(0, 0, width, height))
        self._has_points = True
        self.resetTransform()
        self.fitInView(scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        item = self.itemAt(event.position().toPoint())
        if item is not None:
            case_id = item.data(0)
            if isinstance(case_id, str):
                self.case_selected.emit(case_id)
                event.accept()
                return
        super().mousePressEvent(event)

    def wheelEvent(self, event) -> None:  # noqa: N802
        if not self._has_points:
            return super().wheelEvent(event)
        self.scale(1.15 if event.angleDelta().y() > 0 else 1 / 1.15)
        event.accept()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self._has_points:
            self.fitInView(self._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)


class CaseScatterPanel(QWidget):
    """2D depiction of unchanged complete-link case clusters, per component."""

    case_focused = Signal(str)
    compare_requested = Signal(str)
    case_requested = Signal(str)

    def __init__(
        self,
        cases: list[NTFCase],
        result: CaseClusterResult | None,
    ) -> None:
        super().__init__()
        self.cases = sorted(cases, key=lambda c: c.case_id)
        self.by_id = {case.case_id: case for case in self.cases}
        self.result = result
        self._component_of = {
            case.case_id: signature_for(case).component_key for case in self.cases
        }
        self.focus_id: str | None = None
        self.projection = CaseProjection((), ())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 14, 12, 12)
        layout.setSpacing(11)
        intro = QLabel(
            "Explorative 2D-Projektion der gleichen diagnostischen Signaturen wie "
            "im Fall-Cluster. Die Farben stammen UNVERÄNDERT aus Complete-Link; "
            "Abstände im Bild sind weder Jaccard-Werte noch Ursachenwahrscheinlichkeiten.",
            objectName="PageSubtitle",
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Bauteilfamilie:"))
        self.component_filter = QComboBox()
        names = {
            key: next(case.component_type for case in self.cases if self._component_of[case.case_id] == key)
            for key in set(self._component_of.values())
        }
        counts = Counter(self._component_of.values())
        for key in sorted(names, key=lambda item: (-counts[item], item)):
            self.component_filter.addItem(names[key], key)
        controls.addWidget(self.component_filter)
        controls.addStretch(1)
        self.summary = QLabel(objectName="PageSubtitle")
        self.summary.setWordWrap(True)
        controls.addWidget(self.summary, 1)
        layout.addLayout(controls)

        self.plot = CaseScatterPlot()
        self.plot.case_selected.connect(self._select_point)
        layout.addWidget(self.plot, 1)
        legend = QLabel(
            "Farbe = bestehender Fall-Cluster · Grau = unzugeordnet · "
            "Quadrat = ohne Tauschanker · Dunkler Rand = ausgewählt · "
            "Mausrad = Zoom · Punkt anklicken = Fall fokussieren",
            objectName="PageSubtitle",
        )
        legend.setWordWrap(True)
        layout.addWidget(legend)

        self.detail = QLabel(objectName="PageSubtitle")
        self.detail.setWordWrap(True)
        layout.addWidget(self.detail)

        buttons = QHBoxLayout()
        self.compare_button = QPushButton("Im Fall-Cluster vergleichen")
        self.compare_button.setEnabled(False)
        self.compare_button.clicked.connect(self._compare_focus)
        buttons.addWidget(self.compare_button)
        self.open_button = QPushButton("Fallanalyse öffnen")
        self.open_button.setEnabled(False)
        self.open_button.clicked.connect(self._open_focus)
        buttons.addWidget(self.open_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        self.component_filter.currentIndexChanged.connect(self._refresh)
        self._refresh()

    def set_result(self, result: CaseClusterResult | None) -> None:
        self.result = result
        self._draw()

    def focus_case(self, case_id: str) -> bool:
        if case_id not in self.by_id:
            return False
        self.focus_id = case_id
        index = self.component_filter.findData(self._component_of[case_id])
        if index >= 0 and self.component_filter.currentIndex() != index:
            self.component_filter.setCurrentIndex(index)
        else:
            self._draw()
        return True

    def _refresh(self) -> None:
        family = self.component_filter.currentData()
        subset = [
            case for case in self.cases
            if self._component_of[case.case_id] == family
        ]
        self.projection = project_diagnostic_cases(subset)
        visible = {p.case_id for p in self.projection.points}
        if self.focus_id not in {case.case_id for case in subset}:
            self.focus_id = self.projection.points[0].case_id if self.projection.points else None
        self.summary.setText(
            f"{len(visible)} projizierte Fälle · "
            f"{len(self.projection.omitted_case_ids)} ohne ausreichende Diagnosebasis"
            + (" · 2D bei weniger als 3 Fällen eingeschränkt" if len(visible) < 3 else "")
        )
        self._draw()

    def _draw(self) -> None:
        self.plot.set_points(self.projection, self.result, self.by_id, self.focus_id)
        case = self.by_id.get(self.focus_id) if self.focus_id else None
        if case is None:
            self.detail.setText(
                "Kein Fall ausgewählt. Fälle ohne Diagnosebasis erhalten keine erfundenen Koordinaten."
            )
        else:
            cluster = self.result.cluster_for(case.case_id) if self.result else None
            plotted = case.case_id in {point.case_id for point in self.projection.points}
            self.detail.setText(
                f"Fokus: {case.case_id} · FIN {case.vin} · "
                + (f"Cluster {cluster}" if cluster else "Einzelfall / unzugeordnet")
                + (" · keine 2D-Position (Diagnosebasis fehlt)" if not plotted else "")
                + ". Für exakte Paarähnlichkeit und Merkmalsabdeckung den Fall-Cluster öffnen. "
                + "SSL-Endbefund: " + qec_ssl_finding_label(case)
            )
        self.compare_button.setEnabled(case is not None)
        self.open_button.setEnabled(case is not None)

    def _select_point(self, case_id: str) -> None:
        if self.focus_case(case_id):
            self.case_focused.emit(case_id)

    def _compare_focus(self) -> None:
        if self.focus_id is not None:
            self.compare_requested.emit(self.focus_id)

    def _open_focus(self) -> None:
        if self.focus_id is not None:
            self.case_requested.emit(self.focus_id)
