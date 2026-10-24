"""Projekt-/Workflow-Übersicht mit synthetischen Testdaten."""
from __future__ import annotations

from PySide6.QtWidgets import QApplication

from ntf_insight.app.pages.dashboard_page import DashboardPage, project_overview_rows
from ntf_insight.storage.cluster_evidence_store import ClusterEvidenceStore
from ntf_insight.storage.duckdb_store import DuckDBStore
from ntf_insight.storage.quicktest_store import QuickTestStore
from ntf_insight.storage.workflow_projects import NTFProject, WorkflowProjectStore


def test_overview_shows_all_projects_and_only_their_evidence(tmp_path):
    store = DuckDBStore(tmp_path / "data.duckdb")
    projects = WorkflowProjectStore(store)
    projects.save(NTFProject("coolant_pump", "A 001 002", "Pumpe A", ("CPC3",)))
    projects.save(NTFProject("coolant_pump", "B 003 004", "Pumpe B", ("CPC3",)))
    evidence = ClusterEvidenceStore(store)
    document = tmp_path / "test.cdd"
    document.write_text("synthetische Candela-Probe", encoding="utf-8")
    evidence.add_files("coolant_pump", "A 001 002", "cdd_smrd", [document])
    rows = project_overview_rows(store)
    assert len(rows) == 2
    by_part = {row["part"]: row for row in rows}
    assert by_part["A 001 002"]["documents"] == 1
    assert by_part["A 001 002"]["parsed"] == 0
    assert by_part["B 003 004"]["documents"] == 0
    assert all(row["fins"] == row["ntf"] == row["clusters"] == 0 for row in rows)


def test_overview_row_opens_selected_project(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    store = DuckDBStore(tmp_path / "data.duckdb")
    page = DashboardPage(repository=None, quicktests=QuickTestStore(store))
    emitted = []
    page.project_selected.connect(lambda profile, part: emitted.append((profile, part)))
    page._loaded([{
        "title": "Pumpe A [A 001 002]",
        "profile": "coolant_pump", "part": "A 001 002",
        "fins": 4, "cases": 5, "ntf": 2, "reports": 3,
        "documents": 7, "parsed": 6, "clusters": 1, "step": 3,
    }])
    assert page.table.item(0, 1).text() == "4"
    assert page.table.item(0, 6).text() == "6"
    page._open_row(0, 0)
    assert emitted == [("coolant_pump", "A 001 002")]
    page.close()
    app.processEvents()
