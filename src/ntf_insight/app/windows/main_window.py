"""Main desktop window."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QMainWindow, QStackedWidget, QWidget

from ntf_insight.app.pages.dashboard_page import DashboardPage
from ntf_insight.app.pages.generic_page import GenericPage
from ntf_insight.app.pages.vehicles_page import VehiclesPage
from ntf_insight.app.widgets.navigation import NavigationPanel


class MainWindow(QMainWindow):
    """Top-level NTF Insight desktop window."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("NTF Insight")
        self.resize(1280, 800)
        self.setMinimumSize(1040, 680)

        root = QWidget(objectName="AppRoot")
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.navigation = NavigationPanel()
        self.stack = QStackedWidget()

        self.pages = {
            "dashboard": DashboardPage(),
            "vehicles": VehiclesPage(),
            "cases": GenericPage("Cases", "Case-level NTF analysis and evidence will live here."),
            "dtcs": GenericPage("DTC Explorer", "Explore DTCs across ECUs, vehicles and time."),
            "clusters": GenericPage("Clusters", "Similarity analysis and NTF clusters will live here."),
            "suppliers": GenericPage("Suppliers", "Supplier and population analytics will live here."),
            "quality": GenericPage("Data Quality", "Missing, contradictory and incomplete source data will be tracked here."),
        }

        for page in self.pages.values():
            self.stack.addWidget(page)

        layout.addWidget(self.navigation)
        layout.addWidget(self.stack, 1)
        self.setCentralWidget(root)

        self.navigation.page_selected.connect(self.show_page)
        self.navigation.select_page("dashboard")

    def show_page(self, key: str) -> None:
        page = self.pages.get(key)
        if page is None:
            return
        self.stack.setCurrentWidget(page)
        self.stack.setFocus(Qt.FocusReason.OtherFocusReason)
