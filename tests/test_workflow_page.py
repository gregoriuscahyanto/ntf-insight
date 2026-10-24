"""Tests der workflowbasierten Startseite; ausschließlich synthetische Daten."""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QScrollArea

from ntf_insight.app.windows.main_window import MainWindow
from ntf_insight.storage.duckdb_store import DuckDBStore
from ntf_insight.storage.workflow_progress import WorkflowProgress, WorkflowProgressStore


def test_workflow_progress_per_part_and_profile(tmp_path):
    store = WorkflowProgressStore(DuckDBStore(tmp_path / "data.duckdb"))
    assert store.current_context() == ("coolant_pump", "")
    store.select_context("coolant_pump", " a 123 456 ")
    state = WorkflowProgress(step=4, paused=True, reviewed_steps=(4,))
    store.save("coolant_pump", "A 123 456", state)
    assert store.current_context() == ("coolant_pump", "A 123 456")
    assert store.load("coolant_pump", "A 123 456") == state
    assert store.load("coolant_pump", "B 987 654") == WorkflowProgress()
    assert store.load("hv_battery", "A 123 456") == WorkflowProgress()
    assert WorkflowProgressStore(DuckDBStore(tmp_path / "data.duckdb")).load(
        "coolant_pump", "A 123 456"
    ) == state


def test_workflow_is_non_scrolling_with_resumable_steps(tmp_path, monkeypatch):
    monkeypatch.setenv("NTF_INSIGHT_DATA_DIR", str(tmp_path / "app-data"))
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    workflow = window.pages["workflow"]
    assert window.navigation.buttons["workflow"].isChecked()
    assert not workflow.findChildren(QScrollArea)
    assert len(workflow.cards) == 6
    assert len(workflow.tool_buttons) == 6
    workflow.part_number.setText("A 222 333")
    workflow._change_context()
    workflow._move(1)
    assert workflow.state.step == 1
    workflow.pause_button.click()
    assert workflow.state.paused
    workflow._move(1)
    assert workflow.state.step == 1
    workflow.pause_button.click()
    assert not workflow.state.paused
    workflow._move(1)
    assert workflow.state.step == 2
    workflow._open_step(4)
    workflow.review_button.click()
    assert workflow.state.reviewed_steps == (4,)
    workflow.part_number.setText("B 555 666")
    workflow._change_context()
    assert workflow.state == WorkflowProgress()
    workflow.part_number.setText("A 222 333")
    workflow._change_context()
    assert workflow.state.step == 4
    assert workflow.state.reviewed_steps == (4,)
    window.close()
    app.processEvents()


def test_workflow_actions_reuse_existing_source_panels(tmp_path, monkeypatch):
    monkeypatch.setenv("NTF_INSIGHT_DATA_DIR", str(tmp_path / "app-data"))
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    actions = window.pages["workflow"].tool_buttons
    source = window.pages["sources"]
    assert source.portable_backup_panel is not None
    assert source.ki_analyse_panel is not None
    for key in ("pc_export", "pc_import", "ai_export", "ai_import", "self_import"):
        assert actions[key].isEnabled()
    window.pages["workflow"]._open_step(4)
    assert window.navigation.buttons["cases"].isChecked()
    assert window.pages["cases"].detail_tabs.currentWidget() is (
        window.pages["cases"].cluster_workspace
    )
    window.close()
    app.processEvents()
