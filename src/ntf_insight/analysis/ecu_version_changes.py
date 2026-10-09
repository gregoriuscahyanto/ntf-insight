"""Detect observed ECU HW/SW version differences across diagnostic sessions.

A change in two observed versions only bounds *when* it happened. It does
not establish a flash, part replacement, root cause, or actual change date.

All comparisons are per vehicle and ECU. Missing values and conflicting
simultaneous readings never produce a speculative change.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from ntf_insight.domain.events import ECUStateObservation


VersionKind = Literal["hw", "sw"]
_UNKNOWN = {
    "", "-", "—", "–", "?", "n/a", "na", "none", "null",
    "unknown", "unbekannt", "not available", "nicht verfügbar",
    "nicht vorhanden", "keine angabe", "no data",
}


def _version(value: str | None) -> str | None:
    """Normalize accidental whitespace without collapsing real release details."""
    if value is None:
        return None
    normalized = " ".join(str(value).split())
    return normalized if normalized.casefold() not in _UNKNOWN else None


@dataclass(frozen=True, slots=True)
class ECUVersionChange:
    """Difference bounded by the last and first known ECU observations."""

    ecu: str
    kind: VersionKind
    previous_version: str
    new_version: str
    previous: ECUStateObservation
    current: ECUStateObservation

    @property
    def first_observed_at(self) -> datetime:
        return self.current.occurred_at

    @property
    def last_previous_at(self) -> datetime:
        return self.previous.occurred_at

    @property
    def observation_interval(self) -> str:
        return (
            f"{self.previous.occurred_at:%d.%m.%Y %H:%M} bis "
            f"{self.current.occurred_at:%d.%m.%Y %H:%M}"
        )


def detect_ecu_version_changes(
    observations: list[ECUStateObservation],
) -> list[ECUVersionChange]:
    """Compare successive *known* versions for one FIN + logical ECU.

    Each ECU's HW and SW are compared independently (missing HW does not
    block an SW comparison). Identical reads are deduplicated; conflicting
    values recorded at the same timestamp invalidate the baseline for that
    field rather than implying an arbitrary event order.

    The later diagnostic is the first *observation* of the new version;
    no claim is made about the precise update date between scans.
    """
    grouped: dict[tuple[str, str], list[ECUStateObservation]] = defaultdict(list)
    for event in observations:
        ecu = event.ecu.strip().upper()
        if ecu:
            grouped[(event.vin.strip().upper(), ecu)].append(event)

    changes: list[ECUVersionChange] = []
    for (_, ecu), events in sorted(grouped.items()):
        # Using a timestamp group prevents false HW/SW changes caused by
        # repeated ECU blocks within one QuickTest.
        moments: dict[datetime, list[ECUStateObservation]] = defaultdict(list)
        for event in events:
            moments[event.occurred_at].append(event)

        last_known: dict[VersionKind, tuple[str, ECUStateObservation]] = {}
        for moment, readings in sorted(moments.items()):
            for kind, attribute in (
                ("hw", "hardware_version"),
                ("sw", "software_version"),
            ):
                observed = [
                    (value, event)
                    for event in readings
                    if (value := _version(getattr(event, attribute))) is not None
                ]
                unique = {value.casefold() for value, _ in observed}
                if len(unique) > 1:
                    # The same timestamp contains contradictory versions.
                    # No reliable ordering or baseline can be inferred.
                    last_known.pop(kind, None)
                    continue
                if not observed:
                    # A missing version is not a changed version.
                    continue
                # Stable choice for duplicate identical ECU reads.
                current_version, current_event = min(
                    observed, key=lambda item: item[1].event_id
                )
                previous = last_known.get(kind)
                if previous is not None:
                    previous_version, previous_event = previous
                    comparable = (
                        moment > previous_event.occurred_at
                        and not (
                            moment.date() == previous_event.occurred_at.date()
                            and (
                                getattr(current_event, "time_precision", None) == "date"
                                or getattr(previous_event, "time_precision", None) == "date"
                            )
                        )
                    )
                    if (
                        comparable
                        and previous_version.casefold() != current_version.casefold()
                    ):
                        changes.append(ECUVersionChange(
                            ecu=ecu,
                            kind=kind,
                            previous_version=previous_version,
                            new_version=current_version,
                            previous=previous_event,
                            current=current_event,
                        ))
                last_known[kind] = (current_version, current_event)

    return sorted(
        changes,
        key=lambda change: (
            change.current.occurred_at,
            change.ecu, change.kind,
            change.current.event_id,
        ),
    )
