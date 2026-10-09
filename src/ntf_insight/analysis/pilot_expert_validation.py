"""Audit one expert-reviewed medoid against independently reviewed target FINs.

The reviewer must attest independent technical evidence. A different evidence
reference is a *screening check*, not cryptographic proof of independence.
No cause labels, QEC records, or HDBSCAN memberships are modified.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from typing import TextIO

from ntf_insight.analysis.cluster_pilot_priority import ClusterPilotPlan
from ntf_insight.analysis.hdbscan_clustering import MLClusterResult
from ntf_insight.analysis.mechanism_review import (
    REVIEW_FIELDS, ConfirmedMechanism, safe_spreadsheet_cell,
)
from ntf_insight.analysis.qec_findings import qec_ssl_finding
from ntf_insight.domain.case import NTFCase


PILOT_REVIEW_FIELDS = REVIEW_FIELDS + (
    "pilot_priority",
    "pilot_group",
    "pilot_role",
    "representative_qec_id",
    "cosine_to_representative",
    "shared_cpc3_to_representative",
    "pilot_note",
)


@dataclass(frozen=True, slots=True)
class PilotValidationTarget:
    group: str
    representative_case_id: str
    target_case_id: str
    representative_mechanism: str
    target_mechanism: str
    similarity_to_representative: float
    screened_45: bool
    same_fin: bool
    status: str
    note: str


@dataclass(frozen=True, slots=True)
class PilotValidationGroup:
    group: str
    representative_case_id: str
    representative_confirmed: bool
    members: int
    independently_reviewed_target_fins: int
    concordant_target_fins: int
    discordant_target_fins: int
    screened_agree: int
    screened_disagree: int
    outside_screen_agree: int
    outside_screen_disagree: int
    same_fin_excluded: int
    shared_evidence_excluded: int
    repeated_fin_excluded: int
    open_target_fins: int
    status: str


@dataclass(frozen=True, slots=True)
class PilotExpertValidationReport:
    groups: tuple[PilotValidationGroup, ...]
    targets: tuple[PilotValidationTarget, ...]
    reviewed_representatives: int
    comparable_target_fins: int
    concordant_target_fins: int
    discordant_target_fins: int
    groups_with_conflict: int


def merge_confirmed_mechanisms(
    existing: tuple[ConfirmedMechanism, ...],
    imported: tuple[ConfirmedMechanism, ...],
) -> tuple[ConfirmedMechanism, ...]:
    """Add independent labels without silently deleting/overwriting older ones.

    An incompatible same-case result is a manual adjudication task. This
    preserves previously loaded cases when only a pilot SUBSET is imported.
    """
    result: dict[str, ConfirmedMechanism] = {}
    for label in (*existing, *imported):
        previous = result.get(label.case_id)
        if previous is not None and previous != label:
            raise ValueError(
                "Widersprechende Fachbestätigung für QEC-Fall. "
                "Vorherige Evidenz bleibt erhalten; manuell prüfen."
            )
        result[label.case_id] = label
    if len({label.case_id for label in existing}) != len(existing) or len(
        {label.case_id for label in imported}
    ) != len(imported):
        raise ValueError("QEC-Fachlabel mehrfach in derselben Prüfdatei.")
    return tuple(sorted(result.values(), key=lambda entry: entry.case_id))


def write_pilot_review_template(
    output: TextIO,
    cases: list[NTFCase],
    plan: ClusterPilotPlan,
    *,
    confirmations: tuple[ConfirmedMechanism, ...] = (),
) -> None:
    """Local-only CSV ready for the existing read_confirmed_mechanisms importer.

    Exactly the prioritized medoids and up to two comparison cases per group.
    Already confirmed labels are carried forward with their evidence, not
    overwritten by an unreviewed SSL text or a transferred medoid hypothesis.
    """
    by_case = {case.case_id: case for case in cases}
    labels = {label.case_id: label for label in confirmations}
    if len(by_case) != len(cases) or len(labels) != len(confirmations):
        raise ValueError("Doppelte QEC-ID in der Pilotfachprüfung.")
    if not set(labels).issubset(by_case):
        raise ValueError("Fachlabel stammt nicht aus dem gewählten QEC-Bestand.")
    if not plan.inspections and plan.representative_count:
        raise ValueError("Pilotplan ohne Prüffälle.")
    expected = {item.case_id for item in plan.inspections}
    if not expected.issubset(by_case) or len(expected) != len(plan.inspections):
        raise ValueError("Pilotprüfliste enthält unbekannte oder doppelte QEC-Fälle.")
    if sum("Repräsentant" in item.role for item in plan.inspections) != (
        plan.representative_count
    ):
        raise ValueError("Pilotplan hat nicht genau einen Repräsentanten je Cluster.")
    writer = csv.DictWriter(
        output, fieldnames=PILOT_REVIEW_FIELDS,
        delimiter=";", lineterminator="\n",
    )
    writer.writeheader()
    for item in plan.inspections:
        case = by_case[item.case_id]
        source_finding = qec_ssl_finding(case)
        current = labels.get(item.case_id)
        writer.writerow({
            "qec_case_id": safe_spreadsheet_cell(case.case_id),
            "fin": safe_spreadsheet_cell(case.vin),
            "qec_ssl_end_finding": safe_spreadsheet_cell(
                source_finding.text if source_finding else ""
            ),
            "review_status": "confirmed" if current else "pending",
            "mechanism_code": safe_spreadsheet_cell(
                current.mechanism_code if current else ""
            ),
            "reviewer": safe_spreadsheet_cell(current.reviewer if current else ""),
            "evidence_ref": safe_spreadsheet_cell(
                current.evidence_ref if current else ""
            ),
            "confirmed_on": current.confirmed_on.isoformat() if current else "",
            "pilot_priority": safe_spreadsheet_cell(item.priority),
            "pilot_group": item.group,
            "pilot_role": item.role,
            "representative_qec_id": safe_spreadsheet_cell(
                item.representative_case_id
            ),
            "cosine_to_representative": f"{item.similarity_to_representative:.4f}",
            "shared_cpc3_to_representative": item.shared_cpc3_with_representative,
            "pilot_note": safe_spreadsheet_cell(item.note),
        })


def validate_pilot_evidence(
    cases: list[NTFCase],
    result: MLClusterResult,
    confirmations: tuple[ConfirmedMechanism, ...],
) -> PilotExpertValidationReport:
    """Count validated rep-to-target FIN pairs, excluding weak provenance.

    - A verified target on the same FIN as the medoid is NOT independent.
    - Multiple confirmed QECs on one target FIN require adjudication.
    - Reused evidence_ref (including the medoid's) cannot establish a
      separate independent source in this conservative pilot report.
    - A verified contradiction blocks any cluster-wide transfer hypothesis.
    - No % is reported: selectively sampled expert evidence is not an
      unbiased estimate of all remaining cluster cases.
    """
    by_case = {case.case_id: case for case in cases}
    labels = {label.case_id: label for label in confirmations}
    if len(by_case) != len(cases) or result.case_count != len(cases):
        raise ValueError("Pilotfachvalidierung: QEC-Bestand passt nicht zur ML-Analyse.")
    if len(labels) != len(confirmations) or not set(labels).issubset(by_case):
        raise ValueError("Pilotfachvalidierung: unbekannte/mehrfache Fachbestätigungen.")
    if not set(result.eligible_case_ids).issubset(by_case):
        raise ValueError("ML-Eingaben enthalten unbekannte Fälle.")
    group_rows: list[PilotValidationGroup] = []
    target_rows: list[PilotValidationTarget] = []
    for cluster in result.clusters:
        group_name = f"H{cluster.cluster_id}"
        rep = cluster.representative_case_id
        if rep not in cluster.case_ids:
            raise ValueError("Repräsentant gehört nicht zur HDBSCAN-Gruppe.")
        rep_label = labels.get(rep)
        rep_vin = by_case[rep].vin
        members = tuple(member for member in cluster.members if member.case_id != rep)
        # All confirmed targets with the same FIN share one evidence group.
        by_fin: dict[str, list[str]] = {}
        ref_to_fins: dict[str, set[str]] = {}
        for member in members:
            label = labels.get(member.case_id)
            vin = by_case[member.case_id].vin
            if label is None or vin == rep_vin:
                continue
            by_fin.setdefault(vin, []).append(member.case_id)
        for vin, case_ids in by_fin.items():
            # Reusing one evidence_ref across distinct QECs/FINS is not
            # evidence of multiple independent validations.
            if len(case_ids) == 1:
                ref = labels[case_ids[0]].evidence_ref
                ref_to_fins.setdefault(ref, set()).add(vin)
        same_fin = shared_evidence = repeated_fin = 0
        concordant = discordant = screened_agree = screened_disagree = 0
        outside_agree = outside_disagree = 0
        for member in members:
            cid = member.case_id
            target_label = labels.get(cid)
            target_vin = by_case[cid].vin
            screen = (
                member.similarity_to_representative >= 0.45
                and bool(member.shared_faults)
            )
            if target_vin == rep_vin:
                status = "Gleiche FIN – nicht unabhängig"
                note = "Ein erneuter QEC-Vorgang derselben FIN validiert den Medoid nicht."
                same_fin += int(target_label is not None)
            elif target_label is None:
                status = "Ziel-FIN fachlich noch nicht bestätigt"
                note = "Unabhängige technische Prüfung dieses Fahrzeugs fehlt."
            elif rep_label is None:
                status = "Repräsentant fachlich noch nicht bestätigt"
                note = "Zielmechanismus kann ohne bestätigten Repräsentanten nicht verglichen werden."
            elif len(by_fin.get(target_vin, ())) > 1:
                status = "Mehrere bestätigte QECs derselben FIN – prüfen"
                note = "Eine Fahrzeug-FIN darf nicht mehrfach als unabhängige Bestätigung zählen."
                repeated_fin += 1
            elif (
                target_label.evidence_ref == rep_label.evidence_ref
                or len(ref_to_fins.get(target_label.evidence_ref, set())) > 1
            ):
                status = "Evidenzreferenz mehrfach verwendet – prüfen"
                note = "Eigenständiger technischer Beleg für diese FIN nicht gesichert."
                shared_evidence += 1
            elif target_label.mechanism_code == rep_label.mechanism_code:
                status = "Getrennte Evidenz: Mechanismus übereinstimmend"
                note = "Beobachtung nur am geprüften Zielfall; übrige Clusterfälle ungeprüft."
                concordant += 1
                if screen:
                    screened_agree += 1
                else:
                    outside_agree += 1
            else:
                status = "Widerspruch: anderer bestätigter Mechanismus"
                note = "Befundübertragung im Cluster sperren; Ursache unabhängig klären."
                discordant += 1
                if screen:
                    screened_disagree += 1
                else:
                    outside_disagree += 1
            target_rows.append(PilotValidationTarget(
                group=group_name,
                representative_case_id=rep,
                target_case_id=cid,
                representative_mechanism=rep_label.mechanism_code if rep_label else "",
                target_mechanism=target_label.mechanism_code if target_label else "",
                similarity_to_representative=member.similarity_to_representative,
                screened_45=screen,
                same_fin=target_vin == rep_vin,
                status=status,
                note=note,
            ))
        if not rep_label:
            state = "Repräsentant noch nicht bestätigt – keine Validierung"
        elif discordant:
            state = "Widerspruch – weitere Ursachenübertragung gesperrt"
        elif concordant:
            state = (
                "Übereinstimmung nur in der geprüften Teilmenge – "
                "keine automatische Übertragung"
            )
        else:
            state = "Repräsentant bestätigt; unabhängige Zielprüfung ausstehend"
        confirmed_fin_count = concordant + discordant
        target_fins = {
            by_case[member.case_id].vin
            for member in members if by_case[member.case_id].vin != rep_vin
        }
        group_rows.append(PilotValidationGroup(
            group=group_name, representative_case_id=rep,
            representative_confirmed=rep_label is not None,
            members=len(cluster.members),
            independently_reviewed_target_fins=confirmed_fin_count,
            concordant_target_fins=concordant,
            discordant_target_fins=discordant,
            screened_agree=screened_agree,
            screened_disagree=screened_disagree,
            outside_screen_agree=outside_agree,
            outside_screen_disagree=outside_disagree,
            same_fin_excluded=same_fin,
            shared_evidence_excluded=shared_evidence,
            repeated_fin_excluded=repeated_fin,
            open_target_fins=len(target_fins) - confirmed_fin_count,
            status=state,
        ))
    return PilotExpertValidationReport(
        groups=tuple(group_rows), targets=tuple(target_rows),
        reviewed_representatives=sum(row.representative_confirmed for row in group_rows),
        comparable_target_fins=sum(
            row.independently_reviewed_target_fins for row in group_rows
        ),
        concordant_target_fins=sum(row.concordant_target_fins for row in group_rows),
        discordant_target_fins=sum(row.discordant_target_fins for row in group_rows),
        groups_with_conflict=sum(bool(row.discordant_target_fins) for row in group_rows),
    )
