"""Guardrails for the trainable diagnosis model (synthetic, no customer data)."""

from datetime import datetime, timedelta

from ntf_insight.analysis.root_cause_ml import (
    ConfirmedCause, extract_ml_features, train_root_cause_model,
)
from ntf_insight.domain.case import NTFCase
from ntf_insight.domain.enums import RootCauseCategory
from ntf_insight.domain.events import DiagnosticEvent, DiagnosticSession, PartReplacement, SupplierFinding
from ntf_insight.domain.vehicle import Vehicle


def _case(index: int, cause: RootCauseCategory) -> NTFCase:
    vin = f"SYNTH-{index:05d}"
    base = datetime(2025, 1, 1)
    dtc = {
        RootCauseCategory.COMPONENT_SUPPLIER: "P260000",
        RootCauseCategory.ELECTRICAL_SUPPLY: "U300316",
        RootCauseCategory.WIRING_CONNECTOR: "P260100",
    }[cause]
    return NTFCase(
        case_id=f"S-{index}", vehicle=Vehicle(vin=vin, model_series="TEST"),
        component_type="Coolant Pump",
        diagnostics=[DiagnosticEvent(vin=vin, occurred_at=base, ecu="CPC3", dtc_code=dtc)],
        diagnostic_sessions=[
            DiagnosticSession(vin=vin, occurred_at=base, dtc_count=1),
            DiagnosticSession(vin=vin, occurred_at=base + timedelta(days=2), dtc_count=0),
        ],
        replacements=[PartReplacement(vin=vin, occurred_at=base + timedelta(days=1),
                                      component_type="Coolant Pump", supplier="Supplier Secret")],
        supplier_findings=[SupplierFinding(vin=vin, occurred_at=base + timedelta(days=3),
                                          supplier="Supplier Secret")],
    )


def test_not_ready_without_independent_confirmations():
    case = _case(1, RootCauseCategory.WIRING_CONNECTOR)
    assert train_root_cause_model([case], []).model is None
    assert train_root_cause_model([case], [
        ConfirmedCause(case.case_id, RootCauseCategory.WIRING_CONNECTOR,
                       "Expert", "8D-1", datetime(2025, 1, 4))
    ]).model is None


def test_excludes_supplier_identity_label_and_report_findings():
    case = _case(1, RootCauseCategory.COMPONENT_SUPPLIER)
    case.assessment = None
    original = extract_ml_features(case)
    case.replacements[0].supplier = "Different supplier"
    case.supplier_findings.clear()
    assert extract_ml_features(case) == original
    assert all("supplier" not in name and "vin" not in name.lower() for name in original)


def test_as_of_blocks_future_sessions_and_replacement():
    case = _case(1, RootCauseCategory.WIRING_CONNECTOR)
    early = extract_ml_features(case, as_of=datetime(2025, 1, 1, 12))
    assert early["has_replacement"] == 0
    assert early["recurrence_assessable"] == 0


def test_calibrated_multiclass_probabilities_and_vin_groups():
    causes = [RootCauseCategory.COMPONENT_SUPPLIER,
              RootCauseCategory.ELECTRICAL_SUPPLY,
              RootCauseCategory.WIRING_CONNECTOR]
    cases = [_case(i, causes[i % 3]) for i in range(90)]
    labels = [
        ConfirmedCause(case.case_id, causes[i % 3], "Expert", f"8D-{i}",
                       datetime(2025, 2, 1))
        for i, case in enumerate(cases)
    ]
    result = train_root_cause_model(cases, labels)
    assert result.model is not None, result.message
    metrics = result.model.metrics
    assert metrics.train_count + metrics.calibration_count + metrics.test_count == 90
    assert metrics.test_groups > 0
    assert 0 <= metrics.accuracy <= 1
    for prediction in result.model.predict_many(cases[:4]):
        assert abs(sum(p for _, p in prediction.probabilities) - 1.0) < 1e-7
        assert len(prediction.probabilities) == 3
        assert prediction.top_probability == prediction.probabilities[0][1]
