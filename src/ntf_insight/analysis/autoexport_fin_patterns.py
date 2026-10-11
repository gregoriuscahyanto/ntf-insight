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
    "qec_anchor": "QEC-Ankergruppen · Cosinus (keine HDBSCAN-Gruppen)",
}
MAX_SVD_DIM = 16
MAX_COMPLETE_BLOCK = 450
MIN_COMPLETE_SIMILARITY = 0.45
QEC_ANCHOR_MIN_SIMILARITY = 0.45
QEC_ANCHOR_BATCH_SIZE = 512
# A QEC-backed FIN is preferred when its mean ORIGINAL TF-IDF cosine
# similarity to the whole group is at least 90% of the best candidate.
# This affects only the displayed representative, never cluster membership.
QEC_REPRESENTATIVE_MIN_CENTRALITY_RATIO = 0.90


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
    representative_has_qec: bool = False
    representative_centrality_ratio: float = 1.0
    unconstrained_representative_fin: str = ""
    representative_is_fixed_anchor: bool = False

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
    runtime_seconds: float | None = None
    dtc_keys_by_fin: dict[str, tuple[FaultKey, ...]] | None = None

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


def _qec_anchor_labels(
    prepared: _PreparedFins,
    min_cluster_size: int,
    minimum_similarity: float,
) -> tuple[np.ndarray, np.ndarray, dict[int, str]]:
    """Groups around ACTUAL QEC vehicles using ORIGINAL sparse TF-IDF cosine.

    This is not HDBSCAN or globally linked Complete-Link. Eligible QEC FINs
    are anchors. Identical QEC signatures share a canonical lexical anchor.
    Other FINs join the nearest one only above the explicit cosine limit.
    No unlabeled/absent vehicle is forced into any group. Sparse blocks avoid
    an all-vehicle NxN distance matrix even for 11k+ FINs.
    """
    n = len(prepared.eligible)
    labels = np.full(n, -1, dtype=int)
    strengths = np.zeros(n, dtype=float)
    if not n or prepared.x is None:
        return labels, strengths, {}
    signatures: dict[frozenset[FaultKey], int] = {}
    qec_members: dict[int, int] = {}
    # Eligible FINs are lexical and unique. Equal QEC signatures define
    # one anchor, not two competing identical groups.
    for index, fin in enumerate(prepared.eligible):
        if not prepared.links.get(fin):
            continue
        signature = prepared.faults[fin]
        if signature not in signatures:
            signatures[signature] = index
        qec_members[index] = signatures[signature]
    if not signatures:
        return labels, strengths, {}

    anchor_indices = tuple(sorted(set(qec_members.values())))
    anchor_ids = {
        index: group_id for group_id, index in enumerate(anchor_indices)
    }
    anchor_names = {
        group_id: prepared.eligible[index]
        for index, group_id in anchor_ids.items()
    }
    for index, anchor in qec_members.items():
        labels[index] = anchor_ids[anchor]
        strengths[index] = 1.0

    anchor_x = prepared.x[list(anchor_indices)]
    # Sparse (vehicles x ECU:DTC) @ sparse (DTC x QEC anchors):
    # bounded dense blocks are at most 512 x number_of_QEC_anchors.
    for start in range(0, n, QEC_ANCHOR_BATCH_SIZE):
        end = min(n, start + QEC_ANCHOR_BATCH_SIZE)
        similarities = (prepared.x[start:end] @ anchor_x.T).toarray()
        winners = np.argmax(similarities, axis=1)
        highest = similarities[
            np.arange(end - start), winners
        ]
        for offset in range(end - start):
            index = start + offset
            if index in qec_members:
                continue
            if float(highest[offset]) + 1e-7 < minimum_similarity:
                continue
            winner_anchor = anchor_indices[int(winners[offset])]
            labels[index] = anchor_ids[winner_anchor]
            strengths[index] = float(highest[offset])
    # An anchor with fewer than the minimum FINs is not a claimed
    # cluster; all its FINs remain unassigned/visible as noise.
    counts = np.bincount(labels[labels >= 0], minlength=len(anchor_ids))
    for group_id, size in enumerate(counts):
        if size < min_cluster_size:
            labels[labels == group_id] = -1
    strengths[labels == -1] = 0.0
    return labels, strengths, anchor_names


