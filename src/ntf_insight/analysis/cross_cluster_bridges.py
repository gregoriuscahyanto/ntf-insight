"""Read-only comparison of CPC3 diagnostic patterns ACROSS HDBSCAN groups.

Shared ECU:DTC patterns are diagnostics, not proof of one root cause.
This module does not merge groups or change their representatives/membership.
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from math import isfinite, log
from statistics import median

from ntf_insight.analysis.diagnostic_evidence_audit import DiagnosticEvidenceAudit
from ntf_insight.analysis.hdbscan_clustering import MLClusterResult
from ntf_insight.analysis.mechanism_review import ConfirmedMechanism
from ntf_insight.domain.case import NTFCase


FaultKey = tuple[str, str]


@dataclass(frozen=True, slots=True)
class ClusterBridge:
    left: str
    right: str
    left_representative: str
    right_representative: str
    shared_core_faults: tuple[FaultKey, ...]
    shared_cpc3: tuple[FaultKey, ...]
    left_only_cpc3: tuple[FaultKey, ...]
    right_only_cpc3: tuple[FaultKey, ...]
    cpc3_idf_sum: float
    medoid_cosine: float
    between_median_cosine: float
    between_p10_cosine: float
    weak_between_pairs: int
    between_pairs: int
    same_fin_between_pairs: int
    independent_fin_pairs: int
    reviewed_mechanism_relation: str
    note: str

    @property
    def weak_between_fraction(self) -> float:
        return self.weak_between_pairs / self.between_pairs if self.between_pairs else 0.0


@dataclass(frozen=True, slots=True)
class ClusterBridgeReport:
    compared_pairs: int
    cpc3_bridge_pairs: int
    links: tuple[ClusterBridge, ...]


def _cosine(distance: float) -> float:
    if not isfinite(distance) or distance < 0:
        raise ValueError("Ungültige ML-Distanz: Clusterbrücken nicht auswertbar.")
    return max(0.0, min(1.0, 1.0 - distance * distance / 2.0))


def build_cluster_bridges(
    cases: list[NTFCase],
    result: MLClusterResult,
    audit: DiagnosticEvidenceAudit,
    *,
    confirmations: tuple[ConfirmedMechanism, ...] = (),
    min_shared_cpc3: int = 1,
) -> ClusterBridgeReport:
    """Compare shared *core* CPC3 DTCs, then original N-dimensional cosines.

    Core means ECU:DTC present in EVERY member of both original ML groups.
    Source DTC frequencies give an interpretive IDF sum only, never a learned
    same-cause probability. The 45% weak-pair cutoff is uncalibrated.
    """
    if min_shared_cpc3 < 1:
        raise ValueError("Mindestens ein gemeinsamer CPC3-DTC erforderlich.")
    by_id = {case.case_id: case for case in cases}
    if len(by_id) != len(cases) or result.case_count != len(cases):
        raise ValueError("Fallbestand stimmt nicht mit dem ML-Modell überein.")
    if set(result.eligible_case_ids) - set(by_id):
        raise ValueError("ML-Modell enthält unbekannte QEC-Fälle.")
    if audit.scoped_cases != len(cases) or (
        result.dtc_source != audit.dtc_source
        or result.lookback_days != audit.lookback_days
    ):
        raise ValueError("Diagnoseaudit und Cluster gehören nicht zum gleichen Szenario.")
    if len(result.distances) != len(result.eligible_case_ids) or any(
        len(row) != len(result.eligible_case_ids) for row in result.distances
    ):
        raise ValueError("Ungültige ML-Distanzmatrix.")
    group_ids = [cid for cluster in result.clusters for cid in cluster.case_ids]
    if len(group_ids) != len(set(group_ids)) or not set(group_ids).issubset(
        result.eligible_case_ids
    ):
        raise ValueError("Mehrfach oder ungültig gruppierte QEC-Fälle.")
    labels = {item.case_id: item.mechanism_code for item in confirmations}
    if len(labels) != len(confirmations) or not set(labels).issubset(by_id):
        raise ValueError("Widersprüchliche oder unbekannte Fachbestätigungen.")
    index = {cid: i for i, cid in enumerate(result.eligible_case_ids)}
    frequencies = {row.fault: row.case_count for row in audit.frequencies}
    n = max(1, audit.eligible_cases)
    links: list[ClusterBridge] = []
    compared = 0
    candidates = 0
    for left, right in combinations(result.clusters, 2):
        compared += 1
        shared = tuple(sorted(set(left.common_faults) & set(right.common_faults)))
        shared_cpc3 = tuple(
            fault for fault in shared if fault[0].strip().upper() == "CPC3"
        )
        if shared_cpc3:
            candidates += 1
        if len(shared_cpc3) < min_shared_cpc3:
            continue
        left_cpc3 = {
            fault for fault in left.common_faults if fault[0].strip().upper() == "CPC3"
        }
        right_cpc3 = {
            fault for fault in right.common_faults if fault[0].strip().upper() == "CPC3"
        }
        idf_sum = sum(
            1.0 + log((n + 1) / (frequencies.get(fault, n) + 1))
            for fault in shared_cpc3
        )
        left_rep = left.representative_case_id
        right_rep = right.representative_case_id
        medoid_cosine = _cosine(
            result.distances[index[left_rep]][index[right_rep]]
        )
        pair_cosines = []
        same_fin = 0
        independent = 0
        for left_id in left.case_ids:
            for right_id in right.case_ids:
                pair_cosines.append(
                    _cosine(result.distances[index[left_id]][index[right_id]])
                )
                if by_id[left_id].vin == by_id[right_id].vin:
                    same_fin += 1
                else:
                    independent += 1
        pair_cosines.sort()
        p10_idx = 0.1 * (len(pair_cosines) - 1)
        low, high = int(p10_idx), min(int(p10_idx) + 1, len(pair_cosines) - 1)
        p10 = pair_cosines[low] * (1 - p10_idx % 1) + (
            pair_cosines[high] * (p10_idx % 1)
        )
        left_label, right_label = labels.get(left_rep), labels.get(right_rep)
        if left_label and right_label:
            relation = (
                "Gleiche unabhängig bestätigte Repräsentantenmechanismen"
                if left_label == right_label
                else "Widerspruch: unterschiedliche bestätigte Repräsentantenmechanismen"
            )
        elif left_label or right_label:
            relation = "Nur ein Repräsentant unabhängig bestätigt"
        else:
            relation = "Keine bestätigten Repräsentantenmechanismen"
        note = (
            "Gemeinsame CPC3-Kern-DTCs – technische Bedeutung unabhängig prüfen. "
            "Kein automatisches Zusammenlegen und keine Ursachenübertragung."
        )
        if same_fin:
            note += " Gleiche FIN zwischen den Gruppen: keine unabhängige Replikation."
        if left_label and right_label and left_label != right_label:
            note += " Bestätigte Mechanismen widersprechen sich."
        links.append(ClusterBridge(
            left=f"H{left.cluster_id}",
            right=f"H{right.cluster_id}",
            left_representative=left_rep,
            right_representative=right_rep,
            shared_core_faults=shared,
            shared_cpc3=shared_cpc3,
            left_only_cpc3=tuple(sorted(left_cpc3 - right_cpc3)),
            right_only_cpc3=tuple(sorted(right_cpc3 - left_cpc3)),
            cpc3_idf_sum=round(idf_sum, 4),
            medoid_cosine=round(medoid_cosine, 4),
            between_median_cosine=round(median(pair_cosines), 4),
            between_p10_cosine=round(p10, 4),
            weak_between_pairs=sum(score < 0.45 for score in pair_cosines),
            between_pairs=len(pair_cosines),
            same_fin_between_pairs=same_fin,
            independent_fin_pairs=independent,
            reviewed_mechanism_relation=relation,
            note=note,
        ))
    links.sort(
        key=lambda item: (
            -len(item.shared_cpc3),
            -item.cpc3_idf_sum,
            -item.medoid_cosine,
            item.left,
            item.right,
        )
    )
    return ClusterBridgeReport(
        compared_pairs=compared,
        cpc3_bridge_pairs=candidates,
        links=tuple(links),
    )
