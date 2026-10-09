"""Regression tests for descriptive, non-causal 2D case projection."""

from datetime import datetime

import pytest

from ntf_insight.analysis.case_clustering import (
    cluster_diagnostic_cases,
)
from ntf_insight.analysis.case_projection import project_diagnostic_cases
from ntf_insight.demo.synthetic_cases import build_demo_cases
from ntf_insight.domain.case import NTFCase
from ntf_insight.domain.events import DiagnosticEvent, SupplierFinding
from ntf_insight.domain.enums import SupplierFindingResult
from ntf_insight.domain.vehicle import Vehicle


def test_svd_coordinates_are_deterministic_and_do_not_recluster() -> None:
    cases = build_demo_cases()
    cluster_before = cluster_diagnostic_cases(cases)
    original = project_diagnostic_cases(cases)
    reversed_projection = project_diagnostic_cases(list(reversed(cases)))

    assert len(original.points) == len(cases)
    assert original == reversed_projection
    assert set(p.case_id for p in original.points) == {c.case_id for c in cases}
    assert all(isinstance(p.x, float) and isinstance(p.y, float) for p in original.points)
    assert cluster_diagnostic_cases(cases) == cluster_before


def test_projection_excludes_no_evidence_cases_instead_of_inventing_positions() -> None:
    case = NTFCase(
        case_id="EMPTY", vehicle=Vehicle(vin="TEST-EMPTY"),
        component_type="Coolant Pump",
    )
    result = project_diagnostic_cases([case])
    assert result.points == ()
    assert result.omitted_case_ids == ("EMPTY",)


def test_outcomes_and_duplicate_dtc_source_do_not_move_points() -> None:
    cases = build_demo_cases()
    original = project_diagnostic_cases(cases)
    case = cases[0]
    duplicate = case.diagnostics[0].model_copy(deep=True)
    duplicate.event_id = "autoexport-copy"
    duplicate.source_ref = "raw:synthetic-autoexport#csv:2"
    case.diagnostics.append(duplicate)
    case.supplier_findings.append(SupplierFinding(
        vin=case.vin,
        occurred_at=datetime(2026, 2, 1),
        result=SupplierFindingResult.FAULT_FOUND,
        failure_mode="Hypothetical later result",
    ))
    assert project_diagnostic_cases(cases) == original


def test_unanchored_case_remains_visible_without_automatic_cluster() -> None:
    cases = build_demo_cases()
    candidate = cases[0].model_copy(deep=True)
    candidate.case_id = "UNANCHORED"
    candidate.replacements.clear()
    candidate.investigated_replacement_id = None
    groups = cluster_diagnostic_cases([candidate, cases[0]])
    projection = project_diagnostic_cases([candidate, cases[0]])
    assert not groups.clusters
    assert len(projection.points) == 2
    assert next(p for p in projection.points if p.case_id == "UNANCHORED").has_replacement_anchor is False


def test_duplicate_case_ids_fail_explicitly() -> None:
    case = build_demo_cases()[0]
    with pytest.raises(ValueError, match="eindeutig"):
        project_diagnostic_cases([case, case.model_copy(deep=True)])
