"""Transparent case similarity used before introducing clustering algorithms."""

from __future__ import annotations

from dataclasses import dataclass

from ntf_insight.analysis.recurrence import analyze_recurrence
from ntf_insight.domain.case import NTFCase


@dataclass(frozen=True, slots=True)
class SimilarityResult:
    left_case_id: str
    right_case_id: str
    score: float
    shared_faults: tuple[tuple[str, str], ...]
    shared_ecus: tuple[str, ...]
    same_recurrence_pattern: bool


def _jaccard(left: set[object], right: set[object]) -> float:
    if not left and not right:
        return 1.0
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def compare_cases(left: NTFCase, right: NTFCase) -> SimilarityResult:
    """Compute an explainable baseline similarity score in [0, 1].

    This is intentionally simple and deterministic. It provides a useful baseline and
    debugging tool before HDBSCAN/UMAP are introduced on real data.
    """
    left_faults = {event.fault_key for event in left.diagnostics}
    right_faults = {event.fault_key for event in right.diagnostics}
    left_ecus = {event.ecu.strip().upper() for event in left.diagnostics}
    right_ecus = {event.ecu.strip().upper() for event in right.diagnostics}

    left_rec = analyze_recurrence(left)
    right_rec = analyze_recurrence(right)
    recurrence_match = (
        left_rec.assessable
        and right_rec.assessable
        and left_rec.has_recurrence == right_rec.has_recurrence
    )

    fault_score = _jaccard(set(left_faults), set(right_faults))
    ecu_score = _jaccard(set(left_ecus), set(right_ecus))
    recurrence_score = 1.0 if recurrence_match else 0.0
    score = 0.65 * fault_score + 0.20 * ecu_score + 0.15 * recurrence_score

    return SimilarityResult(
        left_case_id=left.case_id,
        right_case_id=right.case_id,
        score=round(score, 4),
        shared_faults=tuple(sorted(left_faults & right_faults)),
        shared_ecus=tuple(sorted(left_ecus & right_ecus)),
        same_recurrence_pattern=recurrence_match,
    )


def all_pairwise_similarities(cases: list[NTFCase]) -> list[SimilarityResult]:
    results: list[SimilarityResult] = []
    for index, left in enumerate(cases):
        for right in cases[index + 1 :]:
            results.append(compare_cases(left, right))
    return sorted(results, key=lambda item: item.score, reverse=True)
