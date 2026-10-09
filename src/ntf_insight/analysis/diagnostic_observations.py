"""Conservative display-level consolidation of overlapping diagnostic exports.

QuickTest PDFs and AutoExport CSVs can describe the very same DTC reading.
Keep both immutable source records and their provenance. Collapse only strongly
matched cross-source *observations* in derived counts and timeline views;
a repeated fault on a different day or at different mileage stays distinct.

Clustering already uses sets of ECU:DTC keys, so this module must not alter
cluster membership or diagnostic similarity.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Iterable

from ntf_insight.domain.events import DiagnosticEvent

ObservationKey = tuple[str, tuple[str, str], date, int]


@dataclass(frozen=True, slots=True)
class DiagnosticObservation:
    event: DiagnosticEvent
    source_refs: tuple[str, ...]

    @property
    def has_cross_source_confirmation(self) -> bool:
        return len(self.source_refs) > 1


def _origin(event: DiagnosticEvent) -> str | None:
    source = event.source_ref or ""
    if (
        event.session_id
        and event.freeze_frame.get("observed_at_diagnostic_test") is True
        and "#ecu:" in source
    ):
        return "quicktest"
    if not event.session_id and "#csv:" in source:
        return "autoexport"
    return None


def _key(event: DiagnosticEvent) -> ObservationKey | None:
    # Missing km cannot substantiate a shared reading on the same day.
    if event.mileage_km is None:
        return None
    return (event.vin, event.fault_key, event.occurred_at.date(), event.mileage_km)


def unique_diagnostic_observations(
    events: Iterable[DiagnosticEvent],
) -> list[DiagnosticObservation]:
    """Consolidate a QuickTest/AutoExport overlap only with date AND km evidence.

    Never merge two QuickTests, two AutoExport rows, manual entries, or records
    without mileage. With only a date in AutoExport, a matching QuickTest on
    that date at the identical odometer is treated as the same *reported
    observation* for counting. A precise AutoExport timestamp must additionally
    match the QuickTest timestamp. Each reading may absorb at most one other
    source row, to avoid hiding genuine repeated observations.
    """
    items = list(events)
    grouped: dict[ObservationKey, dict[str, list[int]]] = defaultdict(
        lambda: {"quicktest": [], "autoexport": []}
    )
    for index, event in enumerate(items):
        origin, key = _origin(event), _key(event)
        if origin is not None and key is not None:
            grouped[key][origin].append(index)

    hidden: set[int] = set()
    supporting: dict[int, list[int]] = defaultdict(list)
    for groups in grouped.values():
        quicktests = sorted(
            groups["quicktest"],
            key=lambda i: (items[i].occurred_at, items[i].event_id),
        )
        autoexports = sorted(
            groups["autoexport"],
            key=lambda i: (items[i].occurred_at, items[i].event_id),
        )
        available = list(quicktests)
        for export_index in autoexports:
            export = items[export_index]
            matching = next(
                (
                    index for index in available
                    if (
                        getattr(export, "time_precision", "datetime") == "date"
                        or export.occurred_at == items[index].occurred_at
                    )
                ),
                None,
            )
            if matching is not None:
                available.remove(matching)
                hidden.add(export_index)
                supporting[matching].append(export_index)

    observations: list[DiagnosticObservation] = []
    for index, event in enumerate(items):
        if index in hidden:
            continue
        refs = tuple(dict.fromkeys(
            source
            for member in (index, *supporting.get(index, []))
            if (source := items[member].source_ref)
        ))
        observations.append(DiagnosticObservation(event=event, source_refs=refs))
    return observations
