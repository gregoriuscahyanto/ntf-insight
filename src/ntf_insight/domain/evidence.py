"""Explainable evidence attached to an NTF assessment."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from ntf_insight.domain.enums import EvidenceDirection


class Evidence(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: str
    description: str
    direction: EvidenceDirection
    source_ref: str | None = None
    weight: float = 1.0
