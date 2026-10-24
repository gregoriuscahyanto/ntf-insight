"""GUI- und Persistenzprüfungen des horizontalen Workflows (synthetische Daten)."""
from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QScrollArea

from ntf_insight.app.windows.main_window import MainWindow
from ntf_insight.storage.duckdb_store import DuckDBStore
from ntf_insight.storage.workflow_progress import (
    WorkflowProgress, WorkflowProgressStore,
)


def _window(tmp_path, monkeypatch) -> tuple[QApplication, MainWindow]:
    monkeypatch.setenv("NTF_INSIGHT_DATA_DIR", str(tmp_path / "app-data"))
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    return app, window


def _qec_rows() -> list[dict]:
    return [
        {
            "fin": "WDD12345678901234", "case_id": "QEC-DEMO-1",
            "reference": "123456789", "part_number": "A 123 456",
            "finding": "Kein Fehler reproduzierbar", "tp_dashboard": True,
            "decision": "NTF", "reason": "Fachlich bestätigt", "report": False,
        },
        {
            "fin": "WDD12345678901235", "case_id": "QEC-DEMO-2",
            "reference": "123456790", "part_number": "B 987 654",
            "finding": "", "tp_dashboard": False,
            "decision": "Offen", "reason": "", "report": False,
        },
    ]


def test_workflow_upsert_and_context_survive_reopen(tmp_path):
    store = WorkflowProgressStore(DuckDBStore(tmp_path / "workflow.duckdb"))
    assert store.current_context() == ("coolant_pump", "")
    store.select_context("coolant_pump", " a 123 456 ")
    expected = WorkflowProgress(step=4, paused=True, reviewed_steps=(4,))
    store.save("coolant_pump", "A 123 456", expected)
    # Wiederholter UPSERT muss mit DuckDB funktionieren (Regressionsfall).
    store.save("coolant_pump", "A 123 456", expected)
    restored = WorkflowProgressStore(DuckDBStore(tmp_path / "workflow.duckdb"))
    assert restored.current_context() == ("coolant_pump", "A 123 456")
    assert restored.load("coolant_pump", "A 123 456") == expected
    assert restored.load("coolant_pump", "B 987 654") == WorkflowProgress()
    assert restored.load("hv_battery", "A 123 456") == WorkflowProgress()


def test_six_horizontal_steps_show_inline_workspaces_and_resume(tmp_path, monkeypatch):
    app, window = _window(tmp_path, monkeypatch)
    page = window.pages["workflow"]
    assert window.navigation.buttons["workflow"].isChecked()
    assert not page.findChildren(QScrollArea)
    assert len(page.cards) == 6
    assert page.workspaces.count() == 6
    assert all(btn.isCheckable() for btn in page.cards)

    page.cards[1].click()
    assert window.stack.currentWidget() is page
    assert page.state.step == 1
    assert page.workspaces.currentIndex() == 1
    page.next_button.click()
    assert page.state.step == 2
    assert window.stack.currentWidget() is page
    page.previous_button.click()
    assert page.state.step == 1

    page.pause_button.click()
    assert page.state.paused
    page.cards[4].click()
    assert page.state.step == 1
    page.pause_button.click()
    page.cards[4].click()
    assert page.state.step == 4
    page.review_button.click()
    assert page.state.reviewed_steps == (4,)

    page.part_number.setText("A 222 333")
    page._change_context()
    assert page.state == WorkflowProgress()
    page.part_number.setText("")
    page._change_context()
    assert page.state.step == 4
    assert page.state.reviewed_steps == (4,)
    window.close()
    app.processEvents()


def test_imported_qec_rows_are_filtered_to_part_and_target_reference(tmp_path, monkeypatch):
    app, window = _window(tmp_path, monkeypatch)
    page = window.pages["workflow"]
    fake = page.qec_store
    assert fake is not None
    monkeypatch.setattr(fake, "rows", lambda _root: _qec_rows())
    monkeypatch.setattr(
        fake, "active_source", lambda: SimpleNamespace(original_name="QEC_Demo.xlsx"),
    )
    page.refresh_data()
    assert page.fin_model.rowCount() == 2
    assert page.qec_model.rowCount() == 2
    assert page.ntf_model.rowCount() == 2
    assert len(page.qec_targets()) == 2
    assert page.cards[0].property("workflowState") == "done"
    assert page.cards[1].property("workflowState") == "pending"

    page.part_number.setText("a-123456")
    page._change_context()
    assert page.fin_model.rowCount() == 1
    assert page.qec_model.rowCount() == 1
    assert page.ntf_model.rowCount() == 1
    target = page.qec_targets()
    assert len(target) == 1
    assert (target[0].fin, target[0].reference) == (
        "WDD12345678901234", "123456789"
    )
    page.cards[1].click()
    page.qec_table.selectRow(0)
    assert page.qec_targets(selected_only=True) == target
    window.close()
    app.processEvents()


def test_decision_step_has_chatgpt_export_import_without_bottom_button_grid(
    tmp_path, monkeypatch,
):
    app, window = _window(tmp_path, monkeypatch)
    page = window.pages["workflow"]
    page.cards[2].click()
    assert page.workspaces.currentIndex() == 2
    assert page.ai_export_button.parent() is page.workspaces.widget(2)
    assert page.ai_import_button.parent() is page.workspaces.widget(2)
    assert hasattr(page, "ntf_table")
    assert not hasattr(page, "tool_buttons")
    emitted = []
    page.action_requested.connect(emitted.append)
    # Nicht den realen QFileDialog der verborgenen Datenquellen-Seite öffnen.
    window.pages["sources"].ki_analyse_panel.import_button.setEnabled(False)
    page.ai_import_button.click()
    assert emitted[-1] == "ai_import"
    page.set_notice("QEC-Abruf fehlgeschlagen", error=True)
    assert page.cards[2].property("workflowState") == "error"
    window.close()
    app.processEvents()


def test_existing_diagnosis_and_cluster_detail_still_open(tmp_path, monkeypatch):
    app, window = _window(tmp_path, monkeypatch)
    page = window.pages["workflow"]
    page.cards[4].click()
    assert window.stack.currentWidget() is page
    detail = page.workspaces.widget(4)
    from PySide6.QtWidgets import QPushButton
    open_buttons = [
        b for b in detail.findChildren(QPushButton)
        if "Clusteranalyse" in b.text()
    ]
    assert open_buttons
    open_buttons[0].click()
    assert window.navigation.buttons["cases"].isChecked()
    assert window.pages["cases"].detail_tabs.currentWidget() is (
        window.pages["cases"].cluster_workspace
    )
    window.close()
    app.processEvents()


def test_local_qec_csv_export_filters_part_without_false_download_claims(tmp_path, monkeypatch):
    store = DuckDBStore(tmp_path / "local.duckdb")
    from ntf_insight.storage.qec_workflow_store import QecWorkflowStore
    workflow = QecWorkflowStore(store)
    monkeypatch.setattr(workflow, "rows", lambda _root: _qec_rows())
    filename = tmp_path / "export.csv"
    count = workflow.export_csv(
        filename, tmp_path, part_number="A-123456"
    )
    assert count == 1
    text = filename.read_text(encoding="utf-8-sig")
    assert "WDD12345678901234" in text
    assert "WDD12345678901235" not in text
    assert "QEC-Fall" in text
