"""Synthetic regression tests for issue #36 CPC3 software and pump context."""
from __future__ import annotations

import os
from datetime import datetime, timedelta

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from ntf_insight.analysis.cpc3_software import assess_cpc3_software
from ntf_insight.app.widgets.cpc3_software_panel import CPC3SoftwarePanel
from ntf_insight.domain.case import NTFCase
from ntf_insight.domain.events import (
    DiagnosticEvent, DiagnosticSession, ECUStateObservation,
    PartReplacement, SoftwareEvent,
)
from ntf_insight.domain.vehicle import Vehicle
from ntf_insight.storage.duckdb_store import DuckDBStore
from ntf_insight.storage.source_knowledge_store import SourceKnowledgeStore


FIN = "W1TTEST0000000001"
BASE = datetime(2026, 2, 1, 8)


def _state(
    day: int, sw: str | None, *, session: str | None = None,
    precision: str = "datetime", fin: str = FIN, hour: int = 0,
) -> ECUStateObservation:
    return ECUStateObservation(
        vin=fin, ecu="CPC3", occurred_at=BASE + timedelta(
            days=day, hours=hour,
        ),
        software_version=sw, session_id=session,
        source_ref=f"raw:SYNTHETIC#ecu:{day}:{hour}:{session or 'none'}",
        time_precision=precision,
    )


def _case(
    *,
    states=(), sessions=(), diagnostics=(), swap_day: int | None = 5,
    actions=(),
) -> NTFCase:
    replacements = []
    if swap_day is not None:
        replacements.append(PartReplacement(
            vin=FIN, component_type="Coolant Pump",
            occurred_at=BASE + timedelta(days=swap_day),
            time_precision="date",
        ))
    return NTFCase(
        case_id="QEC-SYNTH-CPC3", vehicle=Vehicle(vin=FIN),
        component_type="Coolant Pump",
        ecu_states=list(states), diagnostics=list(diagnostics),
        diagnostic_sessions=list(sessions), replacements=replacements,
        software_events=list(actions),
    )


def _quicktest_session(day: int, name: str) -> DiagnosticSession:
    return DiagnosticSession(
        vin=FIN, occurred_at=BASE + timedelta(days=day),
        session_id=name, source_is_complete_quicktest=True,
    )


def _fault(day: int, session: str, code: str, ecu: str = "CPC3"):
    return DiagnosticEvent(
        vin=FIN, ecu=ecu, dtc_code=code, session_id=session,
        occurred_at=BASE + timedelta(days=day),
    )


def test_known_cpc3_before_and_after_pump_swap_with_complete_qt_behavior():
    case = _case(
        states=(_state(0, "SW-A", session="before"),
                _state(10, "SW-B", session="after")),
        sessions=(_quicktest_session(0, "before"),
                  _quicktest_session(10, "after")),
        diagnostics=(
            _fault(0, "before", "PUMP-1"),
            _fault(0, "before", "SHARED"),
            _fault(10, "after", "SHARED"),
            _fault(10, "after", "NEW-2"),
            _fault(10, "after", "UNRELATED", ecu="MCM"),
        ),
    )
    result = assess_cpc3_software(case)
    assert result.last_before_swap.software_version == "SW-A"
    assert result.first_after_swap.software_version == "SW-B"
    assert result.replacement_day.isoformat() == "2026-02-06"
    assert len(result.versions) == 2
    assert len(result.changes) == 1
    assert result.changes[0].comparable_tests
    assert result.changes[0].new_dtcs == ("NEW-2",)
    assert result.changes[0].absent_in_new_test == ("PUMP-1",)


def test_same_day_sw_and_no_anchor_are_not_misclassified_as_failure_state():
    case = _case(
        states=(_state(5, "SW-DURING"), _state(7, "SW-AFTER")),
    )
    result = assess_cpc3_software(case)
    assert result.on_swap_day == 1
    assert result.last_before_swap is None
    assert result.first_after_swap.software_version == "SW-AFTER"
    without_anchor = assess_cpc3_software(_case(
        states=(_state(5, "SW-DURING"),), swap_day=None,
    ))
    assert without_anchor.replacement_day is None
    assert without_anchor.last_before_swap is None
    assert without_anchor.first_after_swap is None


def test_conflicts_unknowns_and_same_day_date_only_do_not_create_false_sw_change():
    case = _case(states=(
        _state(0, "SW-X", precision="date"),
        _state(0, "SW-Y", precision="date", hour=3),
        _state(2, "n/a"),
        _state(8, "SW-Z"),
    ))
    result = assess_cpc3_software(case)
    assert result.before_ambiguous
    assert result.last_before_swap is None
    assert len(result.ambiguous_days) == 1
    assert result.changes == ()


