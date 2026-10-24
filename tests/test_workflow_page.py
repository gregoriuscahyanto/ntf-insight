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


def test_five_horizontal_steps_show_inline_workspaces_and_resume(tmp_path, monkeypatch):
    app, window = _window(tmp_path, monkeypatch)
    page = window.pages["workflow"]
    assert window.navigation.buttons["workflow"].isChecked()
    assert not isinstance(page.workspaces, QScrollArea)
    assert len(page.cards) == 5
    assert page.workspaces.count() == 5
    assert all(btn.isCheckable() for btn in page.cards)

    page.cards[1].click()
    assert window.stack.currentWidget() is page
    assert page.state.step == 1
    assert page.workspaces.currentIndex() == 1
    page.cards[2].click()
    assert page.state.step == 2
    assert window.stack.currentWidget() is page
    page.cards[1].click()
    assert page.state.step == 1
    assert not hasattr(page, "next_button")
    assert not hasattr(page, "previous_button")
    assert not hasattr(page, "pause_button")
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


def test_existing_local_cluster_is_embedded_only_in_step_five(tmp_path, monkeypatch):
    app, window = _window(tmp_path, monkeypatch)
    page = window.pages["workflow"]
    page.cards[4].click()
    assert window.stack.currentWidget() is page
    assert page.local_cluster_widget is window.pages["cases"].cluster_workspace
    assert page.local_cluster_widget.parentWidget() is page.local_cluster_holder
    assert window.pages["cases"].detail_tabs.indexOf(page.local_cluster_widget) == -1
    assert page.workspaces.currentWidget() is page.workspaces.widget(4)
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



def test_step_four_collects_all_requested_categories_without_page_scroll(
    tmp_path, monkeypatch,
):
    app, window = _window(tmp_path, monkeypatch)
    page = window.pages["workflow"]
    page.cards[3].click()
    assert page.workspaces.currentIndex() == 3
    assert window.stack.currentWidget() is page
    assert not isinstance(page.workspaces, QScrollArea)
    from ntf_insight.storage.cluster_evidence_store import CATEGORY_LABELS
    assert len(CATEGORY_LABELS) == 11
    assert set(page.context_import_buttons) == set(CATEGORY_LABELS)
    assert set(page.context_scraper_buttons) == {
        "tp_dashboard", "diagnosis_viewer", "tips_writer", "celonis",
    }
    assert not page.context_scraper_buttons["tp_dashboard"]["all"].isEnabled()
    assert not page.context_scraper_buttons["celonis"]["all"].isEnabled()
    assert not hasattr(page, "context_base_button")
    assert not hasattr(page, "context_export_button")
    assert page.cluster_originals.isChecked() is False
    assert not page.cluster_export_button.isEnabled()
    assert page.context_model.rowCount() == 0
    actions = []
    monkeypatch.setattr(
        window, "_context_import",
        lambda category: actions.append(f"context_files:{category}"),
    )
    page.context_import_buttons["cdd_smrd"].click()
    assert actions == ["context_files:cdd_smrd"]
    window.close()
    app.processEvents()


def test_context_collection_shows_provenance_and_part_specific_status(
    tmp_path, monkeypatch,
):
    app, window = _window(tmp_path, monkeypatch)
    page = window.pages["workflow"]
    document = tmp_path / "cpc3.cdd"
    document.write_text("Synthetisches CPC3-Testdokument", encoding="utf-8")
    page.part_number.setText("A 123 456")
    page._change_context()
    count = page.context_store.add_files(
        "coolant_pump", "A123456", "cdd_smrd", [document],
    )
    assert count == 1
    page.refresh_context_files()
    page.refresh()
    assert page.context_model.rowCount() == 1
    assert page.context_counts["cdd_smrd"].text() == "1"
    assert page.cards[3].property("workflowState") == "partial"
    page.cards[3].click()
    page.context_review_button.click()
    assert 3 in page.state.reviewed_steps
    assert page.cards[3].property("workflowState") == "done"
    page.part_number.setText("B 987 654")
    page._change_context()
    assert page.context_model.rowCount() == 0
    assert page.cards[3].property("workflowState") == "pending"
    window.close()
    app.processEvents()



