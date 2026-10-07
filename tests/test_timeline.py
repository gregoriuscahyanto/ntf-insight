from ntf_insight.analysis.timeline import build_timeline
from ntf_insight.demo.synthetic_cases import build_demo_cases


def _case(case_id: str):
    return next(case for case in build_demo_cases() if case.case_id == case_id)


def test_timeline_is_chronological() -> None:
    entries = build_timeline(_case("DEMO-001"))
    timestamps = [entry.occurred_at for entry in entries]

    assert timestamps == sorted(timestamps)
    assert any(entry.kind == "replacement" for entry in entries)
    assert any(entry.kind == "diagnostic_session" for entry in entries)
    assert any(entry.kind == "supplier" for entry in entries)
