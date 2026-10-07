"""Root-cause assessment model."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from ntf_insight.domain.enums import Confidence, RootCauseCategory, SupplierInvolvement
from ntf_insight.domain.evidence import Evidence


class Assessment(BaseModel):
    model_config = ConfigDict(frozen=True)

    root_cause: RootCauseCategory = RootCauseCategory.UNKNOWN
    supplier_involvement: SupplierInvolvement = SupplierInvolvement.UNKNOWN
    confidence: Confidence = Confidence.LOW
    summary: str = ""
    evidence: list[Evidence] = Field(default_factory=list)
