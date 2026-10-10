"""Explanations refer to diagnostic overlaps, not laboratory root causes."""
from __future__ import annotations

from dataclasses import replace

import pytest

from ntf_insight.analysis.cluster_explanation import explain_cluster
from ntf_insight.analysis.cluster_workspace_engine import (
    ClusterMember, ClusterParameters, UnifiedCluster, calculate_clusters,
)
from test_hdbscan_clustering import sample


def _first_group(cases):
    result = calculate_clusters(cases, ClusterParameters())
    return result, result.groups[0]


def test_cluster_explanation_names_actual_shared_dtc_and_individual_overlap():
    cases = sample()
    result, group = _first_group(cases)
    info = explain_cluster(
        cases, group, result.parameters, result.eligible_case_ids,
    )
    assert f"Cluster C{group.cluster_id}" in info.heading
    assert f"allen {group.case_count} Fällen" in info.text
    assert "CPC3:CODE-" in info.text
    assert "Pumpenursache" in info.text
    assert len(info.per_case) == group.case_count
    assert "Repräsentativer Fall" in info.evidence_for(group.representative_case_id)
    for member in group.members:
        if member.case_id != group.representative_case_id:
            assert "gleiche ECU:DTC" in info.evidence_for(member.case_id)
    assert "HDBSCAN bildet Dichtegruppen" in info.text


def test_explanation_never_uses_ssl_end_findings_or_post_swap_supplier_labels():
    cases = sample()
    before, group = _first_group(cases)
    initial = explain_cluster(cases, group, before.parameters, before.eligible_case_ids)
    cases[0].qec_ssl_end_finding = "SECRET_SSL_SUPPLIER_ALLEGATION"
    after = explain_cluster(cases, group, before.parameters, before.eligible_case_ids)
    assert after == initial
    assert "SECRET_SSL" not in after.text


def test_heterogeneous_cluster_is_described_as_inconclusive():
    cases = sample()
    eligible = [f"A{i}" for i in range(6)] + [f"B{i}" for i in range(6)]
    invented = UnifiedCluster(
        cluster_id=42,
        representative_case_id="A0",
        members=(ClusterMember("A0", 1.0), ClusterMember("B0", 0.2)),
        vehicle_count=2,
        common_faults=(),
        minimum_pair_similarity=0.2,
        median_pair_similarity=0.2,
        weak_pair_count=1,
        internal_pair_count=1,
    )
    info = explain_cluster(cases, invented, ClusterParameters(), eligible)
    assert "Kein identischer ECU:DTC" in info.text
    assert "uneinheitlich" in info.text
    assert "Kein identischer ECU:DTC" in info.evidence_for("B0")
    assert "Lieferantenverantwortung" in info.text


def test_enabled_common_dtc_filter_cannot_reintroduce_suppressed_dtc():
    cases = sample()
    baseline, group = _first_group(cases)
    info = explain_cluster(
        cases, group,
        replace(baseline.parameters, common_dtc_cutoff=0.35),
        baseline.eligible_case_ids,
    )
    assert "Häufigkeitsfilter" in info.text
    assert "Identische ECU:DTC in allen" not in info.text
    # The filtered-away group root codes must not masquerade as evidence.
    assert "CPC3:CODE-A-ROOT-A" not in info.text
    assert "CPC3:CODE-B-ROOT-A" not in info.text


def test_explanation_rejects_nonmember_reference_and_cross_cohort():
    cases = sample()
    result, group = _first_group(cases)
    with pytest.raises(ValueError, match="Datenbasis"):
        explain_cluster(cases, group, result.parameters, ("OUTLIER",))
    with pytest.raises(ValueError, match="Repräsentant"):
        explain_cluster(
            cases, replace(group, representative_case_id="OUTLIER"),
            result.parameters, result.eligible_case_ids,
        )


def test_strict_review_uses_its_actual_metric_wording():
    cases = sample()
    strict = calculate_clusters(
        cases, ClusterParameters(method="complete_cosine"),
    )
    assert strict.groups
    info = explain_cluster(
        cases, strict.groups[0], strict.parameters, strict.eligible_case_ids,
        strict_review=True,
    )
    assert "Prüfgruppe K" in info.heading
    assert "Complete-Link Cosinus" in info.text
