"""Synthetic-only regression tests of FIN-local QEC diagnostic gap audit."""
from datetime import datetime

from ntf_insight.analysis.diagnostic_evidence_audit import audit_diagnostic_evidence
from ntf_insight.analysis.diagnostic_gap_investigation import investigate_diagnostic_gaps
from ntf_insight.domain.events import DiagnosticEvent

from test_hdbscan_clustering import sample


class QuickTests:
    def diagnostic_times_for_fins(self, fins):
        return {
            fin: [(datetime(2026, 5, 10, 9), 2), (datetime(2026, 5, 21), 1)]
            for fin in fins
        }


class AutoExport:
    def diagnostic_times_for_fins(self, fins):
        return {
            fin: [
                (None, "2026-05-10", 3),
                ("2026-04-20T09:00:00Z", "2026-04-20", 1),
                ("broken", None, 2),
            ] for fin in fins
        }


def test_qec_missing_and_unanchored_stay_excluded_despite_raw_hints():
    cases = sample()
    audit = audit_diagnostic_evidence(cases)
    original = [tuple(c.diagnostics) for c in cases]
    result = investigate_diagnostic_gaps(
        cases, audit, quicktests=QuickTests(), autoexport=AutoExport()
    )
    assert len(result.cases) == 2
    assert result.missing_qec_dtc == 1
    assert result.other_exclusions == 1
    empty = next(row for row in result.cases if row.case_id == "EMPTY")
    assert not empty.raw_pre_hint
    assert "Tauschanker" in empty.detail
    unanchored = next(r for r in result.cases if r.case_id == "UNANCHORED")
    assert unanchored.raw_pre_dtc_rows == 0
    assert [tuple(c.diagnostics) for c in cases] == original


def test_raw_evidence_cannot_fabricate_new_eligible_qec_case():
    cases = sample()
    case = cases[0]
    case.diagnostics.clear()
    audit = audit_diagnostic_evidence(cases)
    report = investigate_diagnostic_gaps(
        cases, audit, quicktests=QuickTests(), autoexport=AutoExport()
    )
    row = next(x for x in report.cases if x.case_id == case.case_id)
    assert row.raw_pre_dtc_rows == 3
    assert row.raw_same_day_dtc_rows == 3
    assert row.raw_post_dtc_rows == 1
    assert row.raw_unusable_date_rows == 2
    assert row.raw_quicktest_dtc_rows == 3
    assert row.raw_autoexport_dtc_rows == 6
    assert row.raw_pre_hint
    assert not case.diagnostics
    assert audit.eligible_cases == 12


def test_date_only_qec_event_same_day_is_unknown_not_pre():
    cases = sample()
    case = cases[0]
    case.diagnostics = [DiagnosticEvent(
        event_id="same-day", vin=case.vin, ecu="CPC3", dtc_code="P00TEST",
        occurred_at=datetime(2026, 5, 10, 12), time_precision="date",
    )]
    audit = audit_diagnostic_evidence(cases)
    row = next(r for r in audit.cases if r.case_id == case.case_id)
    assert "nicht sicher vor" in row.reason
    report = investigate_diagnostic_gaps(cases, audit)
    finding = next(r for r in report.cases if r.case_id == case.case_id)
    assert finding.qec_same_day == 1
    assert not finding.raw_pre_hint


def test_raw_repeated_fin_does_not_create_case_specific_evidence():
    cases = sample()
    cases[1].vehicle = cases[1].vehicle.model_copy(
        update={"vin": cases[0].vin}
    )
    for case in cases[:2]:
        case.diagnostics.clear()
    audit = audit_diagnostic_evidence(cases)
    rows = investigate_diagnostic_gaps(
        cases, audit, quicktests=QuickTests()
    ).cases
    matched = [r for r in rows if r.case_id in {"A0", "A1"}]
    assert len(matched) == 2
    assert all(r.raw_pre_dtc_rows == 2 for r in matched)
    assert all(len(c.diagnostics) == 0 for c in cases[:2])
