"""Desktop application bootstrap."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from ntf_insight.app.logging_config import configure_logging
from ntf_insight.app.settings import AppPaths
from ntf_insight.app.styles import APP_STYLESHEET
from ntf_insight.app.windows.main_window import MainWindow


def main() -> int:
    """Start the NTF Insight desktop application."""
    paths = AppPaths.default()
    paths.ensure()
    configure_logging(paths.data_dir)

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("NTF Insight")
    app.setOrganizationName("NTF Insight")
    app.setStyle("Fusion")
    app.setStyleSheet(APP_STYLESHEET)

    window = MainWindow()
    window.show()

    return app.exec()


run = main
