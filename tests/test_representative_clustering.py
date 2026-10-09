"""Budget constrained representative-cluster tests with only synthetic QEC data."""
from __future__ import annotations

from datetime import datetime

import pytest

from ntf_insight.analysis.case_clustering import cluster_diagnostic_cases
from ntf_insight.analysis.representative_clustering import (
    select_representative_cases,
)
from ntf_insight.domain.case import NTFCase
from ntf_insight.domain.events import (
    DiagnosticEvent, PartReplacement, TipsCaseObservation, SupplierFinding,
)
from ntf_insight.domain.vehicle import Vehicle


def case(name: str, vin: str, faults: tuple[str, ...], *,
         series: str = "214", anchored: bool = True) -> NTFCase:
    swap = datetime(2026, 5, 5, 12)
    return NTFCase(
        case_id=name,
        vehicle=Vehicle(vin=vin, model_series=series),
        component_type="Coolant Pump",
        component_profile_id="coolant_pump",
        replacements=[
            PartReplacement(
                event_id=f"swap-{name}", vin=vin,
                component_type="Coolant Pump", occurred_at=swap,
            )
        ] if anchored else [],
        investigated_replacement_id=f"swap-{name}" if anchored else None,
        diagnostics=[
            DiagnosticEvent(
                event_id=f"{name}:{index}", vin=vin,
                ecu="CPC3", dtc_code=fault,
                occurred_at=datetime(2026, 4, 19, 11),
                source_ref=f"raw:synthetic#csv:{name}:{index}",
            )
            for index, fault in enumerate(faults)
        ],
    )


def sample() -> list[NTFCase]:
    data = [
        case("A1", "W1TTEST0000000011", ("P101", "P102", "A1")),
        case("A2", "W1TTEST0000000012", ("P101", "P102", "A2")),
        case("A3", "W1TTEST0000000013", ("P101", "P102", "A3")),
        case("A4", "W1TTEST0000000014", ("P101", "P102", "A4")),
        case("B1", "W1TTEST0000000021", ("P201", "P202", "B1")),
        case("B2", "W1TTEST0000000022", ("P201", "P202", "B2")),
        case("B3", "W1TTEST0000000023", ("P201", "P202", "B3")),
        case("C", "W1TTEST0000000031", ("P999",)),
        case("MISSING", "W1TTEST0000000032", ()),
        case("UNANCHORED", "W1TTEST0000000033", ("P101", "P102"), anchored=False),
    ]
    return data


def test_two_real_medoid_groups_coverage_abstention_and_budget() -> None:
    cases = sample()
    limited = select_representative_cases(cases, budget=1, minimum_similarity=0.25)
    assert len(limited.clusters) == 1
    assert limited.clusters[0].case_count == 4
    assert limited.covered_count == 4
    assert len(limited.unassigned) == 6

    full = select_representative_cases(cases, budget=12, minimum_similarity=0.25)
    assert len(full.clusters) == 2  # not 12 forced clusters
    assert full.covered_count == 7
    assert len(full.unassigned) == 3
    assert full.missing_pre_diagnostics == 1
    assert full.without_swap_anchor == 1
    assert full.coverage == 0.7
    assert all(group.case_count >= 2 for group in full.clusters)
    assert all(
        rep in group.case_ids
        for group in full.clusters
        for rep in [group.representative_case_id]
    )
    assert all(
        group.weakest_representative_similarity >= 0.25
        for group in full.clusters
    )
    assert {case_id for group in full.clusters for case_id in group.case_ids} == {
        "A1", "A2", "A3", "A4", "B1", "B2", "B3",
    }
    assert select_representative_cases(list(reversed(cases)), budget=12, minimum_similarity=0.25) == full
    assert len(full.pair_scores) == 45


