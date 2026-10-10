"""One-tab GUI with synthetic 2D/3D clustering and method drill-down."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication

from ntf_insight.app.widgets.cluster_workspace import ClusterWorkspace
from test_hdbscan_clustering import sample


def _calculate(panel: ClusterWorkspace, compare: bool = False) -> None:
    if compare:
        panel.compare_methods()
    else:
        panel.run_analysis()
    task = panel._task
    assert task is not None
    spy = QSignalSpy(task.calculated)
    failed = QSignalSpy(task.problem)
    if not spy.count():
        assert spy.wait(45000), (
            f"GUI worker returned no data: {[args[0] for args in failed]}"
        )
    QApplication.processEvents()
    assert not failed.count()
    assert panel.result is not None
    assert panel.run_button.isEnabled()


def test_gui_one_method_parameter_controls_and_graph_case_click():
    app = QApplication.instance() or QApplication([])
    panel = ClusterWorkspace(sample())
    assert panel.method.count() == 4
    assert panel.method.currentData() == "leaf"
    assert panel.min_cluster_size.value() == 3
    assert panel.min_samples.value() == 2
    assert panel.min_samples.isHidden() is False or not panel.isVisible()

    _calculate(panel)
    assert len(panel.result.groups) == 2
    assert panel.result.clustered_count == 12
    assert panel.group_model.rowCount() == 2
    assert panel.member_model.rowCount() == 6
    assert panel.plot.mode == "2d"
    assert set(panel.plot.items_by_case) == {
        f"A{i}" for i in range(6)
    } | {f"B{i}" for i in range(6)} | {"OUTLIER"}
    assert panel.noise_model.rowCount() == 3
    assert panel.focus_case("A2")
    assert panel._focused_case_id == "A2"
    emitted = []
    panel.case_requested.connect(emitted.append)
    panel.case_requested.emit("A2")
    assert emitted == ["A2"]
    # Changing display dimension never changes underlying memberships.
    before = [group.case_ids for group in panel.result.groups]
    panel.dimension.setCurrentIndex(panel.dimension.findData("3d"))
    assert panel.plot.mode == "3d"
    panel.plot.set_rotation(100, -20)
    assert panel.plot.yaw == 100
    assert panel.plot.elevation == -20
    assert set(panel.plot.items_by_case) == set(panel.result.eligible_case_ids)
    panel.dimension.setCurrentIndex(panel.dimension.findData("2d"))
    assert panel.plot.mode == "2d"
    assert [group.case_ids for group in panel.result.groups] == before
    panel.close()
    app.processEvents()


def test_method_selector_displays_relevant_controls_and_compare_toggle():
    app = QApplication.instance() or QApplication([])
    panel = ClusterWorkspace(sample())
    panel.method.setCurrentIndex(panel.method.findData("complete_cosine"))
    assert panel.cosine_threshold.isHidden() or not panel.isVisible()
    assert not panel.min_samples.isVisible()
    assert panel.cosine_threshold.value() == 0.45
    panel.method.setCurrentIndex(panel.method.findData("complete_legacy"))
    assert panel.jaccard_threshold.value() == 0.60
    assert not panel.filter_common.isEnabled()
    panel.method.setCurrentIndex(panel.method.findData("leaf"))
    assert panel.filter_common.isEnabled()

    _calculate(panel, compare=True)
    assert panel.compare_model.rowCount() == 4
    assert len(panel._run_results) == 4
    assert panel.compare_side.isEnabled()
    panel.compare_side.setChecked(True)
    assert panel.other_plot.mode == "2d"
    assert set(panel.other_plot.items_by_case) == set(panel.plot.items_by_case)
    panel.dimension.setCurrentIndex(panel.dimension.findData("3d"))
    assert panel.plot.mode == panel.other_plot.mode == "3d"
    panel.yaw.setValue(132)
    panel.elevation.setValue(43)
    assert panel.plot.yaw == panel.other_plot.yaw == 132
    assert panel.plot.elevation == panel.other_plot.elevation == 43
    panel.close()
    app.processEvents()


def test_method_comparison_selecting_result_replaces_clusters_not_tabs():
    app = QApplication.instance() or QApplication([])
    panel = ClusterWorkspace(sample())
    _calculate(panel, compare=True)
    index = panel.compare_model.index(2, 0)
    panel._compare_row_picked(index)
    assert panel.result is not None
    assert panel.result.parameters.method == "complete_cosine"
    assert panel.method.currentData() == "complete_cosine"
    assert panel.group_model.rowCount() == len(panel.result.groups)
    assert panel.noise_model.rowCount() == (
        len(panel.result.noise_case_ids) + len(panel.result.excluded_case_ids)
    )
    assert panel.focus_case("UNANCHORED")
    assert panel._focused_case_id == "UNANCHORED"
    assert panel.plot.items_by_case.get("UNANCHORED") is None
    panel.close()
    app.processEvents()


def test_select_case_in_map_emits_only_local_id_and_no_remote_access():
    app = QApplication.instance() or QApplication([])
    panel = ClusterWorkspace(sample())
    _calculate(panel)
    panel.resize(1200, 850)
    panel.show()
    app.processEvents()
    emitted = []
    panel.case_requested.connect(emitted.append)
    target = "A2"
    item = panel.plot.items_by_case[target]
    pos = panel.plot.mapFromScene(item.sceneBoundingRect().center())
    QTest.mouseClick(panel.plot.viewport(), Qt.MouseButton.LeftButton, pos=pos)
    assert panel._focused_case_id == target
    panel.open_selected_case()
    assert emitted
    assert emitted[-1] in panel.by_id
    panel.close()
    app.processEvents()
