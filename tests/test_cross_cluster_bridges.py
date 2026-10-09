"""Synthetic CPC3 bridge screening: cross-cluster resemblance is NOT a cause."""
from __future__ import annotations

from datetime import date, datetime

from ntf_insight.analysis.cross_cluster_bridges import build_cluster_bridges
from ntf_insight.analysis.diagnostic_evidence_audit import audit_diagnostic_evidence
from ntf_insight.analysis.hdbscan_clustering import cluster_hdbscan_cases
from ntf_insight.analysis.mechanism_review import ConfirmedMechanism
from ntf_insight.domain.events import DiagnosticEvent
from test_hdbscan_clustering import sample


def _bridged_cases():
    cases = sample()
    for case in cases[:12]:
        case.diagnostics.append(DiagnosticEvent(
            vin=case.vin,
            event_id=f"bridge-{case.case_id}",
            ecu="CPC3", dtc_code="SHARED_TEST_SIGNAL",
            occurred_at=datetime(2026, 4, 29),
        ))
    return cases


def test_different_ml_groups_can_have_common_cpc3_core_without_automatic_merge():
    cases = _bridged_cases()
    result = cluster_hdbscan_cases(cases, selection_method="leaf")
    assert len(result.clusters) == 2
    audit = audit_diagnostic_evidence(cases)
    report = build_cluster_bridges(cases, result, audit)
    assert report.compared_pairs == 1
    assert report.cpc3_bridge_pairs == 1
    assert len(report.links) == 1
    bridge = report.links[0]
    assert ("CPC3", "SHARED_TEST_SIGNAL") in bridge.shared_cpc3
    assert bridge.between_pairs == 36
    assert 0 <= bridge.medoid_cosine <= 1
    assert 0 <= bridge.between_median_cosine <= 1
    assert bridge.independent_fin_pairs == bridge.between_pairs
    assert "Kein automatisches Zusammenlegen" in bridge.note
    assert "Keine bestätigten" in bridge.reviewed_mechanism_relation
    assert result.clustered_count == 12
    assert all(group.case_count == 6 for group in result.clusters)


def test_no_shared_core_cpc3_returns_no_links():
    cases = sample()
    result = cluster_hdbscan_cases(cases)
    audit = audit_diagnostic_evidence(cases)
    report = build_cluster_bridges(cases, result, audit)
    assert report.compared_pairs == 1
    assert not report.cpc3_bridge_pairs
    assert report.links == ()


def test_conflicting_confirmed_medoids_warn_without_relabeling():
    cases = _bridged_cases()
    result = cluster_hdbscan_cases(cases)
    audit = audit_diagnostic_evidence(cases)
    a, b = (group.representative_case_id for group in result.clusters)
    labels = (
        ConfirmedMechanism(case_id=a, mechanism_code="PUMP_WINDING_SHORT",
                           reviewer="Synthetic expert", evidence_ref="LAB-A",
                           confirmed_on=date(2026, 10, 9)),
        ConfirmedMechanism(case_id=b, mechanism_code="PUMP_HOSE_OBSTRUCTION",
                           reviewer="Synthetic expert", evidence_ref="LAB-B",
                           confirmed_on=date(2026, 10, 9)),
    )
    report = build_cluster_bridges(cases, result, audit, confirmations=labels)
    assert "Widerspruch" in report.links[0].reviewed_mechanism_relation
    assert "widersprechen" in report.links[0].note.lower()
    assert not hasattr(cases[0], "transferred_mechanism")


def test_same_fin_between_groups_cannot_be_independent_confirmation():
    cases = _bridged_cases()
    cases[6].vehicle = cases[6].vehicle.model_copy(
        update={"vin": cases[0].vin}
    )
    result = cluster_hdbscan_cases(cases)
    audit = audit_diagnostic_evidence(cases)
    report = build_cluster_bridges(cases, result, audit)
    assert len(report.links) == 1
    assert report.links[0].same_fin_between_pairs == 1
    assert report.links[0].independent_fin_pairs == 35
    assert "keine unabhängige Replikation" in report.links[0].note


def test_post_swap_findings_do_not_change_bridge_assignment():
    cases = _bridged_cases()
    before = cluster_hdbscan_cases(cases)
    audit = audit_diagnostic_evidence(cases)
    first = build_cluster_bridges(cases, before, audit)
    cases[0].qec_ssl_end_finding = "SYNTHETIC DIFFERENT TECHNICAL FINDING"
    assert build_cluster_bridges(cases, before, audit) == first
    after = cluster_hdbscan_cases(cases)
    assert [(g.case_ids, g.representative_case_id) for g in before.clusters] == [
        (g.case_ids, g.representative_case_id) for g in after.clusters
    ]
