"""Synthetic-only HDBSCAN experiments: no real VINs or customer reports."""
from __future__ import annotations

from datetime import datetime

import numpy as np
import pytest
from sklearn.cluster import HDBSCAN

from ntf_insight.analysis.hdbscan_clustering import (
    cluster_hdbscan_cases, compare_hdbscan_methods,
)
from ntf_insight.domain.case import NTFCase
from ntf_insight.domain.events import (
    DiagnosticEvent, PartReplacement, SupplierFinding, TipsCaseObservation,
)
from ntf_insight.domain.vehicle import Vehicle


def synthetic(
    case_id: str, group: str, index: int, *,
    swap: bool = True, vin: str | None = None,
) -> NTFCase:
    vehicle_id = vin or f"W1TTEST000000{index:04d}"
    faults = (
        f"CODE-{group}-ROOT-A",
        f"CODE-{group}-ROOT-B",
        f"CODE-{group}-ROOT-C",
        f"INDIVIDUAL-{index}",
    )
    return NTFCase(
        case_id=case_id,
        vehicle=Vehicle(vin=vehicle_id, model_series="214"),
        component_type="Coolant Pump",
        component_profile_id="coolant_pump",
        replacements=[
            PartReplacement(
                vin=vehicle_id, event_id=f"swap-{case_id}",
                component_type="Coolant Pump",
                occurred_at=datetime(2026, 5, 10, 12),
            )
        ] if swap else [],
        investigated_replacement_id=f"swap-{case_id}" if swap else None,
        diagnostics=[
            DiagnosticEvent(
                vin=vehicle_id, event_id=f"{case_id}:{i}", ecu="CPC3",
                dtc_code=code, occurred_at=datetime(2026, 4, 30),
                source_ref=f"raw:synthetic#csv:{case_id}:{i}",
            )
            for i, code in enumerate(faults)
        ],
    )


def sample() -> list[NTFCase]:
    return (
        [synthetic(f"A{i}", "A", i) for i in range(6)]
        + [synthetic(f"B{i}", "B", 50 + i) for i in range(6)]
        + [synthetic("OUTLIER", "OTHER", 91)]
        + [synthetic("UNANCHORED", "X", 92, swap=False)]
        + [NTFCase(
            case_id="EMPTY", vehicle=Vehicle(vin="W1TTEST0000000093"),
            component_type="Coolant Pump", component_profile_id="coolant_pump",
        )]
    )


def test_hdbscan_finds_two_separate_density_groups_without_fixed_k() -> None:
    cases = sample()
    plan = cluster_hdbscan_cases(cases, min_cluster_size=3, min_samples=2)
    assert HDBSCAN.__module__.startswith("sklearn.")
    assert plan.case_count == 15
    assert plan.vehicle_count == 15
    assert len(plan.eligible_case_ids) == 13
    assert plan.excluded_case_ids == ("EMPTY", "UNANCHORED")
    assert plan.ssl_not_used_as_feature
    assert len(plan.clusters) == 2
    assert {
        frozenset(group.case_ids) for group in plan.clusters
    } == {
        frozenset(f"A{i}" for i in range(6)),
        frozenset(f"B{i}" for i in range(6)),
    }
    assert plan.noise_case_ids == ("OUTLIER",)
    assert plan.clustered_count == 12
    assert plan.coverage == pytest.approx(12/15)
    assert plan.feature_count > 25
    assert all(g.representative_case_id in g.case_ids for g in plan.clusters)
    assert all(g.vehicle_count == g.case_count for g in plan.clusters)
    assert all(len(g.common_faults) == 3 for g in plan.clusters)
    assert all(g.min_membership_strength <= 1 for g in plan.clusters)
    # Extra case-specific DTCs lower weighted cosine; group density, not an
    # arbitrary pair-threshold, is the HDBSCAN membership criterion.
    assert all(g.weakest_internal_similarity >= 0.35 for g in plan.clusters)
    assert all(g.mean_to_representative < 1 for g in plan.clusters)
    assert all(
        len(g.members) >= 3 for g in plan.clusters
    )

    distances = np.asarray(plan.distances)
    assert distances.shape == (13, 13)
    assert np.allclose(distances, distances.T)
    assert np.allclose(np.diag(distances), 0)
    assert (distances >= 0).all()
    assert np.isfinite(distances).all()
    assert {row[0] for row in plan.coordinates} == set(plan.eligible_case_ids)
    assert all(
        np.isfinite((x, y)).all() for _, x, y in plan.coordinates
    )

    other_order = cluster_hdbscan_cases(
        list(reversed(cases)), min_cluster_size=3, min_samples=2
    )
    assert plan == other_order


