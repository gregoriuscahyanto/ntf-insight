"""Vehicle domain model."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field


class Vehicle(BaseModel):
    """Vehicle identity and stable metadata used across NTF cases."""

    model_config = ConfigDict(frozen=True, extra="allow")

    vin: str = Field(min_length=1)
    model_series: str | None = None
    variant: str | None = None
    production_date: date | None = None
    market: str | None = None
