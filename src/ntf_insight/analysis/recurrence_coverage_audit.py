"""Read-only explanation of *missing* before/after diagnostic session evidence.

A QEC DTC row is NOT a complete diagnostic session. FIN-scope QuickTest reports
are only search hints, especially if one VIN has several QEC replacements.
No session is attached or synthesized; no new recurrence conclusion is made.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from ntf_insight.analysis.recurrence import analyze_recurrence, relative_to_replacement
from ntf_insight.domain.case import NTFCase


class _QuickTestReports(Protocol):
    def report_summaries_for_fins(
        self, fins: set[str]
    ) -> dict[str, list[tuple[datetime, int]]]: ...


@dataclass(frozen=True, slots=True)
class RecurrenceCoverageCase:
    case_id: str
    vin: str
    before_dtc_count: int
    after_dtc_count: int
    same_day_or_unknown_dtc_count: int
    before_session_count: int
    after_session_count: int
    same_day_or_unknown_session_count: int
    before_complete_qt_count: int
    after_complete_qt_count: int
    recurrence_assessable: bool
    recurrence_observed: bool | None
    missing_evidence_reason: str
    raw_qt_before: int | None
    raw_qt_same_day: int | None
    raw_qt_after: int | None
    multiple_qec_same_fin: bool


@dataclass(frozen=True, slots=True)
class RecurrenceCoverageReport:
    cases: tuple[RecurrenceCoverageCase, ...]
    qec_with_before_dtc: int
    qec_with_after_dtc: int
    qec_with_before_session: int
    qec_with_after_session: int
    assessable_qec: int
    qec_missing_both_sessions: int
    qec_missing_before_session: int
    qec_missing_after_session: int
    pre_dtc_but_no_pre_session: int
    raw_qt_available: bool
    raw_qt_possible_before: int
    raw_qt_possible_after: int
    repeated_fin_cases: int


def audit_recurrence_coverage(
    cases: list[NTFCase],
    *,
    quicktests: _QuickTestReports | None = None,
) -> RecurrenceCoverageReport:
    """Explain missing sessions without changing case models or ML signatures."""
    if len({case.case_id for case in cases}) != len(cases):
        raise ValueError("Mehrfach vorhandene QEC-Fall-ID in Sitzungsprüfung.")
    fin_counts = Counter(case.vin for case in cases)
    reports = (
        quicktests.report_summaries_for_fins(set(fin_counts))
        if quicktests is not None and cases else {}
    )
    rows: list[RecurrenceCoverageCase] = []
    for case in sorted(cases, key=lambda item: item.case_id):
        anchor = case.investigated_replacement()
        pre_dtc = post_dtc = unknown_dtc = 0
        pre_session = post_session = unknown_session = 0
        pre_complete = post_complete = 0
        if anchor is not None:
            for event in case.diagnostics:
                side = relative_to_replacement(event, anchor)
                if side == "pre":
                    pre_dtc += 1
                elif side == "post":
                    post_dtc += 1
                else:
                    unknown_dtc += 1
            for session in case.diagnostic_sessions:
                side = relative_to_replacement(session, anchor)
                if side == "pre":
                    pre_session += 1
                    pre_complete += int(
                        getattr(session, "source_is_complete_quicktest", False)
                    )
                elif side == "post":
                    post_session += 1
                    post_complete += int(
                        getattr(session, "source_is_complete_quicktest", False)
                    )
                else:
                    unknown_session += 1
        else:
            unknown_dtc = len(case.diagnostics)
            unknown_session = len(case.diagnostic_sessions)

        # Raw PDF sessions are FIN-level evidence, never proof that a
        # particular returned-part QEC case owns this report.
        raw_before = raw_day = raw_after = 0
        if quicktests is not None and anchor is not None:
            for when, _dtc_count in reports.get(case.vin, []):
                if when.date() == anchor.occurred_at.date():
                    # Raw chronology may be on a different clock and the
                    # replacement often only has date precision.
                    raw_day += 1
                elif when < anchor.occurred_at:
                    raw_before += 1
                elif when > anchor.occurred_at:
                    raw_after += 1
        recurrence = analyze_recurrence(case)
        if anchor is None:
            reason = "Tauschanker fehlt"
        elif recurrence.assessable:
            reason = "QEC-Vorher- und Nachher-Sitzung dokumentiert"
        elif not pre_session and not post_session:
            reason = "Beide QEC-Diagnosesitzungen fehlen"
        elif not pre_session:
            reason = "Vorher-Diagnosesitzung fehlt"
        else:
            reason = "Nachher-Diagnosesitzung fehlt"
        rows.append(RecurrenceCoverageCase(
            case_id=case.case_id,
            vin=case.vin,
            before_dtc_count=pre_dtc, after_dtc_count=post_dtc,
            same_day_or_unknown_dtc_count=unknown_dtc,
            before_session_count=pre_session, after_session_count=post_session,
            same_day_or_unknown_session_count=unknown_session,
            before_complete_qt_count=pre_complete,
            after_complete_qt_count=post_complete,
            recurrence_assessable=recurrence.assessable,
            recurrence_observed=(
                recurrence.has_recurrence if recurrence.assessable else None
            ),
            missing_evidence_reason=reason,
            raw_qt_before=raw_before if quicktests is not None else None,
            raw_qt_same_day=raw_day if quicktests is not None else None,
            raw_qt_after=raw_after if quicktests is not None else None,
            multiple_qec_same_fin=fin_counts[case.vin] > 1,
        ))
    return RecurrenceCoverageReport(
        cases=tuple(rows),
        qec_with_before_dtc=sum(r.before_dtc_count > 0 for r in rows),
        qec_with_after_dtc=sum(r.after_dtc_count > 0 for r in rows),
        qec_with_before_session=sum(r.before_session_count > 0 for r in rows),
        qec_with_after_session=sum(r.after_session_count > 0 for r in rows),
        assessable_qec=sum(r.recurrence_assessable for r in rows),
        qec_missing_both_sessions=sum(
            r.missing_evidence_reason == "Beide QEC-Diagnosesitzungen fehlen"
            for r in rows
        ),
        qec_missing_before_session=sum(
            r.missing_evidence_reason == "Vorher-Diagnosesitzung fehlt"
            for r in rows
        ),
        qec_missing_after_session=sum(
            r.missing_evidence_reason == "Nachher-Diagnosesitzung fehlt"
            for r in rows
        ),
        pre_dtc_but_no_pre_session=sum(
            r.before_dtc_count > 0 and not r.before_session_count for r in rows
        ),
        raw_qt_available=quicktests is not None,
        raw_qt_possible_before=sum(bool(r.raw_qt_before) for r in rows),
        raw_qt_possible_after=sum(bool(r.raw_qt_after) for r in rows),
        repeated_fin_cases=sum(r.multiple_qec_same_fin for r in rows),
    )
