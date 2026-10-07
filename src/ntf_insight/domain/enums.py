"""Shared domain enumerations."""

from __future__ import annotations

from enum import StrEnum


class RootCauseCategory(StrEnum):
    COMPONENT_SUPPLIER = "Component / Supplier"
    ELECTRICAL_SUPPLY = "Electrical Supply"
    WIRING_CONNECTOR = "Wiring / Connector"
    ECU_SOFTWARE = "ECU / Software"
    VEHICLE_SYSTEM = "Vehicle System"
    WORKSHOP_PROCESS = "Workshop / Process"
    UNKNOWN = "Unknown / Insufficient Evidence"


class SupplierInvolvement(StrEnum):
    LIKELY = "Likely"
    POSSIBLE = "Possible"
    UNLIKELY = "Unlikely"
    UNKNOWN = "Unknown"


class Confidence(StrEnum):
    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"


class EvidenceDirection(StrEnum):
    SUPPORTS = "Supports"
    CONTRADICTS = "Contradicts"
    NEUTRAL = "Neutral"


class SupplierFindingResult(StrEnum):
    NTF = "NTF"
    FAULT_FOUND = "Fault Found"
    OTHER = "Other"
    UNKNOWN = "Unknown"
