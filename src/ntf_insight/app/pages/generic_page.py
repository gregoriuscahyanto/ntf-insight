"""Simple placeholder page for planned application areas."""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class GenericPage(QWidget):
    def __init__(self, title: str, description: str) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(10)
        layout.addWidget(QLabel(title, objectName="PageTitle"))

        subtitle = QLabel(description, objectName="PageSubtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)
        layout.addStretch(1)