def test_repeated_sources_do_not_change_ml_features_or_membership() -> None:
    cases = sample()
    reference = cluster_hdbscan_cases(cases)
    first = cases[0]
    first.diagnostics.append(DiagnosticEvent(
        vin=first.vin, ecu="CPC3", dtc_code="CODE-A-ROOT-A",
        event_id="autoexport-double",
        occurred_at=datetime(2026, 4, 30),
        source_ref="raw:another#csv:duplicate",
    ))
    changed = cluster_hdbscan_cases(cases)
    assert reference.distances == changed.distances
    assert reference.clusters == changed.clusters
    assert reference.coordinates == changed.coordinates


def test_post_swap_outcomes_are_audit_only_never_cluster_predictors() -> None:
    cases = sample()
    reference = cluster_hdbscan_cases(cases)
    cases[0].supplier_findings.append(SupplierFinding(
        vin=cases[0].vin, occurred_at=datetime(2026, 5, 25),
        failure_mode="Synthetic post-repair supplier result",
        source_ref="Schadteile QEC!2",
    ))
    cases[1].qec_ssl_end_finding = "Synthetic unlike SSL finding"
    cases[2].diagnostics.append(DiagnosticEvent(
        vin=cases[2].vin, ecu="CPC3", dtc_code="AFTER_SWAP_ONLY",
        occurred_at=datetime(2026, 5, 28),
    ))
    cases[3].tips_observations.append(TipsCaseObservation(
        vin=cases[3].vin, occurred_at=datetime(2026, 5, 29),
        complaint="Synthetic complaint after pump replacement",
        performed_actions="Swap pump",
    ))
    updated = cluster_hdbscan_cases(cases)
    assert reference.distances == updated.distances
    assert reference.coordinates == updated.coordinates
    assert reference.clustered_count == updated.clustered_count
    assert [(group.case_ids, group.representative_case_id)
            for group in reference.clusters] == [
        (group.case_ids, group.representative_case_id)
        for group in updated.clusters
    ]
    assert sum(g.ssl_finding_count for g in updated.clusters) >= 2
    assert all(
        len(group.common_faults) == 3 for group in updated.clusters
    )


def test_empty_data_and_no_sufficient_cohort_do_not_fake_clusters() -> None:
    assert cluster_hdbscan_cases([]).clusters == ()
    assert cluster_hdbscan_cases([]).coordinates == ()
    cases = sample()[:2]
    result = cluster_hdbscan_cases(
        cases, min_cluster_size=3, min_samples=2
    )
    assert result.clusters == ()
    assert len(result.noise_case_ids) == 2


@pytest.mark.parametrize("params", [
    {"min_cluster_size": 1}, {"min_cluster_size": 101},
    {"min_samples": 0}, {"min_samples": 101},
    {"dtc_source": "nonsense"}, {"lookback_days": -5},
])
def test_malformed_source_and_hdbscan_settings_are_rejected(params) -> None:
    with pytest.raises(ValueError):
        cluster_hdbscan_cases(sample(), **params)


def test_different_component_families_must_never_mix() -> None:
    cases = sample()
    cases[-1].component_profile_id = "hv_battery"
    with pytest.raises(ValueError, match="Bauteilfamilie"):
        cluster_hdbscan_cases(cases)


def test_source_and_window_cannot_be_ignored() -> None:
    data = sample()
    default = cluster_hdbscan_cases(data)
    quicktest_only = cluster_hdbscan_cases(data, dtc_source="quicktest")
    recent_only = cluster_hdbscan_cases(data, lookback_days=3)
    assert len(default.eligible_case_ids) == 13
    assert quicktest_only.eligible_case_ids == ()
    assert recent_only.eligible_case_ids == ()
    assert not quicktest_only.clusters
    assert not recent_only.clusters



def test_duplicate_fin_cases_are_not_misreported_as_independent_vehicles() -> None:
    cases = sample()
    cases[1] = synthetic("A1", "A", 1, vin=cases[0].vin)
    plan = cluster_hdbscan_cases(cases)
    group = next(g for g in plan.clusters if "A0" in g.case_ids)
    assert group.case_count == 6
    assert group.vehicle_count == 5
    assert any("derselben FIN" in warning for warning in group.warnings)
    assert plan.vehicle_count == 14



