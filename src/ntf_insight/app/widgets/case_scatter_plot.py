"""Interactive case scatter view; projection never determines cluster membership."""

from __future__ import annotations

from collections import Counter, defaultdict
from math import cos, hypot, pi, sin

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QScrollArea,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ntf_insight.analysis.case_clustering import (
    VIEW_WEIGHTS,
    CaseClusterResult,
    cluster_diagnostic_cases,
    signature_for,
)
from ntf_insight.analysis.case_projection import CaseProjection, project_diagnostic_cases
from ntf_insight.analysis.case_similarity_explanation import (
    FEATURE_LABELS,
    explain_case_similarity,
)
from ntf_insight.analysis.qec_findings import qec_ssl_finding_label
from ntf_insight.app.models.simple_table_model import SimpleTableModel
from ntf_insight.domain.case import NTFCase


# Non-cycling first 24 category colours: cluster 1 and 9 must NEVER have
# the same colour just because the dataset has more than eight clusters.
# Colour is only an aid; numerical cluster IDs remain the authoritative key.
PALETTE = (
    "#0057b8", "#c43c39", "#00835e", "#7b41b2",
    "#ca6b09", "#009eb7", "#bd4c8c", "#5e8500",
    "#90512c", "#d492b4", "#4a6fbb", "#a7a125",
    "#d54e62", "#507b5d", "#c15f00", "#6947d4",
    "#237c90", "#a14936", "#6e9220", "#ab6eb2",
    "#00796b", "#bd725e", "#1f5675", "#b36400",
)
UNASSIGNED = "#858e9b"


def color_for_cluster(cluster_id: int | None) -> QColor:
    """Stable mapping by cluster ID; no cyclic palette reuse at ID 9.

    A finite display cannot guarantee human-distinguishable hues for arbitrary
    many clusters. Above the hand-selected palette, generate additional colours;
    always show numeric IDs in the legend/tooltip to remove colour ambiguity.
    """
    if cluster_id is None:
        return QColor(UNASSIGNED)
    if cluster_id < 1:
        raise ValueError("Cluster-IDs müssen positiv sein.")
    if cluster_id <= len(PALETTE):
        return QColor(PALETTE[cluster_id - 1])
    hue = int((cluster_id * 137.50776405) % 360)
    return QColor.fromHsv(
        hue,
        174 + 12 * (cluster_id % 4),
        175 + 12 * (cluster_id % 5),
    )


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
        self._projection_key: tuple[tuple[str, float, float], ...] | None = None
        self._zoom_level = 1.0
        self.items_by_case = {}

    def set_points(
        self,
        projection: CaseProjection,
        result: CaseClusterResult | None,
        by_id: dict[str, NTFCase],
        focus_id: str | None,
    ) -> None:
        scene = self._scene
        new_key = tuple(
            (point.case_id, point.x, point.y) for point in projection.points
        )
        new_projection = new_key != self._projection_key
        self._projection_key = new_key
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
            if new_projection:
                self.reset_zoom()
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

        clusters_by_case = {
            case_id: cluster.cluster_id
            for cluster in (result.clusters if result else ())
            for case_id in cluster.case_ids
        }
        focus_cluster = clusters_by_case.get(focus_id)
        # Dashed links show ACTUAL cluster membership of the focused case.
        # Unlike pixel distances, the colour and these links represent the
        # unchanged weighted-Jaccard/Complete-Link result.
        if focus_cluster is not None and focus_id in locations:
            cx, cy = locations[focus_id]
            line_pen = QPen(color_for_cluster(focus_cluster), 1.2)
            line_pen.setStyle(Qt.PenStyle.DashLine)
            for member_id, member_cluster in clusters_by_case.items():
                if member_cluster != focus_cluster or member_id == focus_id:
                    continue
                if member_id in locations:
                    x_other, y_other = locations[member_id]
                    line = scene.addLine(cx, cy, x_other, y_other, line_pen)
                    line.setZValue(1)
                    line.setOpacity(0.6)

        for point in projection.points:
            case = by_id[point.case_id]
            cluster = clusters_by_case.get(point.case_id)
            color = color_for_cluster(cluster)
            x, y = locations[point.case_id]
            radius = 9.5 if point.case_id == focus_id else 7.0
            outline = QColor("#172638") if point.case_id == focus_id else QColor("#ffffff")
            in_focus_cluster = focus_cluster is not None and cluster == focus_cluster
            pen = QPen(
                outline,
                3.0 if point.case_id == focus_id else 2.0 if in_focus_cluster else 1.3,
            )

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
        if new_projection:
            self.reset_zoom()

    def reset_zoom(self) -> None:
        """Fit the whole plot; explicitly undo any previous manual zoom."""
        self._zoom_level = 1.0
        self.resetTransform()
        self.fitInView(
            self._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio
        )

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
        dy = event.angleDelta().y()
        if dy == 0:
            event.ignore()
            return
        requested = 1.15 if dy > 0 else 1 / 1.15
        target = min(8.0, max(0.5, self._zoom_level * requested))
        factor = target / self._zoom_level
        if factor != 1.0:
            # QGraphicsView.scale requires an x AND y factor.
            self.scale(factor, factor)
            self._zoom_level = target
        event.accept()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        # Do not cancel the user's zoom when the window is resized.
        if self._has_points and self._zoom_level == 1.0:
            self.fitInView(self._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)


