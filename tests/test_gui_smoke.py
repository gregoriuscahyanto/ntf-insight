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
    assert window.pages["sources"].portable_backup_panel is not None
    assert window.pages["sources"].portable_backup_panel.export_button.isEnabled()
    assert window.pages["sources"].portable_backup_panel.restore_button.isEnabled()
    assert "quicktest_download" not in window.pages
    assert "quicktest_download" not in window.navigation.buttons
    assert "cases" in window.pages
    assert hasattr(window.pages["cases"], "case_table")
    assert hasattr(window.pages["cases"], "quicktest_download_all_button")
    assert hasattr(window.pages["cases"], "quicktest_download_selected_button")
    assert not window.pages["cases"].quicktest_download_selected_button.isEnabled()
    assert hasattr(window.pages["cases"], "time_plot")
    assert "dtcs" in window.pages
    assert "clusters" not in window.pages
    assert "clusters" not in window.navigation.buttons
    assert hasattr(window.pages["cases"], "cluster_workspace")
    assert window.pages["cases"].cluster_workspace.plot is not None
    assert window.pages["cases"].detail_tabs.tabText(0) == "Clusteranalyse"
    assert window.pages["cases"].detail_tabs.count() == 5
    assert window.pages["cases"].detail_tabs.tabText(3) == "QuickTest-Gesamtauswertung"
    assert window.pages["cases"].detail_tabs.tabText(4) == "ECU · SW-Übersicht"
    assert window.pages["cases"].detail_tabs.tabText(1) == "FIN / Fallanalyse"
    assert window.pages["cases"].cluster_workspace is (
        window.pages["cases"].autoexport_fin_workspace
    )
    cluster = window.pages["cases"].cluster_workspace
    assert cluster.method_combo.currentData() == "leaf"
    assert cluster.plot is not None
    assert "suppliers" in window.pages
    assert "quality" in window.pages
    assert window.repository.list_cases()
    assert window.application_data.mode == "demo"

    window.close()
    app.processEvents()
