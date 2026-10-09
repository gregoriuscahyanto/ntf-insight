"""Evidence-aware comparison of QEC swap anchors and AutoExport repair dates.

A matching workshop repair is a *candidate* for the physical swap, not proof
that the reported QEC date is wrong. The QEC replacement anchor used by the
recurrence rules must never be changed automatically.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from ntf_insight.domain.case import NTFCase
from ntf_insight.domain.events import PartReplacement, RepairEvent
from ntf_insight.storage.source_knowledge_store import SourceKnowledgeStore


@dataclass(frozen=True, slots=True)
class ReplacementDateCandidate:
    repair: RepairEvent
    date_difference_days: int
    mileage_difference_km: int | None
    association: str
    detail: str


@dataclass(frozen=True, slots=True)
class ReplacementDateComparison:
    qec_anchor: PartReplacement | None
    candidates: tuple[ReplacementDateCandidate, ...]
    status: str
    note: str

    @property
    def preferred_candidate(self) -> ReplacementDateCandidate | None:
        """Only one sufficiently grounded candidate can be nominated.

        This is NOT a confirmed swap and does not replace the QEC anchor.
        """
        if len(self.candidates) == 1:
            return self.candidates[0]
        return None


def _part(value: str | None) -> str:
    return re.sub(r"[^A-Z0-9]", "", (value or "").upper())


def _int(value: object) -> int | None:
    try:
        parsed = int(str(value).replace(" ", "").strip())
        return parsed if parsed >= 0 else None
    except (ValueError, TypeError):
        return None


def _row_repair(record: dict) -> RepairEvent | None:
    raw = record["data"]
    raw_date = str(raw.get("RepairDt") or "").strip()
    if not raw_date:
        return None
    try:
        occurred = datetime.fromisoformat(raw_date)
    except ValueError:
        return None
    if occurred.tzinfo is not None:
        occurred = occurred.replace(tzinfo=None)
    # AutoExport's RepairDt is a repair date; do not fabricate the clock time.
    only_date = len(raw_date) <= 10
    if only_date:
        occurred = occurred.replace(hour=12)
    return RepairEvent(
        event_id=f"autoexport-date:{record['source_sha256']}:{record['source_location']}",
        vin=str(record["fin"]),
        occurred_at=occurred,
        time_precision="date" if only_date else "datetime",
        mileage_km=_int(raw.get("KmReadingNum")),
        complaint=str(raw.get("ComplDsc") or "") or None,
        action=str(raw.get("RepairTypeNmGerman") or "") or None,
        notes=str(raw.get("WorksVisitDsc") or "") or None,
        damaged_part_number=str(raw.get("PartLetterCd") or "") or None,
        part_name=str(raw.get("PartNmDeu") or "") or None,
        source_ref=f"raw:{record['source_sha256']}#{record['source_location']}",
    )


def _potential_repairs(
    case: NTFCase,
    knowledge: SourceKnowledgeStore | None,
) -> list[RepairEvent]:
    repairs = list(case.repairs)
    if knowledge is not None:
        # Stored AutoExport raw records can predate the corresponding QEC import
        # and can be outside the provisional +/-30 day workshop linking window.
        offset = 0
        while True:
            rows = knowledge.list_rows(
                category="autoexport_repair", fin=case.vin, limit=1000,
                offset=offset,
            )
            for row in rows:
                repair = _row_repair(row)
                if repair is not None:
                    repairs.append(repair)
            if len(rows) < 1000:
                break
            offset += len(rows)
    # De-duplicate snapshots and raw-table projections using their observations
    # rather than source row numbering, which differs between CSV readers.
    unique: dict[tuple[str, int | None, str], RepairEvent] = {}
    for repair in repairs:
        key = (
            repair.occurred_at.date().isoformat(),
            repair.mileage_km,
            _part(getattr(repair, "damaged_part_number", None)),
        )
        # Prefer raw-table records that preserve the PartNmDeu field.
        prior = unique.get(key)
        if prior is None or (
            getattr(prior, "part_name", None) is None
            and getattr(repair, "part_name", None) is not None
        ):
            unique[key] = repair
    return list(unique.values())


def compare_replacement_dates(
    case: NTFCase,
    knowledge: SourceKnowledgeStore | None = None,
) -> ReplacementDateComparison:
    # A manually confirmed anchor may later supersede the imported QEC
    # anchor for recurrence. Keep comparing AutoExport with the *original*
    # QEC date so that the disagreement remains visible and auditable.
    original_qec = next(
        (
            replacement for replacement in case.replacements
            if "Schadteile QEC" in (replacement.source_ref or "")
        ),
        None,
    )
    qec = original_qec or case.investigated_replacement()
    if qec is None:
        return ReplacementDateComparison(
            qec_anchor=None,
            candidates=(),
            status="Ohne dokumentierten Tauschanker",
            note="Ein AutoExport-Reparaturdatum darf ohne zugeordneten Schadteilfall nicht als Tausch gelten.",
        )
    part = _part(
        getattr(case, "qec_part_number", None) or qec.old_part_number
    )
    if not part:
        return ReplacementDateComparison(
            qec_anchor=qec,
            candidates=(),
            status="Teilenummer fehlt",
            note="Keine automatische Zuordnung: QEC enthält keine Vergleichs-Teilenummer.",
        )

    candidates = []
    for repair in _potential_repairs(case, knowledge):
        if repair.vin != case.vin:
            continue
        if _part(getattr(repair, "damaged_part_number", None)) != part:
            continue
        delta_days = (
            repair.occurred_at.date() - qec.occurred_at.date()
        ).days
        km = (
            abs(repair.mileage_km - qec.mileage_km)
            if repair.mileage_km is not None and qec.mileage_km is not None
            else None
        )
        # Reject unrelated workshop visits, but allow a conflicting QEC date
        # if VIN, exact part number and odometer strongly support the match.
        if abs(delta_days) > 365:
            continue
        if km is not None and km > 1000:
            continue
        if km is None and abs(delta_days) > 45:
            continue
        association = (
            "Hoch (gleiche Teilenummer und km)"
            if km == 0
            else "Plausibel"
            if km is not None and km <= 200 and abs(delta_days) <= 30
            else "Prüfen"
        )
        detail = (
            f"AutoExport RepairDt · Teilenummer {part} · "
            f"Datumsabweichung {delta_days:+d} Tage · "
            f"km-Abweichung {km if km is not None else 'unbekannt'}"
        )
        candidates.append(ReplacementDateCandidate(
            repair=repair,
            date_difference_days=delta_days,
            mileage_difference_km=km,
            association=association,
            detail=detail,
        ))
    candidates.sort(
        key=lambda item: (
            item.mileage_difference_km
            if item.mileage_difference_km is not None else 999999,
            abs(item.date_difference_days),
            item.repair.occurred_at,
            item.repair.event_id,
        )
    )
    if not candidates:
        return ReplacementDateComparison(
            qec_anchor=qec,
            candidates=(),
            status="AutoExport-Kandidat fehlt",
            note="QEC-Tauschdatum ist vorläufig; keine eindeutig passende Pumpenreparatur gefunden.",
        )
    if len(candidates) > 1:
        return ReplacementDateComparison(
            qec_anchor=qec,
            candidates=tuple(candidates),
            status="Mehrdeutig – prüfen",
            note=(
                f"{len(candidates)} AutoExport-Reparaturkandidaten mit gleicher FIN "
                "und Teilenummer. Keines der Daten wird automatisch als Tausch bestätigt."
            ),
        )
    candidate = candidates[0]
    if candidate.date_difference_days == 0:
        status = "Datum stimmt überein (nicht unabhängig bestätigt)"
    else:
        status = f"Datumsabweichung {candidate.date_difference_days:+d} Tage – prüfen"
    return ReplacementDateComparison(
        qec_anchor=qec,
        candidates=(candidate,),
        status=status,
        note=(
            f"{candidate.association}; {candidate.detail}. "
            "Die NTF-Wiederauftretensanalyse verwendet bis zur Prüfung "
            "weiterhin den dokumentierten Tauschanker."
        ),
    )
