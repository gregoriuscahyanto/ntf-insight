"""Desktop application bootstrap."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from ntf_insight.app.styles import APP_STYLESHEET
from ntf_insight.app.windows.main_window import MainWindow


def main() -> int:
    """Start the NTF Insight desktop application."""
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("NTF Insight")
    app.setOrganizationName("NTF Insight")
    app.setStyle("Fusion")
    app.setStyleSheet(APP_STYLESHEET)

    window = MainWindow()
    window.show()

    return app.exec()


run = main
