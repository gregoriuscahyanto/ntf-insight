"""Synthetic-only validation of individual medoid-to-target mechanism evidence."""
from __future__ import annotations

import csv
from datetime import date
from io import StringIO

import pytest

from ntf_insight.analysis.cluster_pilot_priority import prioritize_cluster_pilots
from ntf_insight.analysis.diagnostic_evidence_audit import audit_diagnostic_evidence
from ntf_insight.analysis.hdbscan_clustering import cluster_hdbscan_cases
from ntf_insight.analysis.mechanism_review import (
    ConfirmedMechanism, read_confirmed_mechanisms,
)
from ntf_insight.analysis.pilot_expert_validation import (
    merge_confirmed_mechanisms, validate_pilot_evidence,
    write_pilot_review_template,
)
from ntf_insight.analysis.representative_transfer import plan_representative_transfer
from test_hdbscan_clustering import sample


def _label(case_id, code="PUMP_MECHANICAL_JAM", evidence=None):
    return ConfirmedMechanism(
        case_id=case_id, mechanism_code=code, reviewer="Fictional expert",
        evidence_ref=evidence or f"SYNTHETIC-LAB-{case_id}",
        confirmed_on=date(2026, 10, 9),
    )


def _baseline():
    cases = sample()
    result = cluster_hdbscan_cases(cases)
    audit = audit_diagnostic_evidence(cases)
    first = result.clusters[0]
    rep = first.representative_case_id
    targets = [cid for cid in first.case_ids if cid != rep]
    return cases, result, audit, first, rep, targets


def test_zero_expert_labels_cannot_report_validated_cause_or_accuracy():
    cases, result, _, _, _, _ = _baseline()
    validation = validate_pilot_evidence(cases, result, ())
    assert validation.reviewed_representatives == 0
    assert validation.comparable_target_fins == 0
    assert validation.concordant_target_fins == 0
    assert validation.discordant_target_fins == 0
    assert validation.groups_with_conflict == 0
    assert all("nicht bestätigt" in group.status for group in validation.groups)
    assert all(not target.representative_mechanism for target in validation.targets)


def test_one_agreement_and_conflict_only_measure_two_separate_target_fins():
    cases, result, _, group, rep, targets = _baseline()
    labels = (
        _label(rep),
        _label(targets[0]),
        _label(targets[1], "PUMP_WINDING_SHORT"),
    )
    validation = validate_pilot_evidence(cases, result, labels)
    section = next(g for g in validation.groups if g.group == f"H{group.cluster_id}")
    assert validation.reviewed_representatives == 1
    assert section.independently_reviewed_target_fins == 2
    assert section.concordant_target_fins == 1
    assert section.discordant_target_fins == 1
    assert section.status.startswith("Widerspruch")
    assert validation.groups_with_conflict == 1
    assert {t.status for t in validation.targets if t.group == section.group} >= {
        "Getrennte Evidenz: Mechanismus übereinstimmend",
        "Widerspruch: anderer bestätigter Mechanismus",
    }
    assert len([t for t in validation.targets if t.group == section.group]) == 5
    # The actual clustering and source cases are not trained on findings.
    assert result.clusters[0] == group
    assert all(not hasattr(case, "transferred_mechanism") for case in cases)


def test_verified_conflict_blocks_other_unreviewed_members():
    cases, result, _, group, rep, targets = _baseline()
    labels = (
        _label(rep),
        _label(targets[0], "PUMP_HOSE_LEAK"),
    )
    transfer = plan_representative_transfer(cases, result, labels)
    others = [
        row for row in transfer.rows
        if row.group == f"H{group.cluster_id}" and row.target_case_id not in targets[:1]
    ]
    assert others
    assert all(
        row.status == "Clusterwiderspruch – Hypothesenübertragung gesperrt"
        for row in others
    )
    assert transfer.candidates == 0


def test_repeated_evidence_ref_is_not_independent_confirmation():
    cases, result, _, group, rep, targets = _baseline()
    labels = (
        _label(rep, evidence="SAME-FICTIONAL-LAB-REPORT"),
        _label(targets[0], evidence="SAME-FICTIONAL-LAB-REPORT"),
    )
    report = validate_pilot_evidence(cases, result, labels)
    section = next(g for g in report.groups if g.group == f"H{group.cluster_id}")
    assert section.shared_evidence_excluded == 1
    assert section.independently_reviewed_target_fins == 0
    target = next(t for t in report.targets if t.target_case_id == targets[0])
    assert "Evidenzreferenz mehrfach" in target.status


def test_same_fin_and_multiple_confirmed_qecs_same_fin_are_not_replicates():
    cases, result, _, group, rep, targets = _baseline()
    by_id = {case.case_id: case for case in cases}
    by_id[targets[0]].vehicle = by_id[targets[0]].vehicle.model_copy(
        update={"vin": by_id[rep].vin}
    )
    by_id[targets[1]].vehicle = by_id[targets[1]].vehicle.model_copy(
        update={"vin": by_id[targets[2]].vin}
    )
    labels = tuple(_label(cid) for cid in (rep, targets[0], targets[1], targets[2]))
    report = validate_pilot_evidence(cases, result, labels)
    section = next(g for g in report.groups if g.group == f"H{group.cluster_id}")
    assert section.same_fin_excluded == 1
    assert section.repeated_fin_excluded == 2
    assert section.independently_reviewed_target_fins == 0
    assert report.comparable_target_fins == 0


