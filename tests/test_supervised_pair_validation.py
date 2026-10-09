"""Gated supervised case-pair experiment with independent FIN holdout."""
from datetime import date, datetime

import pytest

from ntf_insight.analysis.mechanism_review import ConfirmedMechanism
from ntf_insight.analysis.supervised_pair_validation import (
    _pair_features, evaluate_supervised_pairs,
)
from ntf_insight.analysis.case_clustering import signature_for
from ntf_insight.domain.events import DiagnosticEvent, SupplierFinding, TipsCaseObservation

from test_hdbscan_clustering import sample, synthetic


def _labeled_cohort(n: int = 48):
    cases = []
    labels = []
    for i in range(n):
        kind = "A" if i % 2 == 0 else "B"
        case = synthetic(f"QEC-{i:03d}", kind, i + 500)
        cases.append(case)
        labels.append(ConfirmedMechanism(
            case_id=case.case_id,
            mechanism_code="PCB_SHORT" if kind == "A" else "PIN_CORROSION",
            reviewer="Synthetic expert", evidence_ref=f"8D-SYN-{i}",
            confirmed_on=date(2026, 10, 9),
        ))
    return cases, tuple(labels)


def test_gated_pair_model_abstains_without_independent_confirmed_mechanisms():
    cases = sample()
    result = evaluate_supervised_pairs(cases, ())
    assert not result.validated
    assert result.train_pair_count == 0
    assert result.test_precision is None
    assert "mindestens 30" in result.status.lower()
    fake_labels = (
        ConfirmedMechanism(
            case_id=cases[0].case_id,
            mechanism_code="MECH_ALPHA", reviewer="expert",
            evidence_ref="8D-SYN", confirmed_on=date(2026, 10, 9),
        ),
    )
    incomplete = evaluate_supervised_pairs(cases, fake_labels)
    assert not incomplete.validated
    assert incomplete.eligible_confirmations == 1


def test_heldout_pair_model_trains_only_when_confirmed_fin_disjoint():
    cases, labels = _labeled_cohort()
    result = evaluate_supervised_pairs(cases, labels)
    assert result.validated, result.status
    assert result.confirmed_mechanisms == 2
    assert result.independent_vehicles == len(cases)
    assert result.eligible_confirmations == len(cases)
    assert result.train_vehicle_ids.isdisjoint(result.test_vehicle_ids)
    assert len(result.train_vehicle_ids) == result.train_case_count
    assert len(result.test_vehicle_ids) == result.test_case_count
    assert result.train_pair_count > 0 and result.test_pair_count > 0
    assert result.test_same_mechanism_pairs > 0
    assert result.test_different_mechanism_pairs > 0
    assert 0 <= result.test_precision <= 1
    assert 0 <= result.test_recall <= 1
    assert 0 <= result.test_average_precision <= 1
    assert 0 < result.test_positive_fraction < 1
    assert result == evaluate_supervised_pairs(list(reversed(cases)), labels)


def test_after_swap_dtc_and_ssl_and_post_tips_do_not_change_pair_validation():
    cases, labels = _labeled_cohort()
    original = evaluate_supervised_pairs(cases, labels)
    cases[0].qec_ssl_end_finding = "Synthetic PCB solder short"
    cases[1].supplier_findings.append(SupplierFinding(
        vin=cases[1].vin, occurred_at=datetime(2026, 5, 20),
        failure_mode="Synthetic corrosion",
    ))
    cases[2].diagnostics.append(DiagnosticEvent(
        vin=cases[2].vin, occurred_at=datetime(2026, 5, 22),
        ecu="CPC3", dtc_code="OUTCOME_ONLY",
    ))
    cases[3].tips_observations.append(TipsCaseObservation(
        vin=cases[3].vin, occurred_at=datetime(2026, 6, 1),
        complaint="Repair completed and controller replaced",
        performed_actions="Synthetic action",
    ))
    updated = evaluate_supervised_pairs(cases, labels)
    assert updated == original


def test_pair_features_are_symmetric_without_qec_or_vin_or_ssl():
    cases, _ = _labeled_cohort(2)
    a, b = [signature_for(case) for case in cases]
    f = _pair_features(a, b)
    assert f == _pair_features(b, a)
    assert set(f).issubset({
        "dtc_jaccard", "dtc_containment", "dtc_shared_count",
        "dtc_size_ratio", "code_jaccard", "ecu_jaccard",
        "complaint_known", "complaint_jaccard", "software_known",
        "software_jaccard", "variant_known", "variant_jaccard",
    })
    assert all(not name.startswith("qec") and "ssl" not in name
               for name in f)


def test_labels_not_matching_current_scope_are_rejected():
    cases, labels = _labeled_cohort()
    with pytest.raises(ValueError):
        evaluate_supervised_pairs(cases[:30], labels)


def test_insufficient_independent_vehicles_not_enough_for_training():
    cases, labels = _labeled_cohort(48)
    for index, case in enumerate(cases):
        case.vehicle = case.vehicle.model_copy(
            update={"vin": f"SYNTHETIC-CAR-{index % 6}"}
        )
    evaluation = evaluate_supervised_pairs(cases, labels)
    assert not evaluation.validated
    assert "unabhängige FIN" in evaluation.status
