"""Read-only 2D projection of the SAME pre-intervention case signatures.

TruncatedSVD is only a drawing coordinate system. Cluster labels/thresholds
come exclusively from case_clustering.cluster_diagnostic_cases, never from 2D.
No supplier finding, repair action, or post-intervention outcome is a feature.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite, sqrt

from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction import DictVectorizer

from ntf_insight.analysis.case_clustering import VIEW_WEIGHTS, signature_for
from ntf_insight.domain.case import NTFCase


@dataclass(frozen=True, slots=True)
class ProjectedCase:
    case_id: str
    x: float
    y: float
    component_key: str
    has_replacement_anchor: bool
    fault_count: int


@dataclass(frozen=True, slots=True)
class CaseProjection:
    points: tuple[ProjectedCase, ...]
    omitted_case_ids: tuple[str, ...]
    method: str = "TruncatedSVD (2D, diagnostische Signatur)"
    feature_count: int = 0
    components: int = 0
    explained_variance_ratio: tuple[float, ...] = ()
    axis_top_features: tuple[tuple[int, str, float], ...] = ()


def project_diagnostic_cases(
    cases: list[NTFCase], *,
    lookback_days: int | None = None, dtc_source: str = "all",
) -> CaseProjection:
    """Project comparable diagnostic evidence, excluding evidence-free cases.

    Within a populated feature group every observed token has the same weight.
    Normalising by group size stops long DTC lists from dominating the whole
    embedding purely because a record contains more entries. The resulting
    Euclidean positions are NOT the actual Jaccard/complete-link distances.
    """
    ordered = sorted(cases, key=lambda case: case.case_id)
    if len({case.case_id for case in ordered}) != len(ordered):
        raise ValueError("Fall-IDs müssen eindeutig sein.")

    signatures = [
        signature_for(
            case, lookback_days=lookback_days, dtc_source=dtc_source
        ) for case in ordered
    ]
    eligible = [
        sig for sig in signatures if sig.faults or sig.complaint_tokens
    ]
    omitted = tuple(
        sig.case_id for sig in signatures if not (sig.faults or sig.complaint_tokens)
    )
    if not eligible:
        return CaseProjection(points=(), omitted_case_ids=omitted)

    rows = []
    for sig in eligible:
        features: dict[str, float] = {}
        for group, weight in VIEW_WEIGHTS.items():
            tokens = sig.views()[group]
            if not tokens:
                continue
            amplitude = sqrt(weight / len(tokens))
            for token in tokens:
                value = ":".join(token) if isinstance(token, tuple) else str(token)
                features[f"{group}::{value}"] = amplitude
        rows.append(features)

    vectorizer = DictVectorizer(sparse=True)
    matrix = vectorizer.fit_transform(rows)
    feature_count = matrix.shape[1]
    positions = [(0.0, 0.0)] * len(eligible)
    components = 0
    explained_variance: tuple[float, ...] = ()
    top_features: list[tuple[int, str, float]] = []
    # Identical signatures have zero across-case variance. Do not ask SVD to
    # estimate meaningless axes or divide by zero in explained-variance ratios.
    has_variation = (
        len(eligible) >= 2
        and (matrix[1:] - matrix[:-1]).nnz > 0
    )
    if has_variation:
        components = min(2, matrix.shape[0] - 1, matrix.shape[1] - 1)
        if components >= 1:
            svd = TruncatedSVD(n_components=components, random_state=0)
            raw = svd.fit_transform(matrix)
            explained_variance = tuple(
                round(float(v), 6) if isfinite(float(v)) else 0.0
                for v in svd.explained_variance_ratio_
            )
            feature_names = vectorizer.get_feature_names_out()
            for axis_index, weights in enumerate(svd.components_, start=1):
                top_indices = sorted(
                    range(feature_count),
                    key=lambda index: (-abs(float(weights[index])), str(feature_names[index])),
                )[:6]
                for index in top_indices:
                    top_features.append((
                        axis_index,
                        str(feature_names[index]),
                        round(float(weights[index]), 6),
                    ))
            x_mean = float(raw[:, 0].mean())
            y_mean = float(raw[:, 1].mean()) if components == 2 else 0.0
            positions = [
                (
                    round(float(row[0]) - x_mean, 10),
                    round(float(row[1]) - y_mean, 10) if components == 2 else 0.0,
                )
                for row in raw
            ]

    return CaseProjection(
        points=tuple(
            ProjectedCase(
                case_id=sig.case_id,
                x=x,
                y=y,
                component_key=sig.component_key,
                has_replacement_anchor=sig.has_replacement_anchor,
                fault_count=len(sig.faults),
            )
            for sig, (x, y) in zip(eligible, positions)
        ),
        omitted_case_ids=omitted,
        feature_count=feature_count,
        components=components,
        explained_variance_ratio=explained_variance,
        axis_top_features=tuple(top_features),
    )
