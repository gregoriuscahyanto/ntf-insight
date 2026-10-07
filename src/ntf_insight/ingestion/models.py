"""Canonical ingestion results independent from source file formats."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from ntf_insight.domain.events import (
    DiagnosticEvent,
    DiagnosticSession,
    ECUStateObservation,
    PartReplacement,
    RepairEvent,
    SoftwareEvent,
    SupplierFinding,
)
from ntf_insight.domain.population import PopulationExposure
from ntf_insight.domain.reference import DTCTriggerDefinition, ECUChangeRecord
from ntf_insight.domain.vehicle import Vehicle


class ImportSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class ImportIssue(BaseModel):
    model_config = ConfigDict(frozen=True)

    severity: ImportSeverity
    code: str
    message: str
    source_ref: str | None = None


class ImportResult(BaseModel):
    issues: list[ImportIssue] = Field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return not any(issue.severity == ImportSeverity.ERROR for issue in self.issues)


class ParsedVehicleList(ImportResult):
    vehicles: list[Vehicle] = Field(default_factory=list)


class ParsedShortTest(ImportResult):
    """Normalized representation of one source short-test file/run."""

    session: DiagnosticSession
    diagnostics: list[DiagnosticEvent] = Field(default_factory=list)
    ecu_states: list[ECUStateObservation] = Field(default_factory=list)


class ParsedReplacementData(ImportResult):
    replacements: list[PartReplacement] = Field(default_factory=list)


class ParsedSupplierFindingData(ImportResult):
    findings: list[SupplierFinding] = Field(default_factory=list)


class ParsedWorkshopData(ImportResult):
    repairs: list[RepairEvent] = Field(default_factory=list)


class ParsedVehicleSoftwareData(ImportResult):
    software_events: list[SoftwareEvent] = Field(default_factory=list)
    ecu_states: list[ECUStateObservation] = Field(default_factory=list)


class ParsedDTCTriggerCatalog(ImportResult):
    definitions: list[DTCTriggerDefinition] = Field(default_factory=list)


class ParsedECUChangeCatalog(ImportResult):
    changes: list[ECUChangeRecord] = Field(default_factory=list)


class ParsedPopulationData(ImportResult):
    exposures: list[PopulationExposure] = Field(default_factory=list)
