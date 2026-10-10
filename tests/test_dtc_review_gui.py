"""Qt smoke for manual DTC mark and instant FIN-cluster review priority."""
from __future__ import annotations

from dataclasses import replace
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from ntf_insight.analysis.autoexport_fin_patterns import cluster_autoexport_fins
from ntf_insight.app.pages.dtc_page import DTCExplorerPage
from ntf_insight.app.widgets.autoexport_fin_workspace import AutoExportFinWorkspace
from ntf_insight.demo.synthetic_cases import build_demo_repository
from ntf_insight.demo.synthetic_reference import build_demo_reference_repository
from ntf_insight.storage.dtc_review_store import DtcReviewStore
from ntf_insight.storage.duckdb_store import DuckDBStore
from ntf_insight.storage.source_knowledge_store import SourceKnowledgeStore
from test_autoexport_fin_patterns import _synthetic_population


def _mark_page(tmp_path):
    db = DuckDBStore(tmp_path / "synthetic-review.duckdb")
    sources = SourceKnowledgeStore(db)
    marks = DtcReviewStore(db)
    fins, codes, *_ = _synthetic_population()
    rows = []
    for fin, pairs in codes.items():
        for ecu, dtc in pairs:
            rows.append({
                "category": "autoexport_dtc", "fin": fin,
                "data": {
                    "EcuNm": ecu, "EcuFaultNm": dtc,
                    "EcuFaultTxt": "Synthetic pump test",
                },
            })
    sources.save_records("b" * 64, "autoexport_rows", rows)
    return sources, marks, fins, codes


def test_explorer_can_mark_non_qec_autoexport_dtc_and_reopen(tmp_path):
    app = QApplication.instance() or QApplication([])
    sources, marks, _fins, _codes = _mark_page(tmp_path)
    repo = build_demo_repository()
    reference = build_demo_reference_repository()
    page = DTCExplorerPage(
        repo, reference, source_knowledge=sources, review_store=marks,
    )
    matches = [
        i for i, row in enumerate(page.model.rows)
        if row[1:3] == ("CPC3", "SYNT-A")
    ]
    assert len(matches) == 1
    source_index = page.model.index(matches[0], 0)
    page.table.setCurrentIndex(page.proxy.mapFromSource(source_index))
    app.processEvents()
    assert page.review_button.isEnabled()
    assert page.review_button.text() == "★ Für Pumpenprüfung markieren"
    page.note_input.setText("Synthetic review reason")
    page.review_button.click()
    assert page.model.rows[matches[0]][0] == "★"
    assert ("CPC3", "SYNT-A") in marks.list_marks()
    assert marks.list_marks()[("CPC3", "SYNT-A")].note == (
        "Synthetic review reason"
    )

    reopened = DTCExplorerPage(
        repo, reference, source_knowledge=sources,
        review_store=DtcReviewStore(marks.store),
    )
    assert any(
        row[0] == "★" and row[1:3] == ("CPC3", "SYNT-A")
        for row in reopened.model.rows
    )
    source_row = next(
        i for i, row in enumerate(reopened.model.rows)
        if row[1:3] == ("CPC3", "SYNT-A")
    )
    reopened.table.setCurrentIndex(
        reopened.proxy.mapFromSource(reopened.model.index(source_row, 0))
    )
    reopened.review_button.click()
    assert ("CPC3", "SYNT-A") not in marks.list_marks()
    page.close()
    reopened.close()
    app.processEvents()


def test_review_marks_prioritize_groups_without_running_hdbscan_again(tmp_path):
    app = QApplication.instance() or QApplication([])
    _sources, marks, fins, codes = _mark_page(tmp_path)
    panel = AutoExportFinWorkspace(None, [], review_store=marks)
    result = cluster_autoexport_fins(fins, codes)
    ready = replace(
        result,
        dtc_keys_by_fin={
            fin: tuple(sorted(set(pairs))) for fin, pairs in codes.items()
        },
    )
    panel._show_result(ready)
    app.processEvents()
    assert panel.number_labels["total"].text() == "23"
    assert panel.donut.values == (20, 1, 2)
    assert panel._task is None
    assert "0 Cluster hoch" in panel.priority_note.text()

    marks.mark("cpc3", "synt-a", relevant=True, note="Synthetic reason")
    panel.refresh_review_priorities()
    assert panel.result is ready
    assert panel._task is None
    assert "1 Cluster hoch" in panel.priority_note.text()
    assert panel.group_model.rows[0][1] == "Hohe Pruefprioritaet"
    assert "Prüfpriorität: Hohe Pruefprioritaet" in panel.explanation.text()
    assert "★ CPC3:SYNT-A" in panel.explanation.text()
    assert panel.donut.values == (20, 1, 2)
    assert panel.number_labels["groups"].text() == "2"

    marks.mark("CPC3", "SYNT-A", relevant=False)
    panel.refresh_review_priorities()
    assert panel.result is ready
    assert "0 Cluster hoch" in panel.priority_note.text()
    assert panel.donut.values == (20, 1, 2)
    panel.close()
    app.processEvents()
