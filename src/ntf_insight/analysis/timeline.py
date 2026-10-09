"""Timeline reconstruction for NTF cases."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from ntf_insight.domain.case import NTFCase
from ntf_insight.analysis.ecu_version_changes import detect_ecu_version_changes
from ntf_insight.analysis.diagnostic_observations import unique_diagnostic_observations
from ntf_insight.analysis.replacement_dates import ReplacementDateComparison
from ntf_insight.domain.events import (
    DiagnosticEvent,
    DiagnosticSession,
    ECUStateObservation,
    PartReplacement,
    RepairEvent,
    TipsCaseObservation,
    SoftwareEvent,
    SupplierFinding,
)

TimelineKind = Literal[
    "diagnostic_session",
    "diagnostic",
    "ecu_state",
    "ecu_hw_change",
    "ecu_sw_change",
    "replacement",
    "replacement_candidate",
    "repair",
    "tips",
    "software",
    "supplier",
]
TimelineEvent = (
    DiagnosticSession
    | DiagnosticEvent
    | ECUStateObservation
    | PartReplacement
    | RepairEvent
    | TipsCaseObservation
    | SoftwareEvent
    | SupplierFinding
)


@dataclass(frozen=True, slots=True)
class TimelineEntry:
    occurred_at: datetime
    mileage_km: int | None
    kind: TimelineKind
    title: str
    detail: str
    source_ref: str | None
    event: TimelineEvent
    interval_start_at: datetime | None = None
    interval_start_mileage_km: int | None = None


def build_timeline(
    case: NTFCase,
    date_comparison: ReplacementDateComparison | None = None,
) -> list[TimelineEntry]:
    """Return case events and optional separately attributed repair-date candidates."""

    entries: list[TimelineEntry] = []

    for event in case.diagnostic_sessions:
        details = []
        if event.ecu_count is not None:
            details.append(f"{event.ecu_count} ECUs")
        if event.dtc_count is not None:
            details.append(f"{event.dtc_count} DTCs")
        entries.append(
            TimelineEntry(
                occurred_at=event.occurred_at,
                mileage_km=event.mileage_km,
                kind="diagnostic_session",
                title=event.label,
                detail=" · ".join(details),
                source_ref=event.source_ref,
                event=event,
            )
        )

    for observation in unique_diagnostic_observations(case.diagnostics):
        event = observation.event
        detail_parts = [part for part in (event.dtc_text, event.status) if part]
        if observation.has_cross_source_confirmation:
            detail_parts.append(
                "Zusätzlich in AutoExport belegt (gleiche FIN, ECU:DTC, Datum und km)"
            )
            detail_parts.append("Quellen: " + "; ".join(observation.source_refs))
        entries.append(
            TimelineEntry(
                occurred_at=event.occurred_at,
                mileage_km=event.mileage_km,
                kind="diagnostic",
                title=f"{event.ecu} · {event.dtc_code}",
                detail=" · ".join(detail_parts),
                source_ref=event.source_ref,
                event=event,
            )
        )


    for event in case.ecu_states:
        state_parts = [
            value
            for value in (
                f"SW {event.software_version}" if event.software_version else None,
                f"HW {event.hardware_version}" if event.hardware_version else None,
                f"Coding {event.coding}" if event.coding else None,
            )
            if value
        ]
        entries.append(
            TimelineEntry(
                occurred_at=event.occurred_at,
                mileage_km=event.mileage_km,
                kind="ecu_state",
                title=f"HW-/SW-Stand · {event.ecu}",
                detail=" · ".join(state_parts),
                source_ref=event.source_ref,
                event=event,
            )
        )

    # Read-only differences between *observed* versions. A marker at the
    # later QuickTest is not a known software flash/hardware exchange date.
    for change in detect_ecu_version_changes(case.ecu_states):
        label = "HW" if change.kind == "hw" else "SW"
        entries.append(
            TimelineEntry(
                occurred_at=change.first_observed_at,
                mileage_km=change.current.mileage_km,
                kind=(
                    "ecu_hw_change"
                    if change.kind == "hw" else "ecu_sw_change"
                ),
                title=f"{label}-Standabweichung · {change.ecu}",
                detail=(
                    f"{label} {change.previous_version} → "
                    f"{change.new_version} · zwischen "
                    f"{change.observation_interval} beobachtet. "
                    "Tatsächliches Änderungs-/Updatedatum unbekannt."
                ),
                source_ref=change.current.source_ref,
                event=change.current,
                interval_start_at=change.last_previous_at,
                interval_start_mileage_km=change.previous.mileage_km,
            )
        )

    for event in case.replacements:
        part_text = " → ".join(
            part for part in (event.old_part_number, event.new_part_number) if part
        )
        entries.append(
            TimelineEntry(
                occurred_at=event.occurred_at,
                mileage_km=event.mileage_km,
                kind="replacement",
                title=(
                    f"QEC-Tauschdatum (vorläufig) · {event.component_type}"
                    if "Schadteile QEC" in (event.source_ref or "")
                    else f"Dokumentierter Tausch · {event.component_type}"
                ),
                detail=(
                    f"{part_text or event.supplier or ''} · Tauschanker für Analyse"
                    if "Schadteile QEC" in (event.source_ref or "")
                    else part_text or (event.supplier or "")
                ),
                source_ref=event.source_ref,
                event=event,
            )
        )

    def repair_key(event: RepairEvent) -> tuple:
        return (
            event.occurred_at.date(),
            event.mileage_km,
            "".join(
                char for char in (
                    getattr(event, "damaged_part_number", None) or ""
                ).upper() if char.isalnum()
            ),
        )

    candidate_keys: set[tuple] = set()
    if date_comparison is not None:
        for candidate in date_comparison.candidates:
            repair = candidate.repair
            candidate_keys.add(repair_key(repair))
            entries.append(TimelineEntry(
                occurred_at=repair.occurred_at,
                mileage_km=repair.mileage_km,
                kind="replacement_candidate",
                title="AutoExport · Reparaturdatum (Tauschkandidat)",
                detail=(
                    f"{candidate.detail} · {candidate.association}. "
                    "Kein bestätigter Pumpentausch."
                ),
                source_ref=repair.source_ref,
                event=repair,
            ))

    for event in case.repairs:
        # An AutoExport repair that is already shown as a potential swap date
        # must not appear again as a second, visually duplicated workshop event.
        if repair_key(event) in candidate_keys:
            continue
        entries.append(
            TimelineEntry(
                occurred_at=event.occurred_at,
                mileage_km=event.mileage_km,
                kind="repair",
                title=event.action or "Workshop event",
                detail=event.complaint or event.notes or "",
                source_ref=event.source_ref,
                event=event,
            )
        )

    for event in case.tips_observations:
        # CreationDate is the TIPS record date, not a proven repair date.
        detail = " · ".join(
            value for value in (
                ("Kunde: " + event.complaint[:350]) if event.complaint else None,
                ("Werkstattbefund: " + event.workshop_findings[:350])
                if event.workshop_findings else None,
                ("Maßnahmen (ohne Einzeldatum): " + event.performed_actions[:350])
                if event.performed_actions else None,
            ) if value
        )
        entries.append(TimelineEntry(
            occurred_at=event.occurred_at,
            mileage_km=event.mileage_km,
            kind="tips",
            title="TIPS-Vorgang (Erstellungsdatum)" + (
                f" · {event.tips_case_id}" if event.tips_case_id else ""
            ),
            detail=detail or event.symptom or "TIPS-Quellenmeldung",
            source_ref=event.source_ref,
            event=event,
        ))

    for event in case.software_events:
        entries.append(
            TimelineEntry(
                occurred_at=event.occurred_at,
                mileage_km=event.mileage_km,
                kind="software",
                title=f"Software · {event.ecu}",
                detail=event.action or event.software_version or "",
                source_ref=event.source_ref,
                event=event,
            )
        )

    for event in case.supplier_findings:
        entries.append(
            TimelineEntry(
                occurred_at=event.occurred_at,
                mileage_km=event.mileage_km,
                kind="supplier",
                title=f"Lieferantenbefund · {event.result}",
                detail=event.failure_mode or event.notes or "",
                source_ref=event.source_ref,
                event=event,
            )
        )

    return sorted(entries, key=lambda item: (item.occurred_at, item.kind, item.title))
