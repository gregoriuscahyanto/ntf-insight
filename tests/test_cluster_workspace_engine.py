"""Unified multi-method clustering, entirely on synthetic coolant pumps."""
from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from ntf_insight.analysis.cluster_workspace_engine import (
    METHODS, ClusterParameters, calculate_clusters,
    compare_cluster_runs, positive_pairs,
)
from ntf_insight.analysis.hdbscan_clustering import cluster_hdbscan_cases
from ntf_insight.analysis.method_comparison_audit import complete_link_same_metric
from test_hdbscan_clustering import sample


def params(method="leaf", **kwargs):
    return replace(ClusterParameters(method=method), **kwargs)


def test_method_registry_is_unique_and_parameter_defaults_meaningful():
    assert len(METHODS) == len({item.key for item in METHODS}) == 4
    for item in METHODS:
        params(item.key).validate()
    with pytest.raises(ValueError, match="Unbekannte"):
        params("invalid_algorithm").validate()


def test_one_cohort_four_cluster_models_and_no_3d_reclustering():
    cases = sample()
    baseline = cluster_hdbscan_cases(
        cases, min_cluster_size=3, min_samples=2, selection_method="leaf",
    )
    results = [
        calculate_clusters(cases, params(spec.key), reference=baseline)
        for spec in METHODS
    ]
    assert all(set(r.eligible_case_ids) == set(baseline.eligible_case_ids)
               for r in results)
    assert all(set(r.excluded_case_ids) == {"EMPTY", "UNANCHORED"}
               for r in results)
    leaf, eom, cosine, legacy = results
    assert len(leaf.groups) == len(eom.groups) == 2
    assert leaf.clustered_count == baseline.clustered_count == 12
    assert set(case for group in leaf.groups for case in group.case_ids) == (
        {f"A{i}" for i in range(6)} | {f"B{i}" for i in range(6)}
    )
    assert len(leaf.positions) == len(leaf.eligible_case_ids) == 13
    assert all(len(point) == 4 for point in leaf.positions)
    assert np.isfinite([p[1:] for p in leaf.positions]).all()
    assert leaf.positions == eom.positions == cosine.positions == legacy.positions
    assert leaf.original_distances == eom.original_distances == cosine.original_distances
    assert all(r.clustered_count + len(r.noise_case_ids) == 13 for r in results)
    assert all(
        group.representative_case_id in group.case_ids
        for run in results for group in run.groups
    )
    rows = compare_cluster_runs(results)
    assert len(rows) == 4
    assert rows[0]["paaruebereinstimmung"] == 1
    assert rows[-1]["metrik"] == "Gewichteter DTC-Jaccard"
    assert rows[0]["metrik"] != rows[-1]["metrik"]
    assert cosine.clustered_count <= leaf.clustered_count


def test_strict_cosine_groups_equal_existing_reviewed_method_audit():
    cases = sample()
    baseline = cluster_hdbscan_cases(cases, selection_method="leaf")
    for cutoff in (0.45, 0.65):
        run = calculate_clusters(
            cases, params("complete_cosine", minimum_similarity=cutoff),
            reference=baseline,
        )
        audited = complete_link_same_metric(
            cases, baseline, minimum_cosine=cutoff,
        )
        assert len(run.groups) == audited.cluster_count
        assert run.clustered_count == audited.grouped_cases
        assert len(run.noise_case_ids) == audited.noise_cases
        assert sum(bool(group.common_faults) for group in run.groups) == (
            audited.groups_with_common_exact_dtc
        )
        for group in run.groups:
            assert group.minimum_pair_similarity >= cutoff - 0.00011
            assert len({c.vin for c in cases if c.case_id in group.case_ids}) == (
                group.vehicle_count
            )


def test_cluster_assignments_do_not_use_ssl_or_supplier_outcomes():
    cases = sample()
    initial = calculate_clusters(cases, params())
    cases[0].qec_ssl_end_finding = "Synthetic supplier allegation"
    cases[1].qec_ssl_end_finding = "Different result: rejected pump"
    updated = calculate_clusters(cases, params())
    assert [group.case_ids for group in initial.groups] == [
        group.case_ids for group in updated.groups
    ]
    assert positive_pairs(initial) == positive_pairs(updated)
    assert initial.positions == updated.positions


def test_legacy_filter_is_refused_instead_of_silently_changing_method():
    with pytest.raises(ValueError, match="Jaccard-Vergleich"):
        calculate_clusters(
            sample(),
            params("complete_legacy", common_dtc_cutoff=0.35),
        )


def test_comparison_rejects_different_pre_swap_cohorts():
    cases = sample()
    left = calculate_clusters(cases, params("leaf"))
    right = calculate_clusters(cases[:-1], params("eom"))
    # Removing an excluded case leaves eligible population unchanged.
    assert compare_cluster_runs([left, right])
    changed = calculate_clusters(cases[:-3], params("eom"))
    with pytest.raises(ValueError, match="gleicher QEC-Grundgesamtheit"):
        compare_cluster_runs([left, changed])


def test_legacy_complete_link_never_uses_a_qec_from_another_family():
    cases = sample()
    other = cases[0].model_copy(deep=True)
    other.case_id = "DIFFERENT-COMPONENT"
    other.component_profile_id = "battery"
    other.component_type = "Battery"
    with pytest.raises(ValueError, match="Bauteilfamilie"):
        calculate_clusters(cases + [other], params("leaf"))
