"""FIN/case diagnostic plot with selectable date or real odometer x-axis.

Only DTC observations are affected by the ECU/DTC filter. No mileage is
inferred from surrounding observations; records without mileage are shown in a
separate "km unbekannt" region rather than at a fabricated position.
"""
from __future__ import annotations

from datetime import timedelta

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QApplication, QSizePolicy, QWidget

from ntf_insight.analysis.timeline import TimelineEntry


LANE_LABELS = {
    "diagnostic_session": "Kurztest",
    "ecu_state": "Steuergerät HW-/SW-Stand",
    "replacement": "QEC / dokumentierter Tausch",
    "replacement_candidate": "AutoExport-Reparaturdatum",
    "repair": "Werkstatt",
    "software": "Softwareänderung",
    "supplier": "Lieferantenbefund",
}


class EventTimePlot(QWidget):
    """An engineering timeline where both swap-date sources stay distinct."""

    def __init__(self) -> None:
        super().__init__(objectName="EventTimePlot")
        self._entries: list[TimelineEntry] = []
        self._filter_text = ""
        self._axis_mode = "date"
        self.setMinimumHeight(300)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )

    @property
    def axis_mode(self) -> str:
        return self._axis_mode

    def set_axis_mode(self, mode: str) -> None:
        if mode not in {"date", "mileage"}:
            raise ValueError("Achsenmodus muss 'date' oder 'mileage' sein.")
        self._axis_mode = mode
        self._update_height()
        self.update()

    def set_entries(self, entries: list[TimelineEntry]) -> None:
        self._entries = sorted(entries, key=lambda item: item.occurred_at)
        self._update_height()
        self.update()

    def set_filter_text(self, text: str) -> None:
        self._filter_text = text.strip().casefold()
        self._update_height()
        self.update()

    def _visible_entries(self) -> list[TimelineEntry]:
        """Filter *only DTCs*. Keep session, ECU state, repair and supplier visible."""
        if not self._filter_text:
            return list(self._entries)
        return [
            entry for entry in self._entries
            if entry.kind != "diagnostic"
            or self._filter_text in (
                f"{entry.title} {entry.detail or ''}"
            ).casefold()
        ]

    def _update_height(self) -> None:
        lanes = self._lanes(self._visible_entries())
        self.setMinimumHeight(max(300, min(2500, 120 + len(lanes) * 24)))

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
                "muted": QColor("#d1d5db"),
                "grid": QColor("#4b5563"),
                "dtc": QColor("#f3f4f6"),
                "dtc_fill": QColor("#374151"),
                "qec": QColor("#ffcf6a"),
                "auto": QColor("#62d1e5"),
                "event": QColor("#9ca3af"),
            }
        return {
            "bg": QColor("#ffffff"),
            "text": QColor("#111827"),
            "muted": QColor("#4b5563"),
            "grid": QColor("#d1d5db"),
            "dtc": QColor("#111827"),
            "dtc_fill": QColor("#e5e7eb"),
            "qec": QColor("#986800"),
            "auto": QColor("#126782"),
            "event": QColor("#6b7280"),
        }

    def _lanes(self, entries: list[TimelineEntry] | None = None) -> list[tuple[str, str]]:
        entries = self._entries if entries is None else entries
        dtc_titles = sorted({
            entry.title for entry in entries if entry.kind == "diagnostic"
        })
        lanes = [("diagnostic", title) for title in dtc_titles]
        for kind, label in LANE_LABELS.items():
            if any(entry.kind == kind for entry in entries):
                lanes.append((kind, label))
        return lanes

    def _odometer_bounds(
        self, entries: list[TimelineEntry] | None = None
    ) -> tuple[int, int] | None:
        values = [
            entry.mileage_km for entry in (
                self._visible_entries() if entries is None else entries
            )
            if entry.mileage_km is not None
        ]
        if not values:
            return None
        low, high = min(values), max(values)
        if low == high:
            return max(0, low - 100), high + 100
        return low, high

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        colors = self._colors()
        painter.fillRect(self.rect(), colors["bg"])
        entries = self._visible_entries()
        if not entries:
            painter.setPen(colors["muted"])
            painter.drawText(
                self.rect(), Qt.AlignmentFlag.AlignCenter,
                "Keine Diagnoseereignisse vorhanden.",
            )
            return

        lanes = self._lanes(entries)
        if not lanes:
            return

        missing_km = (
            self._axis_mode == "mileage"
            and any(entry.mileage_km is None for entry in entries)
        )
        left, right, top, bottom = 215.0, 32.0, 59.0, 50.0
        if missing_km:
            right += 115.0
        plot_width = max(80.0, self.width() - left - right)
        plot_height = max(80.0, self.height() - top - bottom)
        lane_height = plot_height / len(lanes)
        lane_index = {lane: index for index, lane in enumerate(lanes)}
        plot_end = left + plot_width
        missing_x = plot_end + 64.0 if missing_km else None

        dates = [entry.occurred_at for entry in entries]
        start, end = min(dates), max(dates)
        if start == end:
            start -= timedelta(hours=12)
            end += timedelta(hours=12)
        date_span = max((end - start).total_seconds(), 1)
        km_bounds = self._odometer_bounds(entries) if self._axis_mode == "mileage" else None

        def position(entry: TimelineEntry) -> float:
            if self._axis_mode == "date":
                return left + (
                    (entry.occurred_at - start).total_seconds() / date_span
                ) * plot_width
            if entry.mileage_km is None:
                assert missing_x is not None
                return missing_x
            if km_bounds is None:
                return left + plot_width / 2
            lower, upper = km_bounds
            return left + (
                (entry.mileage_km - lower) / max(upper - lower, 1)
            ) * plot_width

        painter.setFont(QFont(self.font().family(), 8))
        painter.setPen(colors["text"])
        painter.drawText(
            QRectF(left, 4, max(plot_width, 90), 18),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            "X-Achse: Datum / Uhrzeit"
            if self._axis_mode == "date" else
            "X-Achse: Kilometerstand (aus Quellen; fehlende km separat)",
        )

        # Every diagnostic point is rendered once; the two date sources are
        # independently marked even if their x values coincide.
        for kind, color, style, description in (
            ("replacement", colors["qec"], Qt.PenStyle.DashLine, "Tauschanker (QEC/manuell)"),
            ("replacement_candidate", colors["auto"], Qt.PenStyle.DotLine, "AutoExport-Reparaturkandidat"),
        ):
            if any(entry.kind == kind for entry in entries):
                painter.setPen(QPen(color, 2, style))
                painter.drawLine(
                    QPointF(left, 31 if kind == "replacement" else 44),
                    QPointF(left + 22, 31 if kind == "replacement" else 44),
                )
                painter.setPen(colors["muted"])
                painter.drawText(
                    QRectF(left + 26, 21 if kind == "replacement" else 34,
                           min(450.0, plot_width - 30), 20),
                    Qt.AlignmentFlag.AlignVCenter, description,
                )

        for tick in range(5):
            ratio = tick / 4
            x = left + ratio * plot_width
            painter.setPen(QPen(colors["grid"], 1))
            painter.drawLine(QPointF(x, top), QPointF(x, top + plot_height))
            if self._axis_mode == "date":
                moment = start + (end - start) * ratio
                label = moment.strftime("%d.%m.%Y\n%H:%M")
            elif km_bounds is not None:
                low, high = km_bounds
                label = f"{low + (high - low) * ratio:,.0f} km"
            else:
                label = "—"
            painter.setPen(colors["muted"])
            painter.drawText(
                QRectF(x - 55, top + plot_height + 5, 110, 36),
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                label,
            )
        if missing_x is not None:
            painter.setPen(QPen(colors["grid"], 1, Qt.PenStyle.DotLine))
            painter.drawLine(
                QPointF(missing_x, top), QPointF(missing_x, top + plot_height)
            )
            painter.setPen(colors["muted"])
            painter.drawText(
                QRectF(missing_x - 53, top + plot_height + 5, 106, 34),
                Qt.AlignmentFlag.AlignHCenter, "km unbekannt",
            )

        for index, (kind, label) in enumerate(lanes):
            y = top + (index + 0.5) * lane_height
            painter.setPen(QPen(colors["grid"], 1))
            painter.drawLine(QPointF(left, y), QPointF(plot_end, y))
            painter.setPen(colors["text"])
            painter.drawText(
                QRectF(6, y - lane_height / 2, left - 17, lane_height),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                label,
            )

        qec_positions = [
            position(entry) for entry in entries if entry.kind == "replacement"
        ]
        for entry in entries:
            if entry.kind not in {"replacement", "replacement_candidate"}:
                continue
            # A slight visual offset makes coincident source lines distinguishable.
            x = position(entry)
            if (
                entry.kind == "replacement_candidate"
                and any(abs(x - other) < 0.5 for other in qec_positions)
            ):
                x += 3
            color = (
                colors["qec"] if entry.kind == "replacement" else colors["auto"]
            )
            pen_style = (
                Qt.PenStyle.DashLine if entry.kind == "replacement"
                else Qt.PenStyle.DotLine
            )
            painter.setPen(QPen(color, 2, pen_style))
            painter.drawLine(
                QPointF(x, top), QPointF(x, top + plot_height)
            )

        for entry in entries:
            lane_key = (
                ("diagnostic", entry.title)
                if entry.kind == "diagnostic"
                else (entry.kind, LANE_LABELS.get(entry.kind, entry.kind))
            )
            index = lane_index.get(lane_key)
            if index is None:
                continue
            x = position(entry)
            if (
                entry.kind == "replacement_candidate"
                and any(abs(x - other) < 0.5 for other in qec_positions)
            ):
                x += 3
            y = top + (index + 0.5) * lane_height
            if entry.kind == "diagnostic":
                painter.setPen(QPen(colors["dtc"], 1.5))
                painter.setBrush(colors["dtc_fill"])
                painter.drawEllipse(QPointF(x, y), 5.2, 5.2)
            elif entry.kind in {"replacement", "replacement_candidate"}:
                color = (
                    colors["qec"] if entry.kind == "replacement" else colors["auto"]
                )
                painter.setPen(QPen(color, 1.6))
                painter.setBrush(color)
                painter.drawPolygon(QPolygonF([
                    QPointF(x, y - 7), QPointF(x + 7, y),
                    QPointF(x, y + 7), QPointF(x - 7, y),
                ]))
            elif entry.kind == "software":
                painter.setPen(QPen(colors["event"], 1.5))
                painter.setBrush(colors["event"])
                painter.drawPolygon(QPolygonF([
                    QPointF(x, y - 6), QPointF(x + 7, y + 6),
                    QPointF(x - 7, y + 6),
                ]))
            else:
                painter.setPen(QPen(colors["event"], 1.5))
                painter.setBrush(colors["event"])
                painter.drawRect(QRectF(x - 4.5, y - 4.5, 9, 9))
