"""Synthetic read-only GUI tests for all imported AutoExport FINs."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid

from ntf_insight.app.widgets.autoexport_fin_workspace import AutoExportFinWorkspace
from ntf_insight.storage.duckdb_store import DuckDBStore
from ntf_insight.storage.source_knowledge_store import SourceKnowledgeStore
from test_autoexport_fin_patterns import _synthetic_population
from test_hdbscan_clustering import sample


def test_fin_workspace_groups_all_original_fins_and_opens_history(tmp_path):
    all_fins, codes, group_a, group_b, unique_fin = _synthetic_population()
    source = SourceKnowledgeStore(DuckDBStore(tmp_path / "all-fin.db"))
    rows = []
    for fin, faults in codes.items():
        for ecu, dtc in faults:
            rows.append({
                "category": "autoexport_dtc", "fin": fin,
                "data": {
                    "EcuNm": ecu, "EcuFaultNm": dtc,
                    "EcuFaultTxt": "Synthetic diagnostic label",
                },
            })
    for fin in all_fins:
        rows.append({
            "category": "autoexport_repair", "fin": fin,
            "data": {"RepairTypeNmGerman": "Synthetic workshop entry"},
        })
    source.save_records("a" * 64, "autoexport_rows", rows)
    app = QApplication.instance() or QApplication([])
    panel = AutoExportFinWorkspace(
        source, sample(), source.autoexport_population(),
    )
    panel.show()
    app.processEvents()
    assert panel.result is None
    assert panel.start_button.isEnabled()
    assert "23 AutoExport-FINs" in panel.population_note.text()
    panel.start_button.click()
    assert panel._task is not None
    task = panel._task
    for _ in range(1200):
        app.processEvents()
        if panel.result is not None and panel.start_button.isEnabled():
            break
        QTest.qWait(10)
    assert panel.result is not None, panel.status.text()
    if isValid(task):
        assert task.wait(10000)
    app.processEvents()
    assert panel.number_labels["total"].text() == "23"
    assert panel.number_labels["dtc"].text() == "21"
    assert panel.number_labels["assigned"].text() == "20"
    assert panel.number_labels["unassigned"].text() == "1"
    assert panel.number_labels["missing"].text() == "2"
    assert panel.number_labels["groups"].text() == "2"
    assert panel.group_model.rowCount() == 2
    assert "Synthetic diagnostic label" in panel.explanation.text()
    assert "kein Beleg" in panel.explanation.text()
    assert panel.fin_model.rowCount() == 10

    target = group_b[1]
    panel.fin_search.setText(target)
    assert panel.find_fin()
    assert panel._selected_fin == target
    assert "Mustergruppe" in panel.fin_status.text()
    emitted = []
    panel.fin_requested.connect(emitted.append)
    panel.open_button.click()
    assert emitted == [target]

    # The other AutoExport FINs remain searchable, without fake QEC cases.
    panel.fin_search.setText(unique_fin)
    assert panel.find_fin()
    assert "erfüllt aber nicht" in panel.fin_status.text()
    assert panel._selected_fin == unique_fin
    panel.fin_search.setText(all_fins[-2])
    assert panel.find_fin()
    assert "ohne importierte DTC" in panel.fin_status.text()
    panel.close()
    app.processEvents()


def test_one_clusteranalyse_tab_includes_autoexport_and_qec(tmp_path, monkeypatch):
    from ntf_insight.app.windows.main_window import MainWindow

    monkeypatch.setenv("NTF_INSIGHT_DATA_DIR", str(tmp_path))
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    case_page = window.pages["cases"]
    assert case_page.detail_tabs.count() == 3
    assert case_page.detail_tabs.indexOf(
        case_page.autoexport_fin_workspace
    ) == -1
    assert case_page.detail_tabs.currentWidget() == case_page.cluster_workspace
    assert case_page.cluster_workspace.fin_workspace is case_page.autoexport_fin_workspace
    case_page.cluster_workspace.show_fin_mode()
    assert case_page.detail_tabs.currentWidget() == case_page.cluster_workspace
    assert case_page.cluster_workspace.cluster_views.currentWidget() is (
        case_page.autoexport_fin_workspace
    )
    assert case_page.cluster_workspace.population_mode.currentData() == "all_fins"
    assert case_page.autoexport_fin_workspace.start_button.text() == (
        "Clusteranalyse starten"
    )
    case_page.cluster_workspace.show_qec_mode()
    assert case_page.cluster_workspace.cluster_views.currentWidget() is (
        case_page.cluster_workspace.qec_scroll
    )
    assert case_page.cluster_workspace.run_button.text() == "Clusteranalyse starten"
    case_page.autoexport_fin_workspace.fin_requested.emit("W1TTEST0000000001")
    assert case_page.detail_tabs.currentWidget() == case_page.analysis_tab
    assert case_page.autoexport_fin_lookup.text() == "W1TTEST0000000001"
    window.close()
    app.processEvents()


def test_opt_in_qec_pump_date_excludes_unanchored_fins_and_post_swap_dtc(tmp_path):
    """One user-click switches all AutoExport FINs to proven pre-swap subset."""
    from test_hdbscan_clustering import synthetic

    fins = [f"W1TTEST000000{i:04d}" for i in range(6)]
    cases = [
        synthetic(f"QEC-SYN-{i}", "X", i, vin=fins[i])
        for i in range(4)
    ]
    for case in cases:
        case.qec_reference = case.case_id
        # This particular test isolates the AutoExport timestamp filter;
        # QEC DTC co-features are covered by the union regression below.
        case.diagnostics = []
    source = SourceKnowledgeStore(DuckDBStore(tmp_path / "pump-scope.duckdb"))
    rows = []
    for fin in fins:
        rows.extend([
            {"category": "autoexport_dtc", "fin": fin, "data": {
                "EcuNm": "CPC3", "EcuFaultNm": "SHARED-BEFORE",
                "DiagStartDt": "2026-04-02",
            }},
            {"category": "autoexport_dtc", "fin": fin, "data": {
                "EcuNm": "CPC3", "EcuFaultNm": "SHARED-AFTER",
                "DiagStartDt": "2026-06-10",
            }},
        ])
    source.save_records("a" * 64, "autoexport_rows", rows)
    app = QApplication.instance() or QApplication([])
    panel = AutoExportFinWorkspace(
        source, cases, source.autoexport_population()
    )
    panel.show()
    app.processEvents()
    assert len(panel._pump_swap_dates) == 4
    assert not panel.only_pump_swap.isChecked()
    panel.only_pump_swap.setChecked(True)
    assert "Rep.-Datum" in panel.status.text()
    panel.start_button.click()
    task = panel._task
    for _ in range(1000):
        app.processEvents()
        if panel.result is not None and panel.start_button.isEnabled():
            break
        QTest.qWait(10)
    assert panel.result is not None, panel.status.text()
    if isValid(task):
        assert task.wait(10000)
    assert panel.result.total_fins == 4
    assert panel.result.dtc_fins == 4
    assert panel.result.feature_count == 1
    assert len(panel.result.groups) == 1
    assert panel.result.groups[0].fin_count == 4
    assert panel.number_labels["total"].text() == "4"
    assert "vor dem Austausch" in panel.status.text()
    assert "SHARED-BEFORE" in panel.explanation.text()
    assert "SHARED-AFTER" not in panel.explanation.text()

    panel.only_pump_swap.setChecked(False)
    assert panel.result is None
    assert "alle" in panel.status.text().casefold()
    panel.close()
    app.processEvents()
