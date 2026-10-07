"""Sidebar navigation widget."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFrame,
    QLabel,
    QPushButton,
    QVBoxLayout,
)


class NavigationPanel(QFrame):
    page_selected = Signal(str)
    theme_selected = Signal(str)

    ITEMS = (
        ("dashboard", "Übersicht"),
        ("sources", "Datenquellen"),
        ("vehicles", "Fahrzeuge"),
        ("cases", "Fälle"),
        ("dtcs", "DTC-Explorer"),
        ("clusters", "Cluster"),
        ("suppliers", "Lieferanten"),
        ("quality", "Datenqualität"),
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
        layout.addWidget(QLabel("Darstellung", objectName="BrandSubtitle"))
        self.theme_combo = QComboBox()
        self.theme_combo.addItem("Hell", "light")
        self.theme_combo.addItem("Dunkel", "dark")
        self.theme_combo.currentIndexChanged.connect(self._emit_theme)
        layout.addWidget(self.theme_combo)
        layout.addSpacing(8)
        self.font_status = QLabel("Schrift: System", objectName="BrandSubtitle")
        self.font_status.setWordWrap(True)
        layout.addWidget(self.font_status)
        layout.addWidget(QLabel("Pre-alpha", objectName="BrandSubtitle"))

    def _emit_theme(self) -> None:
        theme = self.theme_combo.currentData()
        if theme:
            self.theme_selected.emit(str(theme))

    def set_theme(self, theme: str) -> None:
        index = self.theme_combo.findData(theme)
        if index >= 0:
            self.theme_combo.setCurrentIndex(index)

    def set_font_status(self, body_family: str, heading_family: str) -> None:
        if body_family == heading_family:
            label = body_family
        else:
            label = f"{body_family} / {heading_family}"
        self.font_status.setText(f"Schrift: {label}")
        self.font_status.setToolTip(
            f"UI/Text: {body_family}\nÜberschriften: {heading_family}"
        )

    def select_page(self, key: str) -> None:
        button = self.buttons.get(key)
        if button is None:
            return
        button.setChecked(True)
        self.page_selected.emit(key)
