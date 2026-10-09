"""Transparent numerical audit of each feature group used by case similarity.

This is a read-only decomposition of the existing weighted Jaccard function.
It does not define an alternative score and never changes cluster membership.
"""

from __future__ import annotations

from dataclasses import dataclass

from ntf_insight.analysis.case_clustering import (
    VIEW_WEIGHTS,
    CaseMatch,
    compare_signatures,
    signature_for,
)
from ntf_insight.domain.case import NTFCase


FEATURE_LABELS = {
    "faults": "ECU + DTC",
    "codes": "DTC-Code",
    "ecus": "Steuergeräte",
    "complaint": "Beanstandungsbegriffe",
    "software": "ECU-Softwarestand",
    "variant": "Baureihe / Variante",
}


@dataclass(frozen=True, slots=True)
class SimilarityContribution:
    group: str
    label: str
    weight: float
    left_count: int
    right_count: int
    overlap_count: int
    union_count: int
    jaccard: float | None
    weighted_score: float | None
    normalized_contribution: float | None


@dataclass(frozen=True, slots=True)
class SimilarityExplanation:
    match: CaseMatch
    contributions: tuple[SimilarityContribution, ...]
    weighted_sum: float
    covered_weight: float

    @property
    def reconstructed_score(self) -> float | None:
        if self.match.score is None or self.covered_weight == 0:
            return None
        return self.weighted_sum / self.covered_weight


def explain_case_similarity(
    left: NTFCase, right: NTFCase, *,
    lookback_days: int | None = None, dtc_source: str = "all",
) -> SimilarityExplanation:
    """Show numerator, denominator and per-feature Jaccard used by the MVP.

    Incompatible components may have matching words/DTCs, but must never get
    a computed cross-component similarity score.
    """
    left_sig = signature_for(
        left, lookback_days=lookback_days, dtc_source=dtc_source
    )
    right_sig = signature_for(
        right, lookback_days=lookback_days, dtc_source=dtc_source
    )
    match = compare_signatures(left_sig, right_sig)
    compatible = left_sig.component_key == right_sig.component_key
    paired = [
        (key, weight, left_sig.views()[key], right_sig.views()[key])
        for key, weight in VIEW_WEIGHTS.items()
    ]
    covered = (
        sum(weight for _, weight, a, b in paired if a and b)
        if compatible else 0.0
    )
    weighted = (
        sum(
            weight * len(a & b) / len(a | b)
            for _, weight, a, b in paired if a and b
        ) if compatible else 0.0
    )
    rows = []
    for group, weight, a, b in paired:
        comparable = compatible and bool(a and b)
        common = len(a & b)
        union = len(a | b)
        jaccard = common / union if comparable else None
        rows.append(SimilarityContribution(
            group=group,
            label=FEATURE_LABELS[group],
            weight=weight,
            left_count=len(a),
            right_count=len(b),
            overlap_count=common,
            union_count=union,
            jaccard=jaccard,
            weighted_score=weight * jaccard if jaccard is not None else None,
            normalized_contribution=(
                weight * jaccard / covered
                if jaccard is not None and covered else None
            ),
        ))
    return SimilarityExplanation(
        match=match, contributions=tuple(rows),
        weighted_sum=weighted,
        covered_weight=covered,
    )
