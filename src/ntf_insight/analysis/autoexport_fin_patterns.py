"""FIN-weite Diagnosecluster mit HDBSCAN Leaf/EOM und Complete-Link.

Eine FIN ist genau eine Beobachtung. AutoExport und QEC werden zuvor unter
derselben FIN zusammengeführt. Eine 2D/3D-Projektion ist NUR Visualisierung.

Skalierung: Sparse TF-IDF -> 16-dimensionale SVD -> HDBSCAN. Es wird keine
quadratische Distanzmatrix ueber alle FINs aufgebaut. Complete-Link wird
konservativ innerhalb begrenzter Leaf-Pruefbloecke auf den ORIGINALEN
hochdimensionalen Cosinusabstaenden berechnet (nicht globale Hierarchie).

Weder Cluster noch Mitgliedschaft sind Pumpenfehler/NTF-Wahrscheinlichkeiten.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace
from typing import Callable, Mapping, Sequence

import numpy as np
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import squareform
from sklearn.cluster import HDBSCAN
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction import DictVectorizer
from sklearn.feature_extraction.text import TfidfTransformer
from sklearn.preprocessing import normalize

FaultKey = tuple[str, str]
METHODS = ("leaf", "eom", "complete_cosine")
METHOD_TITLES = {
    "leaf": "HDBSCAN · Leaf",
    "eom": "HDBSCAN · EOM",
    "complete_cosine": "Complete-Link · Cosinus (konservative Prüfgruppen)",
}
MAX_SVD_DIM = 16
MAX_COMPLETE_BLOCK = 450
MIN_COMPLETE_SIMILARITY = 0.45


@dataclass(frozen=True, slots=True)
class FinPatternGroup:
    group_id: int
    members: tuple[tuple[str, float], ...]
    representative_fin: str
    common_faults: tuple[tuple[str, str, int, str], ...]
    qec_fin_count: int
    median_similarity: float
    shared_fault_count: int = 0
    pair_weak_count: int = 0
    checked_pair_count: int = 0

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
    sources_by_fin: dict[str, str] | None = None
    autoexport_fin_count: int = 0
    qec_fin_count: int = 0
    overlap_fin_count: int = 0
    qec_only_fin_count: int = 0
    method: str = "leaf"
    positions: tuple[tuple[str, float, float, float], ...] = ()
    notes: str = ""
    pre_swap_fins: int = 0

    @property
    def assigned_fins(self) -> int:
        return sum(group.fin_count for group in self.groups)

    def group_for(self, fin: str) -> FinPatternGroup | None:
        return next(
            (group for group in self.groups
             if any(member == fin for member, _ in group.members)), None
        )


@dataclass(slots=True)
class _PreparedFins:
    all_fins: tuple[str, ...]
    eligible: tuple[str, ...]
    no_dtc: tuple[str, ...]
    faults: dict[str, frozenset[FaultKey]]
    codes: dict[str, int]
    x: object
    reduced: np.ndarray
    positions: tuple[tuple[str, float, float, float], ...]
    labels: Mapping[FaultKey, str]
    links: dict[str, tuple[str, ...]]
    dimensions: int


def _prepare(
    all_fins: Sequence[str],
    fin_faults: Mapping[str, Sequence[FaultKey]],
    labels: Mapping[FaultKey, str] | None,
    qec_links: Mapping[str, Sequence[str]] | None,
) -> _PreparedFins:
    fins = tuple(sorted({fin.strip().upper() for fin in all_fins if fin.strip()}))
    if len(fins) > 200_000:
        raise ValueError("Die FIN-Anzahl uebersteigt das sichere lokale Analyselimit.")
    finset = set(fins)
    faults = {
        fin: frozenset(
            (ecu.strip().upper(), dtc.strip().upper())
            for ecu, dtc in fin_faults.get(fin, ())
            if ecu.strip() and dtc.strip()
        )
        for fin in fins
    }
    codes = {fin: len(faults[fin]) for fin in fins}
    eligible = tuple(fin for fin in fins if codes[fin])
    no_dtc = tuple(fin for fin in fins if not codes[fin])
    links = {
        fin: tuple(sorted(set(qec_links.get(fin, ()))))
        for fin in fins if qec_links and qec_links.get(fin)
    }
    if not eligible:
        return _PreparedFins(
            fins, (), no_dtc, faults, codes, None,
            np.zeros((0, 3), dtype=np.float32), (), labels or {}, links, 0,
        )

    # ECU:DTC is one exact, binary feature regardless of repeated raw lines.
    # IDF is fitted on all FINs with imported diagnostics, not on QEC only.
    vectorizer = DictVectorizer(sparse=True, dtype=np.float32)
    x = vectorizer.fit_transform([
        {f"{ecu}\u241f{dtc}": 1.0 for ecu, dtc in sorted(faults[fin])}
        for fin in eligible
    ])
    x = TfidfTransformer(norm="l2").fit_transform(x)
    dimensions = int(x.shape[1])
    n = len(eligible)

    # Dense 16-dimensional HDBSCAN avoids an O(n^2) raw-distance matrix.
    # This is a high-dimensional model projection, NOT the plot's 2D space.
    if n < 3 or dimensions < 2:
        reduced = np.asarray(x.toarray(), dtype=np.float32)
    else:
        rank = min(MAX_SVD_DIM, dimensions - 1, n - 1)
        reduced = TruncatedSVD(
            n_components=rank, random_state=42,
        ).fit_transform(x).astype(np.float32)
    reduced = np.asarray(normalize(reduced), dtype=np.float32)

    # 2D and 3D are views of the SAME fitted 16D model embedding.
    # Missing dimensions simply lie on the corresponding coordinate axis.
    points = np.zeros((n, 3), dtype=np.float32)
    points[:, :min(3, reduced.shape[1])] = reduced[:, :3]
    positions = tuple(
        (fin, float(points[i, 0]), float(points[i, 1]), float(points[i, 2]))
        for i, fin in enumerate(eligible)
    )
    return _PreparedFins(
        fins, eligible, no_dtc, faults, codes, x, reduced,
        positions, labels or {}, links, dimensions,
    )


def _hdbscan_labels(
    prepared: _PreparedFins,
    method: str,
    min_cluster_size: int,
    min_samples: int,
) -> tuple[np.ndarray, np.ndarray]:
    n = len(prepared.eligible)
    labels = np.full(n, -1, dtype=int)
    strengths = np.zeros(n, dtype=float)
    if n < min_cluster_size or prepared.dimensions == 0:
        return labels, strengths
    model = HDBSCAN(
        min_cluster_size=min_cluster_size,
        min_samples=min(min_samples, n - 1),
        cluster_selection_method=method,
        metric="euclidean",
        algorithm="auto",
        n_jobs=1,
        allow_single_cluster=False,
    )
    labels = np.asarray(model.fit_predict(prepared.reduced), dtype=int)
    strengths = np.asarray(model.probabilities_, dtype=float)
    return labels, strengths


def _complete_link_labels(
    prepared: _PreparedFins,
    leaf_labels: np.ndarray,
    min_cluster_size: int,
    minimum_similarity: float,
) -> tuple[np.ndarray, np.ndarray]:
    """All accepted pairs pass the threshold; split blocks may miss matches.

    Each real Complete-Link run compares ORIGINAL sparse TF-IDF cosine
    distances for at most 450 FINs. This is a conservative secondary check,
    never presented as a global Complete-Link partition of all vehicles.
    """
    labels = np.full(len(prepared.eligible), -1, dtype=int)
    strengths = np.zeros(len(labels), dtype=float)
    next_id = 0
    for parent in sorted(set(leaf_labels) - {-1}):
        indices = np.flatnonzero(leaf_labels == parent)
        # Deterministic input order. Splitting only reduces recall,
        # not internal pairwise guarantees of Complete-Link.
        for start in range(0, len(indices), MAX_COMPLETE_BLOCK):
            block = indices[start:start + MAX_COMPLETE_BLOCK]
            if len(block) < min_cluster_size:
                continue
            x = prepared.x[block]
            similarity = (x @ x.T).toarray()
            distance = np.clip(1.0 - similarity, 0.0, 1.0)
            distance = np.maximum(distance, distance.T)
            np.fill_diagonal(distance, 0.0)
            tree = linkage(
                squareform(distance, checks=False),
                method="complete",
            )
            subgroups = fcluster(
                tree, t=1.0 - minimum_similarity, criterion="distance",
            )
            for subgroup in sorted(set(subgroups)):
                positions = block[subgroups == subgroup]
                if len(positions) >= min_cluster_size:
                    labels[positions] = next_id
                    strengths[positions] = 1.0
                    next_id += 1
    return labels, strengths


def _make_result(
    prepared: _PreparedFins,
    method: str,
    labels: np.ndarray,
    strengths: np.ndarray,
    *,
    min_cluster_size: int,
    notes: str,
) -> FinPatternResult:
    groups = []
    assigned: set[str] = set()
    for raw in sorted(set(labels) - {-1}):
        positions = np.flatnonzero(labels == raw)
        if len(positions) < min_cluster_size:
            continue
        fins = tuple(prepared.eligible[i] for i in positions)
        # Representative = actual FIN closest to the ORIGINAL TF-IDF
        # group centroid, not an invented average or QEC outcome.
        submatrix = prepared.x[positions]
        centroid = np.asarray(submatrix.mean(axis=0)).ravel()
        centrality = np.asarray(submatrix @ centroid).ravel()
        best = sorted(
            range(len(fins)), key=lambda j: (-centrality[j], fins[j])
        )[0]
        rep_fin = fins[best]
        cos_to_rep = np.clip(
            (submatrix @ submatrix[best].T).toarray().ravel(), 0.0, 1.0,
        )
        members = tuple(sorted(
            ((fin, round(float(cos_to_rep[j]), 4))
             for j, fin in enumerate(fins)),
            key=lambda item: (-item[1], item[0]),
        ))
        frequency = Counter(
            fault for fin in fins for fault in prepared.faults[fin]
        )
        # SVD may bring otherwise unrelated rare-DTC FINs close together.
        # Never publish such a group without at least one repeated ORIGINAL
        # ECU:DTC feature; 2D/3D proximity by itself is not DTC evidence.
        if not any(count >= 2 for count in frequency.values()):
            continue
        common = tuple(
            (ecu, dtc, count, prepared.labels.get((ecu, dtc), ""))
            for (ecu, dtc), count in sorted(
                ((key, count) for key, count in frequency.items()
                 if count >= 2),
                key=lambda item: (-item[1], item[0][0] != "CPC3", item[0]),
            )
        )
        # Assess heterogeneity on bounded, deterministic sample pairs.
        # Never calculate the entire n^2 pair-distance matrix.
        pair_total = len(fins) * (len(fins) - 1) // 2
        rng = np.random.default_rng(42 + len(fins))
        sample_count = min(1200, pair_total)
        if sample_count == pair_total and len(fins) <= 50:
            left, right = np.triu_indices(len(fins), k=1)
        else:
            left = rng.integers(0, len(fins), sample_count)
            right = rng.integers(0, len(fins), sample_count)
            mask = left != right
            left, right = left[mask], right[mask]
        pair_cos = np.asarray(
            submatrix[left].multiply(submatrix[right]).sum(axis=1)
        ).ravel() if len(left) else np.zeros(0)
        weak = int(np.count_nonzero(pair_cos < 0.45))
        assigned.update(fins)
        groups.append(FinPatternGroup(
            group_id=0,
            members=members,
            representative_fin=rep_fin,
            common_faults=common,
            qec_fin_count=sum(fin in prepared.links for fin in fins),
            median_similarity=round(float(np.median(cos_to_rep)), 4),
            shared_fault_count=sum(count == len(fins) for count in frequency.values()),
            pair_weak_count=weak,
            checked_pair_count=len(pair_cos),
        ))
    groups.sort(key=lambda g: (-g.fin_count, g.representative_fin))
    groups = [
        replace(group, group_id=index)
        for index, group in enumerate(groups, 1)
    ]
    noise = tuple(
        fin for fin in prepared.eligible if fin not in assigned
    )
    return FinPatternResult(
        total_fins=len(prepared.all_fins),
        dtc_fins=len(prepared.eligible),
        no_dtc_fins=prepared.no_dtc,
        unassigned_fins=noise,
        groups=tuple(groups),
        code_counts=prepared.codes,
        qec_links=prepared.links,
        initial_group_count=len(groups),
        feature_count=prepared.dimensions,
        method=method,
        positions=prepared.positions,
        notes=notes,
    )


def cluster_fin_methods(
    all_fins: Sequence[str],
    fin_faults: Mapping[str, Sequence[FaultKey]],
    dtc_labels: Mapping[FaultKey, str] | None = None,
    qec_links: Mapping[str, Sequence[str]] | None = None,
    *,
    min_cluster_size: int = 5,
    min_samples: int = 2,
    minimum_similarity: float = MIN_COMPLETE_SIMILARITY,
    progress: Callable[[str], None] | None = None,
) -> dict[str, FinPatternResult]:
    """One computation, three genuine methods, same FIN feature space."""
    if not 2 <= min_cluster_size <= 100:
        raise ValueError("Mindestclustergröße muss zwischen 2 und 100 liegen.")
    if not 1 <= min_samples <= 100:
        raise ValueError("MinSamples muss zwischen 1 und 100 liegen.")
    if not 0 < minimum_similarity < 1:
        raise ValueError("Cosinus-Grenze muss zwischen 0 und 1 liegen.")
    if progress:
        progress("Baue gemeinsame ECU:DTC-Merkmale für eindeutige FINs …")
    prepared = _prepare(all_fins, fin_faults, dtc_labels, qec_links)
    out: dict[str, FinPatternResult] = {}
    for method in ("leaf", "eom"):
        if progress:
            progress(f"Berechne {METHOD_TITLES[method]} …")
        labels, strengths = _hdbscan_labels(
            prepared, method, min_cluster_size, min_samples,
        )
        out[method] = _make_result(
            prepared, method, labels, strengths,
            min_cluster_size=min_cluster_size,
            notes=(
                "Echte HDBSCAN-Dichtegruppen auf 16D-SVD aus Sparse TF-IDF. "
                "Eine Prognose zur Pumpentauschwirkung ist das nicht."
            ),
        )
        if method == "leaf":
            leaf_labels = labels
    if progress:
        progress("Prüfe konservative Complete-Link-Gruppen innerhalb Leaf …")
    labels, strengths = _complete_link_labels(
        prepared, leaf_labels, min_cluster_size, minimum_similarity,
    )
    out["complete_cosine"] = _make_result(
        prepared, "complete_cosine", labels, strengths,
        min_cluster_size=min_cluster_size,
        notes=(
            "Complete-Link prüft originale ECU:DTC-TF-IDF-Cosinusabstände "
            "in Teilblöcken bis 450 FINs innerhalb von HDBSCAN Leaf. "
            "Alle Paare einer ausgewiesenen Prüfgruppe erfüllen die Grenze; "
            "gruppenübergreifende Ähnlichkeiten können übersehen werden. "
            "Das ist ausdrücklich KEINE globale Complete-Link-Partition."
        ),
    )
    return out


def cluster_autoexport_fins(
    all_fins: Sequence[str],
    fin_faults: Mapping[str, Sequence[FaultKey]],
    dtc_labels: Mapping[FaultKey, str] | None = None,
    qec_links: Mapping[str, Sequence[str]] | None = None,
    *,
    method: str = "leaf",
    min_cluster_size: int = 5,
    min_samples: int = 2,
) -> FinPatternResult:
    """Legacy local API, but no KMeans: returns actual requested method."""
    if method not in METHODS:
        raise ValueError("Unbekannte Clustermethode.")
    return cluster_fin_methods(
        all_fins, fin_faults, dtc_labels, qec_links,
        min_cluster_size=min_cluster_size, min_samples=min_samples,
    )[method]