def test_context_scrapers_use_only_current_qec_part_with_single_fetch_action(
    tmp_path, monkeypatch,
):
    """Keine echten Browserkontakte: nur die FIN-Übergabe an vorhandene Downloader."""
    from PySide6.QtCore import QObject, Signal

    class FakeWorker(QObject):
        failed = Signal(str)
        finished = Signal()

    app, window = _window(tmp_path, monkeypatch)
    page = window.pages["workflow"]
    fake = page.qec_store
    monkeypatch.setattr(fake, "rows", lambda _root: _qec_rows())
    monkeypatch.setattr(
        fake, "active_source",
        lambda: SimpleNamespace(original_name="synthetisches_qec.xlsx"),
    )
    page.refresh_data()
    page.part_number.setText("A 123 456")
    page._change_context()
    page.cards[3].click()

    monkeypatch.setattr(window, "_portable_transfer_ready", lambda: True)
    cases = window.pages["cases"]
    calls = []
    quicktest_worker = FakeWorker()

    def fake_start(*, selected_only, fins_override=None):
        calls.append(("diagnosis", selected_only, list(fins_override or [])))
        cases._quicktest_worker = quicktest_worker

    monkeypatch.setattr(cases, "_start_quicktest_download", fake_start)
    window._context_scrape("diagnosis_viewer", "all")
    assert calls == [("diagnosis", False, ["WDD12345678901234"])]
    assert page.context_scraper_buttons["diagnosis_viewer"]["cancel"].isEnabled()
    cases._quicktest_worker = None
    quicktest_worker.finished.emit()
    assert not page.context_scraper_buttons["diagnosis_viewer"]["cancel"].isEnabled()

    tips = cases.tips_download
    assert tips is not None
    tips_worker = FakeWorker()

    def fake_tips_start(fins, *, bulk):
        calls.append(("tips", list(fins), bulk))
        tips.worker = tips_worker

    monkeypatch.setattr(tips, "_start", fake_tips_start)
    assert "selected" not in page.context_scraper_buttons["tips_writer"]
    assert page.context_scraper_buttons["tips_writer"]["parse"].text() == "Einlesen …"
    window._context_scrape("tips_writer", "all")
    assert calls[-1] == ("tips", ["WDD12345678901234"], True)
    assert "Abruf" in page.context_source_dates["tips_writer"].text()
    tips.worker = None
    tips_worker.finished.emit()
    window.close()
    app.processEvents()



def test_header_shows_projects_not_legacy_component_dropdown(tmp_path, monkeypatch):
    app, window = _window(tmp_path, monkeypatch)
    page = window.pages["workflow"]
    assert page.profile.isHidden()
    assert page.part_number.isHidden()
    assert page.project_export_button.text() == "Projekt-Export"
    assert page.project_import_button.text() == "Projekt-Import"
    assert not page.project_export_button.isEnabled()
    assert page.project_import_button.isEnabled()
    assert len(page.cards) == 5
    window.close()
    app.processEvents()


def test_existing_unassigned_qec_dataset_is_adopted_without_second_import(
    tmp_path, monkeypatch,
):
    from PySide6.QtWidgets import QInputDialog, QMessageBox

    app, window = _window(tmp_path, monkeypatch)
    page = window.pages["workflow"]
    monkeypatch.setattr(page.qec_store, "rows", lambda _root: _qec_rows())
    monkeypatch.setattr(
        page.qec_store, "active_source",
        lambda: SimpleNamespace(original_name="synthetische_master.xlsx"),
    )
    page.refresh_data()
    assert page.project_store.list_projects() == []
    assert page.adopt_button.isVisibleTo(page)
    monkeypatch.setattr(window, "_portable_transfer_ready", lambda: True)
    monkeypatch.setattr(
        QInputDialog, "getItem",
        lambda *_args, **_kwargs: ("A 123 456  ·  1 QEC-Fälle", True),
    )
    monkeypatch.setattr(
        QMessageBox, "question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes,
    )
    original = list(page._all_rows)
    page.adopt_button.click()
    project = page.project_store.get("coolant_pump", "A 123 456")
    assert project is not None
    assert project.title == "Kühlmittelpumpe [A 123 456]"
    assert len(page._scoped_rows) == 1
    assert page._scoped_rows[0]["fin"] == "WDD12345678901234"
    assert page._all_rows == original
    assert page.project_export_button.isEnabled()
    assert not page.adopt_button.isVisibleTo(page)
    window.close()
    app.processEvents()



def test_legacy_single_part_adoption_keeps_unscoped_workflow_and_documents(
    tmp_path, monkeypatch,
):
    from PySide6.QtWidgets import QInputDialog, QMessageBox

    app, window = _window(tmp_path, monkeypatch)
    workflow = window.pages["workflow"]
    doc = tmp_path / "cpc3_legacy.cdd"
    doc.write_text("synthetisch, nicht vertraulich", encoding="utf-8")
    workflow.context_store.add_files(
        "coolant_pump", "", "cdd_smrd", [doc],
    )
    workflow.progress_store.save(
        "coolant_pump", "",
        WorkflowProgress(step=2, paused=False, reviewed_steps=()),
    )
    monkeypatch.setattr(
        workflow.qec_store, "rows", lambda _root: [_qec_rows()[0]],
    )
    monkeypatch.setattr(
        workflow.qec_store, "active_sources",
        lambda: [SimpleNamespace(original_name="QEC_demo.xlsx")],
    )
    monkeypatch.setattr(window, "_portable_transfer_ready", lambda: True)
    monkeypatch.setattr(
        QInputDialog, "getItem",
        lambda *_args, **_kwargs: ("A 123 456  ·  1 QEC-Fälle", True),
    )
    monkeypatch.setattr(
        QMessageBox, "question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes,
    )
    workflow.refresh_data()
    assert workflow.adopt_button.isVisibleTo(workflow)
    workflow.adopt_button.click()
    assert workflow._context_part == "A 123 456"
    assert workflow.state.step == 2
    assert workflow.context_model.rowCount() == 1
    assert workflow.context_counts["cdd_smrd"].text() == "1"
    assert workflow.progress_store.load("coolant_pump", "").step == 2
    assert workflow.progress_store.load("coolant_pump", "A123456").step == 0
    assert workflow.progress_store.load("coolant_pump", "A 123 456").step == 2
    window.close()
    app.processEvents()
