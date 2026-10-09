"""Cross-source DTC overlap: de-duplicate displays, never erase raw evidence."""

from datetime import datetime

from ntf_insight.analysis.case_clustering import (
    compare_diagnostic_cases, cluster_diagnostic_cases,
)
from ntf_insight.analysis.diagnostic_observations import unique_diagnostic_observations
from ntf_insight.analysis.dtc_clusters import build_dtc_network
from ntf_insight.analysis.timeline import build_timeline
from ntf_insight.domain.case import NTFCase
from ntf_insight.domain.events import DiagnosticEvent, PartReplacement
from ntf_insight.domain.vehicle import Vehicle


FIN = "W1TTEST0000000001"


def _qt(code="P26F100", *, day=2, km=12340, hour=8, session="report-one"):
    return DiagnosticEvent(
        event_id=f"qt-{session}-{code}", vin=FIN, ecu="CPC3", dtc_code=code,
        occurred_at=datetime(2026, 1, day, hour), mileage_km=km,
        session_id=session,
        source_ref=f"raw:quicktest#ecu:1:dtc:{session}",
        freeze_frame={"observed_at_diagnostic_test": True},
    )


def _auto(code="P26F100", *, day=2, km=12340, precision="date", hour=12, row=2):
    return DiagnosticEvent(
        event_id=f"auto-{row}-{code}", vin=FIN, ecu="cpc3", dtc_code=code,
        occurred_at=datetime(2026, 1, day, hour), mileage_km=km,
        time_precision=precision, source_ref=f"raw:autoexport#csv:{row}",
    )


def _case(case_id: str, events: list[DiagnosticEvent]) -> NTFCase:
    return NTFCase(
        case_id=case_id, vehicle=Vehicle(vin=FIN), component_type="Coolant Pump",
        diagnostics=events,
        replacements=[PartReplacement(
            vin=FIN, component_type="Coolant Pump",
            occurred_at=datetime(2026, 1, 6, 10),
        )],
    )


def test_overlap_collapses_to_one_display_observation_with_both_sources() -> None:
    qt, auto = _qt(), _auto()
    case = _case("SAME-READING", [auto, qt])
    records = unique_diagnostic_observations(case.diagnostics)

    assert len(case.diagnostics) == 2  # raw evidence must remain immutable
    assert len(records) == 1
    assert records[0].event.event_id == qt.event_id
    assert records[0].source_refs == (qt.source_ref, auto.source_ref)
    assert records[0].has_cross_source_confirmation
    assert len([row for row in build_timeline(case) if row.kind == "diagnostic"]) == 1
    assert "AutoExport" in next(row.detail for row in build_timeline(case) if row.kind == "diagnostic")
    node = next(n for n in build_dtc_network([case]).nodes if n.key == qt.fault_key)
    assert node.event_count == 1


def test_same_dtc_at_other_mileage_or_day_is_real_new_observation() -> None:
    events = [_qt(), _auto(km=12341, row=3), _auto(day=3, row=4)]
    assert len(unique_diagnostic_observations(events)) == 3


def test_no_mileage_no_cross_source_match() -> None:
    events = [_qt(km=None), _auto(km=None)]
    assert len(unique_diagnostic_observations(events)) == 2


def test_never_merge_two_distinct_quicktests_or_two_autoexport_rows() -> None:
    events = [
        _qt(session="one", hour=8),
        _qt(session="two", hour=9),
        _auto(row=2),
        _auto(row=3),
    ]
    records = unique_diagnostic_observations(events)
    assert len(records) == 2  # one independent AutoExport row per QuickTest
    assert all(item.has_cross_source_confirmation for item in records)
    assert {item.event.session_id for item in records} == {"one", "two"}


def test_precise_autoexport_time_must_match_exactly() -> None:
    a = _qt(hour=8)
    b = _auto(precision="datetime", hour=9)
    assert len(unique_diagnostic_observations([a, b])) == 2
    b.occurred_at = datetime(2026, 1, 2, 8)
    assert len(unique_diagnostic_observations([a, b])) == 1


def test_same_date_and_code_without_provenance_must_not_be_erased() -> None:
    manual = DiagnosticEvent(
        vin=FIN, ecu="CPC3", dtc_code="P26F100",
        occurred_at=datetime(2026, 1, 2, 8), mileage_km=12340,
    )
    assert len(unique_diagnostic_observations([_qt(), manual])) == 2


def test_cross_source_double_report_does_not_change_similarity_or_clustering() -> None:
    case_a = _case("A", [_qt()])
    case_b = _case("B", [_qt()])
    initial = compare_diagnostic_cases(case_a, case_b)
    initial_clusters = cluster_diagnostic_cases([case_a, case_b])

    case_a.diagnostics.append(_auto())
    case_b.diagnostics.append(_auto(row=3))
    assert compare_diagnostic_cases(case_a, case_b) == initial
    assert cluster_diagnostic_cases([case_a, case_b]).clusters == initial_clusters.clusters
