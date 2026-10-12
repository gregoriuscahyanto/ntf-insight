"""All-case CPC3 / pump software overview with conservative outcome criteria.

Never infer a software flash from two different version readings. Never infer
that software *caused* a repair outcome from absent fault codes after a pump
replacement. Each row represents an actual component case, not just one VIN.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date
from typing import Callable, Iterable, Mapping

from ntf_insight.analysis.cpc3_software import (
    CPC3SoftwareReview, assess_cpc3_software,
)
from ntf_insight.domain.case import NTFCase
from ntf_insight.domain.events import DiagnosticSession, SoftwareEvent

_UPDATE_WORDS = (
    "update", "flash", "programm", "aktualis", "hochzieh",
    "aufspiel", "neu aufgesetzt", "reprogramm",
)


def is_pump_case(case: NTFCase) -> bool:
    """Include explicit coolant-pump profiles and legacy named pump cases."""
    profile = str(case.component_profile_id or "").strip().casefold()
    if profile:
        return profile == "coolant_pump"
    component = case.component_type.casefold()
    return any(word in component for word in (
        "pump", "kühlmittel", "kuehlmittel",
    ))


def is_reported_software_update(event: SoftwareEvent) -> bool:
    """A software EVENT is not automatically a confirmed flash.

    Even an explicitly worded action is only as reliable as its source.
    The UI consequently says 'dokumentiert', never independently verified.
    """
    return any(word in str(event.action or "").casefold() for word in _UPDATE_WORDS)


@dataclass(frozen=True, slots=True)
class CPC3PumpOverviewCase:
    case_id: str
    fin: str
    component: str
    swap_day: date | None
    before_sw: str | None
    after_sw: str | None
    before_source: str | None
    after_source: str | None
    update_status: str
    update_group: str
    update_events: tuple[str, ...]
    interval_description: str
    dtc_status: str
    pre_cpc3_dtcs: tuple[str, ...]
    post_cpc3_dtcs: tuple[str, ...]
    returned_dtcs: tuple[str, ...]
    pre_complete_tests: int
    post_complete_tests: int
    sw_effect: str
    note: str
    truncated: bool


@dataclass(frozen=True, slots=True)
class CPC3PumpOverviewReport:
    cases: tuple[CPC3PumpOverviewCase, ...]
    total_pump_cases: int
    unique_fins: int
    documented_swap_day_updates: int
    documented_nearby_updates: int
    changed_sw_observed: int
    unchanged_sw_observed: int
    not_assessable: int
    dtc_returned: int
    dtc_not_seen: int


def _complete_cpc3_tests(
    case: NTFCase,
) -> tuple[DiagnosticSession, ...]:
    """Only complete PDF tests that also demonstrably contained CPC3."""
    sessions = {
        event.session_id
        for event in case.ecu_states
        if event.ecu.strip().upper() == "CPC3" and event.session_id
    }
    return tuple(sorted(
        (
            event for event in case.diagnostic_sessions
            if event.session_id in sessions
            and getattr(event, "source_is_complete_quicktest", False)
        ),
        key=lambda event: (event.occurred_at, event.session_id),
    ))


def _fault_codes(case: NTFCase, session: DiagnosticSession) -> frozenset[str]:
    return frozenset(
        event.dtc_code.strip().upper()
        for event in case.diagnostics
        if event.session_id == session.session_id
        and event.ecu.strip().upper() == "CPC3"
        and event.dtc_code.strip()
    )


def _outcome(
    case: NTFCase, swap_day: date | None,
) -> tuple[str, tuple[str, ...], tuple[str, ...], tuple[str, ...], int, int]:
    """CPC3 DTC observed in actual complete QTs around the pump replacement.

    Date-only swap anchors rule out all same-day sessions. Use ALL later
    complete sessions for recurrence, not just the first convenient scan.
    """
    if swap_day is None:
        return "Tauschdatum fehlt", (), (), (), 0, 0
    sessions = _complete_cpc3_tests(case)
    before = [s for s in sessions if s.occurred_at.date() < swap_day]
    after = [s for s in sessions if s.occurred_at.date() > swap_day]
    if not before or not after:
        return "Vollständige CPC3-QuickTests fehlen", (), (), (), len(before), len(after)
    # A single pre-test is a limited baseline, not a claim of fault healing.
    baseline = max(before, key=lambda s: (s.occurred_at, s.session_id))
    pre = _fault_codes(case, baseline)
    post = set().union(*(_fault_codes(case, s) for s in after))
    returned = pre & post
    if not pre:
        status = "Kein CPC3-Ausgangs-DTC im letzten Vortest"
    elif returned:
        status = "CPC3-DTC erneut nach Tausch beobachtet"
    else:
        status = f"CPC3-DTC in {len(after)} Nachtests nicht erneut gesehen"
    return (
        status, tuple(sorted(pre)), tuple(sorted(post)),
        tuple(sorted(returned)), len(before), len(after),
    )


def _update_near_swap(
    review: CPC3SoftwareReview, swap_day: date | None,
    *, days: int,
) -> tuple[str, str, tuple[str, ...], str]:
    if swap_day is None:
        return "Tauschdatum fehlt", "no_swap", (), ""
    actions = [
        event for event in review.documented_actions
        if is_reported_software_update(event)
    ]
    same_day = [
        event for event in actions
        if event.occurred_at.date() == swap_day
    ]
    nearby = [
        event for event in actions
        if 0 < abs((event.occurred_at.date() - swap_day).days) <= days
    ]
    descriptions = tuple(
        f"{event.occurred_at:%d.%m.%Y}: "
        f"{event.action or 'SW-Ereignis'}"
        f" ({event.software_version or 'SW nicht angegeben'}), "
        f"Quelle {event.source_ref or 'nicht angegeben'}"
        for event in sorted(same_day + nearby, key=lambda x: x.occurred_at)
    )
    before = review.last_before_swap
    after = review.first_after_swap
    interval = (
        f"{before.occurred_at:%d.%m.%Y} bis "
        f"{after.occurred_at:%d.%m.%Y}"
        if before and after else ""
    )
    if same_day:
        return (
            "SW-Maßnahme am Tauschtag dokumentiert",
            "documented_same_day", descriptions, interval,
        )
    if nearby:
        return (
            f"SW-Maßnahme innerhalb ±{days} Tagen dokumentiert",
            "documented_nearby", descriptions, interval,
        )
    if review.truncated or review.before_ambiguous or review.after_ambiguous:
        return (
            "SW-Belege unvollständig/widersprüchlich",
            "unknown", descriptions, interval,
        )
    if before and after:
        if str(before.software_version).casefold() != str(after.software_version).casefold():
            return (
                "SW-Version vor/nach Tausch verschieden (Updatezeit unbekannt)",
                "observed_change", descriptions, interval,
            )
        return (
            "Gleicher SW-Stand vor/nach Tausch beobachtet",
            "observed_same", descriptions, interval,
        )
    return (
        "SW-Stand vor/nach Tausch nicht vergleichbar",
        "unknown", descriptions, interval,
    )


def evaluate_cpc3_pump_case(
    case: NTFCase,
    *,
    autoexport_rows: Iterable[dict] = (),
    truncated: bool = False,
    nearby_days: int = 14,
) -> CPC3PumpOverviewCase:
    """Assess one true case using its own complete QuickTest associations."""
    if nearby_days < 0:
        raise ValueError("Zeitfenster darf nicht negativ sein.")
    review = assess_cpc3_software(
        case, autoexport_rows=autoexport_rows, truncated=truncated,
    )
    swap_day = review.replacement_day
    update, group, actions, interval = _update_near_swap(
        review, swap_day, days=nearby_days,
    )
    dtc, pre_codes, post_codes, returned, n_pre, n_post = _outcome(
        case, swap_day,
    )
    if not n_pre or not n_post:
        effect = "SW-Wirkung nicht beurteilbar (Diagnosen fehlen)"
    elif not pre_codes:
        effect = "SW-Wirkung nicht beurteilbar (Ausgangs-DTC fehlt)"
    elif returned:
        effect = "DTC erneut beobachtet; SW-Lösung nicht belegt"
    elif group in {"documented_same_day", "documented_nearby", "observed_change"}:
        effect = "DTC nicht erneut beobachtet; SW-Wirkung nicht isolierbar"
    else:
        effect = "DTC nicht erneut beobachtet; kein SW-Wirkungsbeleg"
    missing = []
    if not swap_day:
        missing.append("Pumpentauschdatum fehlt")
    if group == "unknown":
        missing.append("SW-Vergleich unvollständig")
    if review.truncated:
        missing.append("AutoExport-Zeilenlimit erreicht")
    if review.on_swap_day:
        missing.append("Messungen am Tauschtag nicht zeitlich zugeordnet")
    if review.ambiguous_days:
        missing.append("SW-Konflikte an Diagnosekalendertagen")
    if not n_pre or not n_post:
        missing.append("kein vollständiger CPC3-Vor- und Nachtest")
    missing.append(
        "Pumpentausch ist ein konkurrierender Eingriff; DTC-Verlauf "
        "beweist keine kausale SW-Heilung"
    )
    return CPC3PumpOverviewCase(
        case_id=case.case_id, fin=case.vin,
        component=case.component_type, swap_day=swap_day,
        before_sw=(
            review.last_before_swap.software_version
            if review.last_before_swap else None
        ),
        after_sw=(
            review.first_after_swap.software_version
            if review.first_after_swap else None
        ),
        before_source=(
            review.last_before_swap.source_ref
            if review.last_before_swap else None
        ),
        after_source=(
            review.first_after_swap.source_ref
            if review.first_after_swap else None
        ),
        update_status=update, update_group=group,
        update_events=actions, interval_description=interval,
        dtc_status=dtc, pre_cpc3_dtcs=pre_codes,
        post_cpc3_dtcs=post_codes, returned_dtcs=returned,
        pre_complete_tests=n_pre, post_complete_tests=n_post,
        sw_effect=effect, note="; ".join(missing), truncated=review.truncated,
    )


def build_cpc3_pump_overview(
    cases: Iterable[NTFCase],
    *,
    load_autoexport: Callable[[str], tuple[list[dict], bool]] | None = None,
    nearby_days: int = 14,
) -> CPC3PumpOverviewReport:
    """A stable per-case cohort. Read each FIN's local AutoExport rows once."""
    source_cache: dict[str, tuple[list[dict], bool]] = {}
    rows = []
    for case in sorted(cases, key=lambda item: (item.vin, item.case_id)):
        if not is_pump_case(case):
            continue
        if case.vin not in source_cache:
            source_cache[case.vin] = (
                load_autoexport(case.vin) if load_autoexport else ([], False)
            )
        data, truncated = source_cache[case.vin]
        rows.append(evaluate_cpc3_pump_case(
            case, autoexport_rows=data,
            truncated=truncated, nearby_days=nearby_days,
        ))
    counter = Counter(row.update_group for row in rows)
    return CPC3PumpOverviewReport(
        cases=tuple(rows), total_pump_cases=len(rows),
        unique_fins=len({row.fin for row in rows}),
        documented_swap_day_updates=counter["documented_same_day"],
        documented_nearby_updates=counter["documented_nearby"],
        changed_sw_observed=counter["observed_change"],
        unchanged_sw_observed=counter["observed_same"],
        not_assessable=counter["unknown"] + counter["no_swap"],
        dtc_returned=sum(bool(row.returned_dtcs) for row in rows),
        dtc_not_seen=sum(
            row.pre_complete_tests > 0 and row.post_complete_tests > 0
            and bool(row.pre_cpc3_dtcs) and not row.returned_dtcs
            for row in rows
        ),
    )
