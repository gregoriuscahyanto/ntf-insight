"""Synthetic-only tests of pair-level clustering robustness and missingness."""
from __future__ import annotations

from dataclasses import replace

import pytest

from ntf_insight.analysis.cluster_stability import (
    build_stability_report, compare_stability, sensitivity_scenarios,
)
from ntf_insight.analysis.cluster_workspace_engine import (
    ClusterParameters, UnifiedCluster, UnifiedClusterResult, ClusterMember,
    calculate_clusters,
)
from test_hdbscan_clustering import sample


def _group(number, *ids):
    return UnifiedCluster(
        cluster_id=number,
        representative_case_id=ids[0],
        members=tuple(ClusterMember(cid, 1.0) for cid in ids),
        vehicle_count=len(ids),
        common_faults=(),
        minimum_pair_similarity=None,
        median_pair_similarity=None,
        weak_pair_count=None,
        internal_pair_count=len(ids) * (len(ids)-1)//2,
    )


def _run(groups, *, eligible=("A", "B", "C", "D"), method="leaf"):
    assigned = {cid for group in groups for cid in group.case_ids}
    return UnifiedClusterResult(
        parameters=ClusterParameters(method=method),
        groups=tuple(groups),
        eligible_case_ids=eligible,
        noise_case_ids=tuple(cid for cid in eligible if cid not in assigned),
        excluded_case_ids=tuple(sorted(set(("A", "B", "C", "D")) - set(eligible))),
        positions=(),
        original_distances=(),
        note="synthetisch",
    )


def test_pair_coassignment_not_arbitrary_group_ids():
    base = _run((_group(1, "A", "B", "C"),))
    renumbered = _run((_group(99, "A", "B", "C"),))
    row = compare_stability(base, renumbered, label="EOM", category="Verfahren")
    assert row.shared_pairs == row.reference_pairs == 3
    assert row.pair_jaccard == row.reference_pair_retention == 1.0
    assert row.group_rows[0].retention == 1.0


def test_pair_retention_detects_split_and_extra_merges():
    base = _run((_group(1, "A", "B"), _group(2, "C", "D")))
    combined = _run((_group(1, "A", "B", "C", "D"),), method="eom")
    row = compare_stability(base, combined, label="EOM", category="Verfahren")
    assert row.reference_pairs == 2
    assert row.comparison_pairs == 6
    assert row.shared_pairs == 2
    assert row.reference_pair_retention == 1.0
    assert row.pair_jaccard == pytest.approx(1/3)
    assert all(group.newly_joined_external_pairs == 4 for group in row.group_rows)


def test_missing_eligibility_not_a_failure_and_no_zero_division():
    base = _run((_group(1, "A", "B", "C"),))
    candidate = _run((_group(1, "A", "B"),), eligible=("A", "B"))
    row = compare_stability(
        base, candidate, label="Nur QuickTest", category="Daten/Parameter",
    )
    assert row.shared_eligible == 2
    assert row.coverage == 0.5
    assert row.reference_pairs == 1
    assert row.shared_pairs == 1
    assert row.pair_jaccard == 1.0
    assert row.group_rows[0].reference_members == 3
    assert row.group_rows[0].comparable_members == 2
    zero = _run((), eligible=())
    empty = compare_stability(base, zero, label="Leer", category="Daten/Parameter")
    assert empty.pair_jaccard is None
    assert empty.reference_pair_retention is None
    assert empty.shared_eligible == 0


def test_mixed_inputs_are_rejected_instead_of_claiming_comparability():
    a = _run((_group(1, "A", "B"),))
    b = _run((_group(1, "A", "B"),), eligible=("A", "B"))
    with pytest.raises(ValueError, match="geeigneten Fälle"):
        compare_stability(a, replace(b, parameters=replace(b.parameters, method="eom")),
                          label="EOM", category="Verfahren")
    with pytest.raises(ValueError, match="dasselbe Verfahren"):
        compare_stability(a, replace(a, parameters=replace(a.parameters, method="eom")),
                          label="EOM", category="Daten/Parameter")
    with pytest.raises(ValueError, match="Fallbestand"):
        compare_stability(a, replace(a, excluded_case_ids=("SYNTHETIC-FOREIGN",)),
                          label="Fehler", category="Daten/Parameter")


def test_one_factor_scenarios_and_real_engine_on_synthetic_cases():
    cases = sample()
    params = ClusterParameters()
    baseline = calculate_clusters(cases, params)
    scenarios = sensitivity_scenarios(params)
    assert scenarios
    assert len({label for label, _ in scenarios}) == len(scenarios)
    assert all(
        sum(
            getattr(p, field) != getattr(params, field)
            for field in (
                "dtc_source", "lookback_days", "common_dtc_cutoff",
                "min_samples", "min_cluster_size",
            )
        ) == 1
        for _, p in scenarios
    )
    comparisons = []
    for label, settings in scenarios:
        result = calculate_clusters(cases, settings)
        comparisons.append(("Daten/Parameter", label, result))
    report = build_stability_report(baseline, tuple(comparisons))
    assert len(report.comparisons) == len(scenarios)
    assert all(0 <= item.shared_eligible <= item.baseline_eligible
               for item in report.comparisons)
    assert all(item.pair_jaccard is None or 0 <= item.pair_jaccard <= 1
               for item in report.comparisons)
    assert not any(
        "SECRET_FIN" in str(row) for row in report.comparisons
    )


def test_jaccard_method_does_not_enable_unsupported_prevalence_filter():
    settings = ClusterParameters(method="complete_legacy")
    scenarios = sensitivity_scenarios(settings)
    assert all(p.common_dtc_cutoff is None for _, p in scenarios)


def test_no_technical_cause_or_supplier_labels_used():
    cases = sample()
    baseline = calculate_clusters(cases, ClusterParameters())
    before = compare_stability(
        baseline, calculate_clusters(cases, ClusterParameters()),
        label="Kontrolle", category="Daten/Parameter",
    )
    cases[0].qec_ssl_end_finding = "Synthetic laboratory says supplier error"
    after = compare_stability(
        baseline, calculate_clusters(cases, ClusterParameters()),
        label="Kontrolle", category="Daten/Parameter",
    )
    assert before == after
