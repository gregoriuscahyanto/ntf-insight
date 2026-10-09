"""Synthetic-only checks for conservative medoid-to-member hypotheses."""
from datetime import date

from ntf_insight.analysis.hdbscan_clustering import cluster_hdbscan_cases
from ntf_insight.analysis.mechanism_review import ConfirmedMechanism
from ntf_insight.analysis.representative_transfer import plan_representative_transfer

from test_hdbscan_clustering import sample


def _label(case_id, mechanism):
    return ConfirmedMechanism(
        case_id=case_id, mechanism_code=mechanism,
        reviewer="Synth expert", evidence_ref="8D-SYN",
        confirmed_on=date(2026, 10, 9),
    )


def test_no_verified_medoid_never_yields_root_cause():
    cases = sample()
    result = cluster_hdbscan_cases(cases)
    plan = plan_representative_transfer(cases, result, ())
    assert plan.representative_reviewed == 0
    assert plan.candidates == 0
    assert all(not row.mechanism_hypothesis for row in plan.rows)
    assert all("nicht fachlich bestätigt" in row.status for row in plan.rows)


def test_medoid_confirmation_never_assigns_confirmed_target_cause():
    cases = sample()
    result = cluster_hdbscan_cases(cases)
    group = result.clusters[0]
    medoid = group.representative_case_id
    labels = (_label(medoid, "PUMP_IMPELLER_BLOCKAGE"),)
    plan = plan_representative_transfer(cases, result, labels)
    rows = [row for row in plan.rows if row.group == f"H{group.cluster_id}"]
    assert rows
    assert all(row.mechanism_hypothesis == "PUMP_IMPELLER_BLOCKAGE" for row in rows)
    assert all("Prüf" in row.status or "Zurückgestellt" in row.status for row in rows)
    assert all(not hasattr(case, "transferred_mechanism") for case in cases)


def test_conflicting_reviewed_member_blocks_transfer():
    cases = sample()
    result = cluster_hdbscan_cases(cases)
    group = result.clusters[0]
    target = next(cid for cid in group.case_ids if cid != group.representative_case_id)
    labels = (
        _label(group.representative_case_id, "PUMP_ELECTRIC_OPEN"),
        _label(target, "PUMP_MECHANICAL_BLOCK"),
    )
    plan = plan_representative_transfer(cases, result, labels)
    row = next(r for r in plan.rows if r.target_case_id == target)
    assert row.status == "Widerspruch – Übertragung gesperrt"


def test_same_fin_not_independent():
    cases = sample()
    result = cluster_hdbscan_cases(cases)
    group = result.clusters[0]
    target = next(cid for cid in group.case_ids if cid != group.representative_case_id)
    rep_case = next(c for c in cases if c.case_id == group.representative_case_id)
    target_case = next(c for c in cases if c.case_id == target)
    target_case.vehicle = target_case.vehicle.model_copy(update={"vin": rep_case.vin})
    labels = (_label(group.representative_case_id, "PUMP_ELECTRIC_OPEN"),)
    plan = plan_representative_transfer(cases, result, labels)
    row = next(r for r in plan.rows if r.target_case_id == target)
    assert "Gleiche FIN" in row.status
