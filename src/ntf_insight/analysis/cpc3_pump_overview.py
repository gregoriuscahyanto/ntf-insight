"""All-case CPC3 / pump software overview with conservative outcome criteria.

Never infer a software flash from two different version readings. Never infer
that software *caused* a repair outcome from absent fault codes after a pump
replacement. Each row represents an actual component case, not just one VIN.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Callable, Iterable

from ntf_insight.analysis.cpc3_software import (
    CPC3SoftwareReview, _read_autoexport_time, assess_ecu_software,
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
    ecu: str
    sw_versions: tuple[str, ...]
    sw_history: tuple[str, ...]
    sw_observations: tuple[tuple[str, str, str, str], ...]
    pre_dtc_evidence: str
    post_dtc_evidence: str
    pre_dtc_observed: tuple[str, ...]
    post_dtc_observed: tuple[str, ...]
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
    sw_pre_complete_tests: int
    sw_post_complete_tests: int
    sw_post_returned_dtcs: tuple[str, ...]
    note: str
    truncated: bool


@dataclass(frozen=True, slots=True)
class CPC3PumpOverviewReport:
    ecu: str
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


@dataclass(frozen=True, slots=True)
class ECUSoftwareFrequency:
    """Case-cohort concentration, not an ECU fleet failure risk."""

    version: str
    cases: int
    fins: int
    with_pre_dtc: int
    with_pre_complete_comparison: int
    same_dtc_returned: int

    @property
    def recurrence_percent(self) -> float | None:
        if self.with_pre_complete_comparison < 5:
            return None
        return 100 * self.same_dtc_returned / self.with_pre_complete_comparison


def ecu_software_frequencies(
    cases: Iterable[CPC3PumpOverviewCase],
) -> tuple[ECUSoftwareFrequency, ...]:
    """Exactly one version per QEC case (closest unambiguous pre-swap SW).

    Frequencies only apply to observed failed-pump cases. Without an
    installed-vehicle denominator they are not a software defect *risk*.
    """
    group: dict[str, list[CPC3PumpOverviewCase]] = defaultdict(list)
    for case in cases:
        if case.before_sw and not case.truncated:
            group[case.before_sw].append(case)
    result = []
    for sw, group_cases in group.items():
        compared = [
            row for row in group_cases
            if row.pre_complete_tests > 0 and row.post_complete_tests > 0
            and bool(row.pre_cpc3_dtcs)
        ]
        result.append(ECUSoftwareFrequency(
            version=sw, cases=len(group_cases),
            fins=len({row.fin for row in group_cases}),
            with_pre_dtc=sum(row.pre_dtc_evidence == "present" for row in group_cases),
            with_pre_complete_comparison=len(compared),
            same_dtc_returned=sum(bool(row.returned_dtcs) for row in compared),
        ))
    return tuple(sorted(
        result, key=lambda x: (-x.with_pre_dtc, -x.cases, x.version),
    ))


def _complete_cpc3_tests(
    case: NTFCase, ecu: str = "CPC3",
) -> tuple[DiagnosticSession, ...]:
    """Only complete PDF tests that also demonstrably contained CPC3."""
    sessions = {
        event.session_id
        for event in case.ecu_states
        if event.ecu.strip().upper() == ecu and event.session_id
    }
    return tuple(sorted(
        (
            event for event in case.diagnostic_sessions
            if event.session_id in sessions
            and getattr(event, "source_is_complete_quicktest", False)
        ),
        key=lambda event: (event.occurred_at, event.session_id),
    ))


def _fault_codes(
    case: NTFCase, session: DiagnosticSession, ecu: str = "CPC3",
) -> frozenset[str]:
    return frozenset(
        event.dtc_code.strip().upper()
        for event in case.diagnostics
        if event.session_id == session.session_id
        and event.ecu.strip().upper() == ecu
        and event.dtc_code.strip()
    )


def _outcome(
    case: NTFCase, swap_day: date | None, *, ecu: str = "CPC3",
) -> tuple[str, tuple[str, ...], tuple[str, ...], tuple[str, ...], int, int]:
    """CPC3 DTC observed in actual complete QTs around the pump replacement.

    Date-only swap anchors rule out all same-day sessions. Use ALL later
    complete sessions for recurrence, not just the first convenient scan.
    """
    if swap_day is None:
        return "Tauschdatum fehlt", (), (), (), 0, 0
    sessions = _complete_cpc3_tests(case, ecu)
    before = [s for s in sessions if s.occurred_at.date() < swap_day]
    after = [s for s in sessions if s.occurred_at.date() > swap_day]
    if not before or not after:
        return "Vollständige CPC3-QuickTests fehlen", (), (), (), len(before), len(after)
    # A single pre-test is a limited baseline, not a claim of fault healing.
    baseline = max(before, key=lambda s: (s.occurred_at, s.session_id))
    pre = _fault_codes(case, baseline, ecu)
    post = set().union(*(_fault_codes(case, s, ecu) for s in after))
    returned = pre & post
    if not pre:
        status = "Kein ECU-Ausgangs-DTC im letzten Vortest"
    elif returned:
        status = "ECU-DTC erneut nach Tausch beobachtet"
    else:
        status = f"ECU-DTC in {len(after)} Nachtests nicht erneut gesehen"
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


def _effect_after_software_action(
    case: NTFCase, review: CPC3SoftwareReview,
    swap_day: date | None, *, days: int, ecu: str = "CPC3",
) -> tuple[str, int, int, tuple[str, ...]]:
    """Compare complete CPC3 tests around an explicitly recorded SW action.

    Even a clearly worded update and vanishing DTCs only support temporal
    association. A pump replacement between tests is a major confounder.
    """
    if swap_day is None:
        return "SW-Wirkung nicht beurteilbar: Tauschdatum fehlt", 0, 0, ()
    actions = [
        event for event in review.documented_actions
        if is_reported_software_update(event)
        and abs((event.occurred_at.date() - swap_day).days) <= days
    ]
    if not actions:
        return (
            "SW-Updatedatum nicht dokumentiert: SW-Lösung nicht zuordenbar",
            0, 0, (),
        )
    if len(actions) != 1:
        return (
            "Mehrere SW-Maßnahmen: Wirkung nicht einzeln zuordenbar",
            0, 0, (),
        )
    sw_day = actions[0].occurred_at.date()
    sessions = _complete_cpc3_tests(case, ecu)
    before = [
        session for session in sessions
        if session.occurred_at.date() < sw_day
    ]
    after = [
        session for session in sessions
        if session.occurred_at.date() > sw_day
    ]
    if not before or not after:
        return (
            "SW-Wirkung nicht beurteilbar: vollständige "
            "ECU-QuickTests vor/nach SW-Maßnahme fehlen",
            len(before), len(after), (),
        )
    latest = max(before, key=lambda s: (s.occurred_at, s.session_id))
    old_codes = _fault_codes(case, latest, ecu)
    new_codes = set().union(*(_fault_codes(case, s, ecu) for s in after))
    returning = tuple(sorted(old_codes & new_codes))
    if not old_codes:
        label = "SW-Wirkung nicht beurteilbar: kein ECU-Ausgangs-DTC"
    elif returning:
        label = "ECU-DTC nach SW-Maßnahme erneut gesehen; keine SW-Lösung belegt"
    elif (
        latest.occurred_at.date() <= swap_day
        <= max(session.occurred_at.date() for session in after)
    ):
        label = (
            "ECU-DTC nach SW nicht erneut gesehen; Pumpentausch "
            "im Messfenster, SW-Wirkung nicht isolierbar"
        )
    else:
        label = (
            "ECU-DTC nach SW nicht erneut gesehen; zeitlicher "
            "Hinweis, keine kausal bestätigte SW-Heilung"
        )
    return label, len(before), len(after), returning


def _ecu_fault_presence(
    case: NTFCase, autoexport_rows: Iterable[dict],
    swap_day: date | None, ecu: str,
) -> tuple[str, str, tuple[str, ...], tuple[str, ...]]:
    """Combine *positive* AutoExport evidence with complete ECU PDF scans.

    Neither a missing AutoExport row nor an ECU without a full QuickTest is a
    negative test. Same-day observations are not temporally assigned.
    """
    if swap_day is None:
        return "unknown", "unknown", (), ()
    pre: set[str] = set()
    post: set[str] = set()
    for event in case.diagnostics:
        if event.ecu.strip().upper() != ecu or not event.dtc_code.strip():
            continue
        when = event.occurred_at.date()
        if when < swap_day:
            pre.add(event.dtc_code.strip().upper())
        elif when > swap_day:
            post.add(event.dtc_code.strip().upper())
    for raw in autoexport_rows:
        moment = _read_autoexport_time(raw)
        if moment is None:
            continue
        day = moment[0].date()
        codes = {
            str(code).strip().upper()
            for code in raw.get("dtc_codes", ())
            if str(code).strip()
        }
        single = str(raw.get("dtc_code") or "").strip().upper()
        if single:
            codes.add(single)
        if day < swap_day:
            pre.update(codes)
        elif day > swap_day:
            post.update(codes)
    sessions = _complete_cpc3_tests(case, ecu)
    pre_complete = any(s.occurred_at.date() < swap_day for s in sessions)
    post_complete = any(s.occurred_at.date() > swap_day for s in sessions)
    pre_group = (
        "present" if pre else "tested_none" if pre_complete else "unknown"
    )
    post_group = (
        "present" if post else "tested_none" if post_complete else "unknown"
    )
    return pre_group, post_group, tuple(sorted(pre)), tuple(sorted(post))


def _all_versions_and_observations(
    review: CPC3SoftwareReview,
) -> tuple[
    tuple[str, ...], tuple[str, ...],
    tuple[tuple[str, str, str, str], ...],
]:
    sw_versions: list[str] = []
    history: list[str] = []
    detail: list[tuple[str, str, str, str]] = []
    previous_sw = None
    for state in review.states:
        sw = str(state.software_version or "").strip()
        if not sw:
            continue
        if sw.casefold() not in {value.casefold() for value in sw_versions}:
            sw_versions.append(sw)
        day = state.occurred_at.date()
        if review.replacement_day is None:
            relative = "Tauschdatum unbekannt"
        elif day < review.replacement_day:
            relative = "vor Tausch"
        elif day > review.replacement_day:
            relative = "nach Tausch"
        else:
            relative = "Tauschtag (Reihenfolge unbekannt)"
        moment = (
            state.occurred_at.strftime("%d.%m.%Y (nur Datum)")
            if getattr(state, "time_precision", "datetime") == "date"
            else state.occurred_at.strftime("%d.%m.%Y %H:%M")
        )
        detail.append((moment, sw, relative, state.source_ref or ""))
        if sw.casefold() != previous_sw:
            history.append(f"{sw} ({moment})")
            previous_sw = sw.casefold()
    return tuple(sw_versions), tuple(history), tuple(detail)


def evaluate_cpc3_pump_case(
    case: NTFCase,
    *,
    autoexport_rows: Iterable[dict] = (),
    truncated: bool = False,
    nearby_days: int = 14,
    ecu: str = "CPC3",
) -> CPC3PumpOverviewCase:
    """Assess one true case using its own complete QuickTest associations."""
    if nearby_days < 0:
        raise ValueError("Zeitfenster darf nicht negativ sein.")
    chosen_ecu = str(ecu or "").strip().upper()
    source_rows = tuple(autoexport_rows)
    review = assess_ecu_software(
        case, ecu=chosen_ecu, autoexport_rows=source_rows,
        truncated=truncated,
    )
    swap_day = review.replacement_day
    update, group, actions, interval = _update_near_swap(
        review, swap_day, days=nearby_days,
    )
    dtc, pre_codes, post_codes, returned, n_pre, n_post = _outcome(
        case, swap_day, ecu=chosen_ecu,
    )
    pre_group, post_group, pre_observed, post_observed = _ecu_fault_presence(
        case, source_rows, swap_day, chosen_ecu,
    )
    versions, history, observations = _all_versions_and_observations(review)
    effect, sw_pre_tests, sw_post_tests, sw_returned = (
        _effect_after_software_action(
            case, review, swap_day, days=nearby_days, ecu=chosen_ecu,
        )
    )
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
        missing.append("kein vollständiger ECU-Vor- und Nachtest")
    missing.append(
        "Pumpentausch ist ein konkurrierender Eingriff; DTC-Verlauf "
        "beweist keine kausale SW-Heilung"
    )
    return CPC3PumpOverviewCase(
        case_id=case.case_id, fin=case.vin,
        component=case.component_type, swap_day=swap_day,
        ecu=chosen_ecu,
        sw_versions=versions, sw_history=history,
        sw_observations=observations,
        pre_dtc_evidence=pre_group, post_dtc_evidence=post_group,
        pre_dtc_observed=pre_observed, post_dtc_observed=post_observed,
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
        sw_effect=effect,
        sw_pre_complete_tests=sw_pre_tests,
        sw_post_complete_tests=sw_post_tests,
        sw_post_returned_dtcs=sw_returned,
        note="; ".join(missing), truncated=review.truncated,
    )


def build_cpc3_pump_overview(
    cases: Iterable[NTFCase],
    *,
    load_autoexport: Callable[[str], tuple[list[dict], bool]] | None = None,
    load_ecu_history: Callable[
        [list[str], str], dict[str, tuple[list[dict], bool]]
    ] | None = None,
    nearby_days: int = 14,
    ecu: str = "CPC3",
) -> CPC3PumpOverviewReport:
    """A stable per-case cohort. Read each FIN's local AutoExport rows once."""
    pump_cases = sorted(
        (case for case in cases if is_pump_case(case)),
        key=lambda item: (item.vin, item.case_id),
    )
    source_cache: dict[str, tuple[list[dict], bool]] = {}
    if load_ecu_history is not None and pump_cases:
        source_cache.update(load_ecu_history(
            sorted({case.vin for case in pump_cases}), ecu,
        ))
    rows = []
    for case in pump_cases:
        if case.vin not in source_cache:
            source_cache[case.vin] = (
                load_autoexport(case.vin) if load_autoexport else ([], False)
            )
        data, truncated = source_cache[case.vin]
        rows.append(evaluate_cpc3_pump_case(
            case, ecu=ecu, autoexport_rows=data,
            truncated=truncated, nearby_days=nearby_days,
        ))
    counter = Counter(row.update_group for row in rows)
    return CPC3PumpOverviewReport(
        ecu=str(ecu or "").strip().upper(),
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
