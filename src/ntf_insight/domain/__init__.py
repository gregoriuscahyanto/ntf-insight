"""Core, component-agnostic NTF domain models."""

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
    PartReplacement,
    RepairEvent,
    SoftwareEvent,
    SupplierFinding,
)
from ntf_insight.domain.vehicle import Vehicle

__all__ = [
    "Assessment",
    "Confidence",
    "DiagnosticEvent",
    "DiagnosticSession",
    "Evidence",
    "EvidenceDirection",
    "NTFCase",
    "PartReplacement",
    "RepairEvent",
    "RootCauseCategory",
    "SoftwareEvent",
    "SupplierFinding",
    "SupplierFindingResult",
    "SupplierInvolvement",
    "Vehicle",
]