def test_common_high_frequency_dtc_alone_must_not_force_cluster() -> None:
    cases = [
        case(f"C{i}", f"W1TTEST0000000{i:04d}", ("COMMON", f"X{i}"))
        for i in range(10)
    ]
    plan = select_representative_cases(cases, budget=5, minimum_similarity=0.05)
    assert plan.clusters == ()
    assert len(plan.unassigned) == 10
    assert all(
        not pair.eligible
        for pair in plan.pair_scores if pair.shared_faults
    )
    assert any(
        "häufige" in pair.reason for pair in plan.pair_scores
    )


def test_duplicate_dtc_and_post_repair_outcomes_never_change_membership() -> None:
    cases = sample()
    original = select_representative_cases(cases, budget=12, minimum_similarity=0.25)
    cases[0].diagnostics.append(DiagnosticEvent(
        vin=cases[0].vin, ecu="CPC3", dtc_code="P101",
        occurred_at=datetime(2026, 4, 21),
        source_ref="raw:other#ecu:1", session_id="quicktest",
    ))
    cases[1].diagnostics.append(DiagnosticEvent(
        vin=cases[1].vin, ecu="CPC3", dtc_code="NEW-POST",
        occurred_at=datetime(2026, 5, 20),
    ))
    cases[0].supplier_findings.append(SupplierFinding(
        vin=cases[0].vin, occurred_at=datetime(2026, 5, 22),
        failure_mode="Synthetic posttest",
    ))
    cases[1].qec_ssl_end_finding = "Synthetic NTF posttest"
    cases[0].tips_observations.append(TipsCaseObservation(
        vin=cases[0].vin, occurred_at=datetime(2026, 5, 23),
        complaint="Synthetic complaint after swap",
        performed_actions="Changed pump",
    ))
    changed = select_representative_cases(cases, budget=12, minimum_similarity=0.25)
    assert original.representative_ids == changed.representative_ids
    assert original.assigned_case_ids == changed.assigned_case_ids
    assert original.pair_scores == changed.pair_scores
    assert changed.clusters[0].review_warnings != original.clusters[0].review_warnings


def test_untrusted_same_vehicle_episode_and_model_series_never_silently_mixed() -> None:
    left = case("A", "W1TTEST0000000041", ("P101", "P102"))
    right = case("B", "W1TTEST0000000041", ("P101", "P102"))
    other = case("C", "W1TTEST0000000042", ("P101", "P102"), series="999")
    group = select_representative_cases([left, right, other], minimum_similarity=0.3)
    assert len(group.clusters) == 1
    assert group.clusters[0].vehicle_count == 1
    assert "Nur eine FIN" in " ".join(group.clusters[0].review_warnings)
    rejected = next(pair for pair in group.pair_scores
                    if {pair.left_id, pair.right_id} == {"A", "C"})
    assert not rejected.eligible
    assert "Baureihe" in rejected.reason


def test_no_forced_assignment_when_faults_or_anchors_missing() -> None:
    cases = [
        case("U1", "W1TTEST0000000051", ()),
        case("U2", "W1TTEST0000000052", (), anchored=False),
    ]
    plan = select_representative_cases(cases, budget=12)
    assert plan.clusters == ()
    assert plan.coverage == 0
    assert plan.unassigned == ("U1", "U2")
    assert plan.eligible_cases == ()


@pytest.mark.parametrize(
    "kwargs",
    [{"budget": 0}, {"budget": 101}, {"minimum_similarity": 0.0},
     {"minimum_similarity": 1.1}, {"maximum_common_frequency": 0}],
)
def test_configuration_rejects_false_precision(kwargs) -> None:
    with pytest.raises(ValueError):
        select_representative_cases(sample(), **kwargs)


def test_comparison_with_strict_complete_link_is_separate() -> None:
    cases = sample()
    strict = cluster_diagnostic_cases(cases, threshold=0.65)
    plan = select_representative_cases(cases, budget=12, minimum_similarity=0.25)
    assert plan.clusters
    # The two distinct algorithms must NEVER mutate each other's signatures.
    assert strict == cluster_diagnostic_cases(cases, threshold=0.65)
