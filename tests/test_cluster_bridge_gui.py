"""Qt smoke test for cluster bridge and recurrence evidence subviews."""
from __future__ import annotations

from datetime import datetime
from PySide6.QtWidgets import QApplication
from ntf_insight.app.widgets.hdbscan_panel import HDBSCANPanel
from ntf_insight.domain.events import DiagnosticEvent
from test_hdbscan_clustering import sample


def test_bridge_panel_and_recursion_audit_reflect_synthetic_case_evidence():
    app = QApplication.instance() or QApplication([])
    cases = sample()
    for case in cases[:12]:
        case.diagnostics.append(DiagnosticEvent(
            event_id=f"bridge-{case.case_id}", vin=case.vin,
            ecu="CPC3", dtc_code="SHARED_TEST_SIGNAL",
            occurred_at=datetime(2026, 4, 29),
        ))
    panel = HDBSCANPanel(cases)
    panel.run_analysis()
    assert panel.result is not None
    assert panel.bridge_model.rowCount() == 1
    assert panel.bridge_model.rows[0][2] == 1
    assert "CPC3" in panel.bridge_summary.text()
    assert panel.recurrence_coverage_model.rowCount() == len(cases)
    assert "ohne belegte Vorher-Sitzung" in panel.recurrence_coverage_summary.text()
    assert panel.latest_recurrence_report.assessable_qec == 0
    panel.close()
    app.processEvents()
