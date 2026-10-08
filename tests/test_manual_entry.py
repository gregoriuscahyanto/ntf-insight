from datetime import datetime

import pytest

from ntf_insight.analysis.recurrence import analyze_recurrence
from ntf_insight.domain.case import NTFCase
from ntf_insight.domain.events import (
    DiagnosticEvent,
    DiagnosticSession,
    PartReplacement,
    RepairEvent,
)
from ntf_insight.domain.manual import ManualAction
from ntf_insight.domain.vehicle import Vehicle
from ntf_insight.ingestion.manual_entry import ManualCaseService, ManualEntryError
from ntf_insight.storage.duckdb_store import DuckDBStore


def _service(tmp_path):
    store = DuckDBStore(tmp_path / "test.duckdb")
    return ManualCaseService(store, actor="test_user"), store


def _case(case_id="CASE-001", vin="W1TTEST0000000001"):
    return NTFCase(case_id=case_id, vehicle=Vehicle(vin=vin), component_type="Coolant Pump")


def test_manual_case_persists_and_survives_restart(tmp_path):
    service, store = _service(tmp_path)
    created = service.create_case(_case())
    assert created.case_id == "CASE-001"
    assert store.get_case("CASE-001").vin == "W1TTEST0000000001"

    restarted = DuckDBStore(tmp_path / "test.duckdb")
    assert restarted.get_case("CASE-001").case_id == "CASE-001"
    assert restarted.load_manual_changes("CASE-001")[0].action == ManualAction.CREATE_CASE


def test_same_vin_may_have_multiple_cases_but_case_id_must_be_unique(tmp_path):
    service, store = _service(tmp_path)
    service.create_case(_case())
    service.create_case(_case(case_id="CASE-002"))
    assert len(store.load_cases()) == 2
    with pytest.raises(ManualEntryError, match="bereits vergeben"):
        service.create_case(_case())


def test_manual_dtc_sessions_and_swap_drive_recurrence(tmp_path):
    service, store = _service(tmp_path)
    service.create_case(_case())
    before = datetime(2026, 1, 3, 10)
    after = datetime(2026, 1, 11, 10)
    replacement_at = datetime(2026, 1, 7, 10)
    service.add_event(
        "CASE-001", "diagnostic_session",
        DiagnosticSession(vin=_case().vin, occurred_at=before, mileage_km=1000, dtc_count=1),
    )
    pre_session = store.get_case("CASE-001").diagnostic_sessions[0]
    service.add_event(
        "CASE-001", "diagnostic",
        DiagnosticEvent(vin=_case().vin, occurred_at=before, mileage_km=1000, session_id=pre_session.session_id, ecu="CPC3", dtc_code="P26F100"),
    )
    service.add_event(
        "CASE-001", "replacement",
        PartReplacement(vin=_case().vin, occurred_at=replacement_at, mileage_km=1100, component_type="Coolant Pump"),
    )
    service.add_event(
        "CASE-001", "diagnostic_session",
        DiagnosticSession(vin=_case().vin, occurred_at=after, mileage_km=1150, dtc_count=1),
    )
    post_session = store.get_case("CASE-001").diagnostic_sessions[-1]
    service.add_event(
        "CASE-001", "diagnostic",
        DiagnosticEvent(vin=_case().vin, occurred_at=after, mileage_km=1150, session_id=post_session.session_id, ecu="CPC3", dtc_code="P26F100"),
    )
    case = store.get_case("CASE-001")
    assert case.investigated_replacement_id == case.replacements[0].event_id
    assert case.diagnostics[0].source_ref.startswith("manual:")
    assert analyze_recurrence(case).has_recurrence
    assert len(store.load_manual_changes("CASE-001")) == 6


def test_known_clean_post_test_is_not_missing_test(tmp_path):
    service, store = _service(tmp_path)
    service.create_case(_case())
    for kind, event in [
        ("diagnostic_session", DiagnosticSession(vin=_case().vin, occurred_at=datetime(2026, 1, 1), dtc_count=1)),
        ("diagnostic", DiagnosticEvent(vin=_case().vin, occurred_at=datetime(2026, 1, 1), ecu="CPC3", dtc_code="P1")),
        ("replacement", PartReplacement(vin=_case().vin, occurred_at=datetime(2026, 1, 2), component_type="Coolant Pump")),
        ("diagnostic_session", DiagnosticSession(vin=_case().vin, occurred_at=datetime(2026, 1, 3), dtc_count=0)),
    ]:
        service.add_event("CASE-001", kind, event)
    result = analyze_recurrence(store.get_case("CASE-001"))
    assert result.assessable
    assert not result.has_recurrence


def test_correction_keeps_original_snapshot_in_audit(tmp_path):
    service, store = _service(tmp_path)
    service.create_case(_case())
    first = RepairEvent(vin=_case().vin, occurred_at=datetime(2026, 1, 3), notes="Ursprünglicher Text")
    service.add_event("CASE-001", "repair", first)
    corrected = first.model_copy(update={"notes": "Korrigierter Text"})
    service.correct_event("CASE-001", "repair", first.event_id, corrected)

    case = store.get_case("CASE-001")
    audit = store.load_manual_changes("CASE-001")[-1]
    assert case.repairs[0].notes == "Korrigierter Text"
    assert case.repairs[0].source_ref.startswith("manual:correction:")
    assert audit.action == ManualAction.CORRECT_EVENT
    assert "Ursprünglicher Text" in audit.before_json
    assert "Korrigierter Text" in audit.after_json
    assert audit.actor == "test_user"


def test_unsafe_manual_changes_are_rejected(tmp_path):
    service, store = _service(tmp_path)
    service.create_case(_case())
    with pytest.raises(ManualEntryError, match="FIN"):
        service.add_event("CASE-001", "repair", RepairEvent(vin="OTHER", occurred_at=datetime(2026, 1, 1)))
    with pytest.raises(ManualEntryError, match="Kurztest"):
        service.add_event(
            "CASE-001", "diagnostic",
            DiagnosticEvent(vin=_case().vin, occurred_at=datetime(2026, 1, 1), ecu="CPC3", dtc_code="P1", session_id="nonexistent"),
        )
    with pytest.raises(ManualEntryError, match="Demo"):
        service.add_event("DEMO-001", "repair", RepairEvent(vin=_case().vin, occurred_at=datetime(2026, 1, 1)))
    assert not store.get_case("CASE-001").repairs
    assert len(store.load_manual_changes("CASE-001")) == 1
