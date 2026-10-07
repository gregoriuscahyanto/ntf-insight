"""NTF case aggregate."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from ntf_insight.domain.assessment import Assessment
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


class NTFCase(BaseModel):
    """All currently known evidence for one investigated vehicle/component case."""

    model_config = ConfigDict(extra="allow")

    case_id: str
    vehicle: Vehicle
    component_type: str
    component_profile_id: str | None = None
    investigated_replacement_id: str | None = None
    diagnostic_sessions: list[DiagnosticSession] = Field(default_factory=list)
    diagnostics: list[DiagnosticEvent] = Field(default_factory=list)
    ecu_states: list[ECUStateObservation] = Field(default_factory=list)
    repairs: list[RepairEvent] = Field(default_factory=list)
    replacements: list[PartReplacement] = Field(default_factory=list)
    software_events: list[SoftwareEvent] = Field(default_factory=list)
    supplier_findings: list[SupplierFinding] = Field(default_factory=list)
    assessment: Assessment | None = None

    @property
    def vin(self) -> str:
        return self.vehicle.vin

    def investigated_replacement(self) -> PartReplacement | None:
        """Return the explicit replacement anchor, or a deterministic fallback.

        Real imported cases should set investigated_replacement_id when multiple relevant
        replacements exist. The fallback keeps early/demo data usable.
        """
        if self.investigated_replacement_id:
            return next(
                (
                    event
                    for event in self.replacements
                    if event.event_id == self.investigated_replacement_id
                ),
                None,
            )

        matches = [
            event
            for event in self.replacements
            if event.component_type.casefold() == self.component_type.casefold()
        ]
        if not matches:
            return None
        return min(matches, key=lambda event: event.occurred_at)