def test_leaf_is_genuine_hdbscan_and_eom_comparison_same_distances() -> None:
    cases = sample()
    eom = cluster_hdbscan_cases(
        cases, min_cluster_size=3, min_samples=2, selection_method="eom"
    )
    leaf = cluster_hdbscan_cases(
        cases, min_cluster_size=3, min_samples=2, selection_method="leaf"
    )
    assert eom.selection_method == "eom"
    assert leaf.selection_method == "leaf"
    assert eom.distances == leaf.distances
    assert eom.coordinates == leaf.coordinates
    assert set(eom.eligible_case_ids) == set(leaf.eligible_case_ids)
    assert leaf.clustered_count + len(leaf.noise_case_ids) == 13
    for group in (*eom.clusters, *leaf.clusters):
        assert group.internal_pair_count == group.case_count * (group.case_count - 1) // 2
        assert 0 <= group.weak_pair_count <= group.internal_pair_count
        assert 0 <= group.weakest_internal_similarity <= 1
        assert 0 <= group.p10_internal_similarity <= group.median_internal_similarity <= 1
        assert group.weakest_internal_similarity <= group.p10_internal_similarity
        assert group.screening_status in {
            "Heterogen – keine Ursachenübertragung",
            "Uneinheitlich – einzelne schwache Fallpaare",
            "Diagnostischer Prüfkandidat – Ursache unbestätigt",
        }
    comparison = compare_hdbscan_methods(
        cases, min_cluster_size=3, min_samples=2,
    )
    assert comparison.eom.group_count == len(eom.clusters)
    assert comparison.leaf.group_count == len(leaf.clusters)
    assert comparison.eom.clustered_cases == eom.clustered_count
    assert comparison.leaf.clustered_cases == leaf.clustered_count
    assert comparison.eom.weak_pair_count == sum(
        group.weak_pair_count for group in eom.clusters
    )
    assert comparison.leaf.weak_pair_count == sum(
        group.weak_pair_count for group in leaf.clusters
    )
    assert 0 <= comparison.pair_coassignment_jaccard <= 1
    assert comparison == compare_hdbscan_methods(list(reversed(cases)))


def test_leaf_experiment_keeps_duplicate_and_after_swap_sources_out_of_features() -> None:
    cases = sample()
    before = cluster_hdbscan_cases(cases, selection_method="leaf")
    cases[0].diagnostics.append(DiagnosticEvent(
        vin=cases[0].vin,
        event_id="repeat-quicktest-autoexport",
        ecu="CPC3", dtc_code="CODE-A-ROOT-A",
        occurred_at=datetime(2026, 4, 30),
        source_ref="raw:synthetic#csv:duplicate",
    ))
    cases[1].diagnostics.append(DiagnosticEvent(
        vin=cases[1].vin,
        event_id="post-only", ecu="CPC3", dtc_code="POST-ERROR",
        occurred_at=datetime(2026, 5, 30),
    ))
    cases[2].qec_ssl_end_finding = "NTF – unbestätigt"
    after = cluster_hdbscan_cases(cases, selection_method="leaf")
    assert before.distances == after.distances
    assert before.coordinates == after.coordinates
    assert before.eligible_case_ids == after.eligible_case_ids
    assert [(g.case_ids, g.representative_case_id)
            for g in before.clusters] == [
        (g.case_ids, g.representative_case_id)
        for g in after.clusters
    ]


def test_comparison_is_aggregate_only_without_case_or_fin_identifiers() -> None:
    result = compare_hdbscan_methods(sample())
    for summary in result.rows:
        assert summary.selection_method in {"leaf", "eom"}
        assert summary.clustered_cases + summary.noise_cases == 13
        assert summary.weak_pair_count <= summary.all_internal_pair_count
        assert 0 <= summary.weak_pair_fraction <= 1
    assert "W1TTEST" not in repr(result)
    assert "A0" not in repr(result)
    assert "CPC3" not in repr(result)
    assert result.eligible_case_count == 13


@pytest.mark.parametrize("wrong_method", ["unknown", "eom; rm -rf", "Leaf", ""])
def test_unknown_selection_methods_are_rejected(wrong_method: str) -> None:
    with pytest.raises(ValueError, match="Methode"):
        cluster_hdbscan_cases(
            sample(), selection_method=wrong_method
        )
