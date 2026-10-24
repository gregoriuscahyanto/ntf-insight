"""Nicht-blockierender Ladeindikator für Qt-Seitenwechsel."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class LoadingOverlay(QWidget):
    """Abgedunkeltes Overlay mit animiertem Kreis und kurzem Status."""
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("WorkflowLoadingOverlay")
        self.setStyleSheet(
            "QWidget#WorkflowLoadingOverlay {background-color: rgba(13,23,36,178);}"
            "QLabel {color: white; background: transparent; font-weight: 600;}"
        )
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setVisible(False)
        self.angle = 0
        self.timer = QTimer(self)
        self.timer.setInterval(70)
        self.timer.timeout.connect(self._tick)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addStretch()
        self.title = QLabel("Lade Daten …", self)
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addSpacing(76)
        layout.addWidget(self.title)
        layout.addStretch()

    def _tick(self) -> None:
        self.angle = (self.angle + 30) % 360
        self.update()

    def start(self, title: str = "Lade Daten …") -> None:
        self.title.setText(title)
        self.setGeometry(self.parentWidget().rect())
        self.raise_()
        self.show()
        self.timer.start()
        self.update()

    def stop(self) -> None:
        self.timer.stop()
        self.hide()

    def paintEvent(self, _event) -> None:  # noqa: N802
        super().paintEvent(_event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        center = self.rect().center()
        y = center.y() - 38
        for position in range(12):
            painter.save()
            painter.translate(center.x(), y)
            painter.rotate((position * 30 + self.angle) % 360)
            color = QColor(255, 255, 255, 40 + position * 17)
            painter.setPen(QPen(color, 4, Qt.PenStyle.SolidLine,
                                Qt.PenCapStyle.RoundCap))
            painter.drawLine(0, -19, 0, -31)
            painter.restore()
