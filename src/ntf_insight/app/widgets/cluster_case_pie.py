"""Offline PySide6 pie chart: mutually exclusive QEC statuses, no raw data.

Counts cover the same QEC cohort as the selected clustering method:
clustered + eligible unclustered + excluded = all QEC cases.
Not eligible does NOT imply that the workshop never did a diagnosis.
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget


# Graphite/blue accent palette suitable for the German Mercedes-oriented UI.
PIE_COLORS = ("#176BA0", "#8493A1", "#C5AB82")
PIE_LABELS = (
    "Fälle in Clustern",
    "Ohne Cluster (auswertbar)",
    "Vor Tausch nicht auswertbar",
)


class ClusterCasePie(QWidget):
    """One clear, read-only pie; textual counts remain visible beside it."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._values: tuple[int, int, int] | None = None
        self.setMinimumSize(138, 138)
        self.setAccessibleName("Kreisdiagramm der QEC-Fallverteilung")
        self.setToolTip(
            "Analyse starten: Zuordnung und Diagnoseabdeckung der QEC-Fälle."
        )

    @property
    def values(self) -> tuple[int, int, int] | None:
        return self._values

    def set_values(self, values: tuple[int, int, int] | None) -> None:
        if values is not None and (
            len(values) != 3
            or any(not isinstance(n, int) or n < 0 for n in values)
        ):
            raise ValueError("Kreisdiagramm erwartet drei nichtnegative Fallzahlen.")
        self._values = values
        if values is None:
            self.setToolTip("Noch keine Clusteranalyse ausgeführt.")
        else:
            total = sum(values)
            details = "\n".join(
                f"{label}: {count} von {total} "
                f"({count / total:.1%})" if total else f"{label}: 0"
                for label, count in zip(PIE_LABELS, values, strict=True)
            )
            self.setToolTip(details)
        self.update()

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(155, 155)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        diameter = max(0.0, min(self.width(), self.height()) - 12.0)
        if diameter < 1:
            return
        rect = QRectF(
            (self.width() - diameter) / 2,
            (self.height() - diameter) / 2,
            diameter, diameter,
        )
        values = self._values
        total = sum(values) if values is not None else 0
        if not total:
            painter.setPen(QPen(QColor("#AAB2BB"), 1.5))
            painter.setBrush(QColor("#DDE1E5"))
            painter.drawEllipse(rect)
            return

        painter.setPen(Qt.PenStyle.NoPen)
        start = 90 * 16
        remaining = 360 * 16
        for index, count in enumerate(values):
            if not count:
                continue
            sweep = (
                remaining if index == 2
                else round(360 * 16 * count / total)
            )
            sweep = min(remaining, sweep)
            if sweep <= 0:
                continue
            painter.setBrush(QColor(PIE_COLORS[index]))
            painter.drawPie(rect, start, -sweep)
            start -= sweep
            remaining -= sweep
