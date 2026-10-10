"""Offscreen GUI checks: scatter is only a view of existing case clusters."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QGraphicsLineItem

from ntf_insight.analysis.case_clustering import cluster_diagnostic_cases
from ntf_insight.app.widgets.case_scatter_plot import (
    UNASSIGNED,
    CaseScatterPanel,
    color_for_cluster,
)
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
    assert "0 projiziert" in panel.summary.text()
    panel.close()
    app.processEvents()


def test_cluster_workspace_replaces_scatter_tab_and_synchronizes_case_selection(
    tmp_path, monkeypatch,
) -> None:
    from ntf_insight.app.windows.main_window import MainWindow

    monkeypatch.setenv("NTF_INSIGHT_DATA_DIR", str(tmp_path / "empty"))
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    cases = window.pages["cases"]
    cluster = cases.cluster_workspace

    assert "clusters" not in window.pages
    assert "clusters" not in window.navigation.buttons
    assert cases.detail_tabs.widget(0) is cluster
    assert cases.detail_tabs.tabText(0) == "Clusteranalyse"
    assert cases.detail_tabs.widget(1) is cases.analysis_tab
    assert cases.detail_tabs.widget(2) is cases.quicktest_browser
    assert cases.detail_tabs.count() == 3
    assert cluster is cases.autoexport_fin_workspace
    assert cluster.plot is not None
    assert cluster.start_button.text() == "Clusteranalyse starten"

    assert cluster.focus_case("DEMO-004")
    assert cluster.fin_search.text() == "DEMO-VIN-000004"
    cluster.case_requested.emit("DEMO-004")
    assert cases.detail_tabs.currentWidget() is cases.analysis_tab
    assert cases.selector.currentData() == "DEMO-004"

    cases.find_similar_button.click()
    assert cases.detail_tabs.currentWidget() is cluster
    assert cluster._focused_case_id == "DEMO-004"

    cases.show_quicktests()
    assert cases.detail_tabs.currentWidget() is cases.quicktest_browser
    assert cases.quicktest_browser.fin_selector.currentText() == "DEMO-VIN-000004"

    cases.quicktest_browser.select_fin("DEMO-VIN-000003")
    assert cases.selector.currentData() == "DEMO-003"
    assert cluster._focused_case_id == "DEMO-003"
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



def test_palette_is_not_reused_for_14_clusters_and_unassigned_is_gray() -> None:
    """The production screenshot had 14 clusters but only 8 unique colours."""
    first_14 = [color_for_cluster(cluster_id).name() for cluster_id in range(1, 15)]
    assert len(set(first_14)) == 14
    assert first_14[0] != first_14[8]
    assert first_14[5] != first_14[13]
    assert color_for_cluster(None).name() == UNASSIGNED
    assert color_for_cluster(35).name() != color_for_cluster(3).name()


def test_cluster_legend_and_group_note_identify_actual_membership() -> None:
    app = QApplication.instance() or QApplication([])
    cases = build_demo_cases()
    grouped = cluster_diagnostic_cases(cases)
    panel = CaseScatterPanel(cases, grouped)
    assert grouped.clusters
    selected = grouped.clusters[0]
    assert panel.focus_case(selected.case_ids[0])

    assert f"C{selected.cluster_id}" in panel.cluster_legend.text()
    assert f"Fokuscluster C{selected.cluster_id}" in panel.cluster_note.text()
    assert "schwächste originale Paarähnlichkeit" in panel.cluster_note.text()
    assert "größter Abstand" in panel.cluster_note.text()
    assert "Jaccard-Distanz" in panel.cluster_note.text()
    assert panel.result == grouped
    # Dashed links must connect only members of the *same* actual cluster.
    connector_lines = [
        item for item in panel.plot.scene().items()
        if isinstance(item, QGraphicsLineItem) and item.zValue() == 1
    ]
    assert len(connector_lines) == len(selected.case_ids) - 1
    for case_id in selected.case_ids:
        tooltip = panel.plot.items_by_case[case_id].toolTip()
        assert f"Cluster {selected.cluster_id}" in tooltip
    app.processEvents()
    panel.close()


def test_mouse_wheel_zoom_uses_two_factors_and_survives_selection() -> None:
    app = QApplication.instance() or QApplication([])
    cases = build_demo_cases()
    panel = CaseScatterPanel(cases, cluster_diagnostic_cases(cases))
    panel.resize(1100, 850)
    panel.show()
    app.processEvents()
    chart = panel.plot
    initial = chart.transform().m11()

    class Wheel:
        def __init__(self, delta: int):
            self.delta = delta
            self.accepted = False

        def angleDelta(self):
            return QPoint(0, self.delta)

        def accept(self):
            self.accepted = True

        def ignore(self):
            self.accepted = False

    zoom_in = Wheel(120)
    chart.wheelEvent(zoom_in)
    assert zoom_in.accepted
    assert chart._zoom_level > 1
    after = chart.transform().m11()
    assert after > initial

    target = next(
        point.case_id for point in panel.projection.points
        if point.case_id != panel.focus_id
    )
    assert panel.focus_case(target)
    assert abs(chart.transform().m11() - after) < 1e-9

    # Updating cluster threshold must change labels only, not camera zoom.
    panel.threshold.setValue(0.90)
    assert abs(chart.transform().m11() - after) < 1e-9

    zoom_out = Wheel(-120)
    chart.wheelEvent(zoom_out)
    assert zoom_out.accepted
    assert abs(chart._zoom_level - 1) < 1e-8
    assert abs(chart.transform().m11() - initial) < 1e-8

    zoom_in_again = Wheel(120)
    chart.wheelEvent(zoom_in_again)
    chart.reset_zoom()
    assert chart._zoom_level == 1.0
    assert abs(chart.transform().m11() - initial) < 1e-8
    panel.close()
    app.processEvents()
