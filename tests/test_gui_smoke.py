import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from ntf_insight.app.windows.main_window import MainWindow


def test_main_window_can_be_constructed() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()

    assert "dashboard" in window.pages
    assert "vehicles" in window.pages
    assert "cases" in window.pages
    assert window.repository.list_cases()

    window.close()
    app.processEvents()
