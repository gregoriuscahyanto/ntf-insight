"""Regression tests for QEC vs AutoExport repair-date reconciliation.

All VINs, parts and repair events in these tests are fictional.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ntf_insight.analysis.replacement_dates import compare_replacement_dates
from ntf_insight.analysis.timeline import build_timeline
from ntf_insight.app.widgets.event_time_plot import EventTimePlot
from ntf_insight.domain.case import NTFCase
from ntf_insight.domain.events import (
    DiagnosticEvent,
    DiagnosticSession,
    ECUStateObservation,
    PartReplacement,
    RepairEvent,
    SupplierFinding,
)
from ntf_insight.domain.vehicle import Vehicle
from ntf_insight.storage.duckdb_store import DuckDBStore
from ntf_insight.storage.source_knowledge_store import SourceKnowledgeStore


VIN = "W1TTEST0000000001"
PART = "A000123"


def _case() -> NTFCase:
    when = datetime(2026, 2, 12, 12)
    replacement = PartReplacement(
        vin=VIN,
        component_type="Coolant Pump",
        occurred_at=when,
        time_precision="date",
        mileage_km=12345,
        old_part_number="A 000 123",
        source_ref="raw:" + "a" * 64 + "#Schadteile QEC!2",
    )
    return NTFCase(
        case_id="QEC-TEST",
        vehicle=Vehicle(vin=VIN),
        component_type="Coolant Pump",
        qec_part_number=PART,
        replacements=[replacement],
        investigated_replacement_id=replacement.event_id,
        diagnostics=[
            DiagnosticEvent(
                vin=VIN, ecu="CPC3", dtc_code="P26F100",
                occurred_at=when - timedelta(days=2),
                mileage_km=12312,
            ),
            DiagnosticEvent(
                vin=VIN, ecu="AVAS", dtc_code="U012300",
                occurred_at=when + timedelta(days=2),
                mileage_km=None,
            ),
        ],
        diagnostic_sessions=[
            DiagnosticSession(
                vin=VIN, occurred_at=when - timedelta(days=2),
                mileage_km=12312, label="QuickTest",
            ),
        ],
        ecu_states=[
            ECUStateObservation(
                vin=VIN, ecu="CPC3",
                occurred_at=when - timedelta(days=2),
                software_version="25/04 001",
                mileage_km=12312,
            ),
        ],
        supplier_findings=[
            SupplierFinding(
                vin=VIN, occurred_at=when + timedelta(days=20),
                failure_mode="Befund nicht reproduzierbar",
                mileage_km=None,
            ),
        ],
    )


def _knowledge(tmp_path, *rows: dict) -> SourceKnowledgeStore:
    store = SourceKnowledgeStore(DuckDBStore(tmp_path / "cases.duckdb"))
    records = [
        {
            "category": "autoexport_repair",
            "record_number": i,
            "source_location": f"csv:row:{i}",
            "fin": VIN,
            "data": {
                "Fin": VIN,
                "RepairDt": row.get("date", "2026-02-15"),
                "KmReadingNum": row.get("km", 12345),
                "PartLetterCd": row.get("part", "A 000 123"),
                "PartNmDeu": "KUEHLMITTELPUMPE",
                "RepairTypeNmGerman": "Rep. mit Teilen",
            },
        }
        for i, row in enumerate(rows, start=1)
    ]
    store.save_records("b" * 64, "autoexport_rows", records)
    return store


def test_matching_fin_part_and_mileage_show_both_dates_without_changing_anchor(tmp_path):
    case = _case()
    qec_id = case.investigated_replacement_id
    knowledge = _knowledge(tmp_path, {"date": "2026-02-15", "km": "12345"})
    comparison = compare_replacement_dates(case, knowledge)

    assert comparison.qec_anchor is case.replacements[0]
    assert comparison.status == "Datumsabweichung +3 Tage – prüfen"
    assert comparison.preferred_candidate is not None
    assert comparison.preferred_candidate.mileage_difference_km == 0
    assert comparison.preferred_candidate.repair.occurred_at.date().isoformat() == "2026-02-15"
    assert case.investigated_replacement_id == qec_id
    assert len(case.replacements) == 1

    entries = build_timeline(case, comparison)
    qec = [event for event in entries if event.kind == "replacement"]
    candidates = [
        event for event in entries if event.kind == "replacement_candidate"
    ]
    assert len(qec) == len(candidates) == 1
    assert qec[0].occurred_at.date().isoformat() == "2026-02-12"
    assert candidates[0].occurred_at.date().isoformat() == "2026-02-15"
    assert candidates[0].mileage_km == qec[0].mileage_km
    assert "AutoExport" in candidates[0].title
    assert "vorläufig" in qec[0].title
    assert candidates[0].source_ref.startswith("raw:")


def test_no_candidate_for_other_part_even_at_same_vin_and_date(tmp_path):
    case = _case()
    knowledge = _knowledge(tmp_path, {"date": "2026-02-12", "part": "A000999"})
    result = compare_replacement_dates(case, knowledge)
    assert result.candidates == ()
    assert result.status == "AutoExport-Kandidat fehlt"


def test_multiple_matching_workshop_visits_are_not_confirmed(tmp_path):
    case = _case()
    knowledge = _knowledge(
        tmp_path,
        {"date": "2026-02-10", "km": 12340},
        {"date": "2026-02-17", "km": 12345},
    )
    result = compare_replacement_dates(case, knowledge)
    assert len(result.candidates) == 2
    assert result.preferred_candidate is None
    assert "Mehrdeutig" in result.status
    assert len([
        e for e in build_timeline(case, result)
        if e.kind == "replacement_candidate"
    ]) == 2


def test_mileage_conflict_and_distant_unanchored_rows_are_not_matched(tmp_path):
    case = _case()
    knowledge = _knowledge(
        tmp_path,
        {"date": "2026-02-12", "km": 54321},
        {"date": "2023-01-01", "km": 12345},
    )
    assert compare_replacement_dates(case, knowledge).candidates == ()


def test_case_repairs_without_knowledge_are_considered_for_older_imports():
    case = _case()
    case.repairs.append(RepairEvent(
        vin=VIN, occurred_at=datetime(2026, 2, 16),
        mileage_km=12345, action="Rep. mit Teilen",
        damaged_part_number="A000123",
        source_ref="raw:" + "c" * 64 + "#csv:10",
    ))
    result = compare_replacement_dates(case)
    assert len(result.candidates) == 1
    assert result.candidates[0].date_difference_days == 4
    # The associated workshop event should be shown only once as a candidate.
    events = build_timeline(case, result)
    assert sum(event.kind == "replacement_candidate" for event in events) == 1
    assert sum(event.kind == "repair" for event in events) == 0


def test_plot_filter_only_hides_nonmatching_dtcs_not_other_events(tmp_path):
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    case = _case()
    comparison = compare_replacement_dates(
        case, _knowledge(tmp_path, {"date": "2026-02-15"})
    )
    all_events = build_timeline(case, comparison)
    plot = EventTimePlot()
    plot.set_entries(all_events)
    plot.set_filter_text("CPC3")
    visible = plot._visible_entries()

    assert len([
        e for e in visible if e.kind == "diagnostic"
    ]) == 1
    assert all(
        e.kind == "diagnostic" or e in visible for e in all_events
    )
    assert {e.kind for e in visible} >= {
        "diagnostic_session", "ecu_state", "replacement",
        "replacement_candidate", "supplier",
    }
    plot.set_filter_text("DOES-NOT-EXIST")
    assert not any(e.kind == "diagnostic" for e in plot._visible_entries())
    assert any(e.kind == "diagnostic_session" for e in plot._visible_entries())
    assert any(e.kind == "supplier" for e in plot._visible_entries())
    assert any(e.kind == "replacement_candidate" for e in plot._visible_entries())

    plot.set_axis_mode("mileage")
    assert plot.axis_mode == "mileage"
    assert plot._odometer_bounds() is not None
    assert any(e.mileage_km is None for e in plot._visible_entries())
    plot.resize(950, plot.minimumHeight())
    plot.show()
    app.processEvents()
    plot.set_axis_mode("date")
    assert plot.axis_mode == "date"
    with pytest.raises(ValueError):
        plot.set_axis_mode("invented")
    plot.close()


def test_plot_with_only_unknown_mileage_still_displays_events():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    plot = EventTimePlot()
    case = _case()
    for item in case.diagnostics:
        item.mileage_km = None
    for item in case.diagnostic_sessions:
        item.mileage_km = None
    for item in case.ecu_states:
        item.mileage_km = None
    for item in case.replacements:
        item.mileage_km = None
    plot.set_entries(build_timeline(case))
    plot.set_axis_mode("mileage")
    assert plot._odometer_bounds() is None
    plot.resize(900, plot.minimumHeight())
    plot.show()
    app.processEvents()
    plot.close()
