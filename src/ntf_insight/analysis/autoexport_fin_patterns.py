"""Scalable, EXPLORATORY grouping of every imported AutoExport DTC FIN.

This is NOT the QEC/pump-failure analysis: a FIN can have DTC history without
any pump replacement or NTF finding. Grouping intentionally ignores unknown
replacement dates, supplier judgments, SSL outcomes, and post-repair labels.
Do not use an NxN VIN-distance matrix (11k VINs would require >100M entries).
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from math import sqrt
from typing import Mapping, Sequence

import numpy as np
from sklearn.cluster import MiniBatchKMeans
from sklearn.feature_extraction import DictVectorizer
from sklearn.feature_extraction.text import TfidfTransformer
from sklearn.preprocessing import normalize

FaultKey = tuple[str, str]
MIN_FIN_SIMILARITY = 0.35  # exploratory, not validated to any failure mechanism
MIN_GROUP_SIZE = 3
MAX_INITIAL_GROUPS = 64


@dataclass(frozen=True, slots=True)
class FinPatternGroup:
    group_id: int
    members: tuple[tuple[str, float], ...]
    representative_fin: str
    common_faults: tuple[tuple[str, str, int, str], ...]
    qec_fin_count: int
    median_similarity: float

    @property
    def fin_count(self) -> int:
        return len(self.members)


@dataclass(frozen=True, slots=True)
class FinPatternResult:
    total_fins: int
    dtc_fins: int
    no_dtc_fins: tuple[str, ...]
    unassigned_fins: tuple[str, ...]
    groups: tuple[FinPatternGroup, ...]
    code_counts: dict[str, int]
    qec_links: dict[str, tuple[str, ...]]
    initial_group_count: int
    feature_count: int

    @property
    def assigned_fins(self) -> int:
        return sum(group.fin_count for group in self.groups)

    def group_for(self, fin: str) -> FinPatternGroup | None:
        return next(
            (g for g in self.groups
             if any(vin == fin for vin, _ in g.members)), None,
        )


def cluster_autoexport_fins(
    all_fins: Sequence[str],
    fin_faults: Mapping[str, Sequence[FaultKey]],
    dtc_labels: Mapping[FaultKey, str] | None = None,
    qec_links: Mapping[str, Sequence[str]] | None = None,
) -> FinPatternResult:
    """Group full imported FIN histories using sparse TF-IDF and MiniBatchKMeans.

    Never materializes pairwise FIN distances. A candidate requires at least
    one ECU:DTC observed in two different FINs. Weak/undersized assignments
    stay explicitly unassigned rather than being called confirmed clusters.
    Repeated DTC readings on one FIN count as one feature.
    """
    fines = tuple(sorted(set(all_fins)))
    all_set = set(fines)
    if len(fines) > 200_000:
        raise ValueError("Zu viele FINs für die explorative Offline-Analyse.")
    faults = {
        fin: frozenset(
            (ecu.strip().upper(), code.strip().upper())
            for ecu, code in codes
            if ecu.strip() and code.strip()
        )
        for fin, codes in fin_faults.items() if fin in all_set
    }
    linked = {
        fin: tuple(sorted(set(qec_links.get(fin, ()))))
        for fin in fines if qec_links is not None and qec_links.get(fin)
    }
    code_counts = {fin: len(faults.get(fin, ())) for fin in fines}
    observed = tuple(fin for fin in fines if code_counts[fin] > 0)
    no_dtc = tuple(fin for fin in fines if not code_counts[fin])
    prevalence = Counter(f for fin in observed for f in faults[fin])
    # DTC unique to one FIN cannot provide evidence of a shared pattern.
    usable = {fault for fault, count in prevalence.items() if count >= 2}
    candidates = tuple(
        fin for fin in observed if any(key in usable for key in faults[fin])
    )
    if len(candidates) < MIN_GROUP_SIZE:
        return FinPatternResult(
            len(fines), len(observed), no_dtc, observed, (), code_counts,
            linked, 0, len(usable),
        )

    signature_map = {
        fin: tuple(sorted(f for f in faults[fin] if f in usable))
        for fin in candidates
    }
    # Use exact keys; no substring matching or semantic guesswork.
    vectorizer = DictVectorizer(sparse=True, dtype=np.float32)
    matrix = vectorizer.fit_transform([
        {f"{ecu}\u241f{code}": 1.0 for ecu, code in signature_map[fin]}
        for fin in candidates
    ])
    matrix = TfidfTransformer(norm="l2", use_idf=True).fit_transform(matrix)
    n = len(candidates)
    unique_signatures = len(set(signature_map.values()))
    target = min(
        n, unique_signatures, MAX_INITIAL_GROUPS,
        max(2, int(sqrt(n / 2))),
    )
    # n_init and random_state make the comparison repeatable on the same data.
    learner = MiniBatchKMeans(
        n_clusters=target, batch_size=512, n_init=3,
        max_iter=75, random_state=42, reassignment_ratio=0.0,
    )
    learner.fit(matrix)
    centers = normalize(np.asarray(learner.cluster_centers_), axis=1)
    # This is O(n * k) with k <= 64, not O(n*n). Sparse TF-IDF rows
    # remain sparse, the dense score matrix stays bounded at n x 64.
    scores = np.asarray(matrix @ centers.T)
    best_cluster = np.argmax(scores, axis=1)
    best_score = np.max(scores, axis=1)
    grouped: dict[int, list[tuple[str, float]]] = defaultdict(list)
    unassigned = {fin for fin in observed if fin not in signature_map}
    for row, fin in enumerate(candidates):
        similarity = float(best_score[row])
        if similarity < MIN_FIN_SIMILARITY:
            unassigned.add(fin)
        else:
            grouped[int(best_cluster[row])].append((fin, similarity))
    retained = [
        members for members in grouped.values()
        if len(members) >= MIN_GROUP_SIZE
    ]
    for members in grouped.values():
        if len(members) < MIN_GROUP_SIZE:
            unassigned.update(fin for fin, _ in members)
    retained.sort(
        key=lambda members: (-len(members), min(fin for fin, _ in members))
    )
    labels = dtc_labels or {}
    groups = []
    for number, members in enumerate(retained, start=1):
        members.sort(key=lambda item: (-item[1], item[0]))
        local_frequency = Counter(
            code for fin, _ in members for code in faults[fin]
        )
        common_codes = sorted(
            ((key, count) for key, count in local_frequency.items() if count >= 2),
            key=lambda item: (-item[1], item[0] != "CPC3", item[0]),
        )[:16]
        # Median similarity to a centroid is a grouping descriptive score,
        # explicitly NOT P(same component failure).
        groups.append(FinPatternGroup(
            group_id=number,
            members=tuple((fin, round(score, 4)) for fin, score in members),
            representative_fin=members[0][0],
            common_faults=tuple(
                (ecu, dtc, count, labels.get((ecu, dtc), ""))
                for (ecu, dtc), count in common_codes
            ),
            qec_fin_count=sum(fin in linked for fin, _ in members),
            median_similarity=round(
                float(np.median([score for _, score in members])), 4
            ),
        ))
    return FinPatternResult(
        total_fins=len(fines), dtc_fins=len(observed),
        no_dtc_fins=no_dtc, unassigned_fins=tuple(sorted(unassigned)),
        groups=tuple(groups), code_counts=code_counts,
        qec_links=linked, initial_group_count=target,
        feature_count=matrix.shape[1],
    )