def test_evidence_ref_shared_by_two_different_target_fins_is_excluded():
    cases, result, _, group, rep, targets = _baseline()
    labels = (
        _label(rep, evidence="LAB-REP"),
        _label(targets[0], evidence="SAME-LAB-FILE"),
        _label(targets[1], evidence="SAME-LAB-FILE"),
    )
    report = validate_pilot_evidence(cases, result, labels)
    section = next(g for g in report.groups if g.group == f"H{group.cluster_id}")
    assert section.shared_evidence_excluded == 2
    assert section.independently_reviewed_target_fins == 0


def test_editable_pilot_csv_contains_only_selected_cases_and_preserves_labels():
    cases, result, audit, _, rep, targets = _baseline()
    labels = (_label(rep),)
    plan = prioritize_cluster_pilots(
        cases, result, audit, confirmations=labels,
    )
    out = StringIO()
    write_pilot_review_template(
        out, cases, plan, confirmations=labels,
    )
    text = out.getvalue()
    rows = list(csv.DictReader(StringIO(text), delimiter=";"))
    assert len(rows) == len(plan.inspections)
    assert [row["qec_case_id"] for row in rows] == [
        item.case_id for item in plan.inspections
    ]
    assert len(rows) <= 3 * len(result.clusters)
    rep_row = next(row for row in rows if row["qec_case_id"] == rep)
    assert rep_row["review_status"] == "confirmed"
    assert rep_row["evidence_ref"] == f"SYNTHETIC-LAB-{rep}"
    assert rep_row["mechanism_code"] == "PUMP_MECHANICAL_JAM"
    assert all(row["review_status"] == "pending" for row in rows
               if row["qec_case_id"] != rep)
    assert read_confirmed_mechanisms(StringIO(text), cases) == labels

    target_row = next(
        row for row in rows if row["pilot_group"] == f"H{result.clusters[0].cluster_id}"
        and row["qec_case_id"] != rep
    )
    target_row.update(
        review_status="confirmed",
        mechanism_code="PUMP_MECHANICAL_JAM",
        reviewer="Fictional expert",
        evidence_ref="SYNTHETIC-NEW-LAB",
        confirmed_on="2026-10-09",
    )
    csv_output = StringIO()
    writer = csv.DictWriter(csv_output, fieldnames=rows[0], delimiter=";")
    writer.writeheader()
    writer.writerows(rows)
    imported = read_confirmed_mechanisms(StringIO(csv_output.getvalue()), cases)
    assert len(imported) == 2
    review = validate_pilot_evidence(cases, result, imported)
    assert review.comparable_target_fins == 1
    assert review.concordant_target_fins == 1


def test_merge_subsets_preserves_previous_labels_and_refuses_overwrite():
    previous = (_label("A0"),)
    another = (_label("B0"),)
    assert merge_confirmed_mechanisms(previous, another) == (*previous, *another)
    assert merge_confirmed_mechanisms(previous, ()) == previous
    assert merge_confirmed_mechanisms(previous, previous) == previous
    with pytest.raises(ValueError, match="Widersprechende"):
        merge_confirmed_mechanisms(previous, (_label("A0", "OTHER_CAUSE"),))
    with pytest.raises(ValueError, match="mehrfach"):
        merge_confirmed_mechanisms(previous, (another[0], another[0]))


def test_manually_entered_fin_must_match_qec_case():
    cases, _, _, _, rep, _ = _baseline()
    bad = StringIO(
        "qec_case_id;fin;review_status;mechanism_code;reviewer;evidence_ref;confirmed_on\n"
        f"{rep};WRONG-FIN;confirmed;PUMP_MECHANICAL_JAM;expert;LAB-1;2026-10-09\n"
    )
    with pytest.raises(ValueError, match="FIN stimmt nicht"):
        read_confirmed_mechanisms(bad, cases)


def test_same_fin_mechanism_conflict_is_warned_but_not_independent_agreement():
    cases, result, _, group, rep, targets = _baseline()
    by_id = {case.case_id: case for case in cases}
    by_id[targets[0]].vehicle = by_id[targets[0]].vehicle.model_copy(
        update={"vin": by_id[rep].vin}
    )
    findings = (
        _label(rep, code="PUMP_OPEN_CIRCUIT"),
        _label(targets[0], code="PUMP_STUCK_ROTOR"),
    )
    report = validate_pilot_evidence(cases, result, findings)
    current = next(row for row in report.groups if row.group == f"H{group.cluster_id}")
    assert current.independently_reviewed_target_fins == 0
    assert current.unresolved_mechanism_conflicts == 1
    assert report.groups_with_conflict == 1
    assert "gesperrt" in current.status
    plan = plan_representative_transfer(cases, result, findings)
    assert all(
        x.status == "Clusterwiderspruch – Hypothesenübertragung gesperrt"
        for x in plan.rows
        if x.group == current.group and x.target_case_id != targets[0]
    )
