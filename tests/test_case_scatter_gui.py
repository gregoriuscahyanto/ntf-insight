"""Offscreen GUI checks: scatter is only a view of existing case clusters."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from ntf_insight.analysis.case_clustering import cluster_diagnostic_cases
from ntf_insight.app.widgets.case_scatter_plot import CaseScatterPanel
from ntf_insight.demo.synthetic_cases import build_demo_cases


def test_scatter_displays_original_cluster_membership_and_clicks_real_case() -> None:
    app = QApplication.instance() or QApplication([])
    cases = build_demo_cases()
    clusters = cluster_diagnostic_cases(cases)
    panel = CaseScatterPanel(cases, clusters)
    panel.resize(1050, 720)
    panel.show()
    app.processEvents()

    assert len(panel.projection.points) == len(cases)
    assert panel.result.clusters == clusters.clusters
    assert set(panel.plot.items_by_case) == {case.case_id for case in cases}

    target = "DEMO-003"
    selected = []
    panel.case_focused.connect(selected.append)
    item = panel.plot.items_by_case[target]
    click_pos = panel.plot.mapFromScene(item.sceneBoundingRect().center())
    QTest.mouseClick(panel.plot.viewport(), Qt.MouseButton.LeftButton, pos=click_pos)
    app.processEvents()

    assert selected == [target]
    assert panel.focus_id == target
    assert "Fokus: DEMO-003" in panel.detail.text()

    requested = []
    panel.case_requested.connect(requested.append)
    panel.open_button.click()
    assert requested == [target]
    panel.close()
    app.processEvents()


def test_scatter_empty_data_has_no_fabricated_points() -> None:
    app = QApplication.instance() or QApplication([])
    panel = CaseScatterPanel([], None)
    assert panel.plot.items_by_case == {}
    assert not panel.open_button.isEnabled()
    assert "0 projizierte" in panel.summary.text()
    panel.close()
    app.processEvents()


def test_scatter_is_part_of_case_workspace_and_all_tabs_sync(
    tmp_path, monkeypatch,
) -> None:
    from ntf_insight.app.windows.main_window import MainWindow

    monkeypatch.setenv("NTF_INSIGHT_DATA_DIR", str(tmp_path / "empty"))
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    cases = window.pages["cases"]
    scatter = cases.scatter_panel

    assert "clusters" not in window.pages
    assert "clusters" not in window.navigation.buttons
    assert cases.detail_tabs.widget(0) is scatter
    assert cases.detail_tabs.widget(1) is cases.analysis_tab
    assert cases.detail_tabs.widget(2) is cases.quicktest_browser

    before = {p.case_id: (p.x, p.y) for p in scatter.projection.points}
    scatter.threshold.setValue(0.95)
    assert scatter.result.threshold == 0.95
    assert {p.case_id: (p.x, p.y) for p in scatter.projection.points} == before

    assert scatter.focus_case("DEMO-004")
    scatter.open_button.click()
    assert cases.detail_tabs.currentWidget() is cases.analysis_tab
    assert cases.selector.currentData() == "DEMO-004"

    cases.find_similar_button.click()
    assert cases.detail_tabs.currentWidget() is scatter
    assert scatter.focus_id == "DEMO-004"

    scatter.quicktests_button.click()
    assert cases.detail_tabs.currentWidget() is cases.quicktest_browser
    assert cases.quicktest_browser.fin_selector.currentText() == "DEMO-VIN-000004"

    # Changing the FIN in QuickTests also changes the active case.
    cases.quicktest_browser.select_fin("DEMO-VIN-000003")
    assert cases.selector.currentData() == "DEMO-003"
    assert scatter.focus_id == "DEMO-003"
    assert cases.detail_tabs.currentWidget() is cases.quicktest_browser

    window.close()
    app.processEvents()


def test_scatter_numeric_tables_explain_plot_and_pairwise_score() -> None:
    app = QApplication.instance() or QApplication([])
    cases = build_demo_cases()
    panel = CaseScatterPanel(cases, cluster_diagnostic_cases(cases))

    assert panel.projection.feature_count > 0
    assert panel.projection.components == 2
    assert len(panel.projection.explained_variance_ratio) == 2
    assert panel.axis_model.rowCount() > 0
    assert panel.feature_model.rowCount() == 6
    assert panel.coordinate_model.rowCount() == len(cases)
    assert panel.neighbor_model.rowCount() == len(cases) - 1
    assert panel.breakdown_model.rowCount() == 6
    assert "Matrixspalten" not in panel.method_note.text() or panel.projection.feature_count
    assert "TruncatedSVD" in panel.method_note.text()
    assert "Jaccard-Score" in panel.comparison_note.text()
    assert "Cluster" in panel.detail.text()

    panel.focus_case("DEMO-002")
    assert panel.coordinate_model.rows[1][0] == "DEMO-002"
    assert "Fokus: DEMO-002" in panel.detail.text()

    # Selecting a point by its coordinate table updates the exact pair report.
    row = next(i for i, data in enumerate(panel.coordinate_model.rows) if data[0] == "DEMO-006")
    panel.coordinate_table.setCurrentIndex(panel.coordinate_model.index(row, 0))
    assert panel.focus_id == "DEMO-006"
    assert panel.neighbor_model.rowCount() == len(cases) - 1
    assert "Fokus: DEMO-006" in panel.detail.text()
    panel.close()
    app.processEvents()
