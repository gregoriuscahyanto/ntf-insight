"""Small dashboard metric card."""

from __future__ import annotations

from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout


class StatusCard(QFrame):
    def __init__(self, title: str, value: str, subtitle: str) -> None:
        super().__init__(objectName="Card")
        self.setMinimumHeight(120)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(5)
        layout.addWidget(QLabel(title, objectName="CardTitle"))
        layout.addWidget(QLabel(value, objectName="CardValue"))
        layout.addWidget(QLabel(subtitle, objectName="CardSubtitle"))
        layout.addStretch(1)
