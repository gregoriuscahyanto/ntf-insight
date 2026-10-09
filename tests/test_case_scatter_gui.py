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


def test_scatter_is_synchronized_with_main_cluster_threshold_and_navigation(
    tmp_path, monkeypatch,
) -> None:
    from ntf_insight.app.windows.main_window import MainWindow

    monkeypatch.setenv("NTF_INSIGHT_DATA_DIR", str(tmp_path / "empty"))
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    cluster_page = window.pages["clusters"]
    source = cluster_page.case_cluster_panel
    scatter = cluster_page.case_scatter_panel

    before = {p.case_id: (p.x, p.y) for p in scatter.projection.points}
    source.threshold.setValue(0.95)
    assert scatter.result is source.result
    assert {p.case_id: (p.x, p.y) for p in scatter.projection.points} == before

    assert scatter.focus_case("DEMO-004")
    scatter.compare_button.click()
    assert cluster_page.tabs.currentWidget() is source
    assert source.focus.currentData() == "DEMO-004"

    cluster_page.tabs.setCurrentWidget(scatter)
    scatter.open_button.click()
    assert window.stack.currentWidget() is window.pages["cases"]
    assert window.pages["cases"].selector.currentData() == "DEMO-004"

    window.close()
    app.processEvents()