def test_autoexport_is_only_positive_dtc_evidence_not_complete_absence():
    case = _case(swap_day=5)
    source_rows = [
        {
            "diag_date": "2026-02-01",
            "software_version": "SW-A",
            "dtc_code": code,
            "source_ref": f"raw:CSV1#csv:row:{index}",
        }
        for index, code in enumerate(("PUMP-1", "PUMP-2"), 1)
    ]
    source_rows.append({
        "diag_timestamp": "2026-02-11T10:15:00Z",
        "software_version": "SW-B",
        "dtc_code": "PUMP-2",
        "source_ref": "raw:CSV1#csv:row:3",
    })
    result = assess_cpc3_software(
        case, autoexport_rows=source_rows, truncated=True,
    )
    assert result.observation_count == 2
    assert len(result.changes) == 1
    assert result.last_before_swap.software_version == "SW-A"
    assert result.first_after_swap.software_version == "SW-B"
    assert result.changes[0].new_dtcs is None
    assert result.changes[0].absent_in_new_test is None
    assert not result.changes[0].comparable_tests
    assert result.versions[0].observed_dtcs == ("PUMP-1", "PUMP-2")
    assert result.truncated


def test_conflicting_precise_sw_at_same_moment_has_no_boundary_or_change():
    result = assess_cpc3_software(_case(states=(
        _state(0, "SW-A"),
        _state(0, "SW-B"),
        _state(9, "SW-B"),
    )))
    assert result.before_ambiguous
    assert result.last_before_swap is None
    assert result.changes == ()


def test_manual_cpc3_software_event_is_not_invented_from_version_labels():
    case = _case(actions=(
        SoftwareEvent(
            vin=FIN, ecu="CPC3", occurred_at=BASE + timedelta(days=2),
            software_version="SW-RELEASE", action="Werkstatt: SW programmiert",
        ),
        SoftwareEvent(
            vin=FIN, ecu="MCM", occurred_at=BASE + timedelta(days=4),
            software_version="OTHER", action="MCM SW",
        ),
    ))
    result = assess_cpc3_software(case)
    assert not result.versions and not result.changes
    assert len(result.documented_actions) == 1
    assert result.documented_actions[0].action == "Werkstatt: SW programmiert"


def test_local_autoexport_db_read_is_fin_scoped_cpc3_only(tmp_path):
    store = SourceKnowledgeStore(DuckDBStore(tmp_path / "cpc3.duckdb"))
    store.save_records("a" * 64, "autoexport_rows", [
        {"category": "autoexport_dtc", "fin": fin,
         "data": {
             "EcuNm": ecu, "EcuSwVersionTxt": version,
             "DiagStartDt": "2026-02-01", "EcuFaultNm": "PUMP-1",
         }}
        for fin, ecu, version in (
            (FIN, "CPC3", "SW-1"),
            ("MBC" + FIN, "CPC3", "SW-1"),
            ("W1TTEST0000000002", "CPC3", "OTHER-FIN"),
            (FIN, "MCM", "OTHER-ECU"),
            (FIN, "CPC3", ""),
        )
    ])
    rows, truncated = store.cpc3_software_rows_for_fin(FIN)
    assert len(rows) == 2 and not truncated
    assert all(item["software_version"] == "SW-1" for item in rows)
    subset, cap = store.cpc3_software_rows_for_fin(FIN, limit=1)
    assert len(subset) == 1 and cap
    assert store.cpc3_software_rows_for_fin("UNKNOWN") == ([], False)


def test_cpc3_widget_shows_unproven_failure_state_and_no_false_causality(tmp_path):
    app = QApplication.instance() or QApplication([])
    case = _case(
        states=(_state(0, "SW-A", session="before"),
                _state(10, "SW-B", session="after")),
        sessions=(_quicktest_session(0, "before"),
                  _quicktest_session(10, "after")),
        diagnostics=(_fault(0, "before", "PUMP-1"),
                     _fault(10, "after", "NEW-2")),
    )
    panel = CPC3SoftwarePanel()
    panel.show()
    app.processEvents()
    panel.show_case(case)
    assert "SW-A" in panel.swap_summary.text()
    assert "SW-B" in panel.swap_summary.text()
    assert "nicht automatisch belegt" in panel.swap_summary.text()
    assert "Release-Notes" in panel.evidence_note.text()
    assert panel.version_model.rowCount() == 2
    assert panel.change_model.rowCount() == 1
    assert panel.change_model.rows[0][4] == "NEW-2"
    assert panel.change_model.rows[0][5] == "PUMP-1"
    panel.clear()
    assert panel.change_model.rowCount() == 0
    panel.close()
