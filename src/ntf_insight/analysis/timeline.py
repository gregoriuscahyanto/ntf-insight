"""Timeline reconstruction for NTF cases."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from ntf_insight.domain.case import NTFCase
from ntf_insight.domain.events import (
    DiagnosticEvent,
    DiagnosticSession,
    ECUStateObservation,
    PartReplacement,
    RepairEvent,
    SoftwareEvent,
    SupplierFinding,
)

TimelineKind = Literal[
    "diagnostic_session",
    "diagnostic",
    "ecu_state",
    "replacement",
    "repair",
    "software",
    "supplier",
]
TimelineEvent = (
    DiagnosticSession
    | DiagnosticEvent
    | ECUStateObservation
    | PartReplacement
    | RepairEvent
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


def build_timeline(case: NTFCase) -> list[TimelineEntry]:
    """Return all case events in chronological order."""
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

    for event in case.diagnostics:
        detail_parts = [part for part in (event.dtc_text, event.status) if part]
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
                title=f"ECU state · {event.ecu}",
                detail=" · ".join(state_parts),
                source_ref=event.source_ref,
                event=event,
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
                title=f"Replacement · {event.component_type}",
                detail=part_text or (event.supplier or ""),
                source_ref=event.source_ref,
                event=event,
            )
        )

    for event in case.repairs:
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
                title=f"Supplier finding · {event.result}",
                detail=event.failure_mode or event.notes or "",
                source_ref=event.source_ref,
                event=event,
            )
        )

    return sorted(entries, key=lambda item: (item.occurred_at, item.kind, item.title))
