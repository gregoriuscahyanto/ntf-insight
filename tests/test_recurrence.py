from ntf_insight.analysis.recurrence import analyze_recurrence
from ntf_insight.demo.synthetic_cases import build_demo_cases


def _case(case_id: str):
    return next(case for case in build_demo_cases() if case.case_id == case_id)


def test_same_fault_after_replacement_is_detected() -> None:
    result = analyze_recurrence(_case("DEMO-001"))

    assert result.assessable is True
    assert result.has_recurrence is True
    assert ("CPC3", "P26F100") in result.same_faults
    assert result.first_recurrence_after is not None
    assert result.first_recurrence_after.days == 2
    assert result.distance_to_recurrence_km == 50


def test_known_post_test_can_show_disappeared_fault() -> None:
    result = analyze_recurrence(_case("DEMO-002"))

    assert result.assessable is True
    assert result.has_recurrence is False
    assert ("CPC3", "P260000") in result.disappeared_faults


def test_missing_post_test_is_not_interpreted_as_disappearance() -> None:
    result = analyze_recurrence(_case("DEMO-005"))

    assert result.assessable is False
    assert result.has_post_test is False
    assert result.disappeared_faults == frozenset()


def test_new_fault_after_replacement_is_detected() -> None:
    result = analyze_recurrence(_case("DEMO-006"))

    assert result.assessable is True
    assert ("CPC3", "P260100") in result.new_faults
    assert ("CPC3", "P260000") in result.disappeared_faults
