"""Auditable HDBSCAN input population and DTC frequency, never a cause classifier.

All rows count *real QEC cases*, not AUTOEXPORT FINs or individual DTC reports.
Each ECU:DTC can count at most once per QEC case. Source overlap is reported
as evidence availability, not counted a second time in the ML signature.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from ntf_insight.analysis.case_clustering import (
    FaultKey, _in_diagnostic_window, _matches_dtc_source,
    signature_for,
)
from ntf_insight.domain.case import NTFCase


@dataclass(frozen=True, slots=True)
class DiagnosticAvailability:
    case_id: str
    vin: str
    reason: str
    all_event_rows: int
    pre_unique_faults: int
    selected_unique_faults: int
    quicktest_unique_faults: int
    autoexport_unique_faults: int
    overlapping_source_faults: int


@dataclass(frozen=True, slots=True)
class DiagnosticFrequency:
    fault: FaultKey
    case_count: int
    proportion: float
    screened_common: bool


@dataclass(frozen=True, slots=True)
class DiagnosticEvidenceAudit:
    cases: tuple[DiagnosticAvailability, ...]
    frequencies: tuple[DiagnosticFrequency, ...]
    scoped_cases: int
    eligible_cases: int
    without_anchor: int
    without_any_dtc: int
    only_after_swap_or_undated: int
    no_selected_source: int
    outside_lookback: int
    with_source_overlap: int
    overlapping_fault_occurrences: int
    common_cutoff: float
    lookback_days: int | None
    dtc_source: str

    @property
    def excluded_count(self) -> int:
        return self.scoped_cases - self.eligible_cases

    @property
    def high_prevalence_faults(self) -> tuple[DiagnosticFrequency, ...]:
        return tuple(item for item in self.frequencies if item.screened_common)


def audit_diagnostic_evidence(
    cases: list[NTFCase],
    *,
    dtc_source: str = "all",
    lookback_days: int | None = None,
    common_cutoff: float = 0.35,
) -> DiagnosticEvidenceAudit:
    """Explain exactly which cases enter the currently selected ML scenario."""
    if not 0 < common_cutoff <= 1:
        raise ValueError("Die Häufigkeitsgrenze muss im Intervall (0, 1] liegen.")
    # Delegates source/window parameter validation to the same production
    # signature extraction used by HDBSCAN.
    signatures = {
        case.case_id: signature_for(
            case, dtc_source=dtc_source, lookback_days=lookback_days
        ) for case in sorted(cases, key=lambda case: case.case_id)
    }
    if len(signatures) != len(cases):
        raise ValueError("Mehrfach angelegte QEC-Fall-ID in der Diagnosedatenbasis.")
    counts: Counter[FaultKey] = Counter()
    rows: list[DiagnosticAvailability] = []
    reasons: Counter[str] = Counter()
    source_overlap_cases = 0
    source_overlap_count = 0

    for case in sorted(cases, key=lambda item: item.case_id):
        sig = signatures[case.case_id]
        all_events = case.diagnostics
        # These are set-based views: two identical QEC/DTC rows, or the same
        # quicktest fault also in AutoExport, must NOT count twice.
        pre_events = [
            event for event in all_events
            if sig.has_replacement_anchor
            and _in_diagnostic_window(event, case, lookback_days=None)
        ]
        selected_events = [
            event for event in all_events
            if sig.has_replacement_anchor
            and _in_diagnostic_window(event, case, lookback_days=lookback_days)
        ]
        # Source-overlap numbers follow the *selected* diagnostic window;
        # broader pre-history is retained separately for exclusion reasons.
        qt = {
            event.fault_key for event in selected_events
            if _matches_dtc_source(event, "quicktest")
        }
        auto = {
            event.fault_key for event in selected_events
            if _matches_dtc_source(event, "autoexport")
        }
        overlap = qt & auto
        if overlap:
            source_overlap_cases += 1
            source_overlap_count += len(overlap)
        pre_keys = {event.fault_key for event in pre_events}
        selected_keys = {
            event.fault_key for event in selected_events
            if _matches_dtc_source(event, dtc_source)
        }
        # Report one *primary* exclusion reason per case. If there are no
        # DTC rows at all, that is the most immediately actionable barrier,
        # even if the replacement anchor is also missing.
        if not all_events:
            reason = "Kein QEC-zugeordneter DTC dokumentiert"
        elif not sig.has_replacement_anchor:
            reason = "Tauschanker fehlt"
        elif not pre_keys:
            reason = "DTC vorhanden, aber nicht sicher vor dem Tausch"
        elif not selected_keys:
            available_selected_source = {
                event.fault_key for event in pre_events
                if _matches_dtc_source(event, dtc_source)
            }
            if available_selected_source:
                reason = "Vorher-DTC außerhalb des gewählten Zeitfensters"
            else:
                reason = "Keine Vorher-DTC aus ausgewählten Quellen"
        else:
            reason = "Auswertbare Vor-Tausch-Diagnose"
            counts.update(selected_keys)
        reasons[reason] += 1
        rows.append(DiagnosticAvailability(
            case_id=case.case_id,
            vin=case.vin,
            reason=reason,
            all_event_rows=len(all_events),
            pre_unique_faults=len(pre_keys),
            selected_unique_faults=len(selected_keys),
            quicktest_unique_faults=len(qt),
            autoexport_unique_faults=len(auto),
            overlapping_source_faults=len(overlap),
        ))
    eligible = reasons["Auswertbare Vor-Tausch-Diagnose"]
    frequent = tuple(sorted(
        (
            DiagnosticFrequency(
                fault=fault,
                case_count=counter,
                proportion=counter/eligible if eligible else 0.0,
                screened_common=bool(eligible and counter/eligible >= common_cutoff),
            )
            for fault, counter in counts.items()
        ),
        key=lambda x: (-x.case_count, x.fault),
    ))
    return DiagnosticEvidenceAudit(
        cases=tuple(rows), frequencies=frequent,
        scoped_cases=len(cases),
        eligible_cases=eligible,
        without_anchor=reasons["Tauschanker fehlt"],
        without_any_dtc=reasons["Kein QEC-zugeordneter DTC dokumentiert"],
        only_after_swap_or_undated=reasons[
            "DTC vorhanden, aber nicht sicher vor dem Tausch"
        ],
        no_selected_source=reasons[
            "Keine Vorher-DTC aus ausgewählten Quellen"
        ],
        outside_lookback=reasons[
            "Vorher-DTC außerhalb des gewählten Zeitfensters"
        ],
        with_source_overlap=source_overlap_cases,
        overlapping_fault_occurrences=source_overlap_count,
        common_cutoff=common_cutoff,
        lookback_days=lookback_days,
        dtc_source=dtc_source,
    )
