from ntf_insight.analysis.data_quality import QualityStatus, assess_data_quality
from ntf_insight.analysis.evidence_engine import generate_case_evidence
from ntf_insight.analysis.features import extract_case_features
from ntf_insight.analysis.similarity import compare_cases
from ntf_insight.demo.synthetic_cases import build_demo_cases
from ntf_insight.demo.synthetic_reference import build_demo_reference_repository
from ntf_insight.domain.enums import RootCauseCategory


def _case(case_id: str):
    return next(case for case in build_demo_cases() if case.case_id == case_id)


def test_reference_coverage_and_data_quality() -> None:
    references = build_demo_reference_repository()
    report = assess_data_quality(_case("DEMO-001"), references)

    assert report.status_for("replacement_anchor") == QualityStatus.OK
    assert report.status_for("post_test") == QualityStatus.OK
    assert report.trigger_coverage_ratio == 1.0


def test_missing_post_test_remains_visible_in_data_quality() -> None:
    report = assess_data_quality(_case("DEMO-005"), build_demo_reference_repository())

    assert report.status_for("post_test") == QualityStatus.MISSING


def test_multi_ecu_supply_evidence_is_generated_from_semantic_tags() -> None:
    bundle = generate_case_evidence(_case("DEMO-003"), build_demo_reference_repository())

    assert any(item.code == "MULTI_ECU_SUPPLY_VOLTAGE" for item in bundle.evidence)
    assert bundle.balance_by_category()[RootCauseCategory.ELECTRICAL_SUPPLY] > 0


def test_case_features_are_interpretable() -> None:
    features = extract_case_features(_case("DEMO-001"), build_demo_reference_repository())

    assert features.recurrence_assessable is True
    assert features.has_recurrence is True
    assert features.trigger_coverage_ratio == 1.0


def test_similarity_exposes_shared_diagnostic_pattern() -> None:
    result = compare_cases(_case("DEMO-001"), _case("DEMO-003"))

    assert ("CPC3", "P26F100") in result.shared_faults
    assert 0.0 <= result.score <= 1.0
