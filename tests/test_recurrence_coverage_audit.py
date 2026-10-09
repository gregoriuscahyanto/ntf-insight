"""Synthetic-only audit of missing QEC diagnostic sessions."""
from __future__ import annotations

from datetime import datetime

from ntf_insight.analysis.recurrence_coverage_audit import audit_recurrence_coverage
from ntf_insight.domain.events import DiagnosticEvent, DiagnosticSession
from ntf_insight.storage.duckdb_store import DuckDBStore
from ntf_insight.storage.quicktest_store import QuickTestStore
from test_hdbscan_clustering import sample


def test_pre_dtc_without_session_is_not_a_recurrence_test():
    cases = sample()
    report = audit_recurrence_coverage(cases)
    assert len(report.cases) == len(cases)
    assert report.qec_with_before_dtc == 13
    assert report.pre_dtc_but_no_pre_session == 13
    assert report.qec_with_before_session == 0
    assert report.qec_with_after_session == 0
    assert report.assessable_qec == 0
    assert not report.raw_qt_available
    row = next(r for r in report.cases if r.case_id == "A0")
    assert row.before_dtc_count == 4
    assert row.before_session_count == 0
    assert row.recurrence_observed is None
    assert row.raw_qt_before is None
    assert row.missing_evidence_reason == "Beide QEC-Diagnosesitzungen fehlen"


def test_both_explicit_qec_sessions_allow_recursion_but_do_not_invent_dtc():
    cases = sample()
    case = cases[0]
    case.diagnostic_sessions.extend([
        DiagnosticSession(vin=case.vin, occurred_at=datetime(2026, 4, 29),
                          source_is_complete_quicktest=True),
        DiagnosticSession(vin=case.vin, occurred_at=datetime(2026, 5, 15),
                          source_is_complete_quicktest=True),
    ])
    report = audit_recurrence_coverage(cases)
    row = next(r for r in report.cases if r.case_id == case.case_id)
    assert row.before_session_count == 1
    assert row.after_session_count == 1
    assert row.before_complete_qt_count == 1
    assert row.after_complete_qt_count == 1
    assert row.recurrence_assessable
    assert row.recurrence_observed is False
    assert report.assessable_qec == 1


def test_raw_fin_quicktests_include_zero_dtc_sessions_without_qec_attachment(tmp_path):
    cases = sample()
    cases[1].vehicle = cases[1].vehicle.model_copy(
        update={"vin": cases[0].vin}
    )
    db = DuckDBStore(tmp_path / "fictional.duckdb")
    qt = QuickTestStore(db)
    with db.connect() as con:
        for i, (when, count) in enumerate([
            (datetime(2026, 5, 1), 0),
            (datetime(2026, 5, 10, 10), 1),
            (datetime(2026, 5, 14), 0),
        ], start=1):
            con.execute(
                """INSERT INTO quicktest_reports
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [f"SYN-{i}", cases[0].vin, None, when, None, 0, count,
                 "{}", "SYNTHETIC", datetime(2026, 7, 1)],
            )
    assert qt.report_summaries_for_fins({cases[0].vin})[cases[0].vin][0][1] == 0
    before = [tuple(c.diagnostic_sessions) for c in cases]
    report = audit_recurrence_coverage(cases, quicktests=qt)
    assert report.raw_qt_available
    assert report.raw_qt_possible_before == 2
    assert report.raw_qt_possible_after == 2
    assert report.repeated_fin_cases == 2
    for key in ("A0", "A1"):
        row = next(r for r in report.cases if r.case_id == key)
        assert row.raw_qt_before == 1
        assert row.raw_qt_same_day == 1
        assert row.raw_qt_after == 1
        assert row.multiple_qec_same_fin
        assert row.before_session_count == 0
        assert not row.recurrence_assessable
    assert [tuple(c.diagnostic_sessions) for c in cases] == before


def test_day_only_dtc_same_day_not_counted_before():
    cases = sample()
    case = cases[0]
    case.diagnostics.append(DiagnosticEvent(
        event_id="date-only", vin=case.vin,
        ecu="CPC3", dtc_code="P01",
        occurred_at=datetime(2026, 5, 10, 12),
        time_precision="date",
    ))
    report = audit_recurrence_coverage(cases)
    row = next(r for r in report.cases if r.case_id == case.case_id)
    assert row.before_dtc_count == 4
    assert row.same_day_or_unknown_dtc_count == 1
    assert not row.recurrence_assessable
