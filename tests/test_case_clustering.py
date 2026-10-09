"""Regression tests for case-to-case similarity without repair-outcome leakage."""

from datetime import datetime, timedelta

from ntf_insight.analysis.case_clustering import (
    all_diagnostic_matches,
    case_match_explanation,
    cluster_insights,
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
    assert "Kein Kurztest nach der letzten" in unknown.outcome
    assert any("Bauteiltausch" in measure for measure in no_recurrence.measures)


def test_component_aliases_match_same_profile() -> None:
    pump = _case("PUMP", ("P1",), component="Coolant Pump")
    german = _case("GERMAN", ("P1",), component="Kühlmittelpumpe")

    result = compare_diagnostic_cases(pump, german)
    assert result.score is not None and result.eligible_for_cluster
    assert cluster_diagnostic_cases([german, pump]).clusters


def test_repair_after_last_post_test_does_not_count_as_verified_resolution() -> None:
    demo = next(case for case in build_demo_cases() if case.case_id == "DEMO-003")
    observation = resolution_observation(demo)

    assert "Kein Kurztest nach der letzten" in observation.outcome
    assert any("ground connection" in text for text in observation.measures)


def test_nearest_neighbours_rank_substantive_diagnostic_evidence_first() -> None:
    left = _case("A", ("P1",))
    strong = _case("B", ("P1",))
    weak = _case("C", ())
    left.repairs.append(
        RepairEvent(
            vin=left.vin, occurred_at=datetime(2026, 1, 2, 9),
            complaint="electric coolant flow vibration unusual",
        )
    )
    weak.repairs.append(
        RepairEvent(
            vin=weak.vin, occurred_at=datetime(2026, 1, 2, 9),
            complaint="electric coolant flow vibration unusual",
        )
    )
    nearest = matches_for("A", all_diagnostic_matches([left, strong, weak]))

    assert nearest[0].right_case_id == "B"
    assert nearest[0].coverage > nearest[1].coverage


def test_last_repair_outcome_uses_followup_after_that_repair() -> None:
    case = _case("AFTER-REPAIR", ("P1",))
    case.diagnostic_sessions.append(
        DiagnosticSession(
            vin=case.vin, occurred_at=datetime(2026, 1, 6, 10), dtc_count=1
        )
    )
    case.diagnostics.append(
        DiagnosticEvent(
            vin=case.vin, occurred_at=datetime(2026, 1, 6, 10),
            ecu="CPC3", dtc_code="P1",
        )
    )
    case.repairs.append(
        RepairEvent(
            vin=case.vin, occurred_at=datetime(2026, 1, 7, 11),
            action="Leitung repariert",
        )
    )
    case.diagnostic_sessions.append(
        DiagnosticSession(
            vin=case.vin, occurred_at=datetime(2026, 1, 9, 10), dtc_count=0
        )
    )

    result = resolution_observation(case)

    assert "nicht erneut beobachtet" in result.outcome
    assert result.has_post_test
    assert "Leitung repariert" in " ".join(result.measures)


def test_cluster_insight_shows_real_representative_and_conservative_strength() -> None:
    a = _case("A", ("P1", "P2"))
    b = _case("B", ("P1", "P2"))
    c = _case("C", ("P3",))
    result = cluster_diagnostic_cases([c, b, a], threshold=0.65)
    profiles = cluster_insights(result, [a, b, c])

    assert len(profiles) == 1
    cluster = profiles[0]
    assert cluster.case_count == 2
    assert cluster.vehicle_count == 2
    assert cluster.representative_case_id == "A"  # deterministic on ties
    assert cluster.common_faults == (("CPC3", "P1"), ("CPC3", "P2"))
    assert cluster.weakest_pair_similarity >= 0.65
    assert cluster.mean_feature_coverage > 0
    assert cluster.cases_with_pre_and_post_test == 0


def test_neighbour_reason_lists_common_and_nonshared_dtcs() -> None:
    a = _case("A", ("P1", "P2"))
    b = _case("B", ("P1", "P3"))
    match = compare_diagnostic_cases(a, b)
    description = case_match_explanation(a, b, match)

    assert "CPC3:P1" in description
    assert "Nur im gewählten Fall: CPC3:P2" in description
    assert "Nur im Vergleichsfall: CPC3:P3" in description
    assert "keine Ursachen-" in description.lower() or "keine Ursachen-" in description


def test_unanchored_case_can_be_reviewed_but_is_not_auto_clustered() -> None:
    a = _case("A", ("P1",))
    b = _case("B", ("P1",))
    b.replacements.clear()
    match = compare_diagnostic_cases(a, b)
    assert match.score is not None and match.score >= 0.65
    assert match.eligible_for_cluster is False
    assert "ohne dokumentierten Tauschanker" in match.reason
    result = cluster_diagnostic_cases([a, b])
    assert not result.clusters
    assert set(result.unassigned) == {"A", "B"}


def test_cluster_profile_is_not_influenced_by_supplier_conclusion_or_repair_outcome() -> None:
    a = _case("A", ("P1",))
    b = _case("B", ("P1",))
    original = cluster_diagnostic_cases([a, b])
    b.supplier_findings.append(
        SupplierFinding(
            vin=b.vin, occurred_at=datetime(2026, 1, 12),
            result=SupplierFindingResult.FAULT_FOUND,
        )
    )
    b.repairs.append(
        RepairEvent(
            vin=b.vin, occurred_at=datetime(2026, 1, 12),
            action="Wiring repaired",
        )
    )
    updated = cluster_diagnostic_cases([a, b])
    assert original.clusters == updated.clusters
    assert original.matches == updated.matches
