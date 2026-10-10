"""One-tab GUI with synthetic 2D/3D clustering and method drill-down."""
from __future__ import annotations

import csv
import os
from pathlib import Path
from tempfile import TemporaryDirectory

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QHeaderView
from shiboken6 import isValid

from ntf_insight.app.widgets.cluster_workspace import ClusterWorkspace
from test_hdbscan_clustering import sample, synthetic


def _calculate(
    panel: ClusterWorkspace, compare: bool = False, *, leaf_only: bool = False,
) -> None:
    if leaf_only:
        # Large-cohort population smoke: avoid all optional experimental
        # sensitivity runs; those are covered by the small synthetic suite.
        panel._start_methods(("leaf",), include_stability=False)
    elif compare:
        panel.compare_methods()
    else:
        panel.run_analysis()
    assert panel._task is not None
    task = panel._task
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
    # Avoid PySide GC collecting the GUI while a previous test's QThread
    # is still finishing. The UI itself stays asynchronous.
    if isValid(task):
        assert task.wait(10000)
    QApplication.processEvents()


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
    assert panel.display_method.currentData() == "leaf"
    assert "HDBSCAN" in panel.kpi.text()
    # This is the PROMINENT selector next to 3D, not the second plot.
    panel.display_method.setCurrentIndex(
        panel.display_method.findData("eom")
    )
    assert panel.result is panel._run_results["eom"]
    assert panel.plot._result is panel.result
    assert "EOM" in panel.kpi.text()
    assert panel.summary_values["groups"].text() == str(
        len(panel._run_results["eom"].groups)
    )
    assert panel.group_model.rowCount() == len(panel.result.groups)
    assert panel.member_model.rowCount() == panel.result.groups[
        panel.group_table.currentIndex().row()
    ].case_count
    panel.display_method.setCurrentIndex(
        panel.display_method.findData("complete_cosine")
    )
    assert panel.result is panel._run_results["complete_cosine"]
    assert "Complete-Link" in panel.kpi.text()
    assert panel.method.currentData() == "complete_cosine"
    panel.compare_side.setChecked(True)
    panel.other_method.setCurrentIndex(panel.other_method.findData("leaf"))
    assert panel.other_plot._result is panel._run_results["leaf"]
    assert panel.plot._result is panel._run_results["complete_cosine"]
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
    assert panel.display_method.currentData() == "complete_cosine"
    assert "Complete-Link" in panel.kpi.text()
    assert panel.plot._result is panel.result
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
    assert panel.member_title.text().startswith("4. Fälle in Cluster C")
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


def test_strict_details_do_not_count_two_qecs_of_same_fin_as_independent():
    app = QApplication.instance() or QApplication([])
    cases = sample()
    cases[1].vehicle = cases[1].vehicle.model_copy(
        update={"vin": cases[0].vin},
    )
    panel = ClusterWorkspace(cases)
    _calculate(panel)
    matching = next(
        (
            index for index, link in enumerate(panel._visible_core_links)
            if {"A0", "A1"}.issubset(link.core.case_ids)
        ),
        None,
    )
    if matching is not None:
        panel.core_table.selectRow(matching)
        rows = panel.member_model.rows
        same_fin = [row for row in rows if row[2] == cases[0].vin]
        assert len(same_fin) >= 2
        assert any("Mehrfachfall" in row[0] for row in same_fin)
        assert sum("Repräsentant" in row[0] for row in rows) == 1
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
    # SSL evidence is kept in the expert view, not the four-question UI.
    assert panel.member_table.isColumnHidden(6)
    panel.expert_toggle.setChecked(True)
    assert panel.member_table.columnWidth(6) == 480
    panel.close()
    app.processEvents()


