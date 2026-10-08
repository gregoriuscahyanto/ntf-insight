"""Compatibility API for explainable pairwise case similarity.

Diagnostic similarity is calculated exclusively from pre-intervention evidence.
Post-swap recurrence is retained only as an informative *outcome* column.
"""

from __future__ import annotations

from dataclasses import dataclass

from ntf_insight.analysis.case_clustering import compare_diagnostic_cases
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


def compare_cases(left: NTFCase, right: NTFCase) -> SimilarityResult:
    """Explainable diagnostic similarity; recurrence does NOT affect the score."""
    diagnostic = compare_diagnostic_cases(left, right)
    left_rec = analyze_recurrence(left)
    right_rec = analyze_recurrence(right)
    recurrence_match = (
        left_rec.assessable
        and right_rec.assessable
        and left_rec.has_recurrence == right_rec.has_recurrence
    )
    return SimilarityResult(
        left_case_id=left.case_id,
        right_case_id=right.case_id,
        score=diagnostic.score if diagnostic.score is not None else 0.0,
        shared_faults=diagnostic.shared_faults,
        shared_ecus=diagnostic.shared_ecus,
        same_recurrence_pattern=recurrence_match,
    )


def all_pairwise_similarities(cases: list[NTFCase]) -> list[SimilarityResult]:
    results = [
        compare_cases(left, right)
        for index, left in enumerate(cases)
        for right in cases[index + 1:]
    ]
    return sorted(results, key=lambda item: (-item.score, item.left_case_id, item.right_case_id))
