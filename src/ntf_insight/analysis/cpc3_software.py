"""FIN-based CPC3 software evidence at a documented pump replacement.

A replacement is only a proxy for the *investigation window*, never an exact
failure or programming timestamp. Version identifiers do not describe release
contents and DTC differences do not prove a software-induced effect.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Iterable

from ntf_insight.analysis.ecu_version_changes import (
    ECUVersionChange, _version, detect_ecu_version_changes,
)
from ntf_insight.domain.case import NTFCase
from ntf_insight.domain.events import ECUStateObservation, SoftwareEvent


@dataclass(frozen=True, slots=True)
class CPC3ChangeEvidence:
    """A software difference and optional *complete* QuickTest DTC comparison."""

    change: ECUVersionChange
    new_dtcs: tuple[str, ...] | None
    absent_in_new_test: tuple[str, ...] | None

    @property
    def comparable_tests(self) -> bool:
        return self.new_dtcs is not None


@dataclass(frozen=True, slots=True)
class CPC3VersionEvidence:
    version: str
    first_seen: datetime
    last_seen: datetime
    observation_count: int
    sources: tuple[str, ...]
    observed_dtcs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CPC3SoftwareReview:
    """Evidence per FIN, never a root-cause/supplier responsibility verdict."""

    replacement_day: date | None
    last_before_swap: ECUStateObservation | None
    first_after_swap: ECUStateObservation | None
    before_ambiguous: bool
    after_ambiguous: bool
    on_swap_day: int
    ambiguous_days: tuple[date, ...]
    versions: tuple[CPC3VersionEvidence, ...]
    changes: tuple[CPC3ChangeEvidence, ...]
    documented_actions: tuple[SoftwareEvent, ...]
    observation_count: int
    truncated: bool

    @property
    def has_sw_evidence(self) -> bool:
        return bool(self.versions)


def _is_cpc3(value: str) -> bool:
    return str(value).strip().upper() == "CPC3"


def _read_autoexport_time(row: dict[str, Any]) -> tuple[datetime, str] | None:
    """Retain the source wall-clock without inventing a timezone conversion."""
    timestamp = str(row.get("diag_timestamp") or "").strip()
    if timestamp:
        try:
            observed_at = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            return observed_at.replace(tzinfo=None), "datetime"
        except ValueError:
            pass
    raw_date = str(row.get("diag_date") or "").strip()
    if raw_date:
        try:
            observed_at = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
            if len(raw_date) <= 10:
                return observed_at.replace(hour=12, tzinfo=None), "date"
            return observed_at.replace(tzinfo=None), "datetime"
        except ValueError:
            pass
    return None


def _autoexport_observations(
    fin: str, raw_rows: Iterable[dict[str, Any]],
) -> tuple[list[ECUStateObservation], dict[str, frozenset[str]]]:
    """Coalesce repeated DTC CSV lines into one partial observation per export/run.

    AutoExport DTC rows are never considered a complete diagnostic session.
    """
    buckets: dict[tuple[str, datetime, str, str], dict[str, Any]] = {}
    for row in raw_rows:
        sw = _version(row.get("software_version"))
        moment = _read_autoexport_time(row)
        if not sw or moment is None:
            continue
        when, precision = moment
        source_ref = str(row.get("source_ref") or "")
        source_id = source_ref.split("#", 1)[0]
        key = (source_id, when, precision, sw.casefold())
        bucket = buckets.setdefault(key, {
            "sw": sw, "when": when, "precision": precision,
            "source_ref": source_ref, "dtcs": set(),
            "km": None, "hw": None,
        })
        dtc = str(row.get("dtc_code") or "").strip().upper()
        if dtc:
            bucket["dtcs"].add(dtc)
        if bucket["km"] is None:
            try:
                value = int(str(row.get("mileage_km") or ""))
                bucket["km"] = value if value >= 0 else None
            except ValueError:
                pass
        if bucket["hw"] is None:
            bucket["hw"] = _version(row.get("hardware_version"))
    states = []
    dtcs_by_event = {}
    for index, (key, bucket) in enumerate(sorted(buckets.items()), start=1):
        state = ECUStateObservation(
            event_id=f"cpc3-raw:{index}:{key[0]}:{key[1].isoformat()}",
            vin=fin, ecu="CPC3", occurred_at=bucket["when"],
            software_version=bucket["sw"], hardware_version=bucket["hw"],
            mileage_km=bucket["km"], source_ref=bucket["source_ref"],
            time_precision=bucket["precision"],
        )
        states.append(state)
        dtcs_by_event[state.event_id] = frozenset(bucket["dtcs"])
    return states, dtcs_by_event


def _date_ambiguous_days(
    states: list[ECUStateObservation],
) -> set[date]:
    """A date-only snapshot cannot be ordered against other scans that day."""
    per_day: dict[date, list[ECUStateObservation]] = defaultdict(list)
    for state in states:
        per_day[state.occurred_at.date()].append(state)
    return {
        day for day, events in per_day.items()
        if len({
            _version(event.software_version).casefold()
            for event in events if _version(event.software_version)
        }) > 1 and any(
            getattr(event, "time_precision", None) == "date"
            for event in events
        )
    }


def _boundary(
    states: list[ECUStateObservation],
    swap_day: date,
    *, before: bool,
) -> tuple[ECUStateObservation | None, bool]:
    eligible = [
        state for state in states
        if (state.occurred_at.date() < swap_day if before
            else state.occurred_at.date() > swap_day)
    ]
    if not eligible:
        return None, False
    day = (
        max(state.occurred_at.date() for state in eligible)
        if before else min(state.occurred_at.date() for state in eligible)
    )
    same_day = [state for state in eligible if state.occurred_at.date() == day]
    # If any read is date-only, its order relative to other observations
    # that same day is unknowable. Accept only a single unambiguous version.
    variants = {
        _version(state.software_version).casefold()
        for state in same_day if _version(state.software_version)
    }
    if len(variants) > 1 and any(
        getattr(state, "time_precision", None) == "date"
        for state in same_day
    ):
        return None, True
    last_moment = (
        max(state.occurred_at for state in same_day)
        if before else min(state.occurred_at for state in same_day)
    )
    at_moment = [
        state for state in same_day if state.occurred_at == last_moment
    ]
    if len({
        _version(state.software_version).casefold() for state in at_moment
    }) != 1:
        return None, True
    return min(at_moment, key=lambda state: state.event_id), False


def assess_cpc3_software(
    case: NTFCase,
    *,
    autoexport_rows: Iterable[dict[str, Any]] = (),
    truncated: bool = False,
) -> CPC3SoftwareReview:
    """Correlate genuine CPC3 versions with pump replacement and DTC evidence.

    Only complete, identified QuickTest sessions may support a comparison
    showing a code present in one test and absent from the next. Partial
    AutoExport code lists are *positive* observations, not absence evidence.
    """
    raw_states, raw_codes = _autoexport_observations(
        case.vin, autoexport_rows
    )
    original = [
        state for state in case.ecu_states
        if _is_cpc3(state.ecu) and state.vin.strip().upper() == case.vin.upper()
        and _version(state.software_version)
    ]
    # A normal imported case may also contain projections of the same raw
    # CSV. Prefer the independently archived AutoExport version observations
    # when available; retain the case records if the raw index is absent.
    has_raw = bool(raw_states)
    original = [
        state for state in original
        if not (
            has_raw and state.session_id is None
            and "csv:" in (state.source_ref or "")
        )
    ]
    observed = [*original, *raw_states]
    ambiguous_days = _date_ambiguous_days(observed)
    # Do not build a spurious baseline from mixed-precision conflicting days.
    comparable = [
        state for state in observed
        if state.occurred_at.date() not in ambiguous_days
    ]
    changes = [
        change for change in detect_ecu_version_changes(comparable)
        if change.kind == "sw" and _is_cpc3(change.ecu)
    ]
    sessions = {
        item.session_id for item in case.diagnostic_sessions
        if getattr(item, "source_is_complete_quicktest", False)
    }
    complete_codes: dict[str, frozenset[str]] = {}
    for state in original:
        if state.session_id and state.session_id in sessions:
            complete_codes[state.event_id] = frozenset(
                event.dtc_code.strip().upper()
                for event in case.diagnostics
                if event.session_id == state.session_id
                and _is_cpc3(event.ecu) and event.dtc_code.strip()
            )
    # Never promote an AutoExport partial code set into a complete test.
    change_evidence = []
    for change in changes:
        old = complete_codes.get(change.previous.event_id)
        new = complete_codes.get(change.current.event_id)
        both_complete = old is not None and new is not None
        change_evidence.append(CPC3ChangeEvidence(
            change=change,
            new_dtcs=tuple(sorted(new - old)) if both_complete else None,
            absent_in_new_test=tuple(sorted(old - new)) if both_complete else None,
        ))
    versions: dict[str, list[ECUStateObservation]] = defaultdict(list)
    for state in observed:
        if sw := _version(state.software_version):
            versions[sw.casefold()].append(state)
    items = []
    for versions_group in versions.values():
        sample = min(
            versions_group, key=lambda state: (
                state.occurred_at, state.event_id,
            )
        )
        codes = set()
        source_types = set()
        for state in versions_group:
            source_types.add(
                "AutoExport" if state.event_id in raw_codes
                else "QuickTest" if state.session_id in sessions
                else "Falldiagnose"
            )
            codes.update(raw_codes.get(state.event_id, ()))
            codes.update(complete_codes.get(state.event_id, ()))
        items.append(CPC3VersionEvidence(
            version=_version(sample.software_version) or "",
            first_seen=min(s.occurred_at for s in versions_group),
            last_seen=max(s.occurred_at for s in versions_group),
            observation_count=len(versions_group),
            sources=tuple(sorted(source_types)),
            observed_dtcs=tuple(sorted(codes)),
        ))
    swap = case.investigated_replacement()
    swap_day = swap.occurred_at.date() if swap is not None else None
    before, before_ambiguous = (
        _boundary(observed, swap_day, before=True)
        if swap_day is not None else (None, False)
    )
    after, after_ambiguous = (
        _boundary(observed, swap_day, before=False)
        if swap_day is not None else (None, False)
    )
    documented = tuple(sorted(
        (
            event for event in case.software_events
            if _is_cpc3(event.ecu) and event.vin.strip().upper() == case.vin.upper()
        ),
        key=lambda event: (event.occurred_at, event.event_id),
    ))
    return CPC3SoftwareReview(
        replacement_day=swap_day, last_before_swap=before,
        first_after_swap=after, before_ambiguous=before_ambiguous,
        after_ambiguous=after_ambiguous,
        on_swap_day=sum(
            state.occurred_at.date() == swap_day for state in observed
        ) if swap_day is not None else 0,
        ambiguous_days=tuple(sorted(ambiguous_days)),
        versions=tuple(sorted(items, key=lambda item: (
            item.first_seen, item.version,
        ))),
        changes=tuple(change_evidence),
        documented_actions=documented,
        observation_count=len(observed),
        truncated=truncated,
    )
