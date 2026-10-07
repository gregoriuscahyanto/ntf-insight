"""Sidebar navigation widget."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QLabel,
    QPushButton,
    QVBoxLayout,
)


class NavigationPanel(QFrame):
    page_selected = Signal(str)

    ITEMS = (
        ("dashboard", "Overview"),
        ("vehicles", "Vehicles"),
        ("cases", "Cases"),
        ("dtcs", "DTC Explorer"),
        ("clusters", "Clusters"),
        ("suppliers", "Suppliers"),
        ("quality", "Data Quality"),
    )

    def __init__(self) -> None:
        super().__init__(objectName="Sidebar")
        self.setFixedWidth(220)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 22, 18, 22)
        layout.setSpacing(6)

        layout.addWidget(QLabel("NTF Insight", objectName="BrandTitle"))
        layout.addWidget(QLabel("Field Failure Analytics", objectName="BrandSubtitle"))
        layout.addSpacing(24)

        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons: dict[str, QPushButton] = {}

        for key, label in self.ITEMS:
            button = QPushButton(label, objectName="NavButton")
            button.setCheckable(True)
            button.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            button.clicked.connect(
                lambda _checked=False, page=key: self.page_selected.emit(page)
            )
            self.group.addButton(button)
            self.buttons[key] = button
            layout.addWidget(button)

        layout.addStretch(1)
        layout.addWidget(QLabel("Pre-alpha", objectName="BrandSubtitle"))

    def select_page(self, key: str) -> None:
        button = self.buttons.get(key)
        if button is None:
            return
        button.setChecked(True)
        self.page_selected.emit(key)
