"""Feste, nicht scrollende Workflow-Leinwand mit dezenten Blob-Knoten."""
from __future__ import annotations

from dataclasses import dataclass
from math import atan2, cos, sin

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget


@dataclass(frozen=True)
class FlowNode:
    key: str
    title: str
    rect: tuple[float, float, float, float]


NODES = (
    FlowNode("qec", "01  QEC-Liste", (44, 116, 180, 97)),
    FlowNode("befund", "02  Befundung", (265, 116, 180, 97)),
    FlowNode("entscheidung", "03  NTF-Prüfung", (489, 116, 183, 97)),
    FlowNode("kein_ntf", "Kein NTF", (781, 39, 177, 98)),
    FlowNode("ntf", "NTF bestätigt", (781, 220, 177, 98)),
    FlowNode("diagnose", "04  CPC / SAM", (500, 285, 190, 87)),
    FlowNode("cluster", "05  Cluster", (265, 285, 180, 87)),
)
NODES_BY_KEY = {node.key: node for node in NODES}

EDGES = (
    ((224, 164), (265, 164), (239, 164), (251, 164)),
    ((445, 164), (489, 164), (461, 164), (473, 164)),
    ((672, 146), (781, 94), (725, 146), (729, 94)),
    ((672, 185), (781, 269), (724, 185), (726, 269)),
    ((781, 291), (690, 328), (740, 309), (735, 328)),
    ((500, 328), (445, 328), (479, 328), (465, 328)),
)

STATUS_COLORS = {
    "ready": "#24925b",
    "progress": "#c98719",
    "error": "#c43b35",
    "off": "#87939c",
}


def blob_path(rect: QRectF) -> QPainterPath:
    """Geringfügig asymmetrische, rund geschlossene Kontur."""
    x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
    path = QPainterPath(QPointF(x + .22 * w, y + .07 * h))
    path.cubicTo(x + .42 * w, y - .015 * h,
                 x + .79 * w, y + .035 * h, x + .91 * w, y + .18 * h)
    path.cubicTo(x + 1.01 * w, y + .39 * h,
                 x + 1.01 * w, y + .72 * h, x + .87 * w, y + .87 * h)
    path.cubicTo(x + .67 * w, y + 1.02 * h,
                 x + .35 * w, y + 1.00 * h, x + .16 * w, y + .91 * h)
    path.cubicTo(x - .02 * w, y + .77 * h,
                 x - .018 * w, y + .32 * h, x + .11 * w, y + .17 * h)
    path.cubicTo(x + .14 * w, y + .11 * h,
                 x + .17 * w, y + .09 * h, x + .22 * w, y + .07 * h)
    path.closeSubpath()
    return path


class WorkflowCanvas(QWidget):
    """A11y: per click or Left/Right/Up/Down and Enter/Space selectable."""

    stage_selected = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("WorkflowCanvas")
        self.setMinimumHeight(240)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.statuses: dict[str, str] = {}
        self.labels: dict[str, str] = {}
        self.selected = "qec"
        self.current = "qec"

    def set_data(
        self, statuses: dict[str, str], labels: dict[str, str],
        selected: str, current: str,
    ) -> None:
        self.statuses = dict(statuses)
        self.labels = dict(labels)
        self.selected = selected
        self.current = current
        self.update()

    def _dark(self) -> bool:
        return self.palette().window().color().lightness() < 128

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.scale(self.width() / 1000, self.height() / 395)
        dark = self._dark()

        edge_color = QColor("#697783" if dark else "#9ca9b1")
        painter.setPen(QPen(edge_color, 2.5))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for start, end, c1, c2 in EDGES:
            p0, p1 = QPointF(*start), QPointF(*end)
            cp1, cp2 = QPointF(*c1), QPointF(*c2)
            link = QPainterPath(p0)
            link.cubicTo(cp1, cp2, p1)
            painter.drawPath(link)
            angle = atan2(p1.y() - cp2.y(), p1.x() - cp2.x())
            size = 9
            left = QPointF(p1.x() - size * cos(angle - .5),
                           p1.y() - size * sin(angle - .5))
            right = QPointF(p1.x() - size * cos(angle + .5),
                            p1.y() - size * sin(angle + .5))
            arrow = QPainterPath(p1)
            arrow.lineTo(left)
            arrow.lineTo(right)
            arrow.closeSubpath()
            painter.fillPath(arrow, edge_color)

        for node in NODES:
            x, y, w, h = node.rect
            rect = QRectF(x, y, w, h)
            path = blob_path(rect)
            selected = self.selected == node.key
            current = self.current == node.key
            fill = QColor("#343b42" if selected else "#232a31") if dark else (
                QColor("#e9eff2" if selected else "#ffffff")
            )
            border = QColor("#c4d3dc" if dark else "#293944") if selected else (
                QColor("#8d99a4" if dark else "#cbd4d9")
            )
            painter.setBrush(fill)
            painter.setPen(QPen(border, 3 if selected else (2 if current else 1.5)))
            painter.drawPath(path)

            text = QColor("#f6f8fa" if dark else "#17232c")
            secondary = QColor("#c1cad0" if dark else "#55646e")
            painter.setPen(text)
            font = QFont(self.font())
            font.setPointSizeF(12)
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(
                QRectF(x + 10, y + 17, w - 20, 35),
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                node.title,
            )
            font.setBold(False)
            font.setPointSizeF(10)
            painter.setFont(font)
            painter.setPen(secondary)
            painter.drawText(
                QRectF(x + 14, y + 50, w - 28, max(h - 64, 21)),
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                self.labels.get(node.key, "Noch offen"),
            )
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(STATUS_COLORS.get(self.statuses.get(node.key), "#87939c")))
            painter.drawEllipse(QPointF(x + w - 19, y + h - 14), 5.5, 5.5)
            if current:
                painter.setPen(QPen(QColor("#69818e" if dark else "#71818b"), 1))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawEllipse(QPointF(x + 17, y + 20), 4, 4)
        painter.end()

    def _hit(self, pos: QPointF) -> str | None:
        if self.width() <= 0 or self.height() <= 0:
            return None
        point = QPointF(pos.x() * 1000 / self.width(), pos.y() * 395 / self.height())
        for node in NODES:
            if blob_path(QRectF(*node.rect)).contains(point):
                return node.key
        return None

    def mousePressEvent(self, event) -> None:  # noqa: N802
        key = self._hit(event.position())
        if key and event.button() == Qt.MouseButton.LeftButton:
            self.stage_selected.emit(key)
            self.setFocus()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        key = self._hit(event.position())
        self.setCursor(
            Qt.CursorShape.PointingHandCursor if key else Qt.CursorShape.ArrowCursor
        )
        self.setToolTip(
            "Klicken, um diesen Schritt auszuwählen." if key else ""
        )
        super().mouseMoveEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        keys = [node.key for node in NODES]
        index = keys.index(self.selected) if self.selected in keys else 0
        if event.key() in (Qt.Key.Key_Right, Qt.Key.Key_Down):
            self.stage_selected.emit(keys[(index + 1) % len(keys)])
        elif event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Up):
            self.stage_selected.emit(keys[(index - 1) % len(keys)])
        elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.stage_selected.emit(keys[index])
        else:
            super().keyPressEvent(event)
