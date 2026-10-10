"""Local robustness checks for diagnostic clusters, not root-cause validation.

Compare actual co-clustered QEC case PAIRS, never arbitrary cluster labels or
2D/3D coordinates. A data-source/window sensitivity experiment may change
eligibility: only cases eligible in BOTH runs can enter a pair denominator.

The report exposes counts and run-local cluster numbers, but no VINs, QEC
identifiers, DTC keys, laboratory texts or evidence files.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from itertools import combinations

from ntf_insight.analysis.cluster_workspace_engine import (
    ClusterParameters, UnifiedClusterResult, positive_pairs,
)


@dataclass(frozen=True, slots=True)
class GroupPairRetention:
    """Retention of ONE reference group, on the shared eligible cohort."""

    group_number: int
    reference_members: int
    comparable_members: int
    reference_pairs: int
    retained_pairs: int
    newly_joined_external_pairs: int

    @property
    def retention(self) -> float | None:
        return (
            self.retained_pairs / self.reference_pairs
            if self.reference_pairs else None
        )


@dataclass(frozen=True, slots=True)
class StabilityComparison:
    """No case identifiers leave this analytical summary."""

    label: str
    category: str
    shared_eligible: int
    baseline_eligible: int
    comparison_eligible: int
    reference_pairs: int
    comparison_pairs: int
    shared_pairs: int
    pair_jaccard: float | None
    reference_pair_retention: float | None
    group_rows: tuple[GroupPairRetention, ...]
    warning: str

    @property
    def coverage(self) -> float | None:
        return (
            self.shared_eligible / self.baseline_eligible
            if self.baseline_eligible else None
        )


@dataclass(frozen=True, slots=True)
class ClusterStabilityReport:
    reference_method: str
    reference_eligible: int
    comparisons: tuple[StabilityComparison, ...]


def sensitivity_scenarios(
    params: ClusterParameters,
) -> tuple[tuple[str, ClusterParameters], ...]:
    """Predefined one-factor-at-a-time experiments; never fit a threshold.

    Each scenario uses the same cases and the selected *method*, changing
    just one input. This is different from cross-method comparison, where
    all input diagnostic features stay fixed.
    """
    params.validate()
    variants: list[tuple[str, ClusterParameters]] = []
    for source, label in (
        ("all", "QuickTest + AutoExport"),
        ("quicktest", "Nur QuickTest"),
        ("autoexport", "Nur AutoExport"),
    ):
        if source != params.dtc_source:
            variants.append((f"DTC-Quelle: {label}", replace(params, dtc_source=source)))

    for days, label in (
        (None, "Gesamte Vorher-Historie"),
        (90, "90 Tage"),
        (365, "365 Tage"),
    ):
        if days != params.lookback_days:
            variants.append((
                f"Diagnosefenster: {label}",
                replace(params, lookback_days=days),
            ))

    if params.method != "complete_legacy":
        cutoff = None if params.common_dtc_cutoff is not None else 0.35
        label = "Aus" if cutoff is None else "Ab 35 %"
        variants.append((
            f"DTC-Häufigkeitsfilter: {label}",
            replace(params, common_dtc_cutoff=cutoff),
        ))

    if params.method in {"leaf", "eom"}:
        samples = 3 if params.min_samples == 2 else 2
        variants.append((
            f"MinSamples: {samples}",
            replace(params, min_samples=samples),
        ))

    size = 4 if params.min_cluster_size == 3 else 3
    variants.append((
        f"Mindestclustergröße: {size}",
        replace(params, min_cluster_size=size),
    ))
    return tuple(variants)


def _case_universe(run: UnifiedClusterResult) -> frozenset[str]:
    eligible = run.eligible_case_ids
    excluded = run.excluded_case_ids
    noise = run.noise_case_ids
    if (
        len(set(eligible)) != len(eligible)
        or len(set(excluded)) != len(excluded)
        or set(eligible) & set(excluded)
        or len(set(noise)) != len(noise)
        or not set(noise).issubset(eligible)
    ):
        raise ValueError("Stabilitätsprüfung: ungültige Fallgrundgesamtheit.")
    assigned = [cid for group in run.groups for cid in group.case_ids]
    if (
        len(assigned) != len(set(assigned))
        or not set(assigned).issubset(eligible)
        or set(assigned) & set(noise)
        or set(assigned) | set(noise) != set(eligible)
    ):
        raise ValueError("Stabilitätsprüfung: ungültige Gruppenzugehörigkeit.")
    return frozenset(eligible) | frozenset(excluded)


def compare_stability(
    baseline: UnifiedClusterResult,
    candidate: UnifiedClusterResult,
    *,
    label: str,
    category: str,
) -> StabilityComparison:
    """Compare membership *within shared eligibility*, including merges.

    High group retention does NOT imply high global Jaccard: a broader
    method can retain every original group pair but also merge groups.
    Cases missing in the candidate are 'not comparable', never negative
    evidence. No metric is a probability of identical root causes.
    """
    if category not in {"Verfahren", "Daten/Parameter"} or not label.strip():
        raise ValueError("Stabilitätsprüfung: ungültiges Vergleichsszenario.")
    if _case_universe(baseline) != _case_universe(candidate):
        raise ValueError("Stabilitätsprüfung benötigt denselben QEC-Fallbestand.")
    if category == "Verfahren":
        left, right = baseline.parameters, candidate.parameters
        # Only method and method-specific cutoffs may differ here.
        if (
            left.dtc_source != right.dtc_source
            or left.lookback_days != right.lookback_days
            or left.common_dtc_cutoff != right.common_dtc_cutoff
            or left.min_cluster_size != right.min_cluster_size
            or left.min_samples != right.min_samples
        ):
            raise ValueError("Methodenvergleich muss dieselbe Diagnosebasis nutzen.")
        if set(baseline.eligible_case_ids) != set(candidate.eligible_case_ids):
            raise ValueError("Methodenvergleich benötigt dieselben geeigneten Fälle.")
    elif baseline.parameters.method != candidate.parameters.method:
        raise ValueError("Sensitivitätsvergleich muss dasselbe Verfahren nutzen.")

    comparable = set(baseline.eligible_case_ids) & set(candidate.eligible_case_ids)
    left_pairs = {
        pair for pair in positive_pairs(baseline)
        if set(pair).issubset(comparable)
    }
    right_pairs = {
        pair for pair in positive_pairs(candidate)
        if set(pair).issubset(comparable)
    }
    overlap = left_pairs & right_pairs
    union = left_pairs | right_pairs

    detail: list[GroupPairRetention] = []
    for group in baseline.groups:
        original = set(group.case_ids)
        active = sorted(original & comparable)
        possible = set(combinations(active, 2))
        newly_joined = sum(
            (left in active and right not in original)
            or (right in active and left not in original)
            for left, right in right_pairs
        )
        detail.append(GroupPairRetention(
            group_number=group.cluster_id,
            reference_members=group.case_count,
            comparable_members=len(active),
            reference_pairs=len(possible),
            retained_pairs=len(possible & right_pairs),
            newly_joined_external_pairs=newly_joined,
        ))

    if category == "Verfahren":
        warning = (
            "Dieselben Vor-Tausch-Merkmale, keine unabhängigen Ursachenbelege. "
            "DTC-Jaccard nutzt eine andere Metrik."
        )
    else:
        warning = (
            "Andere Datenabdeckung möglich: nur beidseitig geeignete Fälle "
            "im Paarvergleich. Fehlende Diagnosen sind kein Widerspruch."
        )
    return StabilityComparison(
        label=label,
        category=category,
        shared_eligible=len(comparable),
        baseline_eligible=len(baseline.eligible_case_ids),
        comparison_eligible=len(candidate.eligible_case_ids),
        reference_pairs=len(left_pairs),
        comparison_pairs=len(right_pairs),
        shared_pairs=len(overlap),
        pair_jaccard=len(overlap) / len(union) if union else None,
        reference_pair_retention=(
            len(overlap) / len(left_pairs) if left_pairs else None
        ),
        group_rows=tuple(detail),
        warning=warning,
    )


def build_stability_report(
    baseline: UnifiedClusterResult,
    comparisons: tuple[tuple[str, str, UnifiedClusterResult], ...],
) -> ClusterStabilityReport:
    """Aggregate local cross-method and one-factor-at-a-time comparisons."""
    labels = [(category, label) for category, label, _ in comparisons]
    if len(labels) != len(set(labels)):
        raise ValueError("Doppelte Stabilitätsszenarien.")
    return ClusterStabilityReport(
        reference_method=baseline.parameters.method,
        reference_eligible=len(baseline.eligible_case_ids),
        comparisons=tuple(
            compare_stability(baseline, run, label=label, category=category)
            for category, label, run in comparisons
        ),
    )
