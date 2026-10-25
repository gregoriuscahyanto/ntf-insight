"""Interaktive Mercedes-Benz-orientierte Balkenansicht für LLM-Cluster.

Bewusst nur Qt Widgets / QPainter: keine Online-Dienste, kein Javascript,
keine zusätzliche Chart-Abhängigkeit und keine erneute KI-Berechnung.
"""
from __future__ import annotations

from PySide6.QtCore import QSortFilterProxyModel, Qt, QRectF, QSize, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget


_UNASSIGNED = "__nicht_gruppiert__"


class LlmClusterBarChart(QWidget):
    """Interaktive, tastaturbedienbare Größenverteilung mit deutscher Legende."""

    selected = Signal(str)
    _TOP = 42
    _ROW = 32

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.title = title
        self.items: list[tuple[str, str, int]] = []
        self._selected = ""
        self.setObjectName("LLMClusterBarChart")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(94)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setAccessibleName(title)
        self.setToolTip("Balken anklicken, um die Fallliste zu filtern")

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(480, self._TOP + self._ROW * max(1, len(self.items)) + 12)

    def set_items(self, items: list[tuple[str, str, int]]) -> None:
        self.items = [
            (str(key), str(label), int(count))
            for key, label, count in items if int(count) > 0
        ]
        self.setFixedHeight(self.sizeHint().height())
        self.setAccessibleDescription(
            "; ".join(f"{label}: {count} Fälle" for _, label, count in self.items)
            or "Keine auswertbaren Cluster vorhanden"
        )
        self.update()

    def set_selected(self, key: str) -> None:
        if self._selected != key:
            self._selected = key
            self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width = self.width()
        canvas = self.palette().base().color()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(canvas)
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 8, 8)
        text = self.palette().text().color()
        painter.setPen(text)
        font = painter.font()
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(
            QRectF(13, 6, width - 22, 28),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            self.title,
        )
        font.setBold(False)
        painter.setFont(font)
        if not self.items:
            painter.setPen(self.palette().placeholderText().color())
            painter.drawText(
                QRectF(13, self._TOP, width - 26, 30),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                "Noch keine Ergebnisse vorhanden",
            )
            return
        left = max(105, min(220, round(width * .39)))
        right_pad = 64
        bar_x = left + 22
        bar_width = max(25, width - bar_x - right_pad)
        max_count = max(count for _, _, count in self.items)
        fm = painter.fontMetrics()
        for index, (key, label, count) in enumerate(self.items):
            y = self._TOP + index * self._ROW
            active = key == self._selected
            if active:
                selected_bg = QColor("#00ADEF")
                selected_bg.setAlpha(26)
                painter.setBrush(selected_bg)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawRoundedRect(
                    QRectF(5, y - 2, width - 10, self._ROW - 3), 5, 5,
                )
            painter.setPen(text)
            painter.drawText(
                QRectF(13, y, left - 17, 25),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                fm.elidedText(
                    label, Qt.TextElideMode.ElideRight, left - 22,
                ),
            )
            top = y + 7
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#DDE4E9") if canvas.lightness() > 120
                             else QColor("#394550"))
            painter.drawRoundedRect(
                QRectF(bar_x, top, bar_width, 13), 6, 6,
            )
            painter.setBrush(QColor("#00ADEF") if active
                             else QColor("#1F7990"))
            painter.drawRoundedRect(
                QRectF(bar_x, top, max(2, bar_width * count / max_count), 13),
                6, 6,
            )
            painter.setPen(text)
            painter.drawText(
                QRectF(bar_x + bar_width + 9, y, right_pad - 12, 26),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                str(count),
            )
        painter.setPen(QPen(QColor("#9CA9B4"), 1))

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            row = int((event.position().y() - self._TOP) // self._ROW)
            if 0 <= row < len(self.items):
                key = self.items[row][0]
                self.set_selected(key)
                self.selected.emit(key)
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        row = int((event.position().y() - self._TOP) // self._ROW)
        if 0 <= row < len(self.items):
            _key, label, count = self.items[row]
            self.setToolTip(f"{label}: {count} Fälle · anklicken zum Filtern")
        else:
            self.setToolTip("Balken anklicken, um die Fallliste zu filtern")
        super().mouseMoveEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if self.items and event.key() in (
            Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space,
        ):
            available = [key for key, _, _count in self.items]
            key = self._selected if self._selected in available else available[0]
            self.set_selected(key)
            self.selected.emit(key)
            event.accept()
            return
        if self.items and event.key() in (Qt.Key.Key_Down, Qt.Key.Key_Up):
            available = [key for key, _, _count in self.items]
            index = available.index(self._selected) if self._selected in available else -1
            step = 1 if event.key() == Qt.Key.Key_Down else -1
            key = available[(index + step) % len(available)]
            self.set_selected(key)
            self.selected.emit(key)
            event.accept()
            return
        super().keyPressEvent(event)


class LlmCaseFilterProxy(QSortFilterProxyModel):
    """Nur Sichtbarkeitsfilter; verändert niemals Ergebnisdaten/Cluster."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.cluster_id = ""
        self.cause = ""
        self.symptom = ""
        self.proof = ""
        self.query = ""
        self.label_index: list[tuple[tuple[str, ...], tuple[str, ...]]] = []
        self.setSortCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.setDynamicSortFilter(True)

    def set_label_index(
        self, labels: list[tuple[tuple[str, ...], tuple[str, ...]]],
    ) -> None:
        self.label_index = labels
        self.invalidateFilter()

    def update_filter(
        self, *, cluster_id: str, cause: str, query: str,
        symptom: str = "", proof: str = "",
    ) -> None:
        self.cluster_id = cluster_id
        self.cause = cause
        self.symptom = symptom
        self.proof = proof
        self.query = query.strip().casefold()
        self.invalidateFilter()

    def filterAcceptsRow(self, row: int, parent) -> bool:  # noqa: N802
        model = self.sourceModel()
        if model is None:
            return False

        def col(index: int) -> str:
            return str(model.index(row, index, parent).data(
                Qt.ItemDataRole.DisplayRole
            ) or "")

        if self.cluster_id and (
            (self.cluster_id == _UNASSIGNED and col(2) != "Nicht gruppiert")
            or (self.cluster_id != _UNASSIGNED and col(2) != self.cluster_id)
        ):
            return False
        if self.cause and col(4) != self.cause:
            return False
        symptoms, proofs = (
            self.label_index[row]
            if 0 <= row < len(self.label_index)
            else ((), ())
        )
        if self.symptom and self.symptom not in symptoms:
            return False
        if self.proof and self.proof not in proofs:
            return False
        if not self.query:
            return True
        values = " ".join(
            col(column) for column in range(model.columnCount())
        ).casefold()
        return all(term in values for term in self.query.split())
