"""Donutdiagramm fuer eindeutig partitionierte FINs, lokal ohne Web-Charts."""
from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

FIN_COLORS = ("#176BA0", "#8192A1", "#C6AB82")
FIN_LABELS = (
    "FINs in Clustern",
    "Mit DTC, ohne Cluster",
    "Ohne geeignete DTC",
)


class FinStatusDonut(QWidget):
    """A single understandable ring: assigned + noise + missing = all FINs."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._values: tuple[int, int, int] | None = None
        self.setMinimumSize(165, 165)
        self.setAccessibleName("Donutdiagramm der FIN-Verteilung")
        self.setToolTip("Noch keine FIN-Clusteranalyse gestartet.")

    @property
    def values(self) -> tuple[int, int, int] | None:
        return self._values

    def set_values(self, values: tuple[int, int, int] | None) -> None:
        if values is not None and (
            len(values) != 3
            or any(type(value) is not int or value < 0 for value in values)
        ):
            raise ValueError("Donut erwartet drei nichtnegative FIN-Zahlen.")
        self._values = values
        if values is None:
            self.setToolTip("Noch keine FIN-Clusteranalyse gestartet.")
        else:
            total = sum(values)
            self.setToolTip(
                "\n".join(
                    f"{name}: {value:,} von {total:,} "
                    f"({value / total * 100:.1f} %)".replace(",", ".")
                    if total else f"{name}: 0"
                    for name, value in zip(FIN_LABELS, values, strict=True)
                )
            )
        self.update()

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(185, 185)

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        diameter = min(self.width(), self.height()) - 42
        if diameter <= 0:
            return
        square = QRectF(
            (self.width() - diameter) / 2,
            (self.height() - diameter) / 2,
            diameter, diameter,
        )
        pen = QPen(QColor("#DDE3E8"), 23)
        pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        painter.setPen(pen)
        painter.drawEllipse(square)
        total = sum(self._values) if self._values is not None else 0
        if total:
            start = 90 * 16
            remaining = 360 * 16
            for index, count in enumerate(self._values):
                sweep = (
                    remaining if index == 2
                    else min(remaining, round(360 * 16 * count / total))
                )
                if sweep > 0:
                    pen.setColor(QColor(FIN_COLORS[index]))
                    painter.setPen(pen)
                    painter.drawArc(square, start, -sweep)
                    start -= sweep
                    remaining -= sweep
        painter.setPen(QColor("#142234"))
        font = QFont(self.font())
        font.setBold(True)
        font.setPointSize(18)
        painter.setFont(font)
        count = f"{total:,}".replace(",", ".") if self._values else "–"
        center = self.rect().adjusted(0, -13, 0, 0)
        painter.drawText(center, Qt.AlignmentFlag.AlignCenter, count)
        font.setBold(False)
        font.setPointSize(8)
        painter.setFont(font)
        painter.setPen(QColor("#617181"))
        painter.drawText(
            self.rect().adjusted(0, 29, 0, 0),
            Qt.AlignmentFlag.AlignCenter,
            "FINs gesamt",
        )
