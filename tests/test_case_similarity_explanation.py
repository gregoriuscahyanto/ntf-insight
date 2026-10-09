"""Numerical explanations must reproduce the existing cluster comparison."""

from math import isclose

from ntf_insight.analysis.case_clustering import (
    VIEW_WEIGHTS,
    compare_diagnostic_cases,
)
from ntf_insight.analysis.case_projection import project_diagnostic_cases
from ntf_insight.analysis.case_similarity_explanation import explain_case_similarity
from ntf_insight.demo.synthetic_cases import build_demo_cases


def test_weighted_jaccard_table_exactly_matches_cluster_scoring() -> None:
    cases = build_demo_cases()
    for left in cases:
        for right in cases:
            if left.case_id == right.case_id:
                continue
            report = explain_case_similarity(left, right)
            match = compare_diagnostic_cases(left, right)

            assert report.match == match
            assert len(report.contributions) == len(VIEW_WEIGHTS)
            assert isclose(
                sum(row.weight for row in report.contributions),
                1.0, abs_tol=1e-9,
            )
            if match.score is not None:
                assert report.reconstructed_score is not None
                assert abs(report.reconstructed_score - match.score) < 0.00006
                assert isclose(
                    report.covered_weight, match.coverage, abs_tol=1e-6,
                )
                assert isclose(
                    sum(
                        row.normalized_contribution or 0
                        for row in report.contributions
                    ),
                    report.reconstructed_score, abs_tol=1e-9,
                )


def test_no_overlap_or_missing_group_is_not_mislabelled_as_zero_evidence() -> None:
    cases = build_demo_cases()
    report = explain_case_similarity(cases[0], cases[1])
    for group in report.contributions:
        if group.left_count == 0 or group.right_count == 0:
            assert group.jaccard is None
            assert group.normalized_contribution is None
    assert report.covered_weight <= 1.0


def test_svd_reports_real_input_columns_variance_and_top_axis_loadings() -> None:
    projection = project_diagnostic_cases(build_demo_cases())
    assert projection.feature_count > 0
    assert projection.components == 2
    assert len(projection.explained_variance_ratio) == 2
    assert all(0 <= value <= 1 for value in projection.explained_variance_ratio)
    assert len(projection.axis_top_features) >= 2
    for axis, key, loading in projection.axis_top_features:
        assert axis in (1, 2)
        assert "::" in key
        assert -1 <= loading <= 1


def test_single_case_projection_does_not_invent_two_axes() -> None:
    projection = project_diagnostic_cases([build_demo_cases()[0]])
    assert projection.feature_count > 0
    assert projection.components == 0
    assert projection.explained_variance_ratio == ()
    assert projection.points[0].x == 0
    assert projection.points[0].y == 0
