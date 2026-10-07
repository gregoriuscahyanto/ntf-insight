"""Pre/post replacement recurrence analysis."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from ntf_insight.domain.case import NTFCase
from ntf_insight.domain.events import DiagnosticEvent, PartReplacement

FaultKey = tuple[str, str]


@dataclass(frozen=True, slots=True)
class RecurrenceResult:
    assessable: bool
    replacement: PartReplacement | None
    pre_faults: frozenset[FaultKey]
    post_faults: frozenset[FaultKey]
    same_faults: frozenset[FaultKey]
    disappeared_faults: frozenset[FaultKey]
    new_faults: frozenset[FaultKey]
    first_recurrence_after: timedelta | None
    distance_to_recurrence_km: int | None

    @property
    def has_recurrence(self) -> bool:
        return bool(self.same_faults)


def _faults(events: list[DiagnosticEvent]) -> frozenset[FaultKey]:
    return frozenset(event.fault_key for event in events)


def analyze_recurrence(case: NTFCase) -> RecurrenceResult:
    """Compare DTCs before and after the investigated component replacement."""
    replacement = case.investigated_replacement()
    if replacement is None:
        return RecurrenceResult(
            assessable=False,
            replacement=None,
            pre_faults=frozenset(),
            post_faults=frozenset(),
            same_faults=frozenset(),
            disappeared_faults=frozenset(),
            new_faults=frozenset(),
            first_recurrence_after=None,
            distance_to_recurrence_km=None,
        )

    pre_events = [
        event for event in case.diagnostics if event.occurred_at < replacement.occurred_at
    ]
    post_events = [
        event for event in case.diagnostics if event.occurred_at > replacement.occurred_at
    ]

    pre_faults = _faults(pre_events)
    post_faults = _faults(post_events)
    same_faults = pre_faults & post_faults
    disappeared_faults = pre_faults - post_faults
    new_faults = post_faults - pre_faults

    recurrence_events = sorted(
        (event for event in post_events if event.fault_key in same_faults),
        key=lambda event: event.occurred_at,
    )
    first = recurrence_events[0] if recurrence_events else None

    distance: int | None = None
    if first is not None and first.mileage_km is not None and replacement.mileage_km is not None:
        distance = first.mileage_km - replacement.mileage_km
        if distance < 0:
            distance = None

    return RecurrenceResult(
        assessable=True,
        replacement=replacement,
        pre_faults=pre_faults,
        post_faults=post_faults,
        same_faults=same_faults,
        disappeared_faults=disappeared_faults,
        new_faults=new_faults,
        first_recurrence_after=(
            first.occurred_at - replacement.occurred_at if first is not None else None
        ),
        distance_to_recurrence_km=distance,
    )


def format_faults(faults: frozenset[FaultKey]) -> str:
    """Human-readable compact DTC list for the UI."""
    if not faults:
        return "—"
    return ", ".join(f"{ecu}:{dtc}" for ecu, dtc in sorted(faults))
