"""Synthetic coolant-pump cases for UI development and regression tests.

These cases are deliberately fictional. They contain no production or customer data.
"""

from __future__ import annotations

from datetime import datetime

from ntf_insight.domain.assessment import Assessment
from ntf_insight.domain.case import NTFCase
from ntf_insight.domain.enums import (
    Confidence,
    EvidenceDirection,
    RootCauseCategory,
    SupplierFindingResult,
    SupplierInvolvement,
)
from ntf_insight.domain.evidence import Evidence
from ntf_insight.domain.events import (
    DiagnosticEvent,
    DiagnosticSession,
    ECUStateObservation,
    PartReplacement,
    RepairEvent,
    SoftwareEvent,
    SupplierFinding,
)
from ntf_insight.domain.vehicle import Vehicle
from ntf_insight.storage.repositories import InMemoryCaseRepository


def _dt(day: int, hour: int = 9) -> datetime:
    return datetime(2026, 1, day, hour, 0)


def _session(vin: str, day: int, mileage: int, dtc_count: int, hour: int = 8) -> DiagnosticSession:
    return DiagnosticSession(
        vin=vin,
        occurred_at=_dt(day, hour),
        mileage_km=mileage,
        label="Short test",
        ecu_count=28,
        dtc_count=dtc_count,
        source_ref=f"synthetic:{vin}:{day}",
    )


