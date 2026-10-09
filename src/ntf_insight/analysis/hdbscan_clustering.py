"""Experimental, unsupervised HDBSCAN on pre-swap QEC diagnostic signatures.

The model uses a *metric* precomputed Euclidean distance between L2-normalized,
multi-view TF-IDF vectors. This is not clustering 2D plot coordinates or a
learned same-root-cause probability. No QEC SSL/supplier/repair outcome is an
input. Unanchored and DTC-less cases are explicitly excluded, not fabricated.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from math import log, sqrt

import numpy as np
from sklearn.cluster import HDBSCAN
from sklearn.metrics import pairwise_distances

from ntf_insight.analysis.case_clustering import FaultKey, signature_for
from ntf_insight.analysis.qec_findings import qec_ssl_finding
from ntf_insight.domain.case import NTFCase


# Engineering hypotheses for FIRST exploratory implementation; not calibrated
# causality weights. The displayed source and lookback are used for all views.
FEATURE_VIEW_WEIGHTS = {
    "faults": 0.70,
    "codes": 0.08,
    "ecus": 0.03,
    "complaint": 0.14,
    "software": 0.03,
    "variant": 0.02,
}


@dataclass(frozen=True, slots=True)
class MLMember:
    case_id: str
    similarity_to_representative: float
    membership_strength: float
    shared_faults: tuple[FaultKey, ...]


@dataclass(frozen=True, slots=True)
class MLCluster:
    cluster_id: int
    representative_case_id: str
    members: tuple[MLMember, ...]
    vehicle_count: int
    common_faults: tuple[FaultKey, ...]
    majority_faults: tuple[tuple[FaultKey, int], ...]
    mean_to_representative: float
    weakest_internal_similarity: float
    min_membership_strength: float
    ssl_finding_count: int
    warnings: tuple[str, ...]

    @property
    def case_ids(self) -> tuple[str, ...]:
        return tuple(member.case_id for member in self.members)

    @property
    def case_count(self) -> int:
        return len(self.members)


@dataclass(frozen=True, slots=True)
class MLClusterResult:
    clusters: tuple[MLCluster, ...]
    eligible_case_ids: tuple[str, ...]
    noise_case_ids: tuple[str, ...]
    excluded_case_ids: tuple[str, ...]
    coordinates: tuple[tuple[str, float, float], ...]
    case_count: int
    vehicle_count: int
    feature_count: int
    min_cluster_size: int
    min_samples: int
    lookback_days: int | None
    dtc_source: str
    distances: tuple[tuple[float, ...], ...]
    ssl_not_used_as_feature: bool = True

    @property
    def clustered_count(self) -> int:
        return sum(cluster.case_count for cluster in self.clusters)

    @property
    def coverage(self) -> float:
        return self.clustered_count / self.case_count if self.case_count else 0.0


def _feature_matrix(signatures: list) -> tuple[np.ndarray, int]:
    """Per-view binary IDF, L2 per known view, then one L2 per case.

    IDF is fitted ONLY on the eligible pre-swap cohort of the current family.
    Missing views contribute nothing, never a synthetic identical 'unknown'
    token. Exact ECU:DTC is the largest feature group. A repeated DTC in
    QuickTest and AutoExport enters each view once per QEC case.
    """
    n = len(signatures)
    dictionaries = []
    for sig in signatures:
        dictionaries.append({
            name: sig.views()[name] for name in FEATURE_VIEW_WEIGHTS
        })
    matrices = []
    total_columns = 0
    for view, weight in FEATURE_VIEW_WEIGHTS.items():
        vocabulary = sorted({
            token for sig_views in dictionaries for token in sig_views[view]
        })
        if not vocabulary:
            continue
        indices = {token: i for i, token in enumerate(vocabulary)}
        df = Counter(
            token for views in dictionaries for token in views[view]
        )
        idf = {
            token: 1.0 + log((n + 1) / (df[token] + 1))
            for token in vocabulary
        }
        matrix = np.zeros((n, len(vocabulary)), dtype=float)
        for i, views in enumerate(dictionaries):
            for token in views[view]:
                matrix[i, indices[token]] = idf[token]
        norms = np.linalg.norm(matrix, axis=1)
        matrix /= np.maximum(norms[:, None], 1e-12)
        matrix *= sqrt(weight)
        matrices.append(matrix)
        total_columns += len(vocabulary)
    if not matrices:
        return np.zeros((n, 0)), 0
    combined = np.concatenate(matrices, axis=1)
    combined /= np.maximum(np.linalg.norm(combined, axis=1)[:, None], 1e-12)
    return combined, total_columns


def _mds(distances: np.ndarray, ids: tuple[str, ...]) -> tuple[tuple[str, float, float], ...]:
    """Classical 2D MDS on the EXACT distance used by HDBSCAN."""
    n = len(ids)
    if not n:
        return ()
    if n == 1:
        return ((ids[0], 0.0, 0.0),)
    squared = distances * distances
    centered = (
        squared - squared.mean(axis=0)[None, :]
        - squared.mean(axis=1)[:, None] + squared.mean()
    )
    values, vectors = np.linalg.eigh(-0.5 * centered)
    order = np.argsort(values)[::-1][:2]
    points = np.zeros((n, 2))
    for column, index in enumerate(order):
        if values[index] <= 1e-12:
            continue
        vector = vectors[:, index].copy()
        if vector[np.argmax(np.abs(vector))] < 0:
            vector *= -1
        points[:, column] = vector * sqrt(values[index])
    return tuple(
        (case_id, float(points[i, 0]), float(points[i, 1]))
        for i, case_id in enumerate(ids)
    )


def cluster_hdbscan_cases(
    cases: list[NTFCase],
    *,
    min_cluster_size: int = 3,
    min_samples: int = 2,
    lookback_days: int | None = None,
    dtc_source: str = "all",
) -> MLClusterResult:
    """Discover density groups, without any fixed K or Complete-Link gate.

    A probabilistic membership strength is a *cluster stability metric*, NOT
    probability of a common failure mechanism. All cluster membership and
    medoid calculations are based on the same original N-dimensional space.
    """
    if not 2 <= min_cluster_size <= 100:
        raise ValueError("HDBSCAN-Mindestclustergröße muss 2 bis 100 sein.")
    if not 1 <= min_samples <= 100:
        raise ValueError("HDBSCAN-MinSamples muss 1 bis 100 sein.")
    by_id = {case.case_id: case for case in cases}
    if len(by_id) != len(cases):
        raise ValueError("QEC-Fall-IDs müssen eindeutig sein.")
    sigs = {
        cid: signature_for(
            case, dtc_source=dtc_source, lookback_days=lookback_days,
        )
        for cid, case in sorted(by_id.items())
    }
    if len({sig.component_key for sig in sigs.values()}) > 1:
        raise ValueError("HDBSCAN nur innerhalb einer Bauteilfamilie ausführen.")
    eligible = tuple(
        cid for cid, sig in sigs.items()
        if sig.has_replacement_anchor and sig.faults
    )
    excluded = tuple(sorted(set(by_id) - set(eligible)))
    signatures = [sigs[cid] for cid in eligible]
    vectors, dimension_count = _feature_matrix(signatures)
    # Euclidean distance on unit vectors is a genuine metric; cosine distance
    # 1-cosine alone does NOT obey triangle inequality.
    distance = (
        pairwise_distances(vectors, metric="euclidean")
        if len(eligible) else np.zeros((0, 0))
    )
    distance = np.maximum(distance, 0)
    distance = (distance + distance.T) / 2
    np.fill_diagonal(distance, 0)

    labels = np.full(len(eligible), -1, dtype=int)
    strengths = np.zeros(len(eligible), dtype=float)
    if len(eligible) > min_cluster_size:
        model = HDBSCAN(
            min_cluster_size=min_cluster_size,
            min_samples=min(min_samples, len(eligible)-1),
            metric="precomputed",
            cluster_selection_method="eom",
            allow_single_cluster=False,
        )
        labels = np.asarray(model.fit_predict(distance), dtype=int)
        strengths = np.asarray(model.probabilities_, dtype=float)

    unsorted = []
    for raw_label in sorted(set(labels) - {-1}):
        positions = [i for i, label in enumerate(labels) if label == raw_label]
        group_ids = tuple(eligible[i] for i in positions)

        # Medoid: minimum sum of true original-distance to every other case;
        # stable tie break on QEC ID, NEVER post-test findings.
        rep_pos = min(
            positions, key=lambda i: (
                round(sum(float(distance[i, j]) for j in positions if j != i), 12),
                eligible[i],
            )
        )
        representative = eligible[rep_pos]
        offdiag = [
            float(1.0 - distance[i, j] ** 2 / 2.0)
            for idx, i in enumerate(positions)
            for j in positions[idx + 1:]
        ]
        # L2 unit vectors give cosine = 1 - (euclidean^2)/2.
        core = set(sigs[group_ids[0]].faults)
        frequencies: Counter[FaultKey] = Counter()
        for cid in group_ids:
            core.intersection_update(sigs[cid].faults)
            frequencies.update(sigs[cid].faults)

        members = tuple(
            MLMember(
                case_id=eligible[i],
                similarity_to_representative=round(
                    max(0, 1.0 - distance[i, rep_pos] ** 2 / 2.0), 4
                ),
                membership_strength=round(float(strengths[i]), 4),
                shared_faults=tuple(sorted(
                    sigs[eligible[i]].faults & sigs[representative].faults
                )),
            )
            for i in positions
        )
        documented = [
            f.text.strip().casefold()
            for cid in group_ids
            if (f := qec_ssl_finding(by_id[cid])) is not None
        ]
        warnings = []
        if not core:
            warnings.append("Kein ECU:DTC in allen Fällen gemeinsam")
        elif len(core) == 1:
            warnings.append("Nur ein ECU:DTC als gemeinsame Kernevidenz")
        if offdiag and min(offdiag) < 0.45:
            warnings.append(
                "Heterogen: schwächstes Fallpaar unter 45 % Cosinusindex"
            )
        if len(set(documented)) > 1:
            warnings.append("SSL-Endbefundtexte weichen voneinander ab")
        if len(documented) < len(group_ids):
            warnings.append("Nicht alle QEC-Fälle haben einen SSL-Endbefund")
        distinct_vins = {by_id[cid].vin for cid in group_ids}
        if len(distinct_vins) < 2:
            warnings.append("Nur eine FIN; keine fahrzeugübergreifende Replikation")
        elif len(distinct_vins) < len(group_ids):
            warnings.append(
                "Mehrere QEC-Fälle derselben FIN: "
                "geteilte Fahrzeughistorie fachlich prüfen"
            )
        if any(strengths[i] < 0.5 for i in positions):
            warnings.append("Mindestens eine schwache HDBSCAN-Zugehörigkeitsstärke")
        unsorted.append((
            group_ids,
            representative,
            members,
            tuple(sorted(core)),
            tuple(sorted(
                ((fault, count) for fault, count in frequencies.items()
                 if count >= max(2, len(group_ids) // 2)),
                key=lambda item: (-item[1], item[0]),
            )),
            round(float(np.mean(
                [m.similarity_to_representative for m in members
                 if m.case_id != representative]
            )), 4),
            round(min(offdiag), 4) if offdiag else 1.0,
            round(float(min(strengths[i] for i in positions)), 4),
            len(documented),
            tuple(warnings),
        ))

    unsorted.sort(key=lambda row: (-len(row[0]), row[1]))
    groups = tuple(
        MLCluster(
            cluster_id=k,
            representative_case_id=rep,
            members=members,
            vehicle_count=len({by_id[cid].vin for cid in ids}),
            common_faults=core,
            majority_faults=majority,
            mean_to_representative=avg,
            weakest_internal_similarity=weakest,
            min_membership_strength=min_strength,
            ssl_finding_count=ssl_count,
            warnings=warnings,
        )
        for k, (ids, rep, members, core, majority, avg, weakest,
                min_strength, ssl_count, warnings) in enumerate(unsorted, 1)
    )
    noise = tuple(
        eligible[i] for i, label in enumerate(labels) if label == -1
    )
    return MLClusterResult(
        clusters=groups,
        eligible_case_ids=eligible,
        noise_case_ids=noise,
        excluded_case_ids=excluded,
        coordinates=_mds(distance, eligible),
        case_count=len(cases),
        vehicle_count=len({c.vin for c in cases}),
        feature_count=dimension_count,
        min_cluster_size=min_cluster_size,
        min_samples=min_samples,
        lookback_days=lookback_days,
        dtc_source=dtc_source,
        distances=tuple(tuple(float(val) for val in row) for row in distance),
    )
