"""Trainable, retrospective root-cause hypotheses with held-out probability calibration.

Only explicitly expert-confirmed labels are eligible for training. Supplier identity,
VIN, assessments and supplier verdicts are NEVER model features. Probabilities are
conditional on the root-cause classes represented in the training set, not proof
of causation or supplier responsibility.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

import numpy as np
from sklearn.feature_extraction import DictVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, log_loss
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.pipeline import Pipeline

from ntf_insight.analysis.recurrence import analyze_recurrence, relative_to_replacement
from ntf_insight.domain.case import NTFCase
from ntf_insight.domain.enums import RootCauseCategory

MIN_TOTAL = 30
MIN_PER_CLASS = 6
MIN_GROUPS_PER_CLASS = 5
FOLDS = 5
RANDOM_STATE = 41


@dataclass(frozen=True, slots=True)
class ConfirmedCause:
    """An independently reviewed ground-truth label (not an ML prediction)."""

    case_id: str
    cause: RootCauseCategory
    reviewer: str
    evidence_ref: str
    confirmed_at: datetime

    def __post_init__(self) -> None:
        if self.cause == RootCauseCategory.UNKNOWN:
            raise ValueError("Eine unbekannte Ursache ist kein bestätigtes Trainingslabel.")
        if not self.case_id.strip() or not self.reviewer.strip() or not self.evidence_ref.strip():
            raise ValueError("Fall-ID, Prüfer und Evidenzreferenz müssen angegeben sein.")


@dataclass(frozen=True, slots=True)
class ValidationMetrics:
    train_count: int
    calibration_count: int
    test_count: int
    train_groups: int
    calibration_groups: int
    test_groups: int
    accuracy: float
    brier_score: float
    log_loss: float
    temperature: float


@dataclass(frozen=True, slots=True)
class CasePrediction:
    case_id: str
    probabilities: tuple[tuple[RootCauseCategory, float], ...]
    top_cause: RootCauseCategory
    top_probability: float
    review_required: bool
    review_notes: tuple[str, ...]
    supporting_model_features: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TrainingResult:
    model: RootCauseModel | None
    message: str
    eligible_count: int
    ignored_labels: int


def _snapshot(case: NTFCase, as_of: datetime | None) -> NTFCase:
    """Optionally exclude later observations for a timestamp-specific forecast."""
    if as_of is None:
        return case
    fields = (
        "diagnostic_sessions",
        "diagnostics",
        "ecu_states",
        "repairs",
        "replacements",
        "software_events",
        "supplier_findings",
    )
    changes = {
        name: [event for event in getattr(case, name) if event.occurred_at <= as_of]
        for name in fields
    }
    return case.model_copy(update=changes)


def extract_ml_features(case: NTFCase, as_of: datetime | None = None) -> dict[str, float]:
    """Leakage-aware numeric features based on observed vehicle signals and outcomes.

    A supplier finding is NOT a predictor: its presence could directly encode the
    target label. No VIN, supplier, part lot, free-text report or assessment is used.
    Unknown recurrence is kept distinct from an observed fault disappearance.
    """
    selected = _snapshot(case, as_of)
    replacement = selected.investigated_replacement()
    pre_events = [
        event for event in selected.diagnostics
        if replacement is None or relative_to_replacement(event, replacement) == "pre"
    ]
    pre_sessions = [
        session for session in selected.diagnostic_sessions
        if replacement is None or relative_to_replacement(session, replacement) == "pre"
    ]
    dtcs = {event.fault_key for event in pre_events}
    ecus = {ecu for ecu, _ in dtcs}
    features: dict[str, float] = {
        "pre_dtc_events": float(len(pre_events)),
        "pre_unique_dtcs": float(len(dtcs)),
        "pre_ecus": float(len(ecus)),
        "pre_sessions": float(len(pre_sessions)),
        "cpc3_dtc_events": float(sum(event.ecu.strip().upper() == "CPC3" for event in pre_events)),
        "pre_sporadic_events": float(
            sum("sporad" in (event.status or "").casefold()
                or "intermitt" in (event.status or "").casefold()
                for event in pre_events)
        ),
        "has_replacement": float(replacement is not None),
    }
    if selected.vehicle.model_series:
        features["series:" + selected.vehicle.model_series.strip().upper()] = 1.0

    for ecu, dtc in dtcs:
        features["dtc:" + ecu + ":" + dtc] = 1.0
    for ecu in ecus:
        features["ecu:" + ecu] = 1.0

    for state in selected.ecu_states:
        if replacement is not None and relative_to_replacement(state, replacement) != "pre":
            continue
        if state.software_version:
            features[
                "sw:" + state.ecu.strip().upper() + ":" + state.software_version.strip().upper()
            ] = 1.0

    recurrence = analyze_recurrence(selected)
    features["recurrence_assessable"] = float(recurrence.assessable)
    if recurrence.assessable:
        features["same_fault_count"] = float(len(recurrence.same_faults))
        features["new_fault_count"] = float(len(recurrence.new_faults))
        features["disappeared_fault_count"] = float(len(recurrence.disappeared_faults))

    # Only logged software events, not repair success, expert assessment or findings.
    features["cpc3_software_updates"] = float(
        sum(event.ecu.strip().upper() == "CPC3" for event in selected.software_events)
    )
    return features


def _temperature_adjust(probabilities: np.ndarray, temperature: float) -> np.ndarray:
    logits = np.log(np.clip(probabilities, 1e-12, 1.0)) / temperature
    logits -= logits.max(axis=1, keepdims=True)
    weights = np.exp(logits)
    return weights / weights.sum(axis=1, keepdims=True)


def _fit_temperature(probs: np.ndarray, truth: list[str], classes: list[str]) -> float:
    indices = np.array([classes.index(label) for label in truth])
    candidate_temperatures = np.linspace(0.5, 4.0, 71)
    losses = [
        -np.log(np.clip(_temperature_adjust(probs, float(t))[np.arange(len(truth)), indices],
                         1e-12, 1.0)).mean()
        for t in candidate_temperatures
    ]
    return float(candidate_temperatures[int(np.argmin(losses))])


def _new_pipeline() -> Pipeline:
    return Pipeline([
        ("vec", DictVectorizer(sparse=True)),
        ("clf", LogisticRegression(max_iter=2500, random_state=RANDOM_STATE)),
    ])


def _split_by_vehicle(y: list[str], groups: list[str]) -> tuple[list[int], list[int], list[int]] | None:
    """Disjoint VIN-group train/calibration/test partitions, with each class present."""
    wanted = set(y)
    folds = list(
        StratifiedGroupKFold(n_splits=FOLDS, shuffle=True, random_state=RANDOM_STATE)
        .split(np.zeros(len(y)), y, groups)
    )
    test_folds = [set(int(i) for i in test_idx) for _, test_idx in folds]
    everything = set(range(len(y)))
    for test in test_folds:
        for calibration in test_folds:
            if test is calibration:
                continue
            training = everything - test - calibration
            if all({y[i] for i in part} == wanted for part in (training, calibration, test)):
                return sorted(training), sorted(calibration), sorted(test)
    return None


@dataclass(slots=True)
class RootCauseModel:
    """Fitted model; its probabilities are conditional on observed label classes."""

    component_type: str
    pipeline: Pipeline
    metrics: ValidationMetrics

    @property
    def classes(self) -> tuple[RootCauseCategory, ...]:
        return tuple(RootCauseCategory(value) for value in self.pipeline.classes_)

    def predict(self, case: NTFCase, as_of: datetime | None = None) -> CasePrediction:
        if case.component_type.casefold() != self.component_type.casefold():
            raise ValueError("Der Fall gehört nicht zur Bauteilfamilie des Modells.")
        features = extract_ml_features(case, as_of=as_of)
        raw_probs = self.pipeline.predict_proba([features])
        probabilities = _temperature_adjust(raw_probs, self.metrics.temperature)[0]
        indices = np.argsort(-probabilities)
        classes = self.classes
        best = int(indices[0])

        notes: list[str] = []
        if probabilities[best] < 0.70:
            notes.append("Keine ausreichend dominante Ursache.")
        if not case.diagnostic_sessions:
            notes.append("Keine dokumentierten Diagnose-Sitzungen.")
        vocabulary = self.pipeline.named_steps["vec"].vocabulary_
        dtc_features = [key for key in features if key.startswith("dtc:")]
        if dtc_features and not any(key in vocabulary for key in dtc_features):
            notes.append("Unbekanntes DTC-Muster im Trainingsbestand.")
        unseen = set(RootCauseCategory) - set(classes) - {RootCauseCategory.UNKNOWN}
        if unseen:
            notes.append("Nicht alle Ursachenklassen sind im Training vertreten.")

        x = self.pipeline.named_steps["vec"].transform([features])
        coefficients = self.pipeline.named_steps["clf"].coef_
        # sklearn stores one coefficient vector for the positive class in binary models.
        if len(classes) == 2:
            weights = coefficients[0] * (1 if best == 1 else -1)
        else:
            weights = coefficients[best]
        contributions = np.asarray(x.multiply(weights).toarray()).ravel()
        names = self.pipeline.named_steps["vec"].get_feature_names_out()
        ranked = np.argsort(-contributions)
        top_features = tuple(
            str(names[i])
            for i in ranked
            if contributions[i] > 0 and not str(names[i]).startswith("series:")
        )[:4]

        return CasePrediction(
            case_id=case.case_id,
            probabilities=tuple((classes[int(i)], float(probabilities[int(i)])) for i in indices),
            top_cause=classes[best],
            top_probability=float(probabilities[best]),
            review_required=bool(notes),
            review_notes=tuple(notes),
            supporting_model_features=top_features,
        )

    def predict_many(
        self, cases: Iterable[NTFCase], as_of: datetime | None = None
    ) -> list[CasePrediction]:
        return [
            self.predict(case, as_of=as_of)
            for case in cases
            if case.component_type.casefold() == self.component_type.casefold()
        ]


def train_root_cause_model(
    cases: Iterable[NTFCase],
    confirmed: Iterable[ConfirmedCause],
    component_type: str = "Coolant Pump",
) -> TrainingResult:
    """Fit only with expert-confirmed labels; hold test VIN groups completely out."""
    matching_cases = {
        case.case_id: case for case in cases
        if case.component_type.casefold() == component_type.casefold()
    }
    latest_labels = {label.case_id: label for label in confirmed}
    records = sorted(
        ((matching_cases[case_id], label) for case_id, label in latest_labels.items()
         if case_id in matching_cases),
        key=lambda pair: pair[0].case_id,
    )
    ignored = len(latest_labels) - len(records)
    counts = Counter(label.cause.value for _, label in records)
    if len(records) < MIN_TOTAL or len(counts) < 2:
        return TrainingResult(
            None,
            f"Mindestens {MIN_TOTAL} bestätigte Fälle aus mindestens zwei Ursachenklassen erforderlich.",
            len(records),
            ignored,
        )
    if any(count < MIN_PER_CLASS for count in counts.values()):
        return TrainingResult(
            None,
            f"Jede vorhandene Ursachenklasse benötigt mindestens {MIN_PER_CLASS} geprüfte Fälle.",
            len(records),
            ignored,
        )
    if any(
        len({case.vin for case, label in records if label.cause.value == cause})
        < MIN_GROUPS_PER_CLASS
        for cause in counts
    ):
        return TrainingResult(
            None,
            f"Mindestens {MIN_GROUPS_PER_CLASS} unterschiedliche Fahrzeuge je Ursache erforderlich.",
            len(records),
            ignored,
        )

    features = [extract_ml_features(case) for case, _ in records]
    y = [label.cause.value for _, label in records]
    groups = [case.vin for case, _ in records]
    split = _split_by_vehicle(y, groups)
    if split is None:
        return TrainingResult(
            None,
            "Keine valide fahrzeuggetrennte Aufteilung in Training, Kalibrierung und Test möglich.",
            len(records),
            ignored,
        )
    train_idx, cal_idx, test_idx = split
    pipeline = _new_pipeline()
    pipeline.fit([features[i] for i in train_idx], [y[i] for i in train_idx])

    calibration_probabilities = pipeline.predict_proba([features[i] for i in cal_idx])
    classes = list(pipeline.classes_)
    temperature = _fit_temperature(calibration_probabilities, [y[i] for i in cal_idx], classes)
    test_probs = _temperature_adjust(
        pipeline.predict_proba([features[i] for i in test_idx]), temperature
    )
    test_true = [y[i] for i in test_idx]
    truth_matrix = np.eye(len(classes))[[classes.index(label) for label in test_true]]
    brier = float(np.mean(np.sum((test_probs - truth_matrix) ** 2, axis=1)))
    metrics = ValidationMetrics(
        train_count=len(train_idx),
        calibration_count=len(cal_idx),
        test_count=len(test_idx),
        train_groups=len({groups[i] for i in train_idx}),
        calibration_groups=len({groups[i] for i in cal_idx}),
        test_groups=len({groups[i] for i in test_idx}),
        accuracy=float(accuracy_score(test_true, [classes[i] for i in np.argmax(test_probs, axis=1)])),
        brier_score=brier,
        log_loss=float(log_loss(test_true, test_probs, labels=classes)),
        temperature=temperature,
    )
    return TrainingResult(
        RootCauseModel(component_type, pipeline, metrics),
        "Modell trainiert; Testgruppen wurden weder zum Lernen noch zur Kalibrierung verwendet.",
        len(records),
        ignored,
    )
