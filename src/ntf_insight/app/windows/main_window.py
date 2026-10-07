"""Main desktop window."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QMainWindow, QStackedWidget, QWidget

from ntf_insight.app.bootstrap import load_application_data
from ntf_insight.app.pages.case_page import CasePage
from ntf_insight.app.pages.dashboard_page import DashboardPage
from ntf_insight.app.pages.data_quality_page import DataQualityPage
from ntf_insight.app.pages.dtc_page import DTCExplorerPage
from ntf_insight.app.pages.similarity_page import SimilarityPage
from ntf_insight.app.pages.sources_page import SourcesPage
from ntf_insight.app.pages.supplier_page import SupplierPage
from ntf_insight.app.widgets.navigation import NavigationPanel


class MainWindow(QMainWindow):
    """Top-level NTF Insight desktop window."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("NTF Insight")
        self.resize(1320, 820)
        self.setMinimumSize(1080, 700)

        self.application_data = load_application_data()
        self.repository = self.application_data.cases
        self.reference_repository = self.application_data.references

        root = QWidget(objectName="AppRoot")
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.navigation = NavigationPanel()
        self.stack = QStackedWidget()

        self.pages = {
            "dashboard": DashboardPage(self.repository, self.application_data.mode),
            "sources": SourcesPage(
                self.repository,
                self.reference_repository,
                self.application_data.mode,
                str(self.application_data.paths.data_dir),
                str(self.application_data.paths.raw_dir),
                str(self.application_data.paths.database_path),
            ),
            "cases": CasePage(self.repository, self.reference_repository),
            "dtcs": DTCExplorerPage(self.repository, self.reference_repository),
            "clusters": SimilarityPage(self.repository),
            "suppliers": SupplierPage(self.repository),
            "quality": DataQualityPage(self.repository, self.reference_repository),
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
