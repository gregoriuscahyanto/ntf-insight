from datetime import datetime

from ntf_insight.demo.synthetic_cases import build_demo_cases
from ntf_insight.domain.events import DiagnosticEvent, DiagnosticSession
from ntf_insight.ingestion.assembly import CaseAssembler
from ntf_insight.ingestion.models import ParsedShortTest


def test_case_assembler_attaches_short_test_by_unique_vin() -> None:
    seed = build_demo_cases()[0].model_copy(deep=True)
    seed.diagnostic_sessions = []
    seed.diagnostics = []
    assembler = CaseAssembler([seed])
    session = DiagnosticSession(vin=seed.vin, occurred_at=datetime(2026, 2, 1), mileage_km=25000)
    parsed = ParsedShortTest(
        session=session,
        diagnostics=[
            DiagnosticEvent(
                vin=seed.vin,
                occurred_at=datetime(2026, 2, 1),
                mileage_km=25000,
                ecu="CPC3",
                dtc_code="P1",
            )
        ],
    )

    assembler.attach_short_test(parsed)
    result = assembler.result()

    assert not result.issues
    assert len(result.cases[0].diagnostic_sessions) == 1
    assert len(result.cases[0].diagnostics) == 1


def test_case_assembler_refuses_ambiguous_vin_join() -> None:
    first = build_demo_cases()[0].model_copy(deep=True)
    second = first.model_copy(deep=True)
    second.case_id = "SECOND-CASE"
    assembler = CaseAssembler([first, second])
    parsed = ParsedShortTest(
        session=DiagnosticSession(
            vin=first.vin,
            occurred_at=datetime(2026, 2, 1),
            mileage_km=25000,
        )
    )

    assembler.attach_short_test(parsed)
    result = assembler.result()

    assert any(issue.code == "AMBIGUOUS_VIN_CASE" for issue in result.issues)
