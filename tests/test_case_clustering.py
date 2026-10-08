"""Regression tests for case-to-case similarity without repair-outcome leakage."""

from datetime import datetime, timedelta

from ntf_insight.analysis.case_clustering import (
    all_diagnostic_matches,
    cluster_diagnostic_cases,
    compare_diagnostic_cases,
    matches_for,
    resolution_observation,
    signature_for,
)
from ntf_insight.demo.synthetic_cases import build_demo_cases
from ntf_insight.domain.case import NTFCase
from ntf_insight.domain.events import (
    DiagnosticEvent,
    DiagnosticSession,
    PartReplacement,
    RepairEvent,
    SoftwareEvent,
    SupplierFinding,
)
from ntf_insight.domain.enums import SupplierFindingResult
from ntf_insight.domain.vehicle import Vehicle


def _case(case_id: str, faults: tuple[str, ...], component: str = "Coolant Pump") -> NTFCase:
    vin = f"TEST-VIN-{case_id}"
    pre = datetime(2026, 1, 2, 10)
    replacement_at = datetime(2026, 1, 5, 10)
    return NTFCase(
        case_id=case_id,
        vehicle=Vehicle(vin=vin),
        component_type=component,
        diagnostic_sessions=[DiagnosticSession(vin=vin, occurred_at=pre, dtc_count=len(faults))],
        diagnostics=[
            DiagnosticEvent(vin=vin, ecu="CPC3", dtc_code=code, occurred_at=pre)
            for code in faults
        ],
        replacements=[
            PartReplacement(vin=vin, component_type=component, occurred_at=replacement_at)
        ],
    )


def test_same_pre_intervention_dtc_is_close_even_with_different_outcomes() -> None:
    first = _case("ONE", ("P26F100",))
    second = _case("TWO", ("P26F100",))
    baseline = compare_diagnostic_cases(first, second)
    assert baseline.score is not None and baseline.score >= 0.65
    assert baseline.eligible_for_cluster
    assert baseline.shared_faults == (("CPC3", "P26F100"),)

    second.diagnostics.append(
        DiagnosticEvent(
            vin=second.vin, ecu="CPC3", dtc_code="P1234",
            occurred_at=datetime(2026, 1, 10),
        )
    )
    second.supplier_findings.append(
        SupplierFinding(
            vin=second.vin, occurred_at=datetime(2026, 1, 15),
            result=SupplierFindingResult.FAULT_FOUND,
        )
    )
    second.repairs.append(
        RepairEvent(
            vin=second.vin, occurred_at=datetime(2026, 1, 10),
            action="Erfolgreiche Reparatur",
        )
    )
    second.software_events.append(
        SoftwareEvent(
            vin=second.vin, ecu="CPC3",
            occurred_at=datetime(2026, 1, 11),
            software_version="new",
        )
    )
    assert compare_diagnostic_cases(first, second).score == baseline.score


def test_different_components_are_not_automatically_clustered() -> None:
    pump = _case("P", ("P1",))
    battery = _case("B", ("P1",), component="HV Battery")
    result = compare_diagnostic_cases(pump, battery)
    assert result.score is None
    assert not result.eligible_for_cluster
    clusters = cluster_diagnostic_cases([battery, pump], threshold=0.6)
    assert clusters.clusters == ()
    assert set(clusters.unassigned) == {"P", "B"}


def test_missing_diagnostics_is_not_100_percent_similarity() -> None:
    left = _case("X", ())
    right = _case("Y", ())
    result = compare_diagnostic_cases(left, right)
    assert result.score is None
    assert not result.eligible_for_cluster


def test_matching_control_ecu_only_does_not_create_cluster() -> None:
    left = _case("LEFT", ("P1",))
    right = _case("RIGHT", ("P2",))
    result = compare_diagnostic_cases(left, right)
    assert not result.shared_faults
    assert not result.eligible_for_cluster
    assert not cluster_diagnostic_cases([left, right], threshold=0.1).clusters


def test_hierarchical_complete_link_prevents_chaining() -> None:
    a = _case("A", ("P1",))
    b = _case("B", ("P1", "P2"))
    c = _case("C", ("P2",))
    result = cluster_diagnostic_cases([c, a, b], threshold=0.55)

    assert len(result.clusters) == 1
    assert len(result.clusters[0].case_ids) == 2
    assert len(result.unassigned) == 1
    assert result.clusters[0].case_ids != ("A", "B", "C")


def test_clustering_deterministic_and_neighbours_sorted() -> None:
    cases = [_case("C", ("P3",)), _case("A", ("P1",)), _case("B", ("P1",))]
    one = cluster_diagnostic_cases(cases, threshold=0.65)
    two = cluster_diagnostic_cases(list(reversed(cases)), threshold=0.65)
    assert one.clusters == two.clusters
    assert one.unassigned == two.unassigned
    assert one.clusters[0].case_ids == ("A", "B")
    assert matches_for("A", one.matches)[0].right_case_id == "B"
    assert len(all_diagnostic_matches(cases)) == 3


def test_no_replacement_anchor_is_marked_unanchored() -> None:
    first = _case("A", ("P1",))
    second = _case("B", ("P1",))
    second.replacements = []
    result = compare_diagnostic_cases(first, second)
    assert result.score is not None
    assert "ohne Tauschanker" in result.reason
    assert not signature_for(second).has_replacement_anchor


def test_date_only_same_day_post_fault_not_used_as_pre() -> None:
    candidate = _case("B", ("P1",))
    anchor = candidate.replacements[0]
    candidate.diagnostics.append(
        DiagnosticEvent.model_validate({
            "vin": candidate.vin,
            "ecu": "MCM",
            "dtc_code": "U9999",
            "occurred_at": anchor.occurred_at + timedelta(hours=1),
            "time_precision": "date",
        })
    )
    assert ("MCM", "U9999") not in signature_for(candidate).faults


def test_resolution_observation_is_not_claimed_proven_success() -> None:
    demos = {case.case_id: case for case in build_demo_cases()}
    recurred = resolution_observation(demos["DEMO-001"])
    no_recurrence = resolution_observation(demos["DEMO-002"])
    unknown = resolution_observation(demos["DEMO-005"])

    assert "erneut beobachtet" in recurred.outcome
    assert "nicht erneut beobachtet" in no_recurrence.outcome
    assert "nicht überprüfbar" in unknown.outcome
    assert any("Bauteiltausch" in measure for measure in no_recurrence.measures)
