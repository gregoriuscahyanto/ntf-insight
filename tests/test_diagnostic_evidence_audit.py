"""Synthetic evidence audit tests; real QEC data never leave local NTF Insight."""
from datetime import datetime

import pytest

from ntf_insight.analysis.diagnostic_evidence_audit import (
    audit_diagnostic_evidence,
)
from ntf_insight.analysis.hdbscan_clustering import (
    cluster_hdbscan_cases, compare_hdbscan_methods,
)
from ntf_insight.domain.case import NTFCase
from ntf_insight.domain.events import DiagnosticEvent, PartReplacement
from ntf_insight.domain.vehicle import Vehicle

from test_hdbscan_clustering import sample, synthetic


def _event(case, code, *, at=datetime(2026, 4, 30), quicktest=False):
    return DiagnosticEvent(
        event_id=f"sample-{case.case_id}-{code}-{at}",
        vin=case.vin, ecu="CPC3", dtc_code=code, occurred_at=at,
        session_id="SESSION-1" if quicktest else None,
        source_ref="raw:synthetic#ecu:1" if quicktest
        else "raw:synthetic#csv:1",
    )


def test_qec_evidence_audit_matches_unfiltered_hdbscan_and_source_overlap() -> None:
    cases = sample()
    first = cases[0]
    first.diagnostics.append(
        _event(first, "CODE-A-ROOT-A", quicktest=True)
    )
    audit = audit_diagnostic_evidence(cases)
    plan = cluster_hdbscan_cases(cases)
    assert audit.scoped_cases == plan.case_count == 15
    assert audit.eligible_cases == len(plan.eligible_case_ids) == 13
    assert audit.without_anchor == 1
    assert audit.without_any_dtc == 1
    assert audit.excluded_count == 2
    assert audit.with_source_overlap == 1
    assert audit.overlapping_fault_occurrences == 1
    top = next(
        item for item in audit.frequencies
        if item.fault == ("CPC3", "CODE-A-ROOT-A")
    )
    assert top.case_count == 6  # duplicated CSV+QT is NOT 7
    assert top.proportion == pytest.approx(6 / 13)
    assert top.screened_common

    row = next(item for item in audit.cases if item.case_id == first.case_id)
    assert row.all_event_rows == 5
    assert row.pre_unique_faults == row.selected_unique_faults == 4
    assert row.quicktest_unique_faults == 1
    assert row.autoexport_unique_faults == 4
    assert row.overlapping_source_faults == 1


def test_qec_evidence_audit_tells_missing_source_timeline_and_anchor_apart() -> None:
    post = synthetic("POST", "X", 401)
    post.diagnostics = [_event(
        post, "POST_ONLY", at=datetime(2026, 5, 20),
    )]
    old = synthetic("OLD", "X", 402)
    old.diagnostics = [_event(
        old, "OLD_ONLY", at=datetime(2026, 1, 1),
    )]
    no_source = synthetic("ONLY_CSV", "Y", 403)
    no_anchor = synthetic("NO_ANCHOR", "Y", 404, swap=False)
    empty = NTFCase(
        case_id="EMPTY2", vehicle=Vehicle(vin="SYNTHETIC-EMPTY2"),
        component_type="Coolant Pump", component_profile_id="coolant_pump",
        replacements=[
            PartReplacement(
                vin="SYNTHETIC-EMPTY2", component_type="Coolant Pump",
                occurred_at=datetime(2026, 5, 10),
            )
        ],
    )
    cases = [post, old, no_source, no_anchor, empty]
    audit = audit_diagnostic_evidence(
        cases, dtc_source="quicktest", lookback_days=30,
    )
    reasons = {row.case_id: row.reason for row in audit.cases}
    assert "nicht sicher vor dem Tausch" in reasons["POST"]
    assert "außerhalb" not in reasons["ONLY_CSV"]
    assert "ausgewählten Quellen" in reasons["ONLY_CSV"]
    assert "Tauschanker" in reasons["NO_ANCHOR"]
    assert "Kein QEC" in reasons["EMPTY2"]
    assert audit.eligible_cases == 0
    assert audit.without_anchor == 1
    assert audit.without_any_dtc == 1
    assert audit.only_after_swap_or_undated == 1

    time_only = audit_diagnostic_evidence(
        cases, dtc_source="all", lookback_days=30,
    )
    assert "Zeitfensters" in {
        row.case_id: row.reason for row in time_only.cases
    }["OLD"]
    assert time_only.outside_lookback == 1


def test_optional_frequent_code_screening_is_separate_and_never_claims_relevance() -> None:
    cases = sample()
    original = cluster_hdbscan_cases(cases)
    screened = cluster_hdbscan_cases(
        cases, common_dtc_cutoff=0.35,
    )
    assert original.common_dtc_cutoff is None
    assert screened.common_dtc_cutoff == 0.35
    assert original.case_count == screened.case_count
    assert original.distances != screened.distances
    for group in screened.clusters:
        assert not any(
            fault in {("CPC3", "CODE-A-ROOT-A"), ("CPC3", "CODE-B-ROOT-B")}
            for fault in group.common_faults
        )
    comparison = compare_hdbscan_methods(
        cases, common_dtc_cutoff=0.35,
    )
    assert comparison.common_dtc_cutoff == 0.35
    assert comparison.eligible_case_count == len(screened.eligible_case_ids)
    assert screened.clustered_count + len(screened.noise_case_ids) == len(
        screened.eligible_case_ids
    )


def test_frequency_screening_fails_closed_when_all_faults_common() -> None:
    first = synthetic("SAME1", "A", 311)
    second = synthetic("SAME2", "A", 312)
    # Only genuinely shared codes, no individual remaining discriminators.
    for case in (first, second):
        case.diagnostics = [_event(case, "COMMON_A")]
    original = cluster_hdbscan_cases([first, second])
    screened = cluster_hdbscan_cases(
        [first, second], common_dtc_cutoff=0.35,
    )
    assert len(original.eligible_case_ids) == 2
    assert screened.eligible_case_ids == ()
    assert screened.frequency_filtered_case_ids == ("SAME1", "SAME2")
    assert screened.excluded_case_ids == ("SAME1", "SAME2")
    assert screened.clusters == ()
    assert screened.coordinates == ()


@pytest.mark.parametrize("cutoff", [-1.0, 0.0, 1.1])
def test_common_filter_rejects_invalid_frequencies(cutoff):
    cases = sample()
    with pytest.raises(ValueError):
        audit_diagnostic_evidence(cases, common_cutoff=cutoff)
    with pytest.raises(ValueError):
        cluster_hdbscan_cases(cases, common_dtc_cutoff=cutoff)


def test_original_hdbscan_remains_default_and_outcome_excluded() -> None:
    cases = sample()
    original = cluster_hdbscan_cases(cases)
    cases[0].qec_ssl_end_finding = "Synthetic SSL outcome"
    assert cluster_hdbscan_cases(cases) == original
