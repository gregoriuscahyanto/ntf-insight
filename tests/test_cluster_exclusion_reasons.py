"""Explain WHY QEC cases were not eligible for pre-replacement clustering."""
from __future__ import annotations

from ntf_insight.analysis.cluster_exclusion_reasons import exclusion_reasons
from ntf_insight.analysis.cluster_workspace_engine import ClusterParameters, calculate_clusters
from test_hdbscan_clustering import sample, synthetic


def test_disjoint_exclusion_reasons_sum_to_exact_excluded_cohort():
    cases = sample()
    cases.append(synthetic("EMPTY_DTC_ANCHORED", "X", 900))
    cases[-1].diagnostics = []
    cases.append(synthetic("POST_ONLY", "X", 901))
    for event in cases[-1].diagnostics:
        event.occurred_at = event.occurred_at.replace(month=6)
    result = calculate_clusters(cases, ClusterParameters())
    reasons = exclusion_reasons(cases, result)
    assert reasons.total == len(result.excluded_case_ids)
    assert reasons.no_swap_anchor >= 2
    assert reasons.no_imported_dtc >= 1
    assert reasons.no_pre_swap_dtc >= 1
    assert "nicht" in reasons.text
    assert "Pumpentausch-Anker" in reasons.text


def test_source_change_reclassifies_proof_gap_not_number_of_qec_cases():
    cases = sample()
    result = calculate_clusters(
        cases, ClusterParameters(dtc_source="quicktest"),
    )
    reasons = exclusion_reasons(cases, result)
    assert reasons.total == len(cases)
    assert reasons.no_swap_anchor == 2
    assert reasons.no_selected_source == len(cases) - 2


def test_cases_without_replacement_are_excluded_even_when_dtc_exists():
    case = synthetic("WITHOUT_SWAP", "X", 100, swap=False)
    assert case.diagnostics
    output = calculate_clusters([case], ClusterParameters())
    reasons = exclusion_reasons([case], output)
    assert reasons.total == 1
    assert reasons.no_swap_anchor == 1
