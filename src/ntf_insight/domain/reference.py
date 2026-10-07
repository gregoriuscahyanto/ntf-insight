"""Reference/engineering knowledge that is not tied to one vehicle case.

Vehicle events answer "what happened on this VIN?". Reference knowledge answers
"under which conditions is this DTC set?" and "what changed between ECU releases?".
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ChangeKind(StrEnum):
    SOFTWARE = "software"
    HARDWARE = "hardware"
    CALIBRATION = "calibration"
    OTHER = "other"


class DTCTriggerDefinition(BaseModel):
    """Engineering definition of one DTC/monitor, typically sourced from SMR-D data.

    The exact source schema is intentionally not assumed yet. Optional fields are
    populated only when the source actually provides them.
    """

    model_config = ConfigDict(extra="allow")

    definition_id: str
    ecu: str
    dtc_code: str
    dtc_text: str | None = None
    trigger_text: str | None = None
    enable_conditions: list[str] = Field(default_factory=list)
    reset_or_healing_conditions: list[str] = Field(default_factory=list)
    debounce_text: str | None = None
    variant_or_scope: str | None = None
    software_scope: str | None = None
    semantic_tags: list[str] = Field(default_factory=list)
    source_ref: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def fault_key(self) -> tuple[str, str]:
        return self.ecu.strip().upper(), self.dtc_code.strip().upper()


class ECUChangeRecord(BaseModel):
    """One documented HW/SW/calibration change in an ECU release history."""

    model_config = ConfigDict(extra="allow")

    change_id: str
    ecu: str
    kind: ChangeKind
    from_version: str | None = None
    to_version: str | None = None
    release_date: date | None = None
    title: str | None = None
    change_summary: str | None = None
    affected_dtcs: list[str] = Field(default_factory=list)
    affected_functions: list[str] = Field(default_factory=list)
    source_ref: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
