from ntf_insight.analysis.integrity import validate_case_integrity
from ntf_insight.demo.synthetic_cases import build_demo_cases
from ntf_insight.domain.events import DiagnosticEvent


def test_synthetic_case_has_no_integrity_errors() -> None:
    report = validate_case_integrity(build_demo_cases()[0])
    assert report.is_valid is True
    assert report.error_count == 0


def test_integrity_detects_event_vin_mismatch() -> None:
    case = build_demo_cases()[0].model_copy(deep=True)
    case.diagnostics.append(
        DiagnosticEvent(
            vin="OTHER-VIN",
            occurred_at=case.diagnostics[0].occurred_at,
            ecu="CPC3",
            dtc_code="PX",
        )
    )

    report = validate_case_integrity(case)

    assert report.is_valid is False
    assert any(issue.code == "EVENT_VIN_MISMATCH" for issue in report.issues)
