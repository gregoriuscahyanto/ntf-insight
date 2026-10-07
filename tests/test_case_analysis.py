from ntf_insight.analysis.case_analysis import analyze_case
from ntf_insight.demo.synthetic_cases import build_demo_cases
from ntf_insight.demo.synthetic_reference import build_demo_reference_repository


def test_unified_case_analysis_combines_deterministic_layers() -> None:
    case = build_demo_cases()[0]
    result = analyze_case(case, build_demo_reference_repository())

    assert result.case_id == case.case_id
    assert result.timeline
    assert result.features.has_recurrence is True
    assert result.quality.trigger_coverage_ratio == 1.0
    assert result.evidence.evidence
