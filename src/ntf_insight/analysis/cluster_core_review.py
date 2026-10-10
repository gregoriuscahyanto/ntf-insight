"""Local, evidence-safe drill-down of strict Complete-Link pilot groups.

A strict group is linked to *actual shared case IDs* in the currently
displayed clustering, NEVER matched through its arbitrary group number.
All outputs include real QEC/FIN/evidence and MUST remain local.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from typing import TextIO

from ntf_insight.analysis.case_clustering import signature_for
from ntf_insight.analysis.cluster_workspace_engine import (
    UnifiedCluster, UnifiedClusterResult,
)
from ntf_insight.analysis.mechanism_review import safe_spreadsheet_cell
from ntf_insight.analysis.pilot_expert_validation import PILOT_REVIEW_FIELDS
from ntf_insight.analysis.qec_findings import qec_ssl_finding
from ntf_insight.domain.case import NTFCase


@dataclass(frozen=True, slots=True)
class CoreGroupLink:
    core: UnifiedCluster
    active_group_ids: tuple[int, ...]
    dominant_group_id: int | None
    dominant_overlap: int
    fully_contained: bool
    cross_vehicle: bool
    note: str

    @property
    def label(self) -> str:
        return f"K{self.core.cluster_id}"


def link_core_review_groups(
    active: UnifiedClusterResult,
    strict: UnifiedClusterResult,
) -> tuple[CoreGroupLink, ...]:
    """Relate strict groups to the active method by case IDs, not cluster IDs."""
    if strict.parameters.method != "complete_cosine":
        raise ValueError("Kernprüfgruppen müssen Complete-Link Cosinus verwenden.")
    if (
        active.eligible_case_ids != strict.eligible_case_ids
        or active.original_distances != strict.original_distances
        or active.parameters.dtc_source != strict.parameters.dtc_source
        or active.parameters.lookback_days != strict.parameters.lookback_days
        or active.parameters.common_dtc_cutoff != strict.parameters.common_dtc_cutoff
    ):
        raise ValueError(
            "Kernprüfgruppen und gewählte Methode verwenden nicht dieselbe "
            "Vor-Tausch-Diagnosebasis."
        )
    active_by_case = {
        cid: group.cluster_id
        for group in active.groups for cid in group.case_ids
    }
    links = []
    for group in strict.groups:
        overlap: dict[int, int] = {}
        for case_id in group.case_ids:
            cluster_id = active_by_case.get(case_id)
            if cluster_id is not None:
                overlap[cluster_id] = overlap.get(cluster_id, 0) + 1
        ordered = tuple(sorted(overlap))
        dominant = sorted(overlap, key=lambda cid: (-overlap[cid], cid))
        best = dominant[0] if dominant else None
        contained = (
            len(ordered) == 1 and overlap[ordered[0]] == group.case_count
        )
        if contained:
            note = f"Alle {group.case_count} Fälle in C{ordered[0]} enthalten"
        elif not ordered:
            note = "Kein Fall in einem Cluster der aktuellen Methode"
        elif len(ordered) > 1:
            note = (
                "Über mehrere Cluster verteilt: "
                + ", ".join(f"C{cid} ({overlap[cid]})" for cid in ordered)
            )
        else:
            note = (
                f"Nur {overlap[ordered[0]]}/{group.case_count} Fälle "
                f"in C{ordered[0]} enthalten"
            )
        if group.vehicle_count < 2:
            note += " · nur eine FIN; keine unabhängige Fahrzeugbestätigung"
        elif not group.common_faults:
            note += " · kein durchgängiger ECU:DTC-Kern"
        links.append(CoreGroupLink(
            core=group,
            active_group_ids=ordered,
            dominant_group_id=best,
            dominant_overlap=overlap[best] if best is not None else 0,
            fully_contained=contained,
            cross_vehicle=group.vehicle_count >= 2,
            note=note,
        ))
    return tuple(links)


def _independent_targets(
    group: UnifiedCluster,
    cases: dict[str, NTFCase],
) -> tuple[tuple[str, str], ...]:
    """Up to two independent FINs: nearest and contrastive target to medoid."""
    representative = cases[group.representative_case_id]
    eligible = [
        member for member in group.members
        if member.case_id != group.representative_case_id
        and cases[member.case_id].vin != representative.vin
    ]
    # Never count two QECs from one FIN as independently checked vehicles.
    nearest_by_fin = {}
    for member in sorted(
        eligible, key=lambda m: (-m.similarity, m.case_id),
    ):
        nearest_by_fin.setdefault(cases[member.case_id].vin, member)
    distinct = sorted(
        nearest_by_fin.values(), key=lambda m: (-m.similarity, m.case_id),
    )
    if not distinct:
        return ()
    nearest = distinct[0]
    if len(distinct) == 1:
        return ((nearest.case_id, "Unabhängiger Vergleichsfall"),)
    furthest = min(
        (m for m in distinct if m.case_id != nearest.case_id),
        key=lambda m: (m.similarity, m.case_id),
    )
    return (
        (nearest.case_id, "Ähnlichster unabhängiger Vergleich"),
        (furthest.case_id, "Kontrastierender unabhängiger Vergleich"),
    )


def write_core_review_template(
    output: TextIO,
    cases: list[NTFCase],
    strict: UnifiedClusterResult,
) -> None:
    """Write importer-compatible local CSV, initially ALL pending.

    No independent evidence or mechanism is invented or silently inferred.
    """
    if strict.parameters.method != "complete_cosine":
        raise ValueError("Nur Complete-Link Kernprüfgruppen exportieren.")
    by_id = {case.case_id: case for case in cases}
    if len(by_id) != len(cases):
        raise ValueError("Doppelte QEC-IDs im lokalen Datenbestand.")
    if not set(strict.eligible_case_ids).issubset(by_id):
        raise ValueError("Kernprüfgruppen enthalten unbekannte QEC-Fälle.")
    signatures = {
        cid: signature_for(
            by_id[cid], dtc_source=strict.parameters.dtc_source,
            lookback_days=strict.parameters.lookback_days,
        )
        for group in strict.groups for cid in group.case_ids
    }
    writer = csv.DictWriter(
        output, fieldnames=PILOT_REVIEW_FIELDS, delimiter=";",
        lineterminator="\n",
    )
    writer.writeheader()
    for group in strict.groups:
        rep = group.representative_case_id
        if rep not in by_id or rep not in group.case_ids:
            raise ValueError("Kernprüfgruppe ohne gültigen echten Repräsentanten.")
        targets = _independent_targets(group, by_id)
        if len({by_id[cid].vin for cid, _ in targets}) != len(targets):
            raise ValueError("Pilotziel-FINs sind nicht unabhängig.")
        roles = (
            (rep, "Repräsentant (Complete-Link)"),
            *targets,
        )
        members = {member.case_id: member for member in group.members}
        for cid, role in roles:
            case = by_id[cid]
            finding = qec_ssl_finding(case)
            shared = signatures[rep].faults & signatures[cid].faults
            item = members[cid]
            writer.writerow({
                "qec_case_id": safe_spreadsheet_cell(cid),
                "fin": safe_spreadsheet_cell(case.vin),
                "qec_ssl_end_finding": safe_spreadsheet_cell(
                    finding.text if finding is not None else ""
                ),
                "review_status": "pending",
                "mechanism_code": "",
                "reviewer": "",
                "evidence_ref": "",
                "confirmed_on": "",
                "pilot_priority": "",
                "pilot_group": f"K{group.cluster_id}",
                "pilot_role": safe_spreadsheet_cell(role),
                "representative_qec_id": safe_spreadsheet_cell(rep),
                "cosine_to_representative": f"{item.similarity:.4f}",
                "shared_cpc3_to_representative": sum(
                    ecu.upper() == "CPC3" for ecu, _ in shared
                ),
                "pilot_note": (
                    "Diagnosebasierte Prüfgruppe; mechanism_code erst mit "
                    "unabhängig bestätigter technischer Evidenz eintragen. "
                    "Nur lokale vertrauliche Fachprüfung."
                ),
            })
