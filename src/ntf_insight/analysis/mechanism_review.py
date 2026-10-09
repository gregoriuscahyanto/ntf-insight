"""Independent, explicitly expert-confirmed *failure mechanism* reviews.

This is deliberately distinct from broad existing RootCauseCategory feedback.
QEC SSL free text is display-only: it must NEVER auto-create a training label.
The review CSV is local; it may contain sensitive QEC/FIN/evidence identifiers.
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from datetime import date
from itertools import combinations
from typing import TextIO

from ntf_insight.analysis.hdbscan_clustering import MLClusterResult
from ntf_insight.domain.case import NTFCase


# Generic conclusions are not independent *mechanism* confirmation.
NON_CAUSES = frozenset({
    "UNKNOWN", "NTF", "NO_TROUBLE_FOUND", "UNBEKANNT", "UNGEKLAERT",
    "ELEKTRISCHER_FEHLER", "ELECTRICAL_FAULT", "GENERAL", "NONE",
    "PENDING", "OPEN", "KEINE_URSACHE", "NOT_CONFIRMED",
})
REVIEW_FIELDS = (
    "qec_case_id", "fin", "qec_ssl_end_finding",
    "review_status", "mechanism_code", "reviewer",
    "evidence_ref", "confirmed_on",
)


def safe_spreadsheet_cell(value: str) -> str:
    """Avoid CSV formula injection when opening untrusted QEC text in Excel.

    A leading apostrophe is a representation-only escape in the LOCAL
    review/export CSV. Source evidence stored in DuckDB stays untouched.
    """
    if value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + value
    return value


@dataclass(frozen=True, slots=True)
class ConfirmedMechanism:
    case_id: str
    mechanism_code: str
    reviewer: str
    evidence_ref: str
    confirmed_on: date


@dataclass(frozen=True, slots=True)
class MechanismClusterAudit:
    cluster_id: int
    case_count: int
    confirmed_cases: int
    independently_confirmed_vehicles: int
    same_mechanism_pairs: int
    different_mechanism_pairs: int
    labeled_pair_agreement: float | None
    review_note: str


@dataclass(frozen=True, slots=True)
class MechanismReviewResult:
    reviewed_case_count: int
    total_case_count: int
    clustered_reviewed_count: int
    evaluated_cross_fin_pairs: int
    agreeing_cross_fin_pairs: int
    contradicting_cross_fin_pairs: int
    audits: tuple[MechanismClusterAudit, ...]

    @property
    def observed_pair_agreement(self) -> float | None:
        if not self.evaluated_cross_fin_pairs:
            return None
        return self.agreeing_cross_fin_pairs / self.evaluated_cross_fin_pairs


def read_confirmed_mechanisms(
    source: TextIO,
    cases: list[NTFCase],
) -> tuple[ConfirmedMechanism, ...]:
    """Import explicit reviewer decisions; never mine or classify SSL text.

    Blank and unknown review rows are allowed and NOT converted to labels.
    For an accepted label all confirmations (mechanism, evidence, reviewer,
    date) must be present. Duplicate QEC IDs are rejected instead of
    silently overwriting earlier manual decisions.
    """
    available = {case.case_id for case in cases}
    if len(available) != len(cases):
        raise ValueError("QEC-Fall-IDs im Bestand nicht eindeutig.")
    reader = csv.DictReader(source, delimiter=";")
    if reader.fieldnames is None:
        raise ValueError("Die Prüfdatei hat keinen CSV-Header.")
    reader.fieldnames = [
        name.strip().lstrip("\ufeff") for name in reader.fieldnames
    ]
    fields = set(reader.fieldnames)
    required = {
        "qec_case_id", "review_status", "mechanism_code", "reviewer",
        "evidence_ref", "confirmed_on",
    }
    if not required.issubset(fields):
        raise ValueError(
            "Prüfdatei ohne erforderliche Spalten: "
            + ", ".join(sorted(required - fields))
        )
    found: set[str] = set()
    confirmed = []
    for line, row in enumerate(reader, 2):
        if None in row:  # excess unquoted semicolon fields
            raise ValueError(f"Zeile {line}: beschädigte CSV-Spalten.")
        case_id = (row.get("qec_case_id") or "").strip()
        if not case_id:
            raise ValueError(f"Zeile {line}: QEC-ID fehlt.")
        if case_id not in available:
            raise ValueError(
                f"Zeile {line}: QEC-ID ist im aktuellen Fallbestand nicht bekannt."
            )
        if case_id in found:
            raise ValueError(f"Zeile {line}: QEC-ID ist mehrfach vorhanden.")
        found.add(case_id)
        status = (row.get("review_status") or "").strip().casefold()
        if status in {"", "pending", "unknown"}:
            continue
        if status != "confirmed":
            raise ValueError(
                f"Zeile {line}: review_status nur confirmed, pending oder unknown."
            )
        code = (row.get("mechanism_code") or "").strip().upper()
        if code in NON_CAUSES or not re.fullmatch(r"[A-Z][A-Z0-9_.-]{2,63}", code):
            raise ValueError(
                f"Zeile {line}: nur unabhängig bestätigten spezifischen "
                "Fehlermechanismus-Code verwenden, nicht NTF/UNKNOWN."
            )
        reviewer = (row.get("reviewer") or "").strip()
        evidence = (row.get("evidence_ref") or "").strip()
        date_str = (row.get("confirmed_on") or "").strip()
        if not reviewer or not evidence or not date_str:
            raise ValueError(
                f"Zeile {line}: Prüfer, Befund-Evidenz und Bestätigungsdatum "
                "sind für bestätigte Ursachen zwingend."
            )
        try:
            confirmed_date = date.fromisoformat(date_str)
        except ValueError as exc:
            raise ValueError(
                f"Zeile {line}: confirmed_on muss YYYY-MM-DD sein."
            ) from exc
        confirmed.append(ConfirmedMechanism(
            case_id=case_id,
            mechanism_code=code,
            reviewer=reviewer,
            evidence_ref=evidence,
            confirmed_on=confirmed_date,
        ))
    return tuple(sorted(confirmed, key=lambda label: label.case_id))


def write_review_template(
    output: TextIO, cases: list[NTFCase],
) -> None:
    """Explicitly pending template; SSL text cannot become implicit truth."""
    from ntf_insight.analysis.qec_findings import qec_ssl_finding

    writer = csv.DictWriter(output, fieldnames=REVIEW_FIELDS, delimiter=";")
    writer.writeheader()
    for case in sorted(cases, key=lambda item: item.case_id):
        finding = qec_ssl_finding(case)
        writer.writerow({
            "qec_case_id": case.case_id,
            "fin": case.vin,
            "qec_ssl_end_finding": (
                safe_spreadsheet_cell(finding.text) if finding else ""
            ),
            "review_status": "pending",
            "mechanism_code": "",
            "reviewer": "",
            "evidence_ref": "",
            "confirmed_on": "",
        })


def review_cluster_mechanisms(
    cases: list[NTFCase],
    result: MLClusterResult,
    confirmations: tuple[ConfirmedMechanism, ...],
) -> MechanismReviewResult:
    """Measure *observed* label consistency on independent FINs only.

    Agreement among a small, reviewed subset is NOT the precision of an
    unreviewed group and NOT a formal external validation. Labels never
    influence HDBSCAN vectors, medoids or assignments.
    """
    by_id = {case.case_id: case for case in cases}
    if len(by_id) != len(cases):
        raise ValueError("QEC-Fall-IDs müssen eindeutig sein.")
    labels = {review.case_id: review for review in confirmations}
    if len(labels) != len(confirmations):
        raise ValueError("Eine QEC-ID mehrfach bestätigt.")
    if not set(labels).issubset(by_id):
        raise ValueError("Bestätigung für QEC-Fall außerhalb der geladenen Datenbasis.")
    if not set(result.eligible_case_ids).issubset(by_id):
        raise ValueError("HDBSCAN-Ergebnis passt nicht zum aktuellen Fallbestand.")
    rows = []
    total_same = total_different = 0
    grouped_labeled: set[str] = set()
    for cluster in result.clusters:
        reviewed = [cid for cid in cluster.case_ids if cid in labels]
        grouped_labeled.update(reviewed)
        vehicles = {by_id[cid].vin for cid in reviewed}
        same = different = 0
        for first, second in combinations(reviewed, 2):
            if by_id[first].vin == by_id[second].vin:
                continue
            if labels[first].mechanism_code == labels[second].mechanism_code:
                same += 1
            else:
                different += 1
        total_same += same
        total_different += different
        if different:
            note = (
                f"{different} geprüfte Fallpaare mit UNTERSCHIEDLICHEM "
                "Fehlermechanismus. Keine Ergebnisübertragung."
            )
        elif same >= 1:
            note = (
                "Nur innerhalb der fachlich bestätigten Teilmenge "
                "gleicher Mechanismus; übrige Fälle ungeprüft."
            )
        else:
            note = (
                "Keine unabhängigen FIN-Fallpaare mit bestätigten Mechanismen; "
                "fachlich nicht validiert."
            )
        rows.append(MechanismClusterAudit(
            cluster_id=cluster.cluster_id,
            case_count=cluster.case_count,
            confirmed_cases=len(reviewed),
            independently_confirmed_vehicles=len(vehicles),
            same_mechanism_pairs=same,
            different_mechanism_pairs=different,
            labeled_pair_agreement=(
                same / (same + different) if (same + different) else None
            ),
            review_note=note,
        ))
    return MechanismReviewResult(
        reviewed_case_count=len(confirmations),
        total_case_count=len(cases),
        clustered_reviewed_count=len(grouped_labeled),
        evaluated_cross_fin_pairs=total_same + total_different,
        agreeing_cross_fin_pairs=total_same,
        contradicting_cross_fin_pairs=total_different,
        audits=tuple(rows),
    )