def _representative_position(
    fins: tuple[str, ...],
    centrality: np.ndarray,
    qec_links: Mapping[str, tuple[str, ...]],
) -> tuple[int, float]:
    """Prefer a QEC case only if it remains diagnostically representative.

    Centrality = average ORIGINAL TF-IDF cosine to all FINs in this
    cluster (including self); no HDBSCAN labels or distances are changed.
    A QEC FIN must reach >=90% of the optimal centrality. Exact ties
    break by FIN, independently of the input order.
    """
    if not fins:
        raise ValueError("Eine leere Gruppe hat keinen Repräsentanten.")
    order = sorted(
        range(len(fins)),
        key=lambda index: (-float(centrality[index]), fins[index]),
    )
    strongest = order[0]
    selected = strongest
    qec_candidates = [index for index in order if qec_links.get(fins[index])]
    if qec_candidates:
        candidate = qec_candidates[0]
        if (
            float(centrality[candidate])
            >= QEC_REPRESENTATIVE_MIN_CENTRALITY_RATIO
            * float(centrality[strongest]) - 1e-12
        ):
            selected = candidate
    best_value = float(centrality[strongest])
    ratio = float(centrality[selected]) / best_value if best_value > 0 else 1.0
    return selected, round(ratio, 4)


def _make_result(
    prepared: _PreparedFins,
    method: str,
    labels: np.ndarray,
    strengths: np.ndarray,
    *,
    min_cluster_size: int,
    notes: str,
    fixed_representatives: Mapping[int, str] | None = None,
) -> FinPatternResult:
    groups = []
    assigned: set[str] = set()
    for raw in sorted(set(labels) - {-1}):
        positions = np.flatnonzero(labels == raw)
        if len(positions) < min_cluster_size:
            continue
        fins = tuple(prepared.eligible[i] for i in positions)
        # Representative: favour a QEC-backed FIN when it has at least
        # 90% of the best group centrality on ORIGINAL sparse TF-IDF.
        # Never replace the group medoid with a diagnostically atypical QEC.
        submatrix = prepared.x[positions]
        centroid = np.asarray(submatrix.mean(axis=0)).ravel()
        centrality = np.asarray(submatrix @ centroid).ravel()
        # Keep the original diagnostic ranking independent of QEC labels:
        # cluster IDs must remain stable when only QEC links are added.
        diagnostic_best = min(
            range(len(fins)),
            key=lambda index: (-float(centrality[index]), fins[index]),
        )
        fixed_fin = (
            fixed_representatives.get(int(raw))
            if fixed_representatives is not None else None
        )
        if fixed_fin is not None:
            if fixed_fin not in fins or not prepared.links.get(fixed_fin):
                raise ValueError(
                    "QEC-Anker muss FIN dieser Gruppe mit QEC-Bezug sein."
                )
            best = fins.index(fixed_fin)
            strongest = float(centrality[diagnostic_best])
            representative_ratio = round(
                float(centrality[best]) / strongest
                if strongest > 0 else 1.0, 4,
            )
        else:
            best, representative_ratio = _representative_position(
                fins, centrality, prepared.links,
            )
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
            representative_has_qec=rep_fin in prepared.links,
            representative_centrality_ratio=representative_ratio,
            unconstrained_representative_fin=fins[diagnostic_best],
            representative_is_fixed_anchor=fixed_fin is not None,
        ))
    # Retain the historic grouping order based on the unconstrained
    # diagnostic representative. Adding QEC labels must not rename C IDs.
    groups.sort(key=lambda g: (
        -g.fin_count, g.unconstrained_representative_fin,
    ))
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
    include_qec_anchors: bool = False,
    progress: Callable[[str], None] | None = None,
) -> dict[str, FinPatternResult]:
    """One shared FIN feature space; optional separate QEC-seeded analysis."""
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
    if include_qec_anchors:
        if progress:
            progress("Ordne AutoExport-FINs den nächsten QEC-Ankern zu …")
        labels, strengths, fixed = _qec_anchor_labels(
            prepared, min_cluster_size, minimum_similarity,
        )
        out["qec_anchor"] = _make_result(
            prepared, "qec_anchor", labels, strengths,
            min_cluster_size=min_cluster_size,
            fixed_representatives=fixed,
            notes=(
                "Separates QEC-Ankerverfahren, KEIN HDBSCAN: "
                "Jede ausgegebene Gruppe hat eine echte QEC-FIN als Anker. "
                "Andere Fahrzeuge werden nur bei mindestens "
                f"{minimum_similarity:.0%} originaler ECU:DTC-TF-IDF-"
                "Cosinusähnlichkeit zu ihrem nächsten QEC-Anker zugeordnet. "
                "Identische QEC-Signaturen teilen einen Anker. "
                "Nicht passende FINs sowie Gruppen unter Mindestgröße "
                "bleiben unzugeordnet. Die Mindestähnlichkeit gilt "
                "jeweils zum Anker, NICHT zwischen jedem Fahrzeugpaar. "
                "Die Gruppen sind eine explorative Diagnosezuordnung, "
                "kein Pumpenursachen- oder NTF-Nachweis."
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
    """Local API for an explicit method; anchored mode is opt-in."""
    if method not in (*METHODS, "qec_anchor"):
        raise ValueError("Unbekannte Clustermethode.")
    return cluster_fin_methods(
        all_fins, fin_faults, dtc_labels, qec_links,
        min_cluster_size=min_cluster_size, min_samples=min_samples,
        include_qec_anchors=method == "qec_anchor",
    )[method]
