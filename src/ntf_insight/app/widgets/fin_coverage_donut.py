"""Ein einzelnes kompaktes Donut für überlappende FIN-Quellenkennzahlen.

Jedes Ringdiagramm zeigt eine EIGENE Teilmenge im Verhältnis zur selben
analysierten Grundgesamtheit. Die vier Quellenringe dürfen sich überlappen.
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget


class FinCoverageDonut(QWidget):
    def __init__(self, title: str, color: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.title = title
        self.color = QColor(color)
        self.count = 0
        self.total = 0
        self.setMinimumSize(92, 100)
        self.setAccessibleName(f"FIN-Abdeckung: {title}")

    def set_counts(self, count: int, total: int) -> None:
        if count < 0 or total < count:
            raise ValueError("FIN-Quellenabdeckung muss zwischen 0 und Gesamtzahl liegen.")
        self.count = count
        self.total = total
        pct = (100 * count / total) if total else 0
        self.setToolTip(
            f"{self.title}: {count:,} von {total:,} FINs ({pct:.1f} %)".replace(",", ".")
        )
        self.update()

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(105, 110)

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        diameter = min(self.width(), self.height()) - 25
        if diameter <= 0:
            return
        arc = QRectF(
            (self.width() - diameter) / 2,
            (self.height() - diameter) / 2,
            diameter, diameter,
        )
        pen = QPen(QColor("#DCE3E9"), 12)
        pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        painter.setPen(pen)
        painter.drawEllipse(arc)
        if self.total and self.count:
            pen.setColor(self.color)
            painter.setPen(pen)
            sweep = round(360 * 16 * self.count / self.total)
            painter.drawArc(arc, 90 * 16, -sweep)
        font = QFont(self.font())
        font.setBold(True)
        font.setPointSize(10)
        painter.setFont(font)
        painter.setPen(QColor("#162334"))
        label = (
            f"{self.count:,}".replace(",", ".")
            if self.total else "–"
        )
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, label)
