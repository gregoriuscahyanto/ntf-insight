from ntf_insight.analysis.dataset import build_case_feature_frame
from ntf_insight.demo.synthetic_cases import build_demo_cases
from ntf_insight.demo.synthetic_reference import build_demo_reference_repository


def test_feature_frame_contains_one_row_per_case() -> None:
    cases = build_demo_cases()
    frame = build_case_feature_frame(cases, build_demo_reference_repository())

    assert frame.height == len(cases)
    assert "case_id" in frame.columns
    assert "has_recurrence" in frame.columns
    assert "trigger_coverage_ratio" in frame.columns
