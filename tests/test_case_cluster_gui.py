"""Qt smoke tests for case-cluster heatmap and comparable measures."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from ntf_insight.app.widgets.case_cluster_panel import CaseClusterPanel
from ntf_insight.demo.synthetic_cases import build_demo_cases


def test_case_cluster_panel_shows_neighbours_and_heatmap() -> None:
    app = QApplication.instance() or QApplication([])
    panel = CaseClusterPanel(build_demo_cases())

    assert panel.focus.count() == len(build_demo_cases())
    assert panel.result is not None
    assert panel.cluster_model.rowCount() == len(build_demo_cases())
    assert panel.matrix_model.rowCount() >= 2
    assert panel.neighbor_model.rowCount() >= 1
    assert panel.cluster_profile_model.rowCount() >= 1
    assert panel._cluster_profiles[0].case_count >= 2
    assert panel._cluster_profiles[0].representative_case_id in {
        case.case_id for case in build_demo_cases()
    }

    first = panel.matrix_model.index(0, 1)
    assert panel.matrix_model.data(first, Qt.ItemDataRole.ToolTipRole)
    assert panel.matrix_model.data(first, Qt.ItemDataRole.BackgroundRole)
    assert panel.matrix_model.data(first, Qt.ItemDataRole.ForegroundRole)

    panel.threshold.setValue(0.95)
    assert panel.result.threshold == 0.95

    panel.focus.setCurrentIndex(panel.focus.findData("DEMO-002"))
    assert panel.matrix_model.case_ids[0] == "DEMO-002"

    panel.resize(1100, 750)
    panel.show()
    app.processEvents()
    panel.close()


def test_cluster_neighbour_explains_differences_and_opens_real_case() -> None:
    app = QApplication.instance() or QApplication([])
    panel = CaseClusterPanel(build_demo_cases())
    assert panel.focus_case("DEMO-001")

    index = panel.neighbor_model.index(0, 0)
    assert index.isValid()
    panel.neighbor_table.selectRow(0)
    panel._show_neighbor_detail(index)
    explanation = panel.detail.text()
    assert "Gemeinsames Diagnosebild" in explanation
    assert "Nur im gewählten Fall" in explanation
    assert "Beobachteter Verlauf" in explanation
    assert panel.open_case_button.isEnabled()

    selected = []
    panel.case_requested.connect(selected.append)
    panel.open_case_button.click()
    assert len(selected) == 1
    assert selected[0] in {case.case_id for case in build_demo_cases()}
    assert selected[0] != "DEMO-001"

    profile_index = panel.cluster_profile_model.index(0, 0)
    panel._focus_cluster_representative(profile_index)
    assert panel.focus.currentData() == panel._cluster_profiles[0].representative_case_id

    panel.close()
    app.processEvents()


def test_empty_case_repository_does_not_convert_quicktests_to_cases() -> None:
    app = QApplication.instance() or QApplication([])
    panel = CaseClusterPanel([])
    assert panel.result is None
    assert panel.cluster_profile_model.rowCount() == 0
    assert panel.cluster_model.rowCount() == 0
    assert not panel.focus_case("FIN-QUICKTEST:W1TTEST0000000001")
    assert "kein Schadteilfall" in panel.detail.text() or "echte" in panel.summary.text()
    panel.close()
    app.processEvents()


def test_case_page_and_cluster_view_navigate_in_both_directions(
    tmp_path, monkeypatch,
) -> None:
    from ntf_insight.app.windows.main_window import MainWindow

    monkeypatch.setenv("NTF_INSIGHT_DATA_DIR", str(tmp_path / "empty"))
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    cases = window.pages["cases"]
    selected = cases.selector.currentData()
    assert isinstance(selected, str) and selected.startswith("DEMO-")
    assert cases.find_similar_button.isEnabled()
    cases.find_similar_button.click()

    clusters = window.pages["clusters"]
    assert window.stack.currentWidget() is clusters
    assert clusters.case_cluster_panel.focus.currentData() == selected
    assert clusters.tabs.currentIndex() == 0

    panel = clusters.case_cluster_panel
    panel.neighbor_table.selectRow(0)
    expected = panel._selected_neighbor_case()
    assert expected is not None and expected != selected

    # The earlier case search is intentionally set to a nonmatching FIN;
    # opening a comparison must still select the target case.
    cases.case_search.setText("FIN-DOES-NOT-EXIST")
    assert cases.case_proxy.rowCount() == 0
    panel._open_selected_neighbor()
    assert window.stack.currentWidget() is window.pages["cases"]
    assert cases.selector.currentData() == expected
    assert cases.case_search.text() == ""
    assert cases.detail_tabs.currentIndex() == 0

    window.close()
    app.processEvents()


def test_keyboard_neighbour_change_updates_detail_and_disables_stale_action() -> None:
    app = QApplication.instance() or QApplication([])
    panel = CaseClusterPanel(build_demo_cases())
    assert panel.focus_case("DEMO-001")
    assert panel.neighbor_model.rowCount() >= 2

    first_id = panel.neighbor_model.rows[0][0]
    second_id = panel.neighbor_model.rows[1][0]

    panel.neighbor_table.setCurrentIndex(panel.neighbor_model.index(0, 0))
    assert panel.detail.text().startswith(f"Fall {first_id} ")
    assert panel.open_case_button.isEnabled()

    # Arrow-key navigation changes the current row without a mouse-click signal.
    panel.neighbor_table.setCurrentIndex(panel.neighbor_model.index(1, 0))
    assert panel.detail.text().startswith(f"Fall {second_id} ")
    assert panel._selected_neighbor_case() == second_id

    panel.neighbor_table.selectionModel().clearCurrentIndex()
    assert not panel.open_case_button.isEnabled()
    assert panel._selected_neighbor_case() is None
    panel.close()
    app.processEvents()
