"""Synthetische QEC-Endbefund- und FIN-Quellen-UI, ohne Echtdaten."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid

from ntf_insight.app.widgets.autoexport_fin_workspace import AutoExportFinWorkspace
from ntf_insight.storage.duckdb_store import DuckDBStore
from ntf_insight.storage.source_knowledge_store import SourceKnowledgeStore
from test_hdbscan_clustering import synthetic


def _fixtures(tmp_path):
    fins = [f"W1TTEST000000{i:04d}" for i in range(1, 4)]
    qec = [
        synthetic(f"QEC-SYN-{i}", "X", i, vin=fins[i])
        for i in range(2)
    ]
    for i, case in enumerate(qec):
        case.qec_reference = case.case_id
        case.qec_part_number = "SYNTH-PART-A" if i == 0 else "SYNTH-PART-B"
        case.qec_ssl_end_finding = (
            "Synthetischer Prüf-Endbefund"
            if i == 0 else "Synthetisch kein Fehler reproduzierbar"
        )
        case.diagnostics = []  # isolate AutoExport DTC eligibility
    source = SourceKnowledgeStore(DuckDBStore(tmp_path / "finding-scope.duckdb"))
    source.save_records("b" * 64, "autoexport_rows", [
        *[
            {"category": "autoexport_dtc", "fin": fin,
             "data": {
                 "EcuNm": "CPC3", "EcuFaultNm": f"SYNTH-{idx}",
                 "DiagStartDt": "2026-04-05",
             }}
            for idx, fin in enumerate(fins)
        ],
        {"category": "autoexport_tips", "fin": fins[0],
         "data": {"CaseId": "TIPS-SYNTH-1"}},
    ])
    return source, qec, fins


def _wait(panel, app):
    task = panel._task
    for _ in range(1200):
        app.processEvents()
        if panel.result is not None and panel.start_button.isEnabled():
            break
        QTest.qWait(10)
    assert panel.result is not None, panel.status.text()
    if task is not None and isValid(task):
        assert task.wait(10000)


def test_default_qec_filter_exact_selection_search_and_source_donuts(tmp_path):
    app = QApplication.instance() or QApplication([])
    source, qec, fins = _fixtures(tmp_path)
    panel = AutoExportFinWorkspace(
        source, qec, source.autoexport_population(),
        quicktest_fins=(fins[0], fins[2]),
    )
    panel.show()
    app.processEvents()
    assert panel.only_qec.isChecked()
    assert not panel.qec_anchor_mode.isChecked()
    assert len(panel.finding_actions) == 2
    assert panel.finding_menu is not None
    assert "2 QEC-Fälle" in panel.finding_summary.text()

    # Ankerbildung must remain selectable even with QEC-only default.
    panel.qec_anchor_mode.setChecked(True)
    assert panel.only_qec.isChecked()
    assert panel.qec_anchor_mode.isChecked()
    panel.qec_anchor_mode.setChecked(False)

    first = qec[0].qec_ssl_end_finding
    panel.finding_actions[first].setChecked(True)
    panel.finding_search.setText("PRÜF-ENDBEFUND")
    assert "1 QEC-Fälle" in panel.finding_summary.text()
    assert "1 unterschiedliche FINs" in panel.finding_summary.text()

    panel.start_button.click()
    _wait(panel, app)
    assert panel.result.total_fins == 1
    assert panel.number_labels["total"].text() == "1"
    assert panel.coverage_donuts["qec"].count == 1
    assert panel.coverage_donuts["tips"].count == 1
    assert panel.coverage_donuts["quicktest"].count == 1
    assert panel.coverage_donuts["part"].count == 1
    assert panel.coverage_donuts["part"].total == 1
    assert sum(panel.donut.values) == 1

    # An alternative part-number selection affects ONLY its donut count.
    part_b = panel.part_number_combo.findData("SYNTH-PART-B")
    assert part_b >= 0
    previous = panel.result
    panel.part_number_combo.setCurrentIndex(part_b)
    assert panel.coverage_donuts["part"].count == 0
    assert panel.result is previous and panel._task is None

    panel.finding_search.clear()
    assert panel.result is None  # no stale result for a new QEC cohort
    panel.finding_actions[first].setChecked(False)
    assert "2 QEC-Fälle" in panel.finding_summary.text()
    panel.only_qec.setChecked(False)
    assert not panel.only_qec.isChecked()
    panel.qec_anchor_mode.setChecked(True)
    assert panel.qec_anchor_mode.isChecked()
    panel.start_button.click()
    _wait(panel, app)
    assert panel.result.total_fins == 3
    assert panel.number_labels["total"].text() == "3"
    assert panel.coverage_donuts["qec"].count == 2
    assert panel.coverage_donuts["tips"].count == 1
    assert panel.coverage_donuts["quicktest"].count == 2
    assert sum(panel.donut.values) == 3
    panel.close()
    app.processEvents()


def test_unusable_dtc_is_not_identical_to_no_dtc_record(tmp_path):
    app = QApplication.instance() or QApplication([])
    a, b = (f"W1TTEST000000{i:04d}" for i in (1, 2))
    cases = [synthetic(f"QEC-{n}", "X", n, vin=fin)
             for n, fin in enumerate((a, b), start=1)]
    for case in cases:
        case.qec_reference = case.case_id
        case.diagnostics = []
        case.qec_ssl_end_finding = "SYNTH-Endbefund"
    source = SourceKnowledgeStore(DuckDBStore(tmp_path / "only-post-swap.db"))
    source.save_records("c" * 64, "autoexport_rows", [
        {"category": "autoexport_dtc", "fin": a, "data": {
            "EcuNm": "CPC3", "EcuFaultNm": "AFTER-SWAP",
            "DiagStartDt": "2026-06-01",
        }},
        {"category": "autoexport_repair", "fin": b,
         "data": {"RepairTypeNmGerman": "SYNTH"}},
    ])
    panel = AutoExportFinWorkspace(source, cases)
    assert panel.only_qec.isChecked()
    panel.start_button.click()
    _wait(panel, app)
    assert panel.result.total_fins == 2
    assert len(panel.result.no_dtc_fins) == 2
    assert panel.result.no_dtc_without_records == 1
    assert panel.result.no_dtc_with_records_excluded == 1
    assert "1 ohne importierten DTC-Eintrag" in panel.summary_note.text()
    assert "1 mit vorhandenen" in panel.summary_note.text()
    assert sum(panel.donut.values) == 2
    panel.close()
    app.processEvents()


def test_qec_finding_exclusion_cannot_admit_post_swap_autoexport_dtc(tmp_path):
    """Even a filtered-out QEC still anchors its FIN's diagnostic history."""
    app = QApplication.instance() or QApplication([])
    source, cases, fins = _fixtures(tmp_path)
    # First FIN has a documented QEC replacement, but its QEC finding
    # will be filtered out below. Post-swap AutoExport rows must not enter
    # the all-FIN feature space as if the vehicle had no repair date.
    source.save_records("e" * 64, "autoexport_rows", [
        {"category": "autoexport_dtc", "fin": fins[0], "data": {
            "EcuNm": "CPC3", "EcuFaultNm": "ONLY-POST-SWAP",
            "DiagStartDt": "2026-07-01",
        }},
    ])
    panel = AutoExportFinWorkspace(
        source, cases, source.autoexport_population(),
    )
    panel.only_qec.setChecked(False)
    panel.finding_search.setText("kein Fehler reproduzierbar")
    assert "1 QEC-Fälle" in panel.finding_summary.text()
    panel.start_button.click()
    _wait(panel, app)
    assert panel.result.total_fins == len(fins)
    assert ("CPC3", "ONLY-POST-SWAP") not in (
        panel.result.dtc_keys_by_fin[fins[0]]
    )
    assert cases[0].vin not in panel.result.qec_links
    assert cases[1].vin in panel.result.qec_links
    panel.close()
    app.processEvents()