def test_core_csv_is_saved_only_locally_with_pending_mechanism_status(
    monkeypatch,
):
    app = QApplication.instance() or QApplication([])
    panel = ClusterWorkspace(sample())
    _calculate(panel)
    # Repository tests deliberately keep pytest-tmp *inside Git*; genuine
    # customer data exports must use a completely separate private directory.
    with TemporaryDirectory(prefix="ntf-private-core-review-") as directory:
        file = Path(directory) / "Kernpruefgruppen_FIN_QEC_NICHT_HOCHLADEN.csv"
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


def test_local_core_export_refuses_files_in_git_checkout(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    panel = ClusterWorkspace(sample())
    _calculate(panel)
    forbidden = tmp_path / "NEVER_COMMIT_FIN_QEC.csv"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName",
        lambda *a, **k: (str(forbidden), "CSV"),
    )
    panel.core_export.click()
    assert not forbidden.exists()
    assert "Git-Repository" in panel.status.text()
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
    _calculate(panel, leaf_only=True)
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


def test_single_cluster_start_button_runs_all_methods_and_sensitivities():
    app = QApplication.instance() or QApplication([])
    panel = ClusterWorkspace(sample())
    assert panel.run_button.text() == "Clusteranalyse starten"
    assert not hasattr(panel, "compare_button")
    assert not hasattr(panel, "stability_button")
    panel.show()
    app.processEvents()
    assert panel._task is None  # no expensive surprise on tab opening
    assert panel.advanced_panel.isHidden()
    panel.advanced_toggle.setChecked(True)
    assert not panel.advanced_panel.isHidden()
    panel.advanced_toggle.setChecked(False)
    QTest.mouseClick(panel.run_button, Qt.MouseButton.LeftButton)
    assert panel._task is not None
    task = panel._task
    for _ in range(3000):
        QApplication.processEvents()
        if panel._stability_report is not None and panel.run_button.isEnabled():
            break
        if panel._task is None and "nicht möglich" in panel.status.text():
            break
        QTest.qWait(10)
    assert panel._stability_report is not None, panel.status.text()
    if isValid(task):
        assert task.wait(10000)
    QApplication.processEvents()
    report = panel._stability_report
    assert panel.stability_model.rowCount() == len(report.comparisons)
    assert panel.stability_group_model.rowCount() == sum(
        len(item.group_rows) for item in report.comparisons
    )
    assert {"Verfahren", "Daten/Parameter"} == {
        item.category for item in report.comparisons
    }
    assert panel.result.parameters.method == "leaf"
    assert len(panel._run_results) == 4
    assert panel.compare_model.rowCount() == 4
    assert "Kein Ursachen-Voting" in panel.stability_note.text()
    # Parameter changes must invalidate the stale robustness evidence.
    panel.lookback.setCurrentIndex(panel.lookback.findData(90))
    assert panel._stability_report is None
    assert panel.stability_model.rowCount() == 0
    assert panel.run_button.isEnabled()
    panel.close()
    app.processEvents()


def test_four_everyday_questions_are_visible_without_expert_tables():
    app = QApplication.instance() or QApplication([])
    panel = ClusterWorkspace(sample())
    panel.show()
    app.processEvents()
    assert panel.run_button.text() == "Clusteranalyse starten"
    assert panel.expert_panel.isHidden()
    assert panel.advanced_panel.isHidden()
    assert all(value.text() == "–" for value in panel.summary_values.values())
    assert panel.group_table.isColumnHidden(4)
    assert panel.member_table.isColumnHidden(6)

    _calculate(panel)
    assert panel.summary_values["groups"].text() == "2"
    assert panel.summary_values["assigned"].text() == "12"
    assert panel.summary_values["noise"].text() == "1"
    assert panel.summary_values["missing"].text() == "2"
    assert panel.plot.items_by_case
    assert panel.group_table.currentIndex().isValid()
    assert "Warum gehören diese" in panel.why_heading.text()
    assert "CPC3:CODE-" in panel.why_text.text()
    assert panel.member_model.rowCount() == 6
    assert all(row[1] in panel.by_id for row in panel.member_model.rows)
    assert any("gleiche ECU:DTC" in row[5] for row in panel.member_model.rows)
    assert "Wichtig:" in panel.why_text.text()
    initial_group = panel.why_heading.text()
    panel.group_table.selectRow(1)
    assert panel.why_heading.text() != initial_group
    assert "CPC3:CODE-" in panel.why_text.text()

    # Long-standing review and alternative algorithms are not removed.
    panel.expert_toggle.setChecked(True)
    assert not panel.expert_panel.isHidden()
    assert not panel.group_table.isColumnHidden(4)
    assert not panel.member_table.isColumnHidden(6)
    assert panel.compare_model.rowCount() == 4
    assert panel.stability_model.rowCount() > 0
    assert panel.core_model.rowCount() > 0
    panel.expert_toggle.setChecked(False)
    assert panel.expert_panel.isHidden()
    assert panel.group_table.isColumnHidden(4)
    assert panel.member_table.isColumnHidden(6)
    panel.close()
    app.processEvents()


