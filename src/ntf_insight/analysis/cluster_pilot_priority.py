"""Auditable, read-only inspection plan for one real medoid per HDBSCAN group.

This is a *testing priority*, NOT predicted NTF/supplier root cause.
Only independent technical evidence can validate a target mechanism.
The exploratory 45% similarity threshold is not calibrated.
"""
from __future__ import annotations

from dataclasses import dataclass

from ntf_insight.analysis.cross_cluster_bridges import (
    ClusterBridgeReport, build_cluster_bridges,
)
from ntf_insight.analysis.diagnostic_evidence_audit import DiagnosticEvidenceAudit
from ntf_insight.analysis.hdbscan_clustering import MLClusterResult, MLMember
from ntf_insight.analysis.mechanism_review import ConfirmedMechanism
from ntf_insight.domain.case import NTFCase


@dataclass(frozen=True, slots=True)
class PilotInspection:
    group: str
    priority: str
    representative_case_id: str
    case_id: str
    role: str
    similarity_to_representative: float
    shared_cpc3_with_representative: int
    independent_fin: bool
    note: str


@dataclass(frozen=True, slots=True)
class PilotGroup:
    group: str
    priority: str
    reason: str
    representative_case_id: str
    representative_confirmed: bool
    case_count: int
    distinct_fins: int
    cpc3_core_count: int
    weak_pair_count: int
    internal_pair_count: int
    bridge_neighbors: tuple[str, ...]
    independent_validation_candidates: int
    selected_comparison_cases: int


@dataclass(frozen=True, slots=True)
class ClusterPilotPlan:
    groups: tuple[PilotGroup, ...]
    inspections: tuple[PilotInspection, ...]
    representative_count: int
    independent_targets: int
    priority_one_groups: int
    cross_cluster_comparison_groups: int


def _independent_members(
    members: tuple[MLMember, ...],
    *,
    representative_case_id: str,
    vin_by_id: dict[str, str],
    confirmed_ids: set[str],
) -> list[MLMember]:
    """Select at most one independent unreviewed case per target VIN."""
    representative_vin = vin_by_id[representative_case_id]
    unique: dict[str, MLMember] = {}
    for member in sorted(
        members, key=lambda item: (-item.similarity_to_representative, item.case_id)
    ):
        if member.case_id == representative_case_id:
            continue
        if member.case_id in confirmed_ids:
            continue
        vehicle_id = vin_by_id[member.case_id]
        if vehicle_id == representative_vin:
            continue
        unique.setdefault(vehicle_id, member)
    return list(unique.values())


