"""Chronological plot of DTC and case events."""

from __future__ import annotations

from datetime import timedelta

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QApplication, QSizePolicy, QWidget

from ntf_insight.analysis.timeline import TimelineEntry


class EventTimePlot(QWidget):
    """Compact engineering time plot for one FIN/case."""

    def __init__(self) -> None:
        super().__init__(objectName="EventTimePlot")
        self._entries: list[TimelineEntry] = []
        self.setMinimumHeight(270)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_entries(self, entries: list[TimelineEntry]) -> None:
        self._entries = sorted(entries, key=lambda item: item.occurred_at)
        self.update()

    @staticmethod
    def _theme() -> str:
        app = QApplication.instance()
        if app is None:
            return "light"
        value = app.property("ntfTheme")
        return str(value) if value in {"light", "dark"} else "light"

    def _colors(self) -> dict[str, QColor]:
        if self._theme() == "dark":
            return {
                "bg": QColor("#1f2937"),
                "text": QColor("#f9fafb"),
                "muted": QColor("#cbd5e1"),
                "grid": QColor("#4b5563"),
                "dtc": QColor("#f3f4f6"),
                "dtc_fill": QColor("#374151"),
                "replacement": QColor("#e5e7eb"),
                "event": QColor("#9ca3af"),
            }
        return {
            "bg": QColor("#ffffff"),
            "text": QColor("#111827"),
            "muted": QColor("#4b5563"),
            "grid": QColor("#d1d5db"),
            "dtc": QColor("#111827"),
            "dtc_fill": QColor("#e5e7eb"),
            "replacement": QColor("#374151"),
            "event": QColor("#6b7280"),
        }

    def _lanes(self) -> list[tuple[str, str]]:
        dtc_titles = sorted({entry.title for entry in self._entries if entry.kind == "diagnostic"})
        lanes = [("diagnostic", title) for title in dtc_titles]
        labels = {
            "diagnostic_session": "Kurztest",
            "replacement": "Tausch",
            "repair": "Werkstatt",
            "software": "Software",
            "supplier": "Lieferant",
        }
        for kind in ("diagnostic_session", "replacement", "software", "repair", "supplier"):
            if any(entry.kind == kind for entry in self._entries):
                lanes.append((kind, labels[kind]))
        return lanes

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        colors = self._colors()
        painter.fillRect(self.rect(), colors["bg"])

        if not self._entries:
            painter.setPen(colors["muted"])
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Keine zeitlichen Ereignisse verfügbar.")
            return

        lanes = self._lanes()
        if not lanes:
            return

        left = 185.0
        right = 28.0
        top = 30.0
        bottom = 42.0
        plot_width = max(80.0, self.width() - left - right)
        plot_height = max(80.0, self.height() - top - bottom)
        lane_height = plot_height / max(1, len(lanes))

        start = min(entry.occurred_at for entry in self._entries)
        end = max(entry.occurred_at for entry in self._entries)
        if start == end:
            start -= timedelta(hours=12)
            end += timedelta(hours=12)
        span = max(1.0, (end - start).total_seconds())

        def x_for(moment) -> float:
            return left + ((moment - start).total_seconds() / span) * plot_width

        lane_index = {lane: index for index, lane in enumerate(lanes)}

        painter.setFont(QFont(self.font().family(), 8))
        for tick in range(5):
            ratio = tick / 4
            x = left + ratio * plot_width
            painter.setPen(QPen(colors["grid"], 1))
            painter.drawLine(QPointF(x, top), QPointF(x, top + plot_height))
            moment = start + (end - start) * ratio
            painter.setPen(colors["muted"])
            label = moment.strftime("%d.%m.%Y\n%H:%M")
            painter.drawText(
                QRectF(x - 48, top + plot_height + 5, 96, 34),
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                label,
            )

        for index, (kind, label) in enumerate(lanes):
            y = top + (index + 0.5) * lane_height
            painter.setPen(QPen(colors["grid"], 1))
            painter.drawLine(QPointF(left, y), QPointF(left + plot_width, y))
            painter.setPen(colors["text"])
            painter.drawText(
                QRectF(8, y - lane_height / 2, left - 18, lane_height),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                label,
            )

        replacement_times = [
            entry.occurred_at for entry in self._entries if entry.kind == "replacement"
        ]
        painter.setPen(QPen(colors["replacement"], 2, Qt.PenStyle.DashLine))
        for moment in replacement_times:
            x = x_for(moment)
            painter.drawLine(QPointF(x, top), QPointF(x, top + plot_height))

        for entry in self._entries:
            lane_key = (
                ("diagnostic", entry.title)
                if entry.kind == "diagnostic"
                else (entry.kind, {
                    "diagnostic_session": "Kurztest",
                    "replacement": "Tausch",
                    "repair": "Werkstatt",
                    "software": "Software",
                    "supplier": "Lieferant",
                }.get(entry.kind, entry.kind))
            )
            index = lane_index.get(lane_key)
            if index is None:
                continue
            x = x_for(entry.occurred_at)
            y = top + (index + 0.5) * lane_height

            if entry.kind == "diagnostic":
                painter.setPen(QPen(colors["dtc"], 1.5))
                painter.setBrush(colors["dtc_fill"])
                painter.drawEllipse(QPointF(x, y), 5.5, 5.5)
            elif entry.kind == "replacement":
                painter.setPen(QPen(colors["replacement"], 1.5))
                painter.setBrush(colors["replacement"])
                polygon = QPolygonF(
                    [
                        QPointF(x, y - 7),
                        QPointF(x + 7, y),
                        QPointF(x, y + 7),
                        QPointF(x - 7, y),
                    ]
                )
                painter.drawPolygon(polygon)
            elif entry.kind == "software":
                painter.setPen(QPen(colors["event"], 1.5))
                painter.setBrush(colors["event"])
                polygon = QPolygonF(
                    [
                        QPointF(x, y - 7),
                        QPointF(x + 7, y + 6),
                        QPointF(x - 7, y + 6),
                    ]
                )
                painter.drawPolygon(polygon)
            else:
                painter.setPen(QPen(colors["event"], 1.5))
                painter.setBrush(colors["event"])
                painter.drawRect(QRectF(x - 5, y - 5, 10, 10))
