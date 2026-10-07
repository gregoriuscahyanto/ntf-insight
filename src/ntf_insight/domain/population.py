"""Installed-population exposure used for normalized supplier/part analysis."""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class PopulationExposure(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")

    exposure_id: str
    component_type: str
    installed_units: int = Field(ge=0)
    supplier: str | None = None
    part_number: str | None = None
    period_start: date | None = None
    period_end: date | None = None
    source_ref: str | None = None
    dimensions: dict[str, Any] = Field(default_factory=dict)
