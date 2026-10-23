"""Compact native Qt donut for mutually exclusive case-level ECU evidence.

The total is always the sum of the *displayed* filtered QEC case categories.
No plotting data or vehicle identifiers leave the local process.
"""
from __future__ import annotations

from html import escape

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

COLORS = ("#176BA0", "#728A9C", "#BDC4CD", "#8D7791",
          "#C4A77C", "#5C7B74", "#CECECE")


class ECUCaseDonut(QWidget):
    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.title = title
        self.entries: tuple[tuple[str, int], ...] = ()
        self.setMinimumSize(112, 120)
        self.setAccessibleName(f"Ringdiagramm: {title}")

    def set_counts(self, entries: tuple[tuple[str, int], ...]) -> None:
        if any(type(value) is not int or value < 0 for _, value in entries):
            raise ValueError("Ein Diagramm benötigt nichtnegative Fallzahlen.")
        self.entries = entries
        total = sum(value for _, value in entries)
        self.setToolTip(
            f"{self.title} – {total} Fälle\n"
            + "\n".join(
                f"{name}: {value} ({100 * value / total:.1f} %)"
                if total else f"{name}: 0"
                for name, value in entries
            )
        )
        self.update()

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(120, 120)

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        diameter = min(self.height(), self.width()) - 28
        rect = QRectF(
            (self.width() - diameter) / 2,
            (self.height() - diameter) / 2,
            diameter, diameter,
        )
        ring = QPen(QColor("#DBE0E5"), 13)
        ring.setCapStyle(Qt.PenCapStyle.FlatCap)
        painter.setPen(ring)
        painter.drawEllipse(rect)
        total = sum(value for _, value in self.entries)
        if total:
            start, remaining = 90 * 16, 360 * 16
            for index, (_name, value) in enumerate(self.entries):
                sweep = (
                    remaining if index == len(self.entries) - 1
                    else min(remaining, round(360 * 16 * value / total))
                )
                if sweep <= 0:
                    continue
                ring.setColor(QColor(COLORS[index % len(COLORS)]))
                painter.setPen(ring)
                painter.drawArc(rect, start, -sweep)
                start -= sweep
                remaining -= sweep
        painter.setPen(self.palette().text().color())
        font = QFont(self.font())
        font.setBold(True)
        font.setPointSize(12)
        painter.setFont(font)
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, str(total))


class ECUOverviewDonutCard(QWidget):
    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.title = title
        vertical = QVBoxLayout(self)
        vertical.setContentsMargins(6, 4, 6, 4)
        vertical.setSpacing(2)
        heading = QLabel(title)
        heading.setObjectName("CardTitle")
        heading.setWordWrap(True)
        vertical.addWidget(heading)
        body = QHBoxLayout()
        body.setSpacing(6)
        self.donut = ECUCaseDonut(title)
        body.addWidget(self.donut)
        self.legend = QLabel("Keine Auswertung")
        self.legend.setTextFormat(Qt.TextFormat.RichText)
        self.legend.setWordWrap(True)
        self.legend.setMinimumWidth(135)
        body.addWidget(self.legend, 1)
        vertical.addLayout(body)
        self.setMinimumHeight(150)

    def set_counts(self, entries: tuple[tuple[str, int], ...]) -> None:
        self.donut.set_counts(entries)
        self.legend.setText("<br>".join(
            f'<span style="color:{COLORS[index % len(COLORS)]}">●</span> '
            f"{escape(label[:22])}: {count}"
            for index, (label, count) in enumerate(entries) if count
        ) or "Keine Fälle")
        self.legend.setToolTip(self.donut.toolTip())
