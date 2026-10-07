"""Desktop application bootstrap."""

from __future__ import annotations

import logging
import sys

from PySide6.QtCore import QSettings
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from ntf_insight.app.fonts import FontSelection, resolve_fonts
from ntf_insight.app.logging_config import configure_logging
from ntf_insight.app.settings import AppPaths
from ntf_insight.app.styles import stylesheet_for
from ntf_insight.app.windows.main_window import MainWindow

LOGGER = logging.getLogger("ntf_insight.app")


def _apply_appearance(app: QApplication, theme: str, fonts: FontSelection) -> None:
    app.setFont(QFont(fonts.body_family, 10))
    app.setStyleSheet(
        stylesheet_for(
            theme,
            body_font=fonts.body_family,
            heading_font=fonts.heading_family,
        )
    )


def main() -> int:
    """Start the NTF Insight desktop application."""
    paths = AppPaths.default()
    paths.ensure()
    configure_logging(paths.data_dir)

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("NTF Insight")
    app.setOrganizationName("NTF Insight")
    app.setStyle("Fusion")

    fonts = resolve_fonts()
    LOGGER.info(
        "Font selection: body=%s corporate=%s, heading=%s corporate=%s, loaded=%s",
        fonts.body_family,
        fonts.corporate_body,
        fonts.heading_family,
        fonts.corporate_heading,
        ", ".join(fonts.loaded_font_files) or "system fonts only",
    )

    settings = QSettings()
    theme = str(settings.value("appearance/theme", "light"))
    if theme not in {"light", "dark"}:
        theme = "light"
    _apply_appearance(app, theme, fonts)

    window = MainWindow()
    window.navigation.set_theme(theme)
    window.navigation.set_font_status(fonts.body_family, fonts.heading_family)

    def apply_theme(selected: str) -> None:
        settings.setValue("appearance/theme", selected)
        _apply_appearance(app, selected, fonts)

    window.navigation.theme_selected.connect(apply_theme)
    window.show()

    return app.exec()


run = main
