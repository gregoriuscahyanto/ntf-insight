"""Event models used to reconstruct a vehicle case timeline."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from ntf_insight.domain.enums import SupplierFindingResult


class CaseEvent(BaseModel):
    """Common event metadata."""

    model_config = ConfigDict(extra="allow")

    event_id: str = Field(default_factory=lambda: uuid4().hex)
    vin: str
    occurred_at: datetime
    mileage_km: int | None = Field(default=None, ge=0)
    source_ref: str | None = None


class DiagnosticSession(CaseEvent):
    """Metadata for one complete diagnostic/short-test run.

    A session is stored even when it contains zero relevant DTCs. This distinction is
    important for post-replacement analysis: "no DTC in a known post-test" is very
    different from "no post-test data available".
    """

    session_id: str = Field(default_factory=lambda: uuid4().hex)
    label: str = "Short test"
    ecu_count: int | None = Field(default=None, ge=0)
    dtc_count: int | None = Field(default=None, ge=0)


class DiagnosticEvent(CaseEvent):
    """A DTC observation from a short test or another diagnostic source."""

    session_id: str | None = None
    ecu: str
    dtc_code: str
    dtc_text: str | None = None
    status: str | None = None
    occurrence_count: int | None = Field(default=None, ge=0)
    freeze_frame: dict[str, Any] = Field(default_factory=dict)

    @property
    def fault_key(self) -> tuple[str, str]:
        return self.ecu.strip().upper(), self.dtc_code.strip().upper()


class RepairEvent(CaseEvent):
    """Workshop/customer event relevant to the NTF investigation."""

    complaint: str | None = None
    action: str | None = None
    notes: str | None = None


class PartReplacement(CaseEvent):
    """Replacement of the investigated or surrounding component."""

    component_type: str
    old_part_number: str | None = None
    new_part_number: str | None = None
    supplier: str | None = None
    serial_number: str | None = None
    batch: str | None = None


class SoftwareEvent(CaseEvent):
    """ECU software/hardware change relevant to the case."""

    ecu: str
    software_version: str | None = None
    hardware_version: str | None = None
    coding: str | None = None
    action: str | None = None


class SupplierFinding(CaseEvent):
    """Finding from the returned-part or supplier analysis."""

    supplier: str | None = None
    result: SupplierFindingResult = SupplierFindingResult.UNKNOWN
    complaint_reproduced: bool | None = None
    failure_mode: str | None = None
    notes: str | None = None
