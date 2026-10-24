"""Kompakte, datengetriebene Donut-Übersichten für den NTF-Workflow.

Nur Anzeige, keine Schätzung fehlender Daten. Gleiche FIN wird in einer
Donut-Verteilung immer nur einmal gezählt. Farben sind mit Text beschriftet.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QRectF, QSize
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget


PALETTE = (
    "#176B8B", "#268763", "#CA922C", "#A84643",
    "#8061A7", "#64748B", "#3D8997", "#BA6F42",
    "#8B8F96", "#4D6682",
)


class _DonutRing(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.values: list[tuple[str, int]] = []
        self.setMinimumSize(100, 100)
        self.setMaximumSize(148, 148)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(124, 124)

    def set_values(self, values: list[tuple[str, int]]) -> None:
        self.values = [(label, max(0, int(count))) for label, count in values]
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        size = min(self.width(), self.height())
        left = (self.width() - size) / 2
        top = (self.height() - size) / 2
        rect = QRectF(left + 14, top + 14, size - 28, size - 28)
        pen = QPen(QColor("#D5DBE2"), 13)
        pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        painter.setPen(pen)
        painter.drawArc(rect, 0, 360 * 16)
        total = sum(count for _label, count in self.values)
        if total:
            start = 90 * 16
            for index, (_label, count) in enumerate(self.values):
                if not count:
                    continue
                length = round(360 * 16 * count / total)
                pen.setColor(QColor(PALETTE[index % len(PALETTE)]))
                painter.setPen(pen)
                painter.drawArc(rect, start, -length)
                start -= length
        painter.setPen(self.palette().text().color())
        font = QFont(self.font())
        font.setBold(True)
        font.setPointSize(17)
        painter.setFont(font)
        painter.drawText(
            QRectF(left, top + size * .32, size, size * .34),
            Qt.AlignmentFlag.AlignCenter,
            f"{total:,}".replace(",", "."),
        )


class WorkflowDonut(QWidget):
    """Donut plus textuelle Legende; auch ohne Farbe eindeutig."""

    def __init__(self, headline: str) -> None:
        super().__init__()
        self._headline = headline
        self.ring = _DonutRing()
        self._legend = QVBoxLayout()
        self._legend.setSpacing(1)
        self._legend.addStretch(1)
        self.title_label = QLabel(headline, objectName="CardTitle")
        self.title_label.setWordWrap(True)
        self.title_label.setAccessibleName(headline)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 3, 8, 3)
        outer.setSpacing(2)
        outer.addWidget(self.title_label)
        row = QHBoxLayout()
        row.addWidget(self.ring)
        row.addLayout(self._legend, 1)
        outer.addLayout(row)
        self.setMinimumWidth(240)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)

    def set_counts(self, counts: dict[str, int]) -> None:
        values = [(str(label), int(count)) for label, count in counts.items()]
        self.ring.set_values(values)
        while self._legend.count():
            item = self._legend.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for index, (name, count) in enumerate(values):
            item = QLabel(
                f"●  {name}: {count:,}".replace(",", "."),
                objectName="PageSubtitle",
            )
            item.setStyleSheet(f"color: {PALETTE[index % len(PALETTE)]};")
            item.setWordWrap(True)
            self._legend.addWidget(item)
        self._legend.addStretch(1)
        self.setAccessibleDescription(
            ", ".join(f"{name}: {count}" for name, count in values)
            or "Keine Daten"
        )
