"""Explainable evidence attached to an NTF assessment."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from ntf_insight.domain.enums import EvidenceDirection, RootCauseCategory


class Evidence(BaseModel):
    """One explainable signal supporting or weakening a root-cause candidate."""

    model_config = ConfigDict(frozen=True)

    code: str
    description: str
    direction: EvidenceDirection
    category_hint: RootCauseCategory | None = None
    source_ref: str | None = None
    weight: float = 1.0
