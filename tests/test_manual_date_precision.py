from datetime import datetime

from ntf_insight.analysis.data_quality import QualityStatus, assess_data_quality
from ntf_insight.analysis.recurrence import analyze_recurrence, relative_to_replacement
from ntf_insight.domain.case import NTFCase
from ntf_insight.domain.events import DiagnosticEvent, DiagnosticSession, PartReplacement
from ntf_insight.domain.vehicle import Vehicle


def test_day_only_same_day_events_do_not_falsely_count_as_post_test():
    case = NTFCase(
        case_id="MANUAL-DATE-TEST",
        vehicle=Vehicle(vin="W1TTEST0000000001"),
        component_type="Coolant Pump",
    )
    case.diagnostic_sessions.append(
        DiagnosticSession(
            vin=case.vin, occurred_at=datetime(2026, 1, 1, 9), dtc_count=1
        )
    )
    case.diagnostics.append(
        DiagnosticEvent(
            vin=case.vin, occurred_at=datetime(2026, 1, 1, 9),
            ecu="CPC3", dtc_code="P26F100",
        )
    )
    replacement = PartReplacement.model_validate({
        "vin": case.vin,
        "occurred_at": datetime(2026, 1, 2, 12),
        "component_type": "Coolant Pump",
        "time_precision": "date",
    })
    case.replacements.append(replacement)
    same_day_session = DiagnosticSession.model_validate({
        "vin": case.vin,
        "occurred_at": datetime(2026, 1, 2, 15),
        "dtc_count": 0,
        "time_precision": "date",
    })
    case.diagnostic_sessions.append(same_day_session)

    assert relative_to_replacement(same_day_session, replacement) == "unknown"
    result = analyze_recurrence(case)
    assert not result.has_post_test
    assert not result.assessable
    assert assess_data_quality(case).status_for("time_precision") == QualityStatus.WARNING


def test_known_post_day_has_assessable_recurrence_even_if_time_is_day_only():
    case = NTFCase(
        case_id="MANUAL-DATE-TEST",
        vehicle=Vehicle(vin="W1TTEST0000000001"),
        component_type="Coolant Pump",
    )
    case.diagnostic_sessions.append(
        DiagnosticSession.model_validate({
            "vin": case.vin, "occurred_at": datetime(2026, 1, 1, 12),
            "dtc_count": 1, "time_precision": "date",
        })
    )
    case.diagnostics.append(
        DiagnosticEvent.model_validate({
            "vin": case.vin, "occurred_at": datetime(2026, 1, 1, 12),
            "ecu": "CPC3", "dtc_code": "P1", "time_precision": "date",
        })
    )
    case.replacements.append(
        PartReplacement.model_validate({
            "vin": case.vin, "occurred_at": datetime(2026, 1, 2, 12),
            "component_type": "Coolant Pump", "time_precision": "date",
        })
    )
    case.diagnostic_sessions.append(
        DiagnosticSession.model_validate({
            "vin": case.vin, "occurred_at": datetime(2026, 1, 3, 12),
            "dtc_count": 0, "time_precision": "date",
        })
    )
    result = analyze_recurrence(case)
    assert result.assessable
    assert not result.has_recurrence