def prioritize_cluster_pilots(
    cases: list[NTFCase],
    result: MLClusterResult,
    audit: DiagnosticEvidenceAudit,
    *,
    confirmations: tuple[ConfirmedMechanism, ...] = (),
    bridges: ClusterBridgeReport | None = None,
) -> ClusterPilotPlan:
    """Rank transparent *examination opportunity*, not failure likelihood.

    One real medoid is always recommended per cluster. If independent,
    non-confirmed target vehicles are available, propose at most two:
    first, the strongest diagnosable target; second, a contrasting or
    boundary case. This cannot validate the whole cluster automatically.
    """
    case_by_id = {case.case_id: case for case in cases}
    if len(case_by_id) != len(cases) or result.case_count != len(cases):
        raise ValueError("QEC-Fallbestand ist für die Pilotprüfung nicht eindeutig.")
    eligible = set(result.eligible_case_ids)
    if not eligible.issubset(case_by_id):
        raise ValueError("Pilotprüfung enthält unbekannte ML-Fälle.")
    if audit.scoped_cases != len(cases) or (
        audit.dtc_source != result.dtc_source
        or audit.lookback_days != result.lookback_days
    ):
        raise ValueError("Pilotprüfung: Diagnoseaudit gehört zu einem anderen Szenario.")
    verified_ids = [entry.case_id for entry in confirmations]
    if len(verified_ids) != len(set(verified_ids)) or not set(verified_ids).issubset(
        case_by_id
    ):
        raise ValueError("Fachbestätigungen sind nicht eindeutig zugeordnet.")
    confirmed = set(verified_ids)
    if bridges is None:
        bridges = build_cluster_bridges(
            cases, result, audit, confirmations=confirmations,
        )
    bridge_map: dict[str, set[str]] = {}
    for link in bridges.links:
        bridge_map.setdefault(link.left, set()).add(link.right)
        bridge_map.setdefault(link.right, set()).add(link.left)

    vin_by_id = {cid: case.vin for cid, case in case_by_id.items()}
    groups: list[PilotGroup] = []
    inspections: list[PilotInspection] = []
    for cluster in result.clusters:
        name = f"H{cluster.cluster_id}"
        rep = cluster.representative_case_id
        if rep not in cluster.case_ids:
            raise ValueError("Cluster-Repräsentant ist kein Mitglied seines Clusters.")
        cpc3_core = sum(
            ecu.strip().upper() == "CPC3" for ecu, _ in cluster.common_faults
        )
        neighbors = tuple(sorted(
            bridge_map.get(name, set()),
            key=lambda g: int(g[1:]) if g.startswith("H") and g[1:].isdigit() else g,
        ))
        valid_targets = _independent_members(
            cluster.members,
            representative_case_id=rep,
            vin_by_id=vin_by_id,
            confirmed_ids=confirmed,
        )
        if cluster.weak_pair_count == 0 and cpc3_core >= 2:
            priority = "P1 – homogener CPC3-Pilot"
            reason = "Keine schwachen Gruppenpaare und mehrere CPC3-Kern-DTCs"
        elif neighbors and cpc3_core >= 2:
            priority = "P2 – clusterübergreifender CPC3-Vergleich"
            reason = "CPC3-Überlappungen zu unabhängigen HDBSCAN-Gruppen"
        elif cluster.weak_pair_count == 0:
            priority = "P3 – diagnostische Kontrollgruppe"
            reason = "Homogen ohne mehrere durchgehende CPC3-Kern-DTCs"
        else:
            priority = "P4 – explorativ, heterogen"
            reason = "Schwache Gruppenpaare; Ursache nicht gruppenweit übertragbar"

        # Pick strongest independent target for testing a provisional match.
        # Prefer evidence from CPC3 if an equally suitable target is available.
        def _cpc3_count(member: MLMember) -> int:
            return sum(
                ecu.strip().upper() == "CPC3" for ecu, _ in member.shared_faults
            )
        suitable = [
            member for member in valid_targets
            if member.similarity_to_representative >= 0.45
            and bool(member.shared_faults)
        ]
        preferred = sorted(
            suitable, key=lambda member: (
                -int(_cpc3_count(member) > 0),
                -member.similarity_to_representative,
                member.case_id,
            )
        )
        best = preferred[0] if preferred else None
        targets: list[tuple[str, MLMember]] = []
        if best is not None:
            targets.append(("Nächster unabhängiger Vergleichsfall", best))
        leftover = [
            member for member in valid_targets
            if member.case_id not in {entry.case_id for _, entry in targets}
        ]
        # A contrasting case is informative for estimating false transfers.
        if leftover:
            contrast = min(
                leftover,
                key=lambda member: (
                    member.similarity_to_representative,
                    _cpc3_count(member),
                    member.case_id,
                ),
            )
            targets.append(("Grenz-/Widerspruchsfall", contrast))
        if not targets and valid_targets:
            targets.append((
                "Schwacher Vergleichsfall – Ursachenprüfung getrennt",
                max(valid_targets, key=lambda member: (
                    member.similarity_to_representative, member.case_id,
                )),
            ))

        groups.append(PilotGroup(
            group=name, priority=priority, reason=reason,
            representative_case_id=rep,
            representative_confirmed=rep in confirmed,
            case_count=cluster.case_count,
            distinct_fins=cluster.vehicle_count,
            cpc3_core_count=cpc3_core,
            weak_pair_count=cluster.weak_pair_count,
            internal_pair_count=cluster.internal_pair_count,
            bridge_neighbors=neighbors,
            independent_validation_candidates=len(valid_targets),
            selected_comparison_cases=len(targets),
        ))
        inspections.append(PilotInspection(
            group=name, priority=priority, representative_case_id=rep,
            case_id=rep, role="Repräsentant – zuerst technisch unabhängig prüfen",
            similarity_to_representative=1.0,
            shared_cpc3_with_representative=cpc3_core,
            independent_fin=False,
            note=(
                "Unabhängig bestätigt; keine automatische Bestätigung anderer Fälle"
                if rep in confirmed
                else "Erst Labor-/technische Evidenz bestätigen; keine Ursachenzuweisung"
            ),
        ))
        for role, member in targets:
            note = (
                "Einzelfallvergleich; nur unabhängige technische Zielfallevidenz "
                "kann den Mechanismus bestätigen."
                if member.similarity_to_representative >= 0.45
                else "Diagnostisch unter 45 %: als Widerspruchs-/Grenzfall prüfen; "
                "keine Übertragung."
            )
            inspections.append(PilotInspection(
                group=name, priority=priority, representative_case_id=rep,
                case_id=member.case_id, role=role,
                similarity_to_representative=member.similarity_to_representative,
                shared_cpc3_with_representative=_cpc3_count(member),
                independent_fin=True,
                note=note,
            ))
    groups.sort(key=lambda row: (
        int(row.priority[1]) if row.priority[1].isdigit() else 9,
        -row.cpc3_core_count,
        row.weak_pair_count,
        row.group,
    ))
    sorted_inspections = [
        x for group in groups for x in inspections if x.group == group.group
    ]
    return ClusterPilotPlan(
        groups=tuple(groups), inspections=tuple(sorted_inspections),
        representative_count=len(groups),
        independent_targets=sum(row.selected_comparison_cases for row in groups),
        priority_one_groups=sum(row.priority.startswith("P1") for row in groups),
        cross_cluster_comparison_groups=sum(
            bool(row.bridge_neighbors) for row in groups
        ),
    )
