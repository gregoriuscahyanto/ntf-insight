"""Unified, extensible cluster engine for the NTF Insight desktop workspace.

All methods operate exclusively on documented pre-replacement diagnostic
features. The classical weighted-Jaccard method is explicitly marked as
using a DIFFERENT similarity metric and must not be naively compared with
the common TF-IDF Euclidean/Cosine feature-distance methods.

These results are LOCAL: they contain QEC case IDs and diagnosis codes.
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from math import sqrt
from statistics import median

import numpy as np
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import squareform

from ntf_insight.analysis.case_clustering import signature_for
from ntf_insight.analysis.hdbscan_clustering import (
    MLClusterResult, cluster_hdbscan_cases,
)
from ntf_insight.analysis.representative_clustering import select_representative_cases
from ntf_insight.domain.case import NTFCase


@dataclass(frozen=True, slots=True)
class MethodDefinition:
    key: str
    title: str
    description: str
    metric: str
    supports_min_samples: bool = False
    supports_cosine_cutoff: bool = False
    supports_jaccard_cutoff: bool = False


METHODS = (
    MethodDefinition(
        "leaf", "HDBSCAN · Leaf", "Spezifische, kleine Dichtegruppen",
        "TF-IDF / Cosinus", supports_min_samples=True,
    ),
    MethodDefinition(
        "eom", "HDBSCAN · EOM", "Größere, stabilitätsbasierte Dichtegruppen",
        "TF-IDF / Cosinus", supports_min_samples=True,
    ),
    MethodDefinition(
        "complete_cosine", "Complete-Link · Cosinus",
        "Alle Fallpaare müssen die gewählte Cosinusschwelle erreichen",
        "TF-IDF / Cosinus", supports_cosine_cutoff=True,
    ),
    MethodDefinition(
        "complete_legacy", "Complete-Link · DTC-Jaccard",
        "Fachlich restriktiver DTC-Kern; eigene, andere Ähnlichkeitsmetrik",
        "Gewichteter DTC-Jaccard", supports_jaccard_cutoff=True,
    ),
)

BY_METHOD = {item.key: item for item in METHODS}


@dataclass(frozen=True, slots=True)
class ClusterParameters:
    method: str = "leaf"
    min_cluster_size: int = 3
    min_samples: int = 2
    minimum_similarity: float = 0.45
    jaccard_threshold: float = 0.60
    common_dtc_cutoff: float | None = None
    dtc_source: str = "all"
    lookback_days: int | None = None

    def validate(self) -> None:
        if self.method not in BY_METHOD:
            raise ValueError("Unbekannte Clustermethode.")
        if not 2 <= self.min_cluster_size <= 100:
            raise ValueError("Mindestclustergröße: 2 bis 100.")
        if not 1 <= self.min_samples <= 100:
            raise ValueError("MinSamples: 1 bis 100.")
        if not 0 < self.minimum_similarity < 1:
            raise ValueError("Cosinusschwelle muss zwischen 0 und 1 liegen.")
        if not 0 < self.jaccard_threshold <= 1:
            raise ValueError("DTC-Jaccard-Schwelle muss zwischen 0 und 1 liegen.")
        if self.common_dtc_cutoff is not None and not (
            0 < self.common_dtc_cutoff <= 1
        ):
            raise ValueError("DTC-Häufigkeitsfilter muss zwischen 0 und 1 liegen.")
        if self.dtc_source not in {"all", "quicktest", "autoexport"}:
            raise ValueError("Unbekannte DTC-Quelle.")


@dataclass(frozen=True, slots=True)
class ClusterMember:
    case_id: str
    similarity: float
    membership_strength: float | None = None


@dataclass(frozen=True, slots=True)
class UnifiedCluster:
    cluster_id: int
    representative_case_id: str
    members: tuple[ClusterMember, ...]
    vehicle_count: int
    common_faults: tuple[tuple[str, str], ...]
    minimum_pair_similarity: float | None
    median_pair_similarity: float | None
    weak_pair_count: int | None
    internal_pair_count: int
    warnings: tuple[str, ...] = ()

    @property
    def case_ids(self) -> tuple[str, ...]:
        return tuple(member.case_id for member in self.members)

    @property
    def case_count(self) -> int:
        return len(self.members)


@dataclass(frozen=True, slots=True)
class UnifiedClusterResult:
    parameters: ClusterParameters
    groups: tuple[UnifiedCluster, ...]
    eligible_case_ids: tuple[str, ...]
    noise_case_ids: tuple[str, ...]
    excluded_case_ids: tuple[str, ...]
    positions: tuple[tuple[str, float, float, float], ...]
    original_distances: tuple[tuple[float, ...], ...]
    note: str

    @property
    def clustered_count(self) -> int:
        return sum(group.case_count for group in self.groups)


def _project_3d(
    base: MLClusterResult,
) -> tuple[tuple[str, float, float, float], ...]:
    """Classical MDS, 3 components of the ORIGINAL diagnostic distances.

    Projection exists only for display and never supplies cluster features.
    """
    ids = base.eligible_case_ids
    n = len(ids)
    if not n:
        return ()
    if n == 1:
        return ((ids[0], 0.0, 0.0, 0.0),)
    distance = np.asarray(base.distances, dtype=float)
    squared = distance * distance
    centered = squared - squared.mean(axis=0)[None, :]
    centered -= squared.mean(axis=1)[:, None]
    centered += squared.mean()
    values, vectors = np.linalg.eigh(-0.5 * centered)
    coordinates = np.zeros((n, 3), dtype=float)
    for column, index in enumerate(np.argsort(values)[::-1][:3]):
        if values[index] <= 1e-12:
            continue
        vector = vectors[:, index].copy()
        if vector[np.argmax(np.abs(vector))] < 0:
            vector *= -1
        coordinates[:, column] = vector * sqrt(values[index])
    # Use the existing published 2D projection for axes 1/2. This ensures
    # toggling 2D->3D never changes what the user regards as X/Y.
    two_d = {case_id: (x, y) for case_id, x, y in base.coordinates}
    return tuple((
        cid, float(two_d[cid][0]), float(two_d[cid][1]),
        float(coordinates[i, 2]),
    ) for i, cid in enumerate(ids))


def _cosine(distance: float) -> float:
    return float(np.clip(1 - distance * distance / 2.0, 0, 1))


def _from_hdbscan(
    result: MLClusterResult, params: ClusterParameters, positions,
) -> UnifiedClusterResult:
    groups = tuple(
        UnifiedCluster(
            cluster_id=group.cluster_id,
            representative_case_id=group.representative_case_id,
            members=tuple(
                ClusterMember(m.case_id, m.similarity_to_representative,
                              m.membership_strength)
                for m in group.members
            ),
            vehicle_count=group.vehicle_count,
            common_faults=group.common_faults,
            minimum_pair_similarity=group.weakest_internal_similarity,
            median_pair_similarity=group.median_internal_similarity,
            weak_pair_count=group.weak_pair_count,
            internal_pair_count=group.internal_pair_count,
            warnings=group.warnings,
        ) for group in result.clusters
    )
    return UnifiedClusterResult(
        parameters=params,
        groups=groups,
        eligible_case_ids=result.eligible_case_ids,
        noise_case_ids=result.noise_case_ids,
        excluded_case_ids=result.excluded_case_ids,
        positions=positions,
        original_distances=result.distances,
        note="HDBSCAN-Zugehörigkeit ist keine Wahrscheinlichkeit einer gleichen Ursache.",
    )


def _strict_cosine(
    cases: list[NTFCase], base: MLClusterResult,
    params: ClusterParameters, positions,
) -> UnifiedClusterResult:
    ids = base.eligible_case_ids
    matrix = np.asarray(base.distances, dtype=float) if ids else np.zeros((0, 0))
    groups: list[UnifiedCluster] = []
    if len(ids) >= params.min_cluster_size:
        threshold = sqrt(2 * (1 - params.minimum_similarity))
        labels = fcluster(
            linkage(squareform(np.maximum(matrix, 0), checks=True), method="complete"),
            t=threshold, criterion="distance",
        )
        positions_by_label: dict[int, list[int]] = {}
        for i, label in enumerate(labels):
            positions_by_label.setdefault(int(label), []).append(i)
        candidates = [
            members for members in positions_by_label.values()
            if len(members) >= params.min_cluster_size
        ]
        candidates.sort(key=lambda g: (-len(g), tuple(ids[i] for i in g)))
        by_id = {case.case_id: case for case in cases}
        signatures = {
            cid: signature_for(
                by_id[cid], dtc_source=params.dtc_source,
                lookback_days=params.lookback_days,
            )
            for cid in ids
        }
        for index, member_positions in enumerate(candidates, start=1):
            case_ids = tuple(ids[i] for i in member_positions)
            representative_pos = min(
                member_positions,
                key=lambda i: (
                    round(sum(float(matrix[i, j]) for j in member_positions), 12),
                    ids[i],
                ),
            )
            pair_values = [
                _cosine(float(matrix[i, j]))
                for i, j in combinations(member_positions, 2)
            ]
            if any(value < params.minimum_similarity - 1e-8 for value in pair_values):
                raise ValueError("Complete-Link: interne Mindestähnlichkeit verletzt.")
            common = set(signatures[case_ids[0]].faults)
            for cid in case_ids[1:]:
                common.intersection_update(signatures[cid].faults)
            groups.append(UnifiedCluster(
                cluster_id=index,
                representative_case_id=ids[representative_pos],
                members=tuple(
                    ClusterMember(ids[i], round(
                        _cosine(float(matrix[i, representative_pos])), 4,
                    ))
                    for i in member_positions
                ),
                vehicle_count=len({by_id[cid].vin for cid in case_ids}),
                common_faults=tuple(sorted(common)),
                minimum_pair_similarity=round(min(pair_values), 4),
                median_pair_similarity=round(median(pair_values), 4),
                weak_pair_count=sum(value < 0.45 for value in pair_values),
                internal_pair_count=len(pair_values),
                warnings=(
                    "Homogenität durch Grenzwert erzwungen; keine Ursache bestätigt.",
                ),
            ))
    assigned = {cid for group in groups for cid in group.case_ids}
    return UnifiedClusterResult(
        parameters=params,
        groups=tuple(groups),
        eligible_case_ids=ids,
        noise_case_ids=tuple(cid for cid in ids if cid not in assigned),
        excluded_case_ids=base.excluded_case_ids,
        positions=positions,
        original_distances=base.distances,
        note="Complete-Link Cosinus: alle Fallpaare erfüllen die Schwelle; reine Diagnosehypothese.",
    )


def _legacy_jaccard(
    cases: list[NTFCase], base: MLClusterResult,
    params: ClusterParameters, positions,
) -> UnifiedClusterResult:
    if params.common_dtc_cutoff is not None:
        raise ValueError(
            "Die DTC-Häufigkeitsoption des gemeinsamen TF-IDF-Modells ist "
            "mit dem älteren Jaccard-Modell nicht identisch. Bitte deaktivieren."
        )
    plan = select_representative_cases(
        cases,
        minimum_similarity=params.jaccard_threshold,
        dtc_source=params.dtc_source,
        lookback_days=params.lookback_days,
        maximum_common_frequency=0.35,
    )
    # The legacy tool allows pairs; unified min_cluster_size must be honored.
    qualified = [
        group for group in plan.clusters
        if group.case_count >= params.min_cluster_size
    ]
    groups = tuple(
        UnifiedCluster(
            cluster_id=index,
            representative_case_id=group.representative_case_id,
            members=tuple(ClusterMember(m.case_id, m.similarity)
                          for m in group.members),
            vehicle_count=group.vehicle_count,
            common_faults=group.common_faults,
            minimum_pair_similarity=group.weakest_internal_similarity,
            median_pair_similarity=None,
            weak_pair_count=None,
            internal_pair_count=group.case_count * (group.case_count - 1) // 2,
            warnings=group.review_warnings,
        ) for index, group in enumerate(qualified, start=1)
    )
    assigned = {cid for group in groups for cid in group.case_ids}
    eligible = plan.eligible_cases
    if set(eligible) != set(base.eligible_case_ids):
        raise ValueError("Methodenvergleich: Jaccard und TF-IDF nutzen verschiedene Kohorten.")
    return UnifiedClusterResult(
        parameters=params,
        groups=groups,
        eligible_case_ids=eligible,
        noise_case_ids=tuple(cid for cid in eligible if cid not in assigned),
        excluded_case_ids=tuple(sorted(set(case.case_id for case in cases)-set(eligible))),
        positions=positions,
        original_distances=base.distances,
        note=(
            "Andere Metrik (gewichteter DTC-Jaccard); Plotkoordinaten nutzen "
            "TF-IDF-MDS nur als gemeinsame Referenz. Prozentwerte sind "
            "nicht direkt mit Cosinus vergleichbar."
        ),
    )


def calculate_clusters(
    cases: list[NTFCase],
    params: ClusterParameters,
    *,
    reference: MLClusterResult | None = None,
) -> UnifiedClusterResult:
    """Single method registry entry; no QWidget or extra tab per algorithm."""
    params.validate()
    ordered = sorted(cases, key=lambda case: case.case_id)
    baseline = reference
    if baseline is None:
        baseline = cluster_hdbscan_cases(
            ordered, min_cluster_size=params.min_cluster_size,
            min_samples=params.min_samples, selection_method="leaf",
            common_dtc_cutoff=params.common_dtc_cutoff,
            lookback_days=params.lookback_days,
            dtc_source=params.dtc_source,
        )
    if params.method == "complete_legacy" and params.common_dtc_cutoff is not None:
        raise ValueError("Jaccard-Vergleich nur ohne TF-IDF-Häufigkeitsfilter.")
    positions = _project_3d(baseline)
    if params.method == "leaf":
        return _from_hdbscan(baseline, params, positions)
    if params.method == "eom":
        model = cluster_hdbscan_cases(
            ordered, min_cluster_size=params.min_cluster_size,
            min_samples=params.min_samples, selection_method="eom",
            common_dtc_cutoff=params.common_dtc_cutoff,
            dtc_source=params.dtc_source, lookback_days=params.lookback_days,
        )
        return _from_hdbscan(model, params, positions)
    if params.method == "complete_cosine":
        return _strict_cosine(ordered, baseline, params, positions)
    if params.method == "complete_legacy":
        return _legacy_jaccard(ordered, baseline, params, positions)
    raise ValueError("Unbekannte Clustermethode.")


def positive_pairs(result: UnifiedClusterResult) -> set[tuple[str, str]]:
    return {
        (a, b)
        for group in result.groups
        for a, b in combinations(sorted(group.case_ids), 2)
    }


def compare_cluster_runs(
    results: list[UnifiedClusterResult],
) -> tuple[dict, ...]:
    """Pair-overlap is label-invariant. Different metric marked explicitly."""
    if not results:
        return ()
    base = results[0]
    if any(set(x.eligible_case_ids) != set(base.eligible_case_ids) for x in results):
        raise ValueError("Methodenvergleich nur mit gleicher QEC-Grundgesamtheit.")
    before = positive_pairs(base)
    rows = []
    for item in results:
        pairs = positive_pairs(item)
        common = sum(bool(group.common_faults) for group in item.groups)
        cross_fin = sum(group.vehicle_count >= 2 for group in item.groups)
        union = pairs | before
        agreement = len(pairs & before) / len(union) if union else None
        rows.append({
            "methode": BY_METHOD[item.parameters.method].title,
            "cluster": len(item.groups),
            "faelle": item.clustered_count,
            "ausreisser": len(item.noise_case_ids),
            "gemeinsamer_dtc_kern": common,
            "mehrere_fin": cross_fin,
            "paaruebereinstimmung": agreement,
            "metrik": BY_METHOD[item.parameters.method].metric,
        })
    return tuple(rows)