def build_demo_cases() -> list[NTFCase]:
    """Return a small set of fictional cases covering key NTF patterns."""
    component = "Coolant Pump"

    recurrence = NTFCase(
        case_id="DEMO-001",
        vehicle=Vehicle(vin="DEMO-VIN-000001", model_series="BR-D1", variant="A"),
        component_type=component,
        component_profile_id="coolant_pump",
        diagnostic_sessions=[
            _session("DEMO-VIN-000001", 2, 24100, 1),
            _session("DEMO-VIN-000001", 5, 24220, 1),
            _session("DEMO-VIN-000001", 10, 24330, 1),
        ],
        diagnostics=[
            DiagnosticEvent(vin="DEMO-VIN-000001", occurred_at=_dt(2), mileage_km=24100, ecu="CPC3", dtc_code="P26F100", dtc_text="Coolant pump performance", status="stored"),
            DiagnosticEvent(vin="DEMO-VIN-000001", occurred_at=_dt(5), mileage_km=24220, ecu="CPC3", dtc_code="P26F100", dtc_text="Coolant pump performance", status="current"),
            DiagnosticEvent(vin="DEMO-VIN-000001", occurred_at=_dt(10), mileage_km=24330, ecu="CPC3", dtc_code="P26F100", dtc_text="Coolant pump performance", status="stored"),
        ],
        replacements=[PartReplacement(vin="DEMO-VIN-000001", occurred_at=_dt(8), mileage_km=24280, component_type=component, old_part_number="A-DEMO-001", new_part_number="A-DEMO-002", supplier="Supplier A")],
        supplier_findings=[SupplierFinding(vin="DEMO-VIN-000001", occurred_at=_dt(18), supplier="Supplier A", result=SupplierFindingResult.NTF, complaint_reproduced=False, notes="Synthetic NTF finding.")],
        assessment=Assessment(
            root_cause=RootCauseCategory.WIRING_CONNECTOR,
            supplier_involvement=SupplierInvolvement.UNLIKELY,
            confidence=Confidence.MEDIUM,
            summary="Same pump-related DTC reappears shortly after replacement; component cause is weakened.",
            evidence=[Evidence(code="RECURRENCE_AFTER_SWAP", description="Same CPC3 DTC reappears after pump replacement.", direction=EvidenceDirection.CONTRADICTS)],
        ),
    )

    component_fault = NTFCase(
        case_id="DEMO-002",
        vehicle=Vehicle(vin="DEMO-VIN-000002", model_series="BR-D1", variant="B"),
        component_type=component,
        component_profile_id="coolant_pump",
        diagnostic_sessions=[
            _session("DEMO-VIN-000002", 3, 18100, 1),
            _session("DEMO-VIN-000002", 4, 18120, 1),
            _session("DEMO-VIN-000002", 9, 18220, 0),
        ],
        diagnostics=[
            DiagnosticEvent(vin="DEMO-VIN-000002", occurred_at=_dt(3), mileage_km=18100, ecu="CPC3", dtc_code="P260000", dtc_text="Coolant pump control circuit", status="current"),
            DiagnosticEvent(vin="DEMO-VIN-000002", occurred_at=_dt(4), mileage_km=18120, ecu="CPC3", dtc_code="P260000", dtc_text="Coolant pump control circuit", status="current"),
        ],
        replacements=[PartReplacement(vin="DEMO-VIN-000002", occurred_at=_dt(6), mileage_km=18160, component_type=component, old_part_number="A-DEMO-010", new_part_number="A-DEMO-011", supplier="Supplier B")],
        supplier_findings=[SupplierFinding(vin="DEMO-VIN-000002", occurred_at=_dt(17), supplier="Supplier B", result=SupplierFindingResult.FAULT_FOUND, complaint_reproduced=True, failure_mode="Synthetic internal electrical fault")],
        assessment=Assessment(
            root_cause=RootCauseCategory.COMPONENT_SUPPLIER,
            supplier_involvement=SupplierInvolvement.LIKELY,
            confidence=Confidence.HIGH,
            summary="Pump-related DTCs stop after replacement and the synthetic supplier test reproduces a component fault.",
            evidence=[Evidence(code="FAULT_FOUND", description="Returned part finding reproduces a component fault.", direction=EvidenceDirection.SUPPORTS)],
        ),
    )

    supply_fault = NTFCase(
        case_id="DEMO-003",
        vehicle=Vehicle(vin="DEMO-VIN-000003", model_series="BR-D2", variant="A"),
        component_type=component,
        component_profile_id="coolant_pump",
        diagnostic_sessions=[
            _session("DEMO-VIN-000003", 2, 40500, 3),
            _session("DEMO-VIN-000003", 9, 40620, 2),
        ],
        diagnostics=[
            DiagnosticEvent(vin="DEMO-VIN-000003", occurred_at=_dt(2), mileage_km=40500, ecu="CPC3", dtc_code="P26F100", dtc_text="Coolant pump performance", status="stored"),
            DiagnosticEvent(vin="DEMO-VIN-000003", occurred_at=_dt(2, 10), mileage_km=40500, ecu="MCM", dtc_code="U300316", dtc_text="Supply voltage too low", status="stored"),
            DiagnosticEvent(vin="DEMO-VIN-000003", occurred_at=_dt(2, 10), mileage_km=40500, ecu="ACM", dtc_code="U300316", dtc_text="Supply voltage too low", status="stored"),
            DiagnosticEvent(vin="DEMO-VIN-000003", occurred_at=_dt(9), mileage_km=40620, ecu="CPC3", dtc_code="P26F100", dtc_text="Coolant pump performance", status="stored"),
            DiagnosticEvent(vin="DEMO-VIN-000003", occurred_at=_dt(9, 10), mileage_km=40620, ecu="MCM", dtc_code="U300316", dtc_text="Supply voltage too low", status="stored"),
        ],
        replacements=[PartReplacement(vin="DEMO-VIN-000003", occurred_at=_dt(7), mileage_km=40580, component_type=component, supplier="Supplier A")],
        repairs=[RepairEvent(vin="DEMO-VIN-000003", occurred_at=_dt(12), mileage_km=40690, action="Repair ground connection", notes="Synthetic workshop action")],
        assessment=Assessment(
            root_cause=RootCauseCategory.ELECTRICAL_SUPPLY,
            supplier_involvement=SupplierInvolvement.UNLIKELY,
            confidence=Confidence.HIGH,
            summary="Pump DTC and undervoltage faults occur across multiple ECUs before and after replacement.",
            evidence=[Evidence(code="MULTI_ECU_UNDERVOLTAGE", description="Undervoltage DTCs occur in multiple ECUs.", direction=EvidenceDirection.SUPPORTS)],
        ),
    )

    software_case = NTFCase(
        case_id="DEMO-004",
        vehicle=Vehicle(vin="DEMO-VIN-000004", model_series="BR-D2", variant="C"),
        component_type=component,
        component_profile_id="coolant_pump",
        diagnostic_sessions=[
            _session("DEMO-VIN-000004", 3, 11200, 1),
            _session("DEMO-VIN-000004", 9, 11310, 0),
        ],
        diagnostics=[
            DiagnosticEvent(vin="DEMO-VIN-000004", occurred_at=_dt(3), mileage_km=11200, ecu="CPC3", dtc_code="P26F100", dtc_text="Coolant pump performance", status="sporadic"),
        ],
        ecu_states=[
            ECUStateObservation(vin="DEMO-VIN-000004", occurred_at=_dt(3, 8), mileage_km=11200, ecu="CPC3", software_version="DEMO-1.0", hardware_version="DEMO-HW-A", source_ref="synthetic:short-test:pre"),
            ECUStateObservation(vin="DEMO-VIN-000004", occurred_at=_dt(9, 8), mileage_km=11310, ecu="CPC3", software_version="DEMO-2.0", hardware_version="DEMO-HW-A", source_ref="synthetic:short-test:post"),
        ],
        replacements=[PartReplacement(vin="DEMO-VIN-000004", occurred_at=_dt(5), mileage_km=11250, component_type=component, supplier="Supplier C")],
        software_events=[SoftwareEvent(vin="DEMO-VIN-000004", occurred_at=_dt(7), mileage_km=11270, ecu="CPC3", software_version="DEMO-2.0", action="CPC3 software update", source_ref="synthetic:flash-history")],
        assessment=Assessment(
            root_cause=RootCauseCategory.ECU_SOFTWARE,
            supplier_involvement=SupplierInvolvement.UNLIKELY,
            confidence=Confidence.MEDIUM,
            summary="Synthetic case for a software-related diagnostic pattern.",
        ),
    )

    insufficient = NTFCase(
        case_id="DEMO-005",
        vehicle=Vehicle(vin="DEMO-VIN-000005", model_series="BR-D3", variant="A"),
        component_type=component,
        component_profile_id="coolant_pump",
        diagnostic_sessions=[_session("DEMO-VIN-000005", 3, 7300, 1)],
        diagnostics=[DiagnosticEvent(vin="DEMO-VIN-000005", occurred_at=_dt(3), mileage_km=7300, ecu="CPC3", dtc_code="P26F100", status="stored")],
        replacements=[PartReplacement(vin="DEMO-VIN-000005", occurred_at=_dt(5), mileage_km=7350, component_type=component)],
        assessment=Assessment(
            root_cause=RootCauseCategory.UNKNOWN,
            supplier_involvement=SupplierInvolvement.UNKNOWN,
            confidence=Confidence.LOW,
            summary="No post-replacement short test or returned-part finding is available.",
        ),
    )

    new_after_swap = NTFCase(
        case_id="DEMO-006",
        vehicle=Vehicle(vin="DEMO-VIN-000006", model_series="BR-D3", variant="B"),
        component_type=component,
        component_profile_id="coolant_pump",
        diagnostic_sessions=[
            _session("DEMO-VIN-000006", 2, 52600, 1),
            _session("DEMO-VIN-000006", 8, 52670, 1),
        ],
        diagnostics=[
            DiagnosticEvent(vin="DEMO-VIN-000006", occurred_at=_dt(2), mileage_km=52600, ecu="CPC3", dtc_code="P260000", dtc_text="Coolant pump control circuit", status="stored"),
            DiagnosticEvent(vin="DEMO-VIN-000006", occurred_at=_dt(8), mileage_km=52670, ecu="CPC3", dtc_code="P260100", dtc_text="Coolant pump control circuit low", status="current"),
        ],
        replacements=[PartReplacement(vin="DEMO-VIN-000006", occurred_at=_dt(6), mileage_km=52640, component_type=component, supplier="Supplier A")],
        assessment=Assessment(
            root_cause=RootCauseCategory.WORKSHOP_PROCESS,
            supplier_involvement=SupplierInvolvement.UNKNOWN,
            confidence=Confidence.LOW,
            summary="A different electrical DTC appears immediately after replacement; installation/process evidence should be checked.",
            evidence=[Evidence(code="NEW_FAULT_AFTER_SWAP", description="A new pump-circuit DTC appears after the replacement.", direction=EvidenceDirection.NEUTRAL)],
        ),
    )

    return [recurrence, component_fault, supply_fault, software_case, insufficient, new_after_swap]


def build_demo_repository() -> InMemoryCaseRepository:
    return InMemoryCaseRepository(build_demo_cases())
