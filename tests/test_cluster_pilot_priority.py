"""Synthetic, deterministic medoid/target prioritization, never causal inference."""
from __future__ import annotations

from datetime import date

from ntf_insight.analysis.cluster_pilot_priority import prioritize_cluster_pilots
from ntf_insight.analysis.diagnostic_evidence_audit import audit_diagnostic_evidence
from ntf_insight.analysis.hdbscan_clustering import cluster_hdbscan_cases
from ntf_insight.analysis.mechanism_review import ConfirmedMechanism
from test_hdbscan_clustering import sample


def _plan(cases, labels=()):
    model = cluster_hdbscan_cases(cases)
    audit = audit_diagnostic_evidence(cases)
    return prioritize_cluster_pilots(
        cases, model, audit, confirmations=labels,
    ), model


def test_one_actual_medoid_per_cluster_and_only_independent_targets():
    cases = sample()
    plan, model = _plan(cases)
    assert len(model.clusters) == 2
    assert plan.representative_count == len(model.clusters)
    assert len(plan.groups) == len(model.clusters)
    by_id = {case.case_id: case for case in cases}
    for cluster in model.clusters:
        group = next(row for row in plan.groups if row.group == f"H{cluster.cluster_id}")
        entries = [row for row in plan.inspections if row.group == group.group]
        assert entries[0].case_id == cluster.representative_case_id
        assert entries[0].role.startswith("Repräsentant")
        assert len(entries) <= 3
        assert all(entry.representative_case_id == cluster.representative_case_id
                   for entry in entries)
        assert all(by_id[row.case_id].vin != by_id[cluster.representative_case_id].vin
                   for row in entries[1:])
        assert len({by_id[row.case_id].vin for row in entries[1:]}) == len(entries)-1
        assert all("Evidenz" in row.note or "Ursachenprüfung" in row.note
                   or "Einzelfallvergleich" in row.note
                   for row in entries)
    assert plan.independent_targets == len(plan.inspections) - plan.representative_count


def test_same_fin_cannot_be_selected_as_a_separate_validation_vehicle():
    cases = sample()
    model = cluster_hdbscan_cases(cases)
    cluster = model.clusters[0]
    rep = next(c for c in cases if c.case_id == cluster.representative_case_id)
    member = next(c for c in cases if c.case_id in cluster.case_ids and c.case_id != rep.case_id)
    member.vehicle = member.vehicle.model_copy(update={"vin": rep.vin})
    plan, _ = _plan(cases)
    assert all(
        entry.case_id != member.case_id for entry in plan.inspections
        if entry.case_id != entry.representative_case_id
    )


def test_fach_confirmation_only_marks_rep_not_other_cluster_members():
    cases = sample()
    _, model = _plan(cases)
    medoid = model.clusters[0].representative_case_id
    label = ConfirmedMechanism(
        case_id=medoid, mechanism_code="PUMP_MECHANICAL_JAM",
        reviewer="Fictional reviewer", evidence_ref="SYNTHETIC-LAB",
        confirmed_on=date(2026, 10, 9),
    )
    plan, _ = _plan(cases, (label,))
    assert sum(row.representative_confirmed for row in plan.groups) == 1
    assert "Unabhängig bestätigt" in next(
        row.note for row in plan.inspections if row.case_id == medoid
    )
    assert not any(hasattr(case, "transferred_mechanism") for case in cases)
    assert all("automatisch" not in row.role for row in plan.inspections)


def test_plan_is_order_independent_and_never_becomes_root_cause_probability():
    cases = sample()
    original, model = _plan(cases)
    reverse, same_model = _plan(list(reversed(cases)))
    assert model == same_model
    assert original == reverse
    assert all(row.priority.startswith(("P1", "P2", "P3", "P4"))
               for row in original.groups)
