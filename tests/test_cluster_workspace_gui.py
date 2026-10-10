"""One-tab GUI with synthetic 2D/3D clustering and method drill-down."""
from __future__ import annotations

import csv
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QHeaderView

from ntf_insight.app.widgets.cluster_workspace import ClusterWorkspace
from test_hdbscan_clustering import sample, synthetic


def _calculate(panel: ClusterWorkspace, compare: bool = False) -> None:
    if compare:
        panel.compare_methods()
    else:
        panel.run_analysis()
    assert panel._task is not None
    # A tiny synthetic cohort can finish before a spy is attached. Poll the
    # Qt event loop instead of relying on a racy after-start signal hook.
    for _ in range(2000):
        QApplication.processEvents()
        if panel.result is not None and panel.run_button.isEnabled():
            break
        if panel._task is None and "nicht möglich" in panel.status.text():
            break
        QTest.qWait(10)
    assert panel.result is not None, panel.status.text()
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
    item = panel.plot.items_by_case["A2"]
    pos = panel.plot.mapFromScene(item.sceneBoundingRect().center())
    # MDS projection can put multiple real cases on top of one another.
    # The actual topmost clickable point, not the occluded item, must win.
    clicked = panel.plot.itemAt(pos)
    assert clicked is not None
    visible_case_id = clicked.data(0)
    assert isinstance(visible_case_id, str)
    QTest.mouseClick(panel.plot.viewport(), Qt.MouseButton.LeftButton, pos=pos)
    assert panel._focused_case_id == visible_case_id
    panel.open_selected_case()
    assert emitted
    assert emitted[-1] in panel.by_id
    panel.close()
    app.processEvents()


def test_conservative_core_group_drilldown_is_inline_and_not_another_tab():
    app = QApplication.instance() or QApplication([])
    panel = ClusterWorkspace(sample())
    _calculate(panel)
    assert panel._core_result is not None
    assert panel.core_threshold.value() == 0.45
    assert panel.core_model.rowCount() == len(panel._core_result.groups)
    assert panel._core_links
    assert panel.core_export.isEnabled()
    first = panel._core_links[0]
    panel.core_table.selectRow(0)
    assert panel._active_core_group is first.core
    assert panel.member_model.rowCount() == first.core.case_count
    assert "K" in panel.member_title.text()
    assert panel.plot._emphasis_case_ids == set(first.core.case_ids)
    assert panel._focused_case_id == first.core.representative_case_id

    # Selecting a primary model cluster restores its FULL member list.
    another_group_index = 1 if len(panel.result.groups) > 1 else 0
    panel.group_table.selectRow(another_group_index)
    assert panel._active_core_group is None
    assert panel.member_title.text() == panel._member_title_default
    assert panel.plot._emphasis_case_ids is None
    assert panel.member_model.rowCount() == (
        panel.result.groups[another_group_index].case_count
    )

    panel.core_only_group.setChecked(True)
    selected_id = panel.result.groups[another_group_index].cluster_id
    assert panel.core_model.rowCount() == sum(
        selected_id in link.active_group_ids for link in panel._core_links
    )
    panel.close()
    app.processEvents()


def test_core_group_links_follow_selected_method_not_shared_cluster_number():
    app = QApplication.instance() or QApplication([])
    panel = ClusterWorkspace(sample())
    _calculate(panel, compare=True)
    method_keys = list(panel._run_results)
    assert "leaf" in method_keys and "eom" in method_keys
    assert "complete_cosine" in method_keys
    active_initial = panel.result
    panel._compare_row_picked(panel.compare_model.index(
        method_keys.index("eom"), 0,
    ))
    assert panel.result.parameters.method == "eom"
    assert panel._core_result is not None
    assert panel._core_links
    assert all(
        link.dominant_group_id is None or any(
            link.dominant_group_id == group.cluster_id
            for group in panel.result.groups
        )
        for link in panel._core_links
    )
    panel._compare_row_picked(panel.compare_model.index(
        method_keys.index("leaf"), 0,
    ))
    assert panel.result == active_initial
    panel.close()
    app.processEvents()


def test_search_synthetic_fin_finds_overlapping_projected_case():
    app = QApplication.instance() or QApplication([])
    panel = ClusterWorkspace(sample())
    _calculate(panel)
    vin = panel.by_id["A2"].vin
    panel.case_finder.setText(vin)
    assert panel.find_case()
    assert panel._focused_case_id == "A2"
    assert "1 lokale Treffer" in panel.search_feedback.text()
    panel.case_finder.setText("does-not-exist")
    assert not panel.find_case()
    assert "Keine" in panel.search_feedback.text()
    # Long DTC/SSL text is elided on screen but remains accessible on hover.
    index = panel.group_model.index(0, 7)
    assert panel.group_model.data(index, Qt.ItemDataRole.ToolTipRole)
    assert (
        panel.group_table.horizontalHeader().sectionResizeMode(0)
        == QHeaderView.ResizeMode.Interactive
    )
    assert panel.member_table.columnWidth(6) == 480
    panel.close()
    app.processEvents()


def test_core_csv_is_saved_only_locally_with_pending_mechanism_status(
    tmp_path, monkeypatch,
):
    app = QApplication.instance() or QApplication([])
    panel = ClusterWorkspace(sample())
    _calculate(panel)
    file = tmp_path / "Kernpruefgruppen_FIN_QEC_NICHT_HOCHLADEN.csv"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", lambda *a, **k: (str(file), "CSV"),
    )
    panel.core_export.click()
    assert file.is_file()
    with file.open("r", encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream, delimiter=";"))
    assert rows
    assert all(row["review_status"] == "pending" for row in rows)
    assert all(not row["mechanism_code"] for row in rows)
    assert all(row["qec_case_id"] in panel.by_id for row in rows)
    assert "ausschließlich lokal" in panel.status.text()
    panel.close()
    app.processEvents()


def test_synthetic_336_cases_170_eligible_without_publishing_identifiers():
    """Mirror only the QEC COUNTS of the real pilot, never confidential data."""
    app = QApplication.instance() or QApplication([])
    cases = [
        synthetic(
            f"QEC-SYN-{i:04d}", "A" if i % 2 == 0 else "B", i + 1000,
            swap=i < 170,
        )
        for i in range(336)
    ]
    panel = ClusterWorkspace(cases)
    _calculate(panel)
    assert len(panel.result.eligible_case_ids) == 170
    assert len(panel.result.excluded_case_ids) == 166
    assert len(panel.plot.items_by_case) == 170
    assert panel.noise_model.rowCount() == (
        len(panel.result.noise_case_ids) + 166
    )
    assert panel._core_result is not None
    assert panel.core_threshold.value() == 0.45
    panel.close()
    app.processEvents()
