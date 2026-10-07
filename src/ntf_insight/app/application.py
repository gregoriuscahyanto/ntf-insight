"""Desktop application bootstrap."""

from __future__ import annotations

import sys

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from ntf_insight.app.logging_config import configure_logging
from ntf_insight.app.settings import AppPaths
from ntf_insight.app.styles import stylesheet_for
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

    settings = QSettings()
    theme = str(settings.value("appearance/theme", "light"))
    if theme not in {"light", "dark"}:
        theme = "light"
    app.setStyleSheet(stylesheet_for(theme))

    window = MainWindow()
    window.navigation.set_theme(theme)

    def apply_theme(selected: str) -> None:
        settings.setValue("appearance/theme", selected)
        app.setStyleSheet(stylesheet_for(selected))

    window.navigation.theme_selected.connect(apply_theme)
    window.show()

    return app.exec()


run = main
