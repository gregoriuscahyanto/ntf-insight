"""Explanations refer to diagnostic overlaps, not laboratory root causes."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime

import pytest

from ntf_insight.analysis.cluster_explanation import explain_cluster
from ntf_insight.analysis.cluster_workspace_engine import (
    ClusterMember, ClusterParameters, UnifiedCluster, calculate_clusters,
)
from ntf_insight.domain.events import DiagnosticEvent
from test_hdbscan_clustering import sample, synthetic


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
    assert "Ursache in der Kühlmittelpumpe" in info.text
    assert len(info.per_case) == group.case_count
    assert "Repräsentativer Fall" in info.evidence_for(group.representative_case_id)
    for member in group.members:
        if member.case_id != group.representative_case_id:
            assert "gleiche ECU:DTC" in info.evidence_for(member.case_id)
    assert "Dichtegruppen" in info.text
    assert "Wichtig:" in info.text


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
    assert "Kein einzelner Steuergerät-Fehlercode" in info.text
    assert "uneinheitlich" in info.text
    assert "Kein identischer ECU:DTC" in info.evidence_for("B0")
    assert "Verantwortung des Lieferanten" in info.text


def test_enabled_common_dtc_filter_cannot_reintroduce_suppressed_dtc():
    cases = sample()
    baseline, group = _first_group(cases)
    info = explain_cluster(
        cases, group,
        replace(baseline.parameters, common_dtc_cutoff=0.35),
        baseline.eligible_case_ids,
    )
    assert "Häufigkeitsfilter" in info.text
    assert "In allen 6 Fällen sind dieselben" not in info.text
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


def test_explanation_keeps_all_shared_codes_and_warning_pair_denominator():
    """Seven cases: never truncate fourth/fifth code or a 12/21 warning."""
    cases = [synthetic(f"S{i}", "S", i) for i in range(7)]
    extra = ("SHARED-D", "SHARED-E")
    for case in cases:
        for code in extra:
            case.diagnostics.append(DiagnosticEvent(
                vin=case.vin, event_id=f"{case.case_id}:{code}",
                ecu="CPC3", dtc_code=code,
                occurred_at=datetime(2026, 4, 30),
                source_ref=f"raw:synthetic#csv:{case.case_id}:{code}",
            ))
    group = UnifiedCluster(
        cluster_id=7,
        representative_case_id="S0",
        members=tuple(ClusterMember(f"S{i}", 1.0) for i in range(7)),
        vehicle_count=7,
        common_faults=(),
        minimum_pair_similarity=0.1,
        median_pair_similarity=0.5,
        weak_pair_count=12,
        internal_pair_count=21,
    )
    ids = tuple(c.case_id for c in cases)
    info = explain_cluster(cases, group, ClusterParameters(), ids)
    assert "5 Steuergerät-Fehlercode-Kombinationen" in info.text
    assert "CPC3:SHARED-D" in info.text
    assert "CPC3:SHARED-E" in info.text
    assert "(+" not in info.text
    assert "21 Fallpaare" in info.text
    assert "12 Paare" in info.text
    assert "45 % Cosinus-Ähnlichkeit" in info.text
    assert "Wichtig:" in info.text
    assert "CPC3:SHARED-E" in info.evidence_for("S1")


def test_dtc_explorer_text_is_shown_only_when_the_exact_key_has_a_text():
    """All pre-swap code keys remain; descriptions are labels, not features."""
    cases = sample()
    before, group = _first_group(cases)
    cases[0].diagnostics[0].dtc_text = (
        "Synthetic coolant circulation: no communication with control unit"
    )
    # A second ECU with the same DTC must NOT borrow CPC3's text.
    cases[1].diagnostics.append(DiagnosticEvent(
        vin=cases[1].vin, ecu="OTHER", dtc_code="CODE-A-ROOT-A",
        occurred_at=datetime(2026, 7, 1),
        dtc_text="Other ECU has an unrelated code description",
        source_ref="raw:synthetic#csv:later:other",
    ))
    info = explain_cluster(cases, group, before.parameters, before.eligible_case_ids)
    assert "CPC3:CODE-A-ROOT-A — Synthetic coolant circulation" in info.text
    assert "CPC3:CODE-A-ROOT-B" in info.text
    assert "CPC3:CODE-A-ROOT-B —" not in info.text
    assert "OTHER:CODE-A-ROOT-A" not in info.text
    assert "nicht zur Clusterbildung verwendet" in info.text
    assert "anderen Diagnosezeitpunkt" in info.text
    # Only labels changed; the originally eligible pre-swap group is stable.
    unchanged = calculate_clusters(cases, ClusterParameters())
    assert {frozenset(g.case_ids) for g in before.groups} == {
        frozenset(g.case_ids) for g in unchanged.groups
    }


def test_label_from_later_observation_does_not_add_post_swap_dtc_as_feature():
    cases = sample()
    before, group = _first_group(cases)
    # No pre-swap text for CODE-A-ROOT-B, but another observation has a label.
    cases[0].diagnostics.append(DiagnosticEvent(
        vin=cases[0].vin, ecu="CPC3", dtc_code="CODE-A-ROOT-B",
        occurred_at=datetime(2026, 7, 1),
        dtc_text="Synthetic descriptive label from later session",
        source_ref="raw:synthetic#csv:after",
    ))
    info = explain_cluster(cases, group, before.parameters, before.eligible_case_ids)
    assert "CPC3:CODE-A-ROOT-B — Synthetic descriptive label" in info.text
    assert "anderen Diagnosezeitpunkt" in info.text
    again = calculate_clusters(cases, ClusterParameters())
    assert before.eligible_case_ids == again.eligible_case_ids
    assert [g.case_ids for g in before.groups] == [g.case_ids for g in again.groups]