class CaseScatterPanel(QWidget):
    """Linked case scatter + numerical provenance in the FIN workspace.

    Only the original cluster_diagnostic_cases() determines memberships.
    This view uses SVD coordinates exclusively for positioning.
    """

    case_focused = Signal(str)
    case_requested = Signal(str)
    quicktests_requested = Signal(str)

    def __init__(
        self, cases: list[NTFCase], result: CaseClusterResult | None = None
    ) -> None:
        super().__init__()
        self.cases = sorted(cases, key=lambda case: case.case_id)
        self.by_id = {case.case_id: case for case in self.cases}
        self._component_of = {
            case.case_id: signature_for(case).component_key for case in self.cases
        }
        self.result = result if result is not None else (
            cluster_diagnostic_cases(self.cases) if self.cases else None
        )
        self.focus_id: str | None = None
        self.projection = CaseProjection((), ())
        self._visible_case_ids: list[str] = []
        self._neighbour_ids: list[str] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll)
        content = QWidget()
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(22, 18, 22, 20)
        layout.setSpacing(12)

        layout.addWidget(QLabel("Fallübersicht · 2D-Streudiagramm", objectName="PageTitle"))
        intro = QLabel(
            "Ein Punkt ist ein echter Fall, nicht ein QuickTest. Die Position kommt "
            "aus den diagnostischen Vorher-Merkmalen (TruncatedSVD). "
            "Die Farbzuordnung zeigt das unveränderte Complete-Link-Ergebnis; "
            "jede Cluster-ID erhält eine eigene Kennzeichnung. "
            "QEC-SSL-Endbefunde und Reparaturergebnisse ändern die Position nicht.",
            objectName="PageSubtitle",
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Bauteilfamilie"))
        self.component_filter = QComboBox()
        names = {
            key: next(
                case.component_type for case in self.cases
                if self._component_of[case.case_id] == key
            )
            for key in set(self._component_of.values())
        }
        counts = Counter(self._component_of.values())
        for key in sorted(names, key=lambda item: (-counts[item], item)):
            self.component_filter.addItem(names[key], key)
        controls.addWidget(self.component_filter)
        controls.addSpacing(18)
        controls.addWidget(QLabel("Cluster-Mindestähnlichkeit"))
        self.threshold = QDoubleSpinBox()
        self.threshold.setRange(0.05, 1.0)
        self.threshold.setSingleStep(0.05)
        self.threshold.setDecimals(2)
        self.threshold.setValue(self.result.threshold if self.result else 0.65)
        self.threshold.setToolTip(
            "Mindestwert für alle Paarwerte in einer Clustergruppe. "
            "Ändert ausschließlich die Clusterfarben, niemals die 2D-Koordinaten."
        )
        controls.addWidget(self.threshold)
        controls.addStretch(1)
        layout.addLayout(controls)

        self.summary = QLabel(objectName="PageSubtitle")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)

        self.plot = CaseScatterPlot()
        self.plot.case_selected.connect(self._select_point)
        layout.addWidget(self.plot)
        zoom_row = QHBoxLayout()
        zoom_row.addStretch(1)
        zoom_reset = QPushButton("Zoom zurücksetzen")
        zoom_reset.setToolTip(
            "Stellt das gesamte Diagramm wieder dar; der Mausrad-Zoom "
            "bleibt auch beim Auswählen eines Falls erhalten."
        )
        zoom_reset.clicked.connect(self.plot.reset_zoom)
        zoom_row.addWidget(zoom_reset)
        layout.addLayout(zoom_row)
        legend = QLabel(
            "Farbe + Cluster-Nr. = bestehende Clusterzuordnung · Grau = unzugeordnet · "
            "Quadrat = fehlender Tauschanker · Dunkler Rand = Fokusfall · "
            "Gestrichelte Verbindung = andere Fälle desselben Fokusclusters "
            "(keine Ähnlichkeitsdistanz) · "
            "Bei gleicher Position werden Symbole nur für die Auswahl versetzt. "
            "Die 2D-Entfernung ist KEIN Jaccard-Wert.",
            objectName="PageSubtitle",
        )
        legend.setWordWrap(True)
        layout.addWidget(legend)
        self.cluster_legend = QLabel(objectName="PageSubtitle")
        self.cluster_legend.setWordWrap(True)
        self.cluster_legend.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(self.cluster_legend)
        self.cluster_note = QLabel(objectName="PageSubtitle")
        self.cluster_note.setWordWrap(True)
        layout.addWidget(self.cluster_note)

        self.detail = QLabel(objectName="PageSubtitle")
        self.detail.setWordWrap(True)
        layout.addWidget(self.detail)

        buttons = QHBoxLayout()
        self.open_button = QPushButton("FIN / Fallanalyse öffnen")
        self.open_button.setEnabled(False)
        self.open_button.clicked.connect(self._open_focus)
        buttons.addWidget(self.open_button)
        self.quicktests_button = QPushButton("QuickTests dieser FIN")
        self.quicktests_button.setEnabled(False)
        self.quicktests_button.clicked.connect(self._open_quicktests)
        buttons.addWidget(self.quicktests_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        layout.addWidget(QLabel("Warum liegen die Punkte dort?", objectName="CardTitle"))
        self.method_note = QLabel(objectName="PageSubtitle")
        self.method_note.setWordWrap(True)
        self.method_note.setTextInteractionFlags(
            self.method_note.textInteractionFlags()
            | Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self.method_note)

        layout.addWidget(QLabel("Berechnungsgrundlage: Merkmalsgewichte", objectName="CardTitle"))
        self.feature_model = SimpleTableModel((
            "Merkmalsgruppe", "Gewicht", "Merkmale im Fokusfall",
            "Regel für die Projektion",
        ))
        self.feature_table = self._table(self.feature_model, 195)
        layout.addWidget(self.feature_table)

        layout.addWidget(QLabel("Erklärbare SVD-Achsen: wichtigste Ladungen", objectName="CardTitle"))
        axis_note = QLabel(
            "Die Vorzeichen und Achsenrichtungen sind mathematisch austauschbar. "
            "Die Ladungen zeigen, welche gewichteten Merkmale die dargestellten "
            "Achsen am stärksten prägen – nicht, welche Fehlerursache vorliegt.",
            objectName="PageSubtitle",
        )
        axis_note.setWordWrap(True)
        layout.addWidget(axis_note)
        self.axis_model = SimpleTableModel((
            "SVD-Achse", "Merkmalsgruppe", "Merkmal", "Ladung",
        ))
        self.axis_table = self._table(self.axis_model, 210)
        layout.addWidget(self.axis_table)

        layout.addWidget(QLabel("Alle Fallkoordinaten und Eingangsdaten", objectName="CardTitle"))
        self.coordinate_model = SimpleTableModel((
            "Fall", "FIN", "Cluster", "SVD 1", "SVD 2",
            "ECU:DTC vor Tausch", "Merkmalsgruppen", "Tauschanker",
        ))
        self.coordinate_table = self._table(self.coordinate_model, 235)
        self.coordinate_table.selectionModel().currentRowChanged.connect(
            self._coordinate_selected
        )
        layout.addWidget(self.coordinate_table)

        layout.addWidget(QLabel("Fallvergleich: echte Ähnlichkeit statt Plotabstand", objectName="CardTitle"))
        compare_note = QLabel(
            "Sortierung: Jaccard-Ähnlichkeit × Merkmalsabdeckung. "
            "Der SVD-Punktabstand steht zum Vergleich daneben, ist jedoch "
            "keine diagnostische Ähnlichkeitszahl. "
            "SSL-Endbefunde sind nachgelagerte Informationen und kein Score-Merkmal.",
            objectName="PageSubtitle",
        )
        compare_note.setWordWrap(True)
        layout.addWidget(compare_note)
        self.neighbor_model = SimpleTableModel((
            "Vergleichsfall", "Jaccard", "Abdeckung", "Score × Abdeckung",
            "Gleiche ECU:DTCs", "SVD-Distanz", "Clusterpaar zulässig",
            "QEC SSL-Endbefund",
        ))
        self.neighbor_table = self._table(self.neighbor_model, 230)
        self.neighbor_table.selectionModel().currentRowChanged.connect(
            self._neighbor_selected
        )
        layout.addWidget(self.neighbor_table)

        layout.addWidget(QLabel("Numerische Zerlegung des ausgewählten Paarvergleichs", objectName="CardTitle"))
        self.comparison_note = QLabel(objectName="PageSubtitle")
        self.comparison_note.setWordWrap(True)
        self.comparison_note.setTextInteractionFlags(
            self.comparison_note.textInteractionFlags()
            | Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self.comparison_note)
        self.breakdown_model = SimpleTableModel((
            "Gruppe", "Gewicht", "Fokus", "Vergleich", "Schnitt", "Vereinigung",
            "Jaccard", "Beitrag zum Score",
        ))
        self.breakdown_table = self._table(self.breakdown_model, 205)
        layout.addWidget(self.breakdown_table)

        self.component_filter.currentIndexChanged.connect(self._refresh)
        self.threshold.valueChanged.connect(self._recluster)
        self._refresh()

    @staticmethod
    def _table(model: SimpleTableModel, height: int) -> QTableView:
        table = QTableView()
        table.setModel(model)
        table.setMinimumHeight(min(130, height))
        table.setMaximumHeight(height)
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        table.horizontalHeader().setStretchLastSection(True)
        return table

    def set_result(self, result: CaseClusterResult | None) -> None:
        """Compatibility hook for callers using a precomputed cluster result."""
        self.result = result
        if result is not None and self.threshold.value() != result.threshold:
            self.threshold.blockSignals(True)
            self.threshold.setValue(result.threshold)
            self.threshold.blockSignals(False)
        self._draw()

    def _recluster(self) -> None:
        self.result = (
            cluster_diagnostic_cases(self.cases, threshold=self.threshold.value())
            if self.cases else None
        )
        # Recompute only visible labels/tables, never SVD positions.
        self._draw()

    def clear_focus(self) -> None:
        """FIN-only QuickTests are never treated as existing QEC cases."""
        if self.focus_id is not None:
            self.focus_id = None
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
        self._visible_case_ids = [
            case.case_id for case in self.cases
            if self._component_of[case.case_id] == family
        ]
        subset = [self.by_id[case_id] for case_id in self._visible_case_ids]
        self.projection = project_diagnostic_cases(subset)
        if self.focus_id not in self._visible_case_ids:
            self.focus_id = self._visible_case_ids[0] if self._visible_case_ids else None
        self._draw()

    def _draw(self) -> None:
        projected = {p.case_id: p for p in self.projection.points}
        self.plot.set_points(self.projection, self.result, self.by_id, self.focus_id)
        count = len(self.projection.points)
        self.summary.setText(
            f"{len(self._visible_case_ids)} echte Fälle · {count} projiziert · "
            f"{len(self.projection.omitted_case_ids)} ohne Diagnosebasis · "
            f"{self.projection.feature_count} gewichtete Matrixspalten · "
            f"{len(self.result.clusters) if self.result else 0} Cluster (alle Bauteile)"
        )
        visible_ids = set(projected)
        color_keys = []
        for group in (self.result.clusters if self.result else ()):
            matching = visible_ids.intersection(group.case_ids)
            if not matching:
                continue
            colour = color_for_cluster(group.cluster_id).name()
            color_keys.append(
                f'<span style="color: {colour};"><b>● C{group.cluster_id}</b> '
                f'({len(matching)} Fälle)</span>'
            )
        number_unassigned = sum(
            self.result is None or self.result.cluster_for(case_id) is None
            for case_id in visible_ids
        )
        if number_unassigned:
            color_keys.append(
                f'<span style="color: {UNASSIGNED};"><b>● Unzugeordnet</b> '
                f'({number_unassigned})</span>'
            )
        self.cluster_legend.setText(
            "Cluster-Legende (nur geplottete Fälle): "
            + (" · ".join(color_keys) if color_keys else "Keine Clusterpunkte")
        )

        if self.projection.components > 0:
            percentages = ", ".join(
                f"Achse {i}: {100 * v:.1f} %"
                for i, v in enumerate(self.projection.explained_variance_ratio, 1)
            )
        else:
            percentages = "keine belastbare Achse (zu wenige Fälle/Merkmale)"
        self.method_note.setText(
            "Datengrundlage: ausschließlich diagnostische Merkmale vor dem "
            "untersuchten Tausch. Doppelte ECU:DTC-Quellzeilen zählen als "
            "ein Mengenmerkmal. Für jede Merkmalsgruppe g und jeden vorkommenden "
            "Token wird X[Fall, Token] = sqrt(Gruppengewicht / Tokenanzahl "
            "dieses Falls in dieser Gruppe) gesetzt; sonst 0. "
            "Die Sparse-Matrix hat hier "
            f"{count} Zeilen und {self.projection.feature_count} Spalten. "
            f"TruncatedSVD berechnet {self.projection.components} Komponenten; "
            "deren projizierte Koordinaten werden je Achse mittelwertzentriert. "
            f"Erklärte Varianz der Matrix: {percentages}. "
            "Das ist NICHT die bewahrte Jaccard-Ähnlichkeit. "
            "Die Clusterfarben folgen weiterhin dem gewichteten Jaccard "
            f"und der konservativen Complete-Link-Schwelle {self.threshold.value():.2f}. "
            "Die Merkmalsgewichte sind fachliche Startwerte, keine "
            "empirisch kalibrierten Wahrscheinlichkeiten."
        )

        axis_rows = []
        for axis, key, loading in self.projection.axis_top_features:
            group, _, feature = key.partition("::")
            axis_rows.append((
                f"SVD {axis}", FEATURE_LABELS.get(group, group),
                feature, f"{loading:+.4f}",
            ))
        self.axis_model.set_rows(axis_rows)

        rows = []
        for case_id in self._visible_case_ids:
            case = self.by_id[case_id]
            signature = signature_for(case)
            point = projected.get(case_id)
            cluster = self.result.cluster_for(case_id) if self.result else None
            rows.append((
                case_id, case.vin,
                f"Cluster {cluster}" if cluster else "Einzelfall",
                f"{point.x:+.5f}" if point else "k. A.",
                f"{point.y:+.5f}" if point else "k. A.",
                len(signature.faults),
                sum(bool(view) for view in signature.views().values()),
                "Ja" if signature.has_replacement_anchor else "Nein",
            ))
        self.coordinate_model.set_rows(rows)
        self._render_focus(projected)

    def _render_focus(self, projected: dict | None = None) -> None:
        projected = projected if projected is not None else {
            p.case_id: p for p in self.projection.points
        }
        case = self.by_id.get(self.focus_id) if self.focus_id else None
        self.open_button.setEnabled(case is not None)
        self.quicktests_button.setEnabled(case is not None)
        if case is None:
            self.cluster_note.setText(
                "Keine Clustergruppe gewählt. Gleichfarbigkeit allein ist "
                "keine Identifikation: Entscheidend ist die Cluster-Nr."
            )
            self.detail.setText(
                "Kein NTF-/QEC-Fall. Reine FIN-QuickTests findest du im "
                "benachbarten QuickTest-Reiter."
            )
            self.feature_model.set_rows([])
            self.neighbor_model.set_rows([])
            self.breakdown_model.set_rows([])
            self.comparison_note.setText("Kein Fallvergleich verfügbar.")
            return

        signature = signature_for(case)
        point = projected.get(case.case_id)
        cluster = self.result.cluster_for(case.case_id) if self.result else None
        if cluster is not None and self.result is not None:
            members = next(
                group.case_ids for group in self.result.clusters
                if group.cluster_id == cluster
            )
            member_set = set(members)
            real_pairs = [
                match.score for match in self.result.matches
                if match.left_case_id in member_set
                and match.right_case_id in member_set
                and match.score is not None
            ]
            member_positions = [
                (projected[case_id].x, projected[case_id].y)
                for case_id in members if case_id in projected
            ]
            largest_2d_distance = max(
                (
                    hypot(a[0] - b[0], a[1] - b[1])
                    for i, a in enumerate(member_positions)
                    for b in member_positions[i + 1:]
                ),
                default=0.0,
            )
            weakest = (
                f"{min(real_pairs):.1%}" if real_pairs else "nicht berechenbar"
            )
            self.cluster_note.setText(
                f"Fokuscluster C{cluster}: {len(members)} Fälle · "
                f"schwächste originale Paarähnlichkeit {weakest} · "
                f"größter Abstand in der 2D-Projektion "
                f"{largest_2d_distance:.5f}. "
                "Der 2D-Abstand ist keine Jaccard-Distanz. "
                "Die gestrichelten Linien verbinden reale Gruppenmitglieder."
            )
        else:
            self.cluster_note.setText(
                "Fokusfall unzugeordnet: kein automatisch bestätigter Cluster. "
                "Die grauen Punkte bilden keine gemeinsame Gruppe."
            )
        position = (
            f"({point.x:+.5f}; {point.y:+.5f})"
            if point is not None else "keine Koordinaten (Diagnosebasis fehlt)"
        )
        self.detail.setText(
            f"Fokus: {case.case_id} · FIN {case.vin} · "
            f"{'Cluster ' + str(cluster) if cluster else 'Einzelfall / unzugeordnet'} · "
            f"SVD-Koordinaten: {position} · "
            f"ECU:DTCs vor Tausch: {len(signature.faults)}. "
            "QEC SSL-Endbefund (nicht im Score): "
            + qec_ssl_finding_label(case)
        )

        self.feature_model.set_rows([
            (
                FEATURE_LABELS[group],
                f"{weight:.0%}",
                len(signature.views()[group]),
                (
                    f"sqrt({weight:.2f} / Anzahl Tokens)"
                    if signature.views()[group] else "keine Daten; Spalten = 0"
                ),
            )
            for group, weight in VIEW_WEIGHTS.items()
        ])
        match_map = {
            (m.right_case_id if m.left_case_id == case.case_id else m.left_case_id): m
            for m in (self.result.matches if self.result else ())
            if case.case_id in (m.left_case_id, m.right_case_id)
        }
        matches = [
            (other, match_map.get(other))
            for other in self._visible_case_ids if other != case.case_id
        ]
        matches.sort(key=lambda item: (
            -(
                (item[1].score * item[1].coverage)
                if item[1] is not None and item[1].score is not None else -1
            ),
            item[0],
        ))
        self._neighbour_ids = [other for other, _ in matches]
        table_rows = []
        for other_id, match in matches:
            other_point = projected.get(other_id)
            distance = (
                hypot(point.x - other_point.x, point.y - other_point.y)
                if point is not None and other_point is not None else None
            )
            table_rows.append((
                other_id,
                f"{match.score:.1%}" if match and match.score is not None else "k. A.",
                f"{match.coverage:.0%}" if match and match.score is not None else "k. A.",
                f"{match.score * match.coverage:.3f}"
                if match and match.score is not None else "k. A.",
                len(match.shared_faults) if match else 0,
                f"{distance:.5f}" if distance is not None else "k. A.",
                (
                    "Ja" if match and match.eligible_for_cluster
                    and match.score is not None and match.score >= self.threshold.value()
                    else "Nein"
                ),
                qec_ssl_finding_label(self.by_id[other_id]),
            ))
        self.neighbor_model.set_rows(table_rows)
        if matches:
            self.neighbor_table.selectRow(0)
            self._display_pair(matches[0][0])
        else:
            self.breakdown_model.set_rows([])
            self.comparison_note.setText(
                "Kein weiterer Fall dieser Bauteilfamilie verfügbar. "
                "Eine 2D-Projektion allein kann keine Ähnlichkeit bestätigen."
            )

        # Reflect selection in the input-coordinates table without re-entering
        # case-change handlers or automatically switching to another tab.
        if case.case_id in self._visible_case_ids:
            row = self._visible_case_ids.index(case.case_id)
            selection = self.coordinate_table.selectionModel()
            selection.blockSignals(True)
            self.coordinate_table.selectRow(row)
            selection.blockSignals(False)

    def _display_pair(self, other_id: str) -> None:
        if self.focus_id not in self.by_id or other_id not in self.by_id:
            return
        explanation = explain_case_similarity(
            self.by_id[self.focus_id], self.by_id[other_id]
        )
        match = explanation.match
        self.breakdown_model.set_rows([
            (
                row.label, f"{row.weight:.0%}", row.left_count,
                row.right_count, row.overlap_count, row.union_count,
                f"{row.jaccard:.1%}" if row.jaccard is not None else "k. A.",
                f"{row.normalized_contribution:.4f}"
                if row.normalized_contribution is not None else "k. A.",
            )
            for row in explanation.contributions
        ])
        if match.score is None:
            score_description = "Nicht vergleichbar: " + match.reason
        else:
            score_description = (
                f"Gewichtete Summe {explanation.weighted_sum:.4f} "
                f"÷ Abdeckungsgewicht {explanation.covered_weight:.2f} "
                f"= Jaccard-Score {match.score:.1%} "
                f"(interne Rundung auf vier Dezimalstellen). "
                f"Merkmalsabdeckung {match.coverage:.0%}."
            )
        self.comparison_note.setText(
            f"{self.focus_id} ↔ {other_id}: {score_description} "
            "Nur beidseitig vorhandene Gruppen stehen im Nenner; "
            "fehlende Informationen bedeuten nicht 0 % Übereinstimmung. "
            "Clusterfähig nur bei gemeinsamer ECU:DTC-Kombination, "
            "mindestens 50 % Abdeckung, dokumentierten Tauschankern und "
            f"Paarwert ≥ {self.threshold.value():.2f}. "
            f"Entscheidung für dieses Paar: {'zulässig' if match.eligible_for_cluster and match.score is not None and match.score >= self.threshold.value() else 'nicht zulässig'}. "
            "Ein zulässiges Paar garantiert dennoch nicht, dass beide Fälle "
            "im selben Complete-Link-Cluster liegen."
        )

    def _coordinate_selected(self, current, _previous) -> None:
        if current.isValid() and 0 <= current.row() < len(self._visible_case_ids):
            self._select_point(self._visible_case_ids[current.row()])

    def _neighbor_selected(self, current, _previous) -> None:
        if current.isValid() and 0 <= current.row() < len(self._neighbour_ids):
            self._display_pair(self._neighbour_ids[current.row()])

    def _select_point(self, case_id: str) -> None:
        if self.focus_case(case_id):
            self.case_focused.emit(case_id)

    def _open_focus(self) -> None:
        if self.focus_id is not None:
            self.case_requested.emit(self.focus_id)

    def _open_quicktests(self) -> None:
        case = self.by_id.get(self.focus_id) if self.focus_id else None
        if case is not None:
            self.quicktests_requested.emit(case.vin)

