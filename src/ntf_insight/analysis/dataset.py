"""Build a flat feature dataset for later clustering and statistical analysis."""

from __future__ import annotations

import polars as pl

from ntf_insight.analysis.features import extract_case_features
from ntf_insight.domain.case import NTFCase
from ntf_insight.storage.reference_repositories import ReferenceRepository


def build_case_feature_frame(
    cases: list[NTFCase],
    references: ReferenceRepository | None = None,
) -> pl.DataFrame:
    rows: list[dict[str, object]] = []
    for case in cases:
        row: dict[str, object] = {
            "case_id": case.case_id,
            "vin": case.vin,
            "component_type": case.component_type,
        }
        row.update(extract_case_features(case, references).as_dict())
        rows.append(row)
    return pl.DataFrame(rows) if rows else pl.DataFrame()
