"""Evidence-homogeneous clustering, without any fixed number of groups."""
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


def case(
    name: str, vin: str, faults: tuple[str, ...], *,
    series: str = "214", anchored: bool = True,
) -> NTFCase:
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
                event_id=f"{name}:{index}", vin=vin, ecu="CPC3",
                dtc_code=fault, occurred_at=datetime(2026, 4, 19, 11),
                source_ref=f"raw:synthetic#csv:{name}:{index}",
            ) for index, fault in enumerate(faults)
        ],
    )


def sample() -> list[NTFCase]:
    return [
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


def test_automatic_groups_have_no_fixed_count_and_reject_singletons() -> None:
    cases = sample()
    plan = select_representative_cases(cases, minimum_similarity=0.45)
    assert len(plan.clusters) == 2
    assert {frozenset(c.case_ids) for c in plan.clusters} == {
        frozenset(("A1", "A2", "A3", "A4")),
        frozenset(("B1", "B2", "B3")),
    }
    assert plan.covered_count == 7
    assert plan.coverage == 0.7
    assert plan.unassigned == ("C", "MISSING", "UNANCHORED")
    assert plan.missing_pre_diagnostics == 1
    assert plan.without_swap_anchor == 1
    assert plan.screening_population == 8
    assert all(cluster.vehicle_count == cluster.case_count for cluster in plan.clusters)
    assert all(cluster.common_faults for cluster in plan.clusters)
    assert all(cluster.weakest_internal_similarity >= 0.45 for cluster in plan.clusters)
    assert all(cluster.weakest_representative_similarity >= 0.45
               for cluster in plan.clusters)
    assert all(cluster.mean_similarity < 1 for cluster in plan.clusters)
    assert select_representative_cases(
        list(reversed(cases)), minimum_similarity=0.45
    ) == plan
    assert len(plan.pair_scores) == 45


def test_complete_link_prevents_medoid_star_with_weak_internal_pair() -> None:
    cases = [
        case("A", "W1TTEST0000000041", ("P100", "P200")),
        case("B", "W1TTEST0000000042", ("P100", "P200", "P300")),
        case("C", "W1TTEST0000000043", ("P100", "P300")),
    ]
    plan = select_representative_cases(cases)
    assert len(plan.clusters) == 1
    assert plan.clusters[0].case_count == 2
    assert plan.covered_count == 2
    assert len(plan.unassigned) == 1
    # A-C share only a frequent code and cannot be joined via B.
    ac = next(p for p in plan.pair_scores
              if {p.left_id, p.right_id} == {"A", "C"})
    assert not ac.eligible
    for cluster in plan.clusters:
        pairs = [
            p for p in plan.pair_scores
            if p.left_id in cluster.case_ids and p.right_id in cluster.case_ids
        ]
        assert all(p.eligible and p.similarity >= plan.minimum_similarity
                   for p in pairs)
        assert min(p.similarity for p in pairs) == pytest.approx(
            cluster.weakest_internal_similarity, abs=1e-4
        )


def test_high_frequency_dtc_denominator_excludes_missing_diagnoses() -> None:
    # Five out of ten *observed* cases share U1127, even though there are
    # 20 QEC references in total. 50%, not an artificial 25%.
    cases = [
        case(f"D{i}", f"W1TTEST0000000{i:04d}", ("U1127", f"P{i}"))
        for i in range(5)
    ] + [
        case(f"D{i}", f"W1TTEST0000000{i:04d}", (f"P{i}",))
        for i in range(5, 10)
    ] + [
        case(f"EMPTY{i}", f"W1TTEST0000010{i:03d}", ())
        for i in range(10)
    ]
    plan = select_representative_cases(
        cases, minimum_similarity=0.05, maximum_common_frequency=0.35,
    )
    assert plan.screening_population == 10
    pair = next(p for p in plan.pair_scores
                if {p.left_id, p.right_id} == {"D0", "D1"})
    assert not pair.eligible
    assert "häufig" in pair.reason
    assert not plan.clusters


def test_all_group_members_share_informative_dtc_core() -> None:
    cases = [
        case("A", "W1TTEST0000000041", ("P100", "P200")),
        case("B", "W1TTEST0000000042", ("P100", "P200", "P300")),
        case("C", "W1TTEST0000000043", ("P200", "P300")),
        case("D", "W1TTEST0000000044", ("P300", "P400")),
    ]
    plan = select_representative_cases(cases, minimum_similarity=0.45)
    assert all(group.common_faults for group in plan.clusters)
    for group in plan.clusters:
        for pair in plan.pair_scores:
            if pair.left_id in group.case_ids and pair.right_id in group.case_ids:
                assert pair.eligible and pair.similarity >= 0.45
        core = set(group.common_faults)
        for member_id in group.case_ids:
            original = next(c for c in cases if c.case_id == member_id)
            codes = {(e.ecu, e.dtc_code) for e in original.diagnostics}
            assert core <= codes


def test_post_swap_findings_may_warn_but_never_change_clusters() -> None:
    cases = sample()
    before = select_representative_cases(cases, minimum_similarity=0.45)
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
    after = select_representative_cases(cases, minimum_similarity=0.45)
    assert before.representative_ids == after.representative_ids
    assert before.assigned_case_ids == after.assigned_case_ids
    assert before.pair_scores == after.pair_scores
    assert any(a.review_warnings != b.review_warnings
               for a, b in zip(before.clusters, after.clusters))


def test_series_mismatch_and_same_fin_warning() -> None:
    a = case("A", "W1TTEST0000000041", ("P101", "P102"))
    b = case("B", "W1TTEST0000000041", ("P101", "P102"))
    other = case(
        "C", "W1TTEST0000000042", ("P101", "P102"), series="999"
    )
    plan = select_representative_cases([a, b, other])
    assert len(plan.clusters) == 1
    assert plan.clusters[0].vehicle_count == 1
    assert "Nur eine FIN" in " ".join(plan.clusters[0].review_warnings)
    rejected = next(p for p in plan.pair_scores
                    if {p.left_id, p.right_id} == {"A", "C"})
    assert not rejected.eligible and "Baureihe" in rejected.reason


def test_missing_dtc_or_anchor_is_not_forcibly_assigned() -> None:
    cases = [
        case("U1", "W1TTEST0000000051", ()),
        case("U2", "W1TTEST0000000052", (), anchored=False),
    ]
    plan = select_representative_cases(cases)
    assert plan.clusters == ()
    assert plan.coverage == 0
    assert plan.unassigned == ("U1", "U2")
    assert plan.eligible_cases == ()


@pytest.mark.parametrize(
    "kwargs",
    [{"minimum_similarity": 0}, {"minimum_similarity": 1.1},
     {"maximum_common_frequency": 0}, {"maximum_common_frequency": 1.1}],
)
def test_invalid_policy_is_rejected(kwargs) -> None:
    with pytest.raises(ValueError):
        select_representative_cases(sample(), **kwargs)


def test_original_strict_complete_link_method_is_untouched() -> None:
    cases = sample()
    strict = cluster_diagnostic_cases(cases, threshold=0.65)
    plan = select_representative_cases(cases, minimum_similarity=0.45)
    assert plan.clusters
    assert strict == cluster_diagnostic_cases(cases, threshold=0.65)



def test_member_mean_excludes_100_percent_self_comparison() -> None:
    first = case("A", "W1TTEST0000000081", ("P101", "P102"))
    second = case("B", "W1TTEST0000000082", ("P101", "P102", "P103"))
    plan = select_representative_cases([first, second], minimum_similarity=0.50)
    assert len(plan.clusters) == 1
    group = plan.clusters[0]
    pair = plan.pair_scores[0]
    assert pair.similarity < 1
    assert group.mean_similarity == pytest.approx(pair.similarity, abs=1e-4)
    assert group.weakest_internal_similarity == pytest.approx(
        pair.similarity, abs=1e-4
    )
    assert group.weakest_representative_similarity == pytest.approx(
        pair.similarity, abs=1e-4
    )
    assert sum(member.similarity == 1.0 for member in group.members) == 1
    assert group.mean_similarity != pytest.approx(
        (1 + pair.similarity) / 2
    )


def test_unassigned_explains_missing_vs_weak_vs_incohesive() -> None:
    cases = [
        case("A", "W1TTEST0000000081", ("P100", "P200")),
        case("B", "W1TTEST0000000082", ("P100", "P200", "P300")),
        case("C", "W1TTEST0000000083", ("P100", "P300")),
        case("D", "W1TTEST0000000084", ()),
        case("E", "W1TTEST0000000085", ("Q1",), anchored=False),
    ]
    plan = select_representative_cases(cases)
    assert len(plan.unassigned_reasons) == len(plan.unassigned)
    reasons = {entry.case_id: entry for entry in plan.unassigned_reasons}
    assert "Vor-Tausch" in reasons["D"].reason
    assert "Tauschanker" in reasons["E"].reason
    assert len(plan.clusters) == 1
    assert len({"A", "B", "C"} & set(plan.unassigned)) == 1
    candidate = next(entry for entry in plan.unassigned_reasons
                     if entry.case_id in {"A", "B", "C"})
    assert candidate.nearest_diagnostic_case_id in {"A", "B", "C"}
    assert candidate.nearest_similarity is not None
    assert candidate.nearest_similarity >= plan.minimum_similarity
    assert "keine homogene Gruppe" in candidate.reason
