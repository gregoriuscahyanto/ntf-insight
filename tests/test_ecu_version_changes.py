"""Synthetic HW/SW version comparison tests; no internal Mercedes data."""
from __future__ import annotations

import os
from datetime import datetime, timedelta

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ntf_insight.analysis.ecu_version_changes import detect_ecu_version_changes
from ntf_insight.analysis.timeline import build_timeline
from ntf_insight.domain.case import NTFCase
from ntf_insight.domain.events import (
    DiagnosticEvent,
    DiagnosticSession,
    ECUStateObservation,
    PartReplacement,
)
from ntf_insight.domain.vehicle import Vehicle


FIN = "W1TTEST0000000001"
START = datetime(2026, 1, 1, 8)


def _state(
    day: int,
    *,
    ecu: str = "CPC3",
    fin: str = FIN,
    hw: str | None = "23/15 000",
    sw: str | None = "25/04 001",
    km: int | None = 10000,
    offset_hours: int = 0,
    precision: str | None = None,
) -> ECUStateObservation:
    state = ECUStateObservation(
        vin=fin, ecu=ecu, occurred_at=START + timedelta(
            days=day, hours=offset_hours
        ),
        mileage_km=km, hardware_version=hw,
        software_version=sw,
        source_ref=f"raw:fictional#ecu:{ecu}:{day}:{offset_hours}",
    )
    if precision:
        state.time_precision = precision
    return state


def test_detects_separate_hw_and_sw_version_differences_per_fin_and_ecu():
    readings = [
        _state(10, hw="23/16 001", sw="25/04 002", km=10500),
        _state(0, hw="23/15 000", sw="25/04 001", km=10000),
        _state(5, hw="23/15 000", sw="25/04 002", km=10200),
        _state(10, ecu="MCM", hw="22/01 000", sw="24/03 000", km=10500),
        _state(0, ecu="MCM", hw="22/01 000", sw="24/03 000", km=10000),
        _state(10, fin="OTHER", hw="33/00 000", sw="99/00 000"),
    ]

    found = detect_ecu_version_changes(readings)
    assert len(found) == 2
    assert [(v.ecu, v.kind) for v in found] == [
        ("CPC3", "sw"), ("CPC3", "hw")
    ]
    sw, hw = found
    assert (sw.previous_version, sw.new_version) == (
        "25/04 001", "25/04 002"
    )
    assert (hw.previous_version, hw.new_version) == (
        "23/15 000", "23/16 001"
    )
    assert sw.last_previous_at == START
    assert sw.first_observed_at == START + timedelta(days=5)
    assert hw.last_previous_at == START + timedelta(days=5)
    assert hw.first_observed_at == START + timedelta(days=10)
    assert sw.current.mileage_km == 10200


def test_first_observation_is_baseline_and_no_changed_sw_when_only_hw_differs():
    assert detect_ecu_version_changes([_state(0)]) == []
    found = detect_ecu_version_changes([
        _state(0), _state(3, hw="23/16 000")
    ])
    assert [(v.kind, v.new_version) for v in found] == [
        ("hw", "23/16 000")
    ]


def test_unknowns_whitespace_and_repeated_identical_reports_do_not_fake_changes():
    assert detect_ecu_version_changes([
        _state(0, hw="23/15 000", sw="25/04 001"),
        _state(2, hw="-", sw=None),
        _state(4, hw=" 23/15   000 ", sw="25/04 001"),
        _state(4, hw="23/15 000", sw="25/04 001"),
        _state(5, hw="unbekannt", sw="n/a"),
    ]) == []


def test_sw_can_be_compared_when_hw_unknown_and_mileage_missing():
    found = detect_ecu_version_changes([
        _state(0, hw=None, sw="25/04 001", km=None),
        _state(3, hw="?", sw="25/04 002", km=None),
    ])
    assert len(found) == 1
    assert found[0].kind == "sw"
    assert found[0].current.mileage_km is None
    assert found[0].previous.mileage_km is None


