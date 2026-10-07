from ntf_insight.demo.synthetic_cases import build_demo_cases
from ntf_insight.demo.synthetic_reference import build_demo_reference_repository
from ntf_insight.reporting.markdown import render_case_report, save_case_report


def test_markdown_case_report_contains_traceable_analysis_sections(tmp_path) -> None:
    case = build_demo_cases()[0]
    references = build_demo_reference_repository()

    text = render_case_report(case, references)

    assert f"# NTF Insight Case Report — {case.case_id}" in text
    assert "## Pre/post replacement analysis" in text
    assert "## Generated evidence" in text
    assert "## Data quality" in text
    assert "## Timeline" in text

    path = save_case_report(tmp_path / "case.md", case, references)
    assert path.read_text(encoding="utf-8") == text
