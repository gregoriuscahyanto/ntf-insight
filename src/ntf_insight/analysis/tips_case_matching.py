"""Human-reviewed TIPS-to-QEC episode links with immutable source provenance.

FIN equality is necessary but *never* sufficient proof of the same episode.
The existing deterministic 365-day pre / 180-day post window is preserved.
Ambiguous candidates are displayed for explicit review, not auto-linked.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import NAMESPACE_URL, uuid5

from ntf_insight.domain.case import NTFCase
from ntf_insight.domain.events import TipsCaseObservation
from ntf_insight.ingestion.real_source_parsers import (
    _date_event,
    canonical_fin,
)
from ntf_insight.storage.duckdb_store import DuckDBStore
from ntf_insight.storage.source_knowledge_store import SourceKnowledgeStore


@dataclass(frozen=True, slots=True)
class TipsLinkCandidate:
    source_sha256: str
    source_location: str
    tips_case_id: str
    fin: str
    creation_date: str
    qec_case_id: str | None
    delta_days: float | None
    status: str
    reason: str
    can_confirm: bool

    @property
    def key(self) -> tuple[str, str, str | None]:
        return self.source_sha256, self.source_location, self.qec_case_id


def _raw_tip_rows(knowledge: SourceKnowledgeStore) -> list[dict]:
    rows = []
    offset = 0
    while True:
        portion = knowledge.list_rows(
            category="autoexport_tips", limit=1000, offset=offset
        )
        if not portion:
            break
        rows.extend(portion)
        offset += len(portion)
        if len(portion) < 1000:
            break
    return rows


def suggest_tips_links(
    cases: list[NTFCase], knowledge: SourceKnowledgeStore,
) -> tuple[TipsLinkCandidate, ...]:
    """One row per possible (TIPS, QEC) link; never change case evidence."""
    by_fin: dict[str, list[NTFCase]] = {}
    existing: dict[tuple[str, str, str], str] = {}
    for case in cases:
        by_fin.setdefault(case.vin, []).append(case)
        for linked in case.tips_observations:
            if linked.tips_case_id:
                existing[(
                    case.vin, linked.tips_case_id.strip(),
                    linked.occurred_at.date().isoformat(),
                )] = case.case_id
    suggestions: list[TipsLinkCandidate] = []
    seen: set[tuple[str, str, str]] = set()
    for row in _raw_tip_rows(knowledge):
        data = row["data"]
        fin = canonical_fin(row["fin"] or data.get("Fin"))
        ref = str(data.get("CaseId") or row["reference"] or "").strip()
        created = _date_event(data.get("CreationDate"))
        if not fin or not ref or not created:
            continue
        event_date = created["occurred_at"]
        date_label = event_date.date().isoformat()
        # Source files can be re-exported; repeating a TIPS CaseId on the
        # same FIN/day does not create more opportunities to attach it.
        key = fin, ref, date_label
        if key in seen:
            continue
        seen.add(key)
        already = existing.get(key)
        local = sorted(by_fin.get(fin, ()), key=lambda case: case.case_id)
        if not local:
            suggestions.append(TipsLinkCandidate(
                row["source_sha256"], row["source_location"], ref, fin,
                date_label, None, None,
                "Ohne QEC-Fall", "Gleiche FIN in keiner QEC-Referenz", False,
            ))
            continue
        for case in local:
            swap = case.investigated_replacement()
            days = (
                (event_date - swap.occurred_at).total_seconds() / 86400
                if swap is not None else None
            )
            in_window = days is not None and -365 <= days <= 180
            matched = already == case.case_id
            status = (
                "Bereits verknüpft" if matched
                else "Anderem QEC-Fall zugeordnet" if already
                else "Prüfbar (mehrere QEC-Fälle)" if len(local) > 1 and in_window
                else "Prüfbar (FIN + Zeit)" if in_window
                else "Tauschanker fehlt" if days is None
                else "Außerhalb Zuordnungsfenster"
            )
            reason = (
                "Manuelle Zuordnung erfordert VIN-, Ereignis- und "
                "Reparaturabgleich; eine FIN allein bestätigt keine Ursache."
            )
            suggestions.append(TipsLinkCandidate(
                row["source_sha256"], row["source_location"], ref, fin,
                date_label, case.case_id, round(days, 2) if days is not None else None,
                status, reason, bool(in_window and not already),
            ))
    return tuple(sorted(
        suggestions,
        key=lambda item: (
            not item.can_confirm, item.status != "Bereits verknüpft",
            item.fin, item.tips_case_id, item.qec_case_id or "",
        ),
    ))


def confirm_tips_link(
    store: DuckDBStore,
    candidate: TipsLinkCandidate,
) -> NTFCase:
    """Persist an explicitly reviewed exact source row and its case link.

    Both writes occur in one transaction; links cannot be reassigned silently.
    No supplier finding, work result or later action changes similarity.
    """
    if not candidate.can_confirm or not candidate.qec_case_id:
        raise ValueError("Kein manuell überprüfbarer TIPS-/QEC-Kandidat.")
    with store.connect() as con:
        con.execute("BEGIN TRANSACTION")
        try:
            row = con.execute(
                """
                SELECT payload_json FROM source_knowledge_rows
                WHERE source_sha256 = ? AND source_location = ?
                  AND category = 'autoexport_tips'
                """,
                [candidate.source_sha256, candidate.source_location],
            ).fetchone()
            if row is None:
                raise ValueError("Die ursprüngliche TIPS-Quellenzeile fehlt.")
            import json

            data = json.loads(row[0])
            fin = canonical_fin(data.get("Fin"))
            case_row = con.execute(
                "SELECT payload_json FROM case_snapshots WHERE case_id = ?",
                [candidate.qec_case_id],
            ).fetchone()
            if case_row is None:
                raise ValueError("Der ausgewählte QEC-Fall fehlt.")
            case = NTFCase.model_validate_json(case_row[0])
            date_fields = _date_event(data.get("CreationDate"))
            if not date_fields or fin != case.vin or fin != candidate.fin:
                raise ValueError("FIN oder Erstellungsdatum widersprechen der Quelle.")
            event_date = date_fields["occurred_at"]
            swap = case.investigated_replacement()
            if swap is None or not (
                -365 <= (event_date - swap.occurred_at).total_seconds() / 86400 <= 180
            ):
                raise ValueError("TIPS-Meldung liegt außerhalb des Tauschfensters.")
            tips_id = str(data.get("CaseId") or "").strip()
            if tips_id != candidate.tips_case_id:
                raise ValueError("TIPS-Referenz stimmt nicht mehr mit der Quelle überein.")
            # A real TIPS episode cannot be linked to two QEC cases by repeated
            # imports or by concurrent/manual confirmations.
            all_rows = con.execute(
                "SELECT payload_json FROM case_snapshots WHERE vin = ?",
                [fin],
            ).fetchall()
            for (payload,) in all_rows:
                other = NTFCase.model_validate_json(payload)
                if any(
                    obs.tips_case_id == tips_id
                    and obs.occurred_at.date() == event_date.date()
                    for obs in other.tips_observations
                ):
                    raise ValueError("Dieser TIPS-Vorgang ist bereits einem Fall zugeordnet.")

            token = uuid5(
                NAMESPACE_URL,
                f"ntf-insight:manually-linked-tips:{candidate.source_sha256}:"
                f"{candidate.source_location}",
            ).hex
            new_observation = TipsCaseObservation(
                event_id=token, vin=fin, tips_case_id=tips_id,
                complaint=str(
                    data.get("InitialWorkshopMessageCustomerComplaint") or ""
                ) or None,
                workshop_findings=str(
                    data.get("InitialWorkshopMessageWorkshopFindings") or ""
                ) or None,
                performed_actions=str(
                    data.get("InitialWorkshopMessagePerformedActions") or ""
                ) or None,
                symptom=str(
                    data.get("SymptomName") or data.get("SymptomLevel3Name") or ""
                ) or None,
                source_ref=f"raw:{candidate.source_sha256}#{candidate.source_location}",
                manually_confirmed=True,
                **date_fields,
            )
            case.tips_observations.append(new_observation)
            con.execute(
                """
                UPDATE case_snapshots SET payload_json = ?
                WHERE case_id = ? AND vin = ?
                """,
                [case.model_dump_json(), case.case_id, fin],
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS manual_tips_links (
                    source_sha256 VARCHAR NOT NULL,
                    source_location VARCHAR NOT NULL,
                    case_id VARCHAR NOT NULL,
                    fin VARCHAR NOT NULL,
                    tips_case_id VARCHAR NOT NULL,
                    linked_at TIMESTAMP NOT NULL,
                    PRIMARY KEY (source_sha256, source_location)
                )
                """
            )
            con.execute(
                """
                INSERT INTO manual_tips_links
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                [
                    candidate.source_sha256, candidate.source_location,
                    case.case_id, fin, tips_id,
                ],
            )
            con.execute("COMMIT")
            return case
        except Exception:
            con.execute("ROLLBACK")
            raise
