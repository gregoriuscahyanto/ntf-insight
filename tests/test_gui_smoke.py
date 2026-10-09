import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from ntf_insight.app.windows.main_window import MainWindow


def test_main_window_can_be_constructed(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("NTF_INSIGHT_DATA_DIR", str(tmp_path / "app-data"))
    app = QApplication.instance() or QApplication([])
    window = MainWindow()

    assert "dashboard" in window.pages
    assert "sources" in window.pages
    assert "cases" in window.pages
    assert hasattr(window.pages["cases"], "case_table")
    assert hasattr(window.pages["cases"], "time_plot")
    assert "dtcs" in window.pages
    assert "clusters" not in window.pages
    assert "clusters" not in window.navigation.buttons
    assert hasattr(window.pages["cases"], "scatter_panel")
    assert window.pages["cases"].scatter_panel.plot is not None
    assert "suppliers" in window.pages
    assert "quality" in window.pages
    assert window.repository.list_cases()
    assert window.application_data.mode == "demo"

    window.close()
    app.processEvents()
