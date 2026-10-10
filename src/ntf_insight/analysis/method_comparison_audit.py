"""Fair, local-only clustering-method comparison on ONE diagnostic feature space.

HDBSCAN Leaf/EOM use precisely the original pre-swap metric feature space;
Complete-Link experiments reuse that SAME Euclidean distance matrix, not
the legacy weighted-Jaccard Complete-Link scoring from case_clustering.py.

No threshold or cluster quality statistic is a failure-cause probability.
No private case identifiers are included in serialized summaries.
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from math import sqrt

import numpy as np
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import squareform

from ntf_insight.analysis.case_clustering import signature_for
from ntf_insight.analysis.hdbscan_clustering import (
    HDBSCANMethodComparison, MLClusterResult,
)
from ntf_insight.domain.case import NTFCase


@dataclass(frozen=True, slots=True)
class StrictCompleteLinkSummary:
    minimum_cosine: float
    min_members: int
    cluster_count: int
    grouped_cases: int
    noise_cases: int
    largest_cluster: int
    groups_with_common_exact_dtc: int
    groups_with_multiple_fins: int
    groups_with_core_and_multiple_fins: int
    internal_pair_count: int
    pair_jaccard_with_leaf: float | None


def _pairs(group_members: list[tuple[str, ...]]) -> set[tuple[str, str]]:
    return {
        pair
        for group in group_members
        for pair in combinations(sorted(group), 2)
    }


def _jaccard(left: set[tuple[str, str]], right: set[tuple[str, str]]) -> float | None:
    union = left | right
    return round(len(left & right) / len(union), 4) if union else None


def complete_link_same_metric(
    cases: list[NTFCase],
    leaf: MLClusterResult,
    *,
    minimum_cosine: float = 0.45,
    min_members: int = 3,
) -> StrictCompleteLinkSummary:
    """Strict hierarchical Complete-Link on Leaf's ORIGINAL distance matrix.

    Each returned intra-cluster pair has cosine similarity >= threshold.
    Groups with fewer than min_members are recorded as unassigned, not
    reinterpreted as proven No-Trouble-Found cases or supplier faults.
    """
    if leaf.selection_method != "leaf":
        raise ValueError("Für den Methodenvergleich HDBSCAN Leaf erforderlich.")
    if leaf.common_dtc_cutoff is not None:
        raise ValueError("Complete-Link-Szenario verlangt ungefilterte DTC-Eingaben.")
    if not 0 < minimum_cosine < 1:
        raise ValueError("Complete-Link-Schwelle muss strikt zwischen 0 und 1 liegen.")
    if not 2 <= min_members <= 100:
        raise ValueError("Complete-Link-Mindestgruppengröße muss 2 bis 100 betragen.")

    by_id = {case.case_id: case for case in cases}
    ids = leaf.eligible_case_ids
    if len(by_id) != len(cases) or leaf.case_count != len(cases):
        raise ValueError("Complete-Link: QEC-Fallbestand ist nicht eindeutig.")
    if len(ids) != len(set(ids)) or not set(ids).issubset(by_id):
        raise ValueError("Complete-Link: unbekannte oder doppelte QEC-Fälle.")
    matrix = np.asarray(leaf.distances, dtype=float)
    if (
        matrix.shape != (len(ids), len(ids))
        or not np.isfinite(matrix).all()
        or np.min(matrix, initial=0) < -1e-10
        or not np.allclose(matrix, matrix.T, atol=1e-8)
        or not np.allclose(np.diag(matrix), 0, atol=1e-8)
    ):
        raise ValueError("Complete-Link: ungültige originale ML-Distanzmatrix.")

    groups: list[tuple[str, ...]] = []
    limit = sqrt(2.0 * (1.0 - minimum_cosine))
    if len(ids) >= min_members:
        # Equal case ID ordering and the unchanged original distances ensure
        # stable results. fcluster(distance) never bridges a weak pair.
        dendrogram = linkage(
            squareform(np.maximum(matrix, 0), checks=True),
            method="complete",
        )
        labels = fcluster(dendrogram, t=limit, criterion="distance")
        candidates: dict[int, list[int]] = {}
        for position, label in enumerate(labels):
            candidates.setdefault(int(label), []).append(position)
        for positions in candidates.values():
            if len(positions) < min_members:
                continue
            if any(
                (1.0 - float(matrix[i, j]) ** 2 / 2.0) < minimum_cosine - 1e-8
                for i, j in combinations(positions, 2)
            ):
                raise ValueError("Complete-Link-Schwelle nicht für alle Paare erfüllt.")
            groups.append(tuple(ids[i] for i in positions))
    groups.sort(key=lambda members: (-len(members), members))

    signatures = {
        case_id: signature_for(
            by_id[case_id],
            dtc_source=leaf.dtc_source,
            lookback_days=leaf.lookback_days,
        )
        for group in groups for case_id in group
    }
    core_count = independent_count = both_count = 0
    for group in groups:
        core = set(signatures[group[0]].faults)
        for case_id in group[1:]:
            core.intersection_update(signatures[case_id].faults)
        independent = len({by_id[case_id].vin for case_id in group}) >= 2
        core_count += bool(core)
        independent_count += independent
        both_count += bool(core) and independent
    leaf_pairs = _pairs([tuple(group.case_ids) for group in leaf.clusters])
    candidate_pairs = _pairs(groups)
    grouped_count = sum(len(group) for group in groups)
    return StrictCompleteLinkSummary(
        minimum_cosine=minimum_cosine,
        min_members=min_members,
        cluster_count=len(groups),
        grouped_cases=grouped_count,
        noise_cases=len(ids) - grouped_count,
        largest_cluster=max((len(group) for group in groups), default=0),
        groups_with_common_exact_dtc=core_count,
        groups_with_multiple_fins=independent_count,
        groups_with_core_and_multiple_fins=both_count,
        internal_pair_count=len(candidate_pairs),
        pair_jaccard_with_leaf=_jaccard(candidate_pairs, leaf_pairs),
    )


def build_method_evaluation(
    cases: list[NTFCase],
    leaf: MLClusterResult,
    methods: HDBSCANMethodComparison,
) -> dict:
    """Compare two HDBSCAN variants and two Complete-Link cutoffs fairly.

    This dictionary contains counts/ratios only; source identities and
    actual cluster memberships remain on the local host.
    """
    if (
        leaf.selection_method != "leaf"
        or methods.leaf.group_count != len(leaf.clusters)
        or methods.leaf.clustered_cases != leaf.clustered_count
        or methods.eligible_case_count != len(leaf.eligible_case_ids)
        or methods.lookback_days != leaf.lookback_days
        or methods.dtc_source != leaf.dtc_source
        or methods.common_dtc_cutoff != leaf.common_dtc_cutoff
    ):
        raise ValueError("Die verglichenen Modelle stammen nicht aus demselben Szenario.")
    def hdbscan_row(summary) -> dict:
        return {
            "cluster": summary.group_count,
            "clusterfaelle": summary.clustered_cases,
            "ausreisser": summary.noise_cases,
            "groesster_cluster": summary.largest_cluster_size,
            "cluster_mit_dtc_kern": summary.groups_with_common_faults,
            "cluster_ohne_schwache_paare": summary.groups_without_weak_pairs,
            "schwache_fallpaare": summary.weak_pair_count,
            "alle_internen_fallpaare": summary.all_internal_pair_count,
            "median_cluster_mediane": summary.median_of_group_medians,
        }

    strict_45 = complete_link_same_metric(
        cases, leaf, minimum_cosine=0.45, min_members=leaf.min_cluster_size,
    )
    strict_65 = complete_link_same_metric(
        cases, leaf, minimum_cosine=0.65, min_members=leaf.min_cluster_size,
    )

    def complete_row(summary: StrictCompleteLinkSummary) -> dict:
        return {
            "cluster": summary.cluster_count,
            "clusterfaelle": summary.grouped_cases,
            "ausreisser": summary.noise_cases,
            "groesster_cluster": summary.largest_cluster,
            "cluster_mit_dtc_kern": summary.groups_with_common_exact_dtc,
            "cluster_mit_mehreren_fin": summary.groups_with_multiple_fins,
            "cluster_mit_dtc_kern_und_mehreren_fin": (
                summary.groups_with_core_and_multiple_fins
            ),
            "alle_internen_fallpaare": summary.internal_pair_count,
            "paaruebereinstimmung_zu_leaf": summary.pair_jaccard_with_leaf,
            "grenze_cosinus": summary.minimum_cosine,
        }

    return {
        "vergleichsmodus": "GLEICHE_VOR_TAUSCH_FEATURES_UND_DISTANZEN",
        "evidenzhinweis": (
            "Diagnostische Homogenität ist KEIN Ursachennachweis. "
            "Complete-Link erzwingt die Mindestpaarähnlichkeit konstruktiv; "
            "keine unabhängig bestätigten Fehlermechanismen als Gütemaß verfügbar."
        ),
        "geeignete_faelle": len(leaf.eligible_case_ids),
        "methode_leaf": hdbscan_row(methods.leaf),
        "methode_eom": hdbscan_row(methods.eom),
        "methode_complete_link_45": complete_row(strict_45),
        "methode_complete_link_65": complete_row(strict_65),
        "paaruebereinstimmung_leaf_eom": methods.pair_coassignment_jaccard,
        "hinweis_legacy_complete_link": (
            "Bestehende GUI-Complete-Link-Implementierung arbeitet mit "
            "gewichtetem Jaccard statt diesem identischen Cosinus-Featureabstand."
        ),
    }


def approved_method_totals(report: dict) -> dict:
    """Explicitly approved numeric schema; refuse any extra unexpected fields."""
    original = report["methodenbewertung"]
    methods = {}
    columns = {
        "methode_leaf": (
            "cluster", "clusterfaelle", "ausreisser", "cluster_mit_dtc_kern",
            "cluster_ohne_schwache_paare", "schwache_fallpaare",
            "alle_internen_fallpaare",
        ),
        "methode_eom": (
            "cluster", "clusterfaelle", "ausreisser", "cluster_mit_dtc_kern",
            "cluster_ohne_schwache_paare", "schwache_fallpaare",
            "alle_internen_fallpaare",
        ),
        "methode_complete_link_45": (
            "cluster", "clusterfaelle", "ausreisser",
            "cluster_mit_dtc_kern", "cluster_mit_mehreren_fin",
            "cluster_mit_dtc_kern_und_mehreren_fin",
        ),
        "methode_complete_link_65": (
            "cluster", "clusterfaelle", "ausreisser",
            "cluster_mit_dtc_kern", "cluster_mit_mehreren_fin",
            "cluster_mit_dtc_kern_und_mehreren_fin",
        ),
    }
    for name, keys in columns.items():
        methods[name] = {key: original[name][key] for key in keys}
    methods["geeignete_faelle"] = original["geeignete_faelle"]
    for row in methods.values():
        values = row.values() if isinstance(row, dict) else (row,)
        if any(type(value) is not int or value < 0 for value in values):
            raise ValueError("Freigabe nur für nichtnegative aggregierte Ganzzahlen.")
    return methods