def test_simple_selection_via_plot_finds_cases_and_reasons():
    app = QApplication.instance() or QApplication([])
    panel = ClusterWorkspace(sample())
    _calculate(panel)
    panel.focus_case("B2")
    assert "B2" in panel._member_ids
    assert panel.member_model.rowCount() == 6
    assert panel.group_table.currentIndex().isValid()
    assert "CODE-B-" in panel.why_text.text()
    panel.lookback.setCurrentIndex(panel.lookback.findData(90))
    assert panel.summary_values["groups"].text() == "–"
    assert panel.group_model.rowCount() == 0
    assert "Bitte zuerst" in panel.why_text.text()
    panel.close()
    app.processEvents()


def test_3d_left_drag_rotates_tilts_and_click_still_selects_cases():
    """Left drag is rotation, click is selection, no cluster membership changes."""
    app = QApplication.instance() or QApplication([])
    panel = ClusterWorkspace(sample())
    panel.show()
    app.processEvents()
    _calculate(panel)
    panel.dimension.setCurrentIndex(panel.dimension.findData("3d"))
    app.processEvents()
    assert panel.plot.mode == "3d"
    assert panel.rotation_label.parentWidget() is not None
    assert panel.expert_panel.isHidden()

    plot = panel.plot
    before = tuple(group.case_ids for group in panel.result.groups)
    point = plot.mapFromScene(
        plot.items_by_case["A2"].sceneBoundingRect().center()
    )
    initial_focus = panel._focused_case_id
    yaw0, elev0 = plot.yaw, plot.elevation
    QTest.mousePress(
        plot.viewport(), Qt.MouseButton.LeftButton, pos=point,
    )
    for offset in (QPoint(26, -14), QPoint(48, -24)):
        moved = point + offset
        drag = QMouseEvent(
            QEvent.Type.MouseMove, QPointF(moved),
            Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        QApplication.sendEvent(plot.viewport(), drag)
    QTest.mouseRelease(
        plot.viewport(), Qt.MouseButton.LeftButton,
        pos=point + QPoint(48, -24),
    )
    assert plot.yaw != yaw0
    assert plot.elevation != elev0
    assert panel.yaw.value() == plot.yaw
    assert panel.elevation.value() == plot.elevation
    assert panel.other_plot.yaw == plot.yaw
    assert panel._focused_case_id == initial_focus
    assert tuple(group.case_ids for group in panel.result.groups) == before

    # A click (without movement) must select the actual point, not rotate.
    item = plot.items_by_case["B2"]
    clicked = plot.mapFromScene(item.sceneBoundingRect().center())
    yaw, elevation = plot.yaw, plot.elevation
    QTest.mouseClick(
        plot.viewport(), Qt.MouseButton.LeftButton, pos=clicked,
    )
    assert panel._focused_case_id == "B2"
    assert (plot.yaw, plot.elevation) == (yaw, elevation)
    assert "CODE-B-" in panel.why_text.text()
    panel.close()
    app.processEvents()