def test_conflicting_same_timestamp_clears_baseline_instead_of_fake_flash():
    readings = [
        _state(0, sw="v1"),
        _state(1, sw="v2", hw="23/15 000"),
        _state(1, sw="v3", hw="23/15 000"),
        _state(2, sw="v3"),
        _state(3, sw="v4"),
    ]
    found = [x for x in detect_ecu_version_changes(readings) if x.kind == "sw"]
    assert len(found) == 1
    assert (found[0].previous_version, found[0].new_version) == (
        "v3", "v4"
    )
    assert found[0].last_previous_at == START + timedelta(days=2)


def test_same_day_date_only_reports_do_not_assert_unknown_order():
    changes = detect_ecu_version_changes([
        _state(0, sw="v1", precision="date"),
        _state(0, sw="v2", offset_hours=6, precision="date"),
    ])
    assert changes == []


def test_timeline_marks_changes_at_later_observation_not_at_fake_update_date():
    states = [
        _state(0, sw="v1", hw="h1", km=100),
        _state(3, sw="v2", hw="h2", km=130),
    ]
    case = NTFCase(
        case_id="TEST-HW-SW",
        vehicle=Vehicle(vin=FIN),
        component_type="Coolant Pump",
        ecu_states=states,
        diagnostic_sessions=[
            DiagnosticSession(
                vin=FIN, occurred_at=START, mileage_km=100, label="QuickTest"
            ),
        ],
        diagnostics=[
            DiagnosticEvent(
                vin=FIN, occurred_at=START, mileage_km=100,
                ecu="CPC3", dtc_code="P26F100"
            ),
        ],
        replacements=[
            PartReplacement(
                vin=FIN, occurred_at=START + timedelta(days=1),
                mileage_km=110, component_type="Coolant Pump"
            ),
        ],
    )
    entries = build_timeline(case)
    kinds = {entry.kind for entry in entries}
    assert "ecu_hw_change" in kinds
    assert "ecu_sw_change" in kinds
    assert "ecu_state" in kinds
    assert "replacement" in kinds
    assert "diagnostic_session" in kinds
    changes = [
        entry for entry in entries
        if entry.kind in {"ecu_hw_change", "ecu_sw_change"}
    ]
    assert len(changes) == 2
    assert all(entry.occurred_at == START + timedelta(days=3) for entry in changes)
    assert all(entry.interval_start_at == START for entry in changes)
    assert all(entry.interval_start_mileage_km == 100 for entry in changes)
    assert all(entry.mileage_km == 130 for entry in changes)
    assert all("unbekannt" in entry.detail for entry in changes)
    assert any("h1 → h2" in entry.detail for entry in changes)
    assert any("v1 → v2" in entry.detail for entry in changes)


def test_plot_keeps_hw_sw_markers_and_intervals_despite_dtc_filter():
    from PySide6.QtWidgets import QApplication
    from ntf_insight.app.widgets.event_time_plot import EventTimePlot

    app = QApplication.instance() or QApplication([])
    case = NTFCase(
        case_id="SYNTHETIC-1", vehicle=Vehicle(vin=FIN),
        component_type="Coolant Pump",
        ecu_states=[
            _state(0, sw="v1", hw="h1", km=None),
            _state(2, sw="v2", hw="h2", km=110),
        ],
        diagnostics=[
            DiagnosticEvent(
                vin=FIN, occurred_at=START, ecu="CPC3", dtc_code="P26F100"
            ),
        ],
    )
    plot = EventTimePlot()
    plot.set_entries(build_timeline(case))
    plot.set_filter_text("does-not-exist")
    assert not any(x.kind == "diagnostic" for x in plot._visible_entries())
    assert {x.kind for x in plot._visible_entries()} >= {
        "ecu_hw_change", "ecu_sw_change", "ecu_state",
    }
    assert plot._lanes() != []
    plot.set_axis_mode("date")
    plot.resize(1100, plot.minimumHeight())
    plot.show()
    app.processEvents()
    plot.set_axis_mode("mileage")
    assert plot._odometer_bounds() == (10, 210)
    app.processEvents()
    plot.close()
