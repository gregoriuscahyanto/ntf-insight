"""Read-only, FIN-scoped investigation of QEC diagnostic coverage gaps.

Separate QEC-attached events from independently stored QuickTest / AutoExport
history. Finding raw FIN evidence is NOT a safe QEC-case association and must
never repair source data, replacement anchors or ML labels automatically.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from ntf_insight.analysis.diagnostic_evidence_audit import DiagnosticEvidenceAudit
from ntf_insight.analysis.recurrence import relative_to_replacement
from ntf_insight.domain.case import NTFCase


class _QuickTestLookup(Protocol):
    def diagnostic_times_for_fins(
        self, fins: set[str]
    ) -> dict[str, list[tuple[datetime, int]]]: ...


class _AutoExportLookup(Protocol):
    def diagnostic_times_for_fins(
        self, fins: set[str]
    ) -> dict[str, list[tuple[str | None, str | None, int]]]: ...


@dataclass(frozen=True, slots=True)
class DiagnosticGapCase:
    case_id: str
    vin: str
    exclusion: str
    detail: str
    qec_same_day: int
    qec_after: int
    qec_other_unknown: int
    raw_pre_dtc_rows: int
    raw_same_day_dtc_rows: int
    raw_post_dtc_rows: int
    raw_unusable_date_rows: int
    raw_quicktest_dtc_rows: int
    raw_autoexport_dtc_rows: int

    @property
    def raw_pre_hint(self) -> bool:
        return self.raw_pre_dtc_rows > 0


@dataclass(frozen=True, slots=True)
class DiagnosticGapReport:
    cases: tuple[DiagnosticGapCase, ...]
    missing_qec_dtc: int
    unsafe_time: int
    other_exclusions: int
    raw_available: bool
    with_raw_pre_hint: int
    qec_same_day_cases: int
    qec_post_only_cases: int


def _when(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        # Match source import: retain source clock instead of inventing
        # a timezone conversion to the workshop's local time.
        return datetime.fromisoformat(raw.strip().replace("Z", "+00:00")).replace(
            tzinfo=None
        )
    except ValueError:
        return None


def _side(when: datetime | None, precision: str, anchor) -> str:
    if when is None:
        return "unknown"
    if (
        when.date() == anchor.occurred_at.date()
        and (precision == "date" or getattr(anchor, "time_precision", "") == "date")
    ):
        return "same_day"
    if when < anchor.occurred_at:
        return "pre"
    if when > anchor.occurred_at:
        return "post"
    return "unknown"


def investigate_diagnostic_gaps(
    cases: list[NTFCase],
    audit: DiagnosticEvidenceAudit,
    *,
    quicktests: _QuickTestLookup | None = None,
    autoexport: _AutoExportLookup | None = None,
) -> DiagnosticGapReport:
    """Inspect excluded cases only; raw FIN sources are non-binding leads.

    All raw timestamps are retained as reported. The returned case counts
    describe the *same* QEC exclusion population as the existing audit.
    QEC cases from one FIN remain separate and are never automatically linked.
    """
    by_case = {c.case_id: c for c in cases}
    if len(by_case) != len(cases) or len(audit.cases) != len(cases):
        raise ValueError("Diagnoseprüfung passt nicht zum QEC-Fallbestand.")
    excluded = [r for r in audit.cases if r.reason != "Auswertbare Vor-Tausch-Diagnose"]
    if set(r.case_id for r in audit.cases) != set(by_case):
        raise ValueError("Diagnoseprüfung enthält andere QEC-Fall-IDs.")
    fins = {by_case[r.case_id].vin for r in excluded}
    qt = quicktests.diagnostic_times_for_fins(fins) if quicktests is not None and fins else {}
    auto = autoexport.diagnostic_times_for_fins(fins) if autoexport is not None and fins else {}
    output: list[DiagnosticGapCase] = []
    hints = same_day_cases = post_only_cases = 0
    for row in excluded:
        case = by_case[row.case_id]
        anchor = case.investigated_replacement()
        qec_same = qec_post = qec_unknown = 0
        pre = same_day = post = unknown = raw_qt = raw_auto = 0
        if anchor is not None:
            for event in case.diagnostics:
                status = relative_to_replacement(event, anchor)
                if status == "post":
                    qec_post += 1
                elif status == "unknown":
                    if event.occurred_at.date() == anchor.occurred_at.date():
                        qec_same += 1
                    else:
                        qec_unknown += 1
            for when, count in qt.get(case.vin, []):
                if count <= 0:
                    continue
                raw_qt += count
                side = _side(when, "datetime", anchor)
                if side == "pre":
                    pre += count
                elif side == "same_day":
                    same_day += count
                elif side == "post":
                    post += count
                else:
                    unknown += count
            for exact, day, count in auto.get(case.vin, []):
                if count <= 0:
                    continue
                raw_auto += count
                parsed_exact = _when(exact)
                parsed_day = _when(day)
                side = _side(
                    parsed_exact or parsed_day,
                    "datetime" if parsed_exact is not None else "date",
                    anchor,
                )
                if side == "pre":
                    pre += count
                elif side == "same_day":
                    same_day += count
                elif side == "post":
                    post += count
                else:
                    unknown += count
        if qec_same:
            same_day_cases += 1
        if qec_post and not qec_same:
            post_only_cases += 1
        if pre:
            hints += 1
        if anchor is None:
            detail = "Tauschanker fehlt; FIN-Rohdaten nicht zeitlich bewertbar"
        elif pre:
            detail = "Vor-Tausch-Hinweis in FIN-Rohquelle – QEC-Zuordnung fachlich prüfen"
        elif qec_same:
            detail = "QEC-DTC am Tauschtag: Reihenfolge nicht nachgewiesen"
        elif qec_post:
            detail = "QEC-DTC erst nach Tausch; kein belegter Vorher-DTC"
        elif same_day:
            detail = "FIN-Rohquelle am Tauschtag; Reihenfolge unklar"
        elif not (quicktests or autoexport):
            detail = "FIN-Rohquellen nicht angebunden – keine Aussage zur Verfügbarkeit"
        elif post:
            detail = "FIN-Rohquelle nur nach Tausch; keine Vorher-Evidenz"
        elif unknown:
            detail = "FIN-Rohquelle mit ungültiger/fehlender Zeitinformation"
        else:
            detail = "In angebundenen FIN-Rohquellen kein Vor-Tausch-Hinweis"
        output.append(DiagnosticGapCase(
            case_id=case.case_id, vin=case.vin, exclusion=row.reason,
            detail=detail, qec_same_day=qec_same, qec_after=qec_post,
            qec_other_unknown=qec_unknown, raw_pre_dtc_rows=pre,
            raw_same_day_dtc_rows=same_day, raw_post_dtc_rows=post,
            raw_unusable_date_rows=unknown, raw_quicktest_dtc_rows=raw_qt,
            raw_autoexport_dtc_rows=raw_auto,
        ))
    return DiagnosticGapReport(
        cases=tuple(output),
        missing_qec_dtc=audit.without_any_dtc,
        unsafe_time=audit.only_after_swap_or_undated,
        other_exclusions=(
            audit.without_anchor + audit.no_selected_source + audit.outside_lookback
        ),
        raw_available=quicktests is not None or autoexport is not None,
        with_raw_pre_hint=hints,
        qec_same_day_cases=same_day_cases,
        qec_post_only_cases=post_only_cases,
    )
