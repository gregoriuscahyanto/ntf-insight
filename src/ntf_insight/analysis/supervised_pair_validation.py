"""Offline supervised *pair* learning from independently verified mechanisms.

This experiment is NOT a production root-cause model. Only explicitly confirmed
case-level mechanisms can make a pair label. Pair *features* use pre-swap
diagnostics exclusively. All instances of the same FIN are split together
BEFORE pair construction, so no QEC case or vehicle crosses train/test.
No training is performed if independent labeled evidence is insufficient.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from itertools import combinations

import numpy as np
from sklearn.feature_extraction import DictVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, precision_score, recall_score
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from ntf_insight.analysis.case_clustering import DiagnosticSignature, signature_for
from ntf_insight.analysis.mechanism_review import ConfirmedMechanism
from ntf_insight.domain.case import NTFCase


MIN_CONFIRMED_CASES = 30
MIN_VINS_PER_MECHANISM = 8
RANDOM_STATE = 41


@dataclass(frozen=True, slots=True)
class PairLearningEvaluation:
    status: str
    eligible_confirmations: int
    confirmed_mechanisms: int
    independent_vehicles: int
    train_case_count: int = 0
    test_case_count: int = 0
    train_pair_count: int = 0
    test_pair_count: int = 0
    test_same_mechanism_pairs: int = 0
    test_different_mechanism_pairs: int = 0
    test_precision: float | None = None
    test_recall: float | None = None
    test_average_precision: float | None = None
    test_positive_fraction: float | None = None
    train_vehicle_ids: frozenset[str] = field(default_factory=frozenset, repr=False)
    test_vehicle_ids: frozenset[str] = field(default_factory=frozenset, repr=False)

    @property
    def validated(self) -> bool:
        return self.test_average_precision is not None


def _jaccard(left: frozenset, right: frozenset) -> float:
    return len(left & right) / len(left | right) if left or right else 0.0


def _pair_features(a: DiagnosticSignature, b: DiagnosticSignature) -> dict[str, float]:
    """Symmetric, semantic-free feature groups, no case/VIN/SSL/repair tokens."""
    intersection = a.faults & b.faults
    return {
        "dtc_jaccard": _jaccard(a.faults, b.faults),
        "dtc_containment": (
            len(intersection) / min(len(a.faults), len(b.faults))
            if a.faults and b.faults else 0.0
        ),
        "dtc_shared_count": float(min(len(intersection), 20)),
        "dtc_size_ratio": (
            min(len(a.faults), len(b.faults))
            / max(len(a.faults), len(b.faults)) if a.faults and b.faults else 0.0
        ),
        "code_jaccard": _jaccard(a.codes, b.codes),
        "ecu_jaccard": _jaccard(a.ecus, b.ecus),
        "complaint_known": float(bool(a.complaint_tokens and b.complaint_tokens)),
        "complaint_jaccard": _jaccard(a.complaint_tokens, b.complaint_tokens),
        "software_known": float(bool(a.ecu_software and b.ecu_software)),
        "software_jaccard": _jaccard(a.ecu_software, b.ecu_software),
        "variant_known": float(bool(a.vehicle_variant and b.vehicle_variant)),
        "variant_jaccard": _jaccard(a.vehicle_variant, b.vehicle_variant),
    }


def _build_pairs(
    cases: list[NTFCase],
    labels: dict[str, ConfirmedMechanism],
    sigs: dict[str, DiagnosticSignature],
) -> tuple[list[dict[str, float]], np.ndarray]:
    # Each pair contains TWO different FINs. Correlated pair observations
    # still exist within a split, so precision must be treated as exploratory.
    x: list[dict[str, float]] = []
    y: list[int] = []
    for a, b in combinations(sorted(cases, key=lambda case: case.case_id), 2):
        if a.vin == b.vin:
            continue
        x.append(_pair_features(sigs[a.case_id], sigs[b.case_id]))
        y.append(int(
            labels[a.case_id].mechanism_code == labels[b.case_id].mechanism_code
        ))
    return x, np.asarray(y, dtype=int)


def evaluate_supervised_pairs(
    cases: list[NTFCase],
    confirmations: tuple[ConfirmedMechanism, ...],
    *,
    dtc_source: str = "all",
    lookback_days: int | None = None,
) -> PairLearningEvaluation:
    """Train/evaluate a temporary pair model only with enough reviewed cases.

    This is a test-only report: the model is deliberately not exposed for
    assigning new cluster members or recommending a repair.
    """
    by_id = {c.case_id: c for c in cases}
    if len(by_id) != len(cases):
        raise ValueError("Mehrfach angelegte QEC-Fall-ID.")
    labels = {review.case_id: review for review in confirmations}
    if len(labels) != len(confirmations):
        raise ValueError("Mehrfach bestätigte QEC-ID.")
    if not set(labels).issubset(by_id):
        raise ValueError("Fachliche Ursachenlabels passen nicht zum Fallbestand.")
    sigs = {
        cid: signature_for(case, dtc_source=dtc_source, lookback_days=lookback_days)
        for cid, case in sorted(by_id.items())
    }
    records = [
        by_id[cid] for cid in sorted(labels)
        if sigs[cid].has_replacement_anchor and sigs[cid].faults
    ]
    mechanism_counts = Counter(labels[c.case_id].mechanism_code for c in records)
    vehicles = {c.vin for c in records}
    base = {
        "eligible_confirmations": len(records),
        "confirmed_mechanisms": len(mechanism_counts),
        "independent_vehicles": len(vehicles),
    }
    if len(records) < MIN_CONFIRMED_CASES:
        return PairLearningEvaluation(
            f"Noch keine belastbare Lernbasis: mindestens {MIN_CONFIRMED_CASES} "
            "fachlich bestätigte QEC-Fälle mit Vorher-DTC benötigt.", **base
        )
    if len(mechanism_counts) < 2:
        return PairLearningEvaluation(
            "Mindestens zwei UNTERSCHIEDLICHE bestätigte Fehlermechanismen nötig.",
            **base,
        )
    if any(
        len({c.vin for c in records if labels[c.case_id].mechanism_code == mechanism})
        < MIN_VINS_PER_MECHANISM
        for mechanism in mechanism_counts
    ):
        return PairLearningEvaluation(
            f"Jeder Mechanismus braucht mindestens {MIN_VINS_PER_MECHANISM} "
            "unabhängige FINs mit bestätigtem Befund.", **base
        )

    label_y = [labels[c.case_id].mechanism_code for c in records]
    groups = [c.vin for c in records]
    splitter = StratifiedGroupKFold(
        n_splits=4, shuffle=True, random_state=RANDOM_STATE
    )
    candidate = None
    for train_idx, test_idx in splitter.split(
        np.zeros(len(records)), label_y, groups,
    ):
        training = [records[int(i)] for i in train_idx]
        testing = [records[int(i)] for i in test_idx]
        y_train = {label_y[int(i)] for i in train_idx}
        y_test = {label_y[int(i)] for i in test_idx}
        if len(y_train) < 2 or len(y_test) < 2:
            continue
        train_x, train_targets = _build_pairs(training, labels, sigs)
        test_x, test_targets = _build_pairs(testing, labels, sigs)
        if not train_x or not test_x or len(set(train_targets)) < 2 or len(set(test_targets)) < 2:
            continue
        candidate = (
            training, testing, train_x, train_targets, test_x, test_targets
        )
        break
    if candidate is None:
        return PairLearningEvaluation(
            "Keine fahrzeuggetrennte Testaufteilung mit positiven und "
            "negativen Ursachepaaren möglich. Kein Modell trainiert.", **base
        )

    training, testing, train_x, train_y, test_x, test_y = candidate
    model = Pipeline([
        ("features", DictVectorizer(sparse=False)),
        ("scale", StandardScaler()),
        ("logistic", LogisticRegression(
            max_iter=2500, class_weight="balanced", random_state=RANDOM_STATE,
        )),
    ])
    model.fit(train_x, train_y)
    scores = model.predict_proba(test_x)[:, 1]
    predictions = (scores >= 0.5).astype(int)
    return PairLearningEvaluation(
        status=(
            "Experimenteller fahrzeuggetrennter Test bestanden. "
            "Paar-Beobachtungen innerhalb der Testgruppe sind abhängig; "
            "keine Ursachenwahrscheinlichkeiten und keine Freigabe zur "
            "Ergebnisübertragung oder automatischen Fallzuordnung."
        ),
        train_case_count=len(training),
        test_case_count=len(testing),
        train_pair_count=len(train_y),
        test_pair_count=len(test_y),
        test_same_mechanism_pairs=int(test_y.sum()),
        test_different_mechanism_pairs=int(len(test_y) - test_y.sum()),
        test_precision=float(precision_score(
            test_y, predictions, zero_division=0,
        )),
        test_recall=float(recall_score(
            test_y, predictions, zero_division=0,
        )),
        test_average_precision=float(average_precision_score(test_y, scores)),
        test_positive_fraction=float(test_y.mean()),
        train_vehicle_ids=frozenset(c.vin for c in training),
        test_vehicle_ids=frozenset(c.vin for c in testing),
        **base,
    )
