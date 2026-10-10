"""Synthetic-only, pre-swap, equal-distance clustering comparisons."""
from __future__ import annotations

import json
from dataclasses import replace

import pytest

from ntf_insight.analysis.hdbscan_clustering import (
    cluster_hdbscan_cases, compare_hdbscan_methods,
)
from ntf_insight.analysis.method_comparison_audit import (
    approved_method_totals, build_method_evaluation, complete_link_same_metric,
)
from test_hdbscan_clustering import sample


def _evaluate(cases=None):
    cases = sample() if cases is None else cases
    leaf = cluster_hdbscan_cases(
        cases, min_cluster_size=3, min_samples=2, selection_method="leaf",
    )
    compared = compare_hdbscan_methods(
        cases, min_cluster_size=3, min_samples=2,
    )
    return build_method_evaluation(cases, leaf, compared)


def test_all_methods_use_same_eligible_cohort_and_unchanged_leaf_clusters():
    cases = sample()
    before = cluster_hdbscan_cases(cases, selection_method="leaf")
    report = _evaluate(cases)
    after = cluster_hdbscan_cases(cases, selection_method="leaf")
    assert before == after
    assert report["geeignete_faelle"] == len(before.eligible_case_ids) == 13
    assert report["methode_leaf"]["cluster"] == len(before.clusters) == 2
    assert report["methode_leaf"]["clusterfaelle"] == 12
    for method in (
        "methode_leaf", "methode_eom",
        "methode_complete_link_45", "methode_complete_link_65",
    ):
        row = report[method]
        assert row["clusterfaelle"] + row["ausreisser"] == 13
        assert row["cluster"] <= 13


def test_complete_link_is_strict_and_cutoff_changes_number_of_grouped_cases():
    cases = sample()
    leaf = cluster_hdbscan_cases(cases, selection_method="leaf")
    weak = complete_link_same_metric(
        cases, leaf, minimum_cosine=0.45, min_members=3,
    )
    strong = complete_link_same_metric(
        cases, leaf, minimum_cosine=0.65, min_members=3,
    )
    assert weak.grouped_cases >= strong.grouped_cases
    assert weak.noise_cases <= strong.noise_cases
    assert weak.cluster_count > 0
    assert 0 <= weak.groups_with_core_and_multiple_fins <= weak.cluster_count
    assert weak.groups_with_core_and_multiple_fins <= weak.groups_with_common_exact_dtc
    assert weak.groups_with_core_and_multiple_fins <= weak.groups_with_multiple_fins
    assert weak.internal_pair_count >= weak.cluster_count * 3
    assert weak.pair_jaccard_with_leaf is not None
    assert 0 <= weak.pair_jaccard_with_leaf <= 1
    assert _evaluate(cases) == _evaluate(list(reversed(cases)))


def test_same_fin_cases_do_not_count_as_independent_vehicle_groups():
    cases = sample()
    for case in cases[1:6]:
        case.vehicle = case.vehicle.model_copy(
            update={"vin": cases[0].vin}
        )
    leaf = cluster_hdbscan_cases(cases, selection_method="leaf")
    strict = complete_link_same_metric(cases, leaf, minimum_cosine=0.45)
    assert strict.groups_with_multiple_fins <= strict.cluster_count
    assert strict.groups_with_core_and_multiple_fins <= strict.groups_with_multiple_fins


def test_approved_method_statistics_contain_only_whitelisted_nonnegative_ints():
    report = {"methodenbewertung": _evaluate()}
    # This text simulates confidential information accidentally included in a
    # future internal report. It must not enter the explicit method log export.
    report["methodenbewertung"]["methode_leaf"]["qec_case_id"] = "SECRET_QEC_001"
    report["methodenbewertung"]["fin"] = "SECRET_FIN_DO_NOT_LOG"
    payload = approved_method_totals(report)
    assert set(payload) == {
        "methode_leaf", "methode_eom", "methode_complete_link_45",
        "methode_complete_link_65", "geeignete_faelle",
    }
    dumped = json.dumps(payload, ensure_ascii=False)
    assert "SECRET_" not in dumped
    assert "W1TTEST" not in dumped
    assert "CODE-" not in dumped
    assert "CPC3" not in dumped
    assert "qec_case_id" not in dumped
    for value in payload.values():
        if isinstance(value, dict):
            assert all(type(count) is int and count >= 0 for count in value.values())
        else:
            assert type(value) is int and value >= 0


def test_approved_method_statistics_reject_injected_string_and_negative_count():
    report = {"methodenbewertung": _evaluate()}
    report["methodenbewertung"]["methode_eom"]["cluster"] = "QEC_SECRET"
    with pytest.raises(ValueError, match="Ganzzahlen"):
        approved_method_totals(report)
    report["methodenbewertung"]["methode_eom"]["cluster"] = -1
    with pytest.raises(ValueError, match="Ganzzahlen"):
        approved_method_totals(report)


def test_empty_cohort_does_not_invent_clusters_or_100_percent_agreement():
    assert _evaluate([])["methode_complete_link_45"]["cluster"] == 0
    assert _evaluate([])["paaruebereinstimmung_leaf_eom"] is None
    assert _evaluate([])["methode_complete_link_45"][
        "paaruebereinstimmung_zu_leaf"
    ] is None


@pytest.mark.parametrize("threshold", [-1, 0, 1, 1.01])
def test_complete_link_rejects_invalid_threshold(threshold: float):
    cases = sample()
    leaf = cluster_hdbscan_cases(cases, selection_method="leaf")
    with pytest.raises(ValueError, match="Schwelle"):
        complete_link_same_metric(
            cases, leaf, minimum_cosine=threshold,
        )


def test_complete_link_requires_leaf_and_consistent_cohort():
    cases = sample()
    leaf = cluster_hdbscan_cases(cases, selection_method="leaf")
    with pytest.raises(ValueError, match="Fallbestand"):
        complete_link_same_metric(cases[:-1], leaf)
    with pytest.raises(ValueError, match="Leaf"):
        complete_link_same_metric(cases, replace(leaf, selection_method="eom"))
