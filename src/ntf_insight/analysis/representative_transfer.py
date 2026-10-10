"""Conservative representative-result transfer planning for HDBSCAN groups.

A reviewed medoid can seed testable hypotheses, NEVER confirmed root causes.
The observed cosines and DTC overlaps are uncalibrated; manual independent
evidence is mandatory before accepting a target result.
"""
from __future__ import annotations

from dataclasses import dataclass

from ntf_insight.analysis.hdbscan_clustering import MLClusterResult
from ntf_insight.analysis.mechanism_review import ConfirmedMechanism
from ntf_insight.domain.case import NTFCase


@dataclass(frozen=True, slots=True)
class RepresentativeTransfer:
    group: str
    representative_case_id: str
    target_case_id: str
    mechanism_hypothesis: str
    cosine: float
    shared_dtc_count: int
    status: str
    explanation: str


@dataclass(frozen=True, slots=True)
class RepresentativeTransferPlan:
    rows: tuple[RepresentativeTransfer, ...]
    representative_reviewed: int
    candidates: int
    withheld: int


def plan_representative_transfer(
    cases: list[NTFCase],
    result: MLClusterResult,
    confirmations: tuple[ConfirmedMechanism, ...],
) -> RepresentativeTransferPlan:
    """Offer *review-only* transfer of the confirmed medoid mechanism.

    Even high diagnostic similarity never confirms an unreviewed target.
    A conflicting confirmed target is blocked, not overwritten. Weak
    links are held for independent investigation. No source is mutated.
    """
    by_id = {case.case_id: case for case in cases}
    labels = {item.case_id: item for item in confirmations}
    if len(by_id) != len(cases) or len(labels) != len(confirmations):
        raise ValueError("QEC-ID für Befundübertragungsprüfung nicht eindeutig.")
    if not set(labels).issubset(by_id):
        raise ValueError("Bestätigter Fall nicht im aktuellen Bestand.")
    if not set(result.eligible_case_ids).issubset(by_id):
        raise ValueError("Clusterbestand stimmt nicht mit QEC-Fällen überein.")
    rows = []
    reviewed = candidates = withheld = 0
    for cluster in result.clusters:
        representative = cluster.representative_case_id
        finding = labels.get(representative)
        if finding:
            reviewed += 1
        for member in cluster.members:
            if member.case_id == representative:
                continue
            target = by_id[member.case_id]
            existing = labels.get(member.case_id)
            cosine = member.similarity_to_representative
            shared = len(member.shared_faults)
            if finding is None:
                status = "Repräsentant noch nicht fachlich bestätigt"
                explanation = "Zuerst Medoid prüfen: unabhängige Evidenz erforderlich."
            elif target.vin == by_id[representative].vin:
                status = "Gleiche FIN – keine unabhängige Bestätigung"
                explanation = "Weitere Fälle derselben FIN sind kein externer Ursachenbeleg."
            elif existing and existing.mechanism_code != finding.mechanism_code:
                status = "Widerspruch – Übertragung gesperrt"
                explanation = "Ziel besitzt anderen unabhängig bestätigten Mechanismus."
            elif existing:
                status = "Bereits unabhängig bestätigt"
                explanation = "Mechanismus am Ziel bereits bestätigt; keine Übertragung nötig."
            elif shared > 0 and cosine >= 0.45:
                # A mixed cluster does not invalidate a strong *individual*
                # comparison to its medoid, but it requires a stronger warning.
                # This is NOT a calibrated same-cause probability.
                if cluster.screening_status == (
                    "Diagnostischer Prüfkandidat – Ursache unbestätigt"
                ):
                    status = "Prüfhypothese – keine automatische Übertragung"
                    explanation = (
                        "Diagnostische Übereinstimmung mit dem Medoid; Ursache "
                        "des Zielfalls unabhängig nachzuweisen."
                    )
                else:
                    status = "Prüfhypothese mit Clusterwarnung – besonders prüfen"
                    explanation = (
                        "Individuell ähnlich zum Medoid, aber die Gesamtgruppe "
                        "ist uneinheitlich. Keine gruppenweite Ursachenzuweisung; "
                        "technische Unterschiede zuerst ausschließen."
                    )
                candidates += 1
            else:
                status = "Zurückgestellt – unzureichende Cluster-Evidenz"
                explanation = (
                    "Keine ausreichende individuelle Ähnlichkeit zum Medoid "
                    "oder kein gemeinsamer ECU:DTC. Keine Ursache zuweisen."
                )
            if not status.startswith("Prüfhypothese"):
                withheld += 1
            rows.append(RepresentativeTransfer(
                group=f"H{cluster.cluster_id}",
                representative_case_id=representative,
                target_case_id=member.case_id,
                mechanism_hypothesis=(
                    finding.mechanism_code if finding is not None else ""
                ),
                cosine=cosine, shared_dtc_count=shared,
                status=status, explanation=explanation,
            ))
    return RepresentativeTransferPlan(
        rows=tuple(rows), representative_reviewed=reviewed,
        candidates=candidates, withheld=withheld,
    )
