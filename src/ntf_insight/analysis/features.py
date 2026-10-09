"""Interpretable case features for similarity, clustering and dashboards."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from ntf_insight.analysis.recurrence import analyze_recurrence
from ntf_insight.analysis.diagnostic_observations import unique_diagnostic_observations
from ntf_insight.domain.case import NTFCase
from ntf_insight.domain.enums import SupplierFindingResult
from ntf_insight.storage.reference_repositories import ReferenceRepository


@dataclass(frozen=True, slots=True)
class CaseFeatures:
    diagnostic_session_count: int
    diagnostic_event_count: int
    unique_fault_count: int
    ecu_count: int
    has_replacement: bool
    has_pre_test: bool
    has_post_test: bool
    recurrence_assessable: bool
    has_recurrence: bool
    same_fault_count: int
    new_fault_count: int
    disappeared_fault_count: int
    software_event_count: int
    supplier_ntf: bool
    supplier_fault_found: bool
    trigger_coverage_ratio: float | None
    related_release_change_count: int

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def extract_case_features(
    case: NTFCase,
    references: ReferenceRepository | None = None,
) -> CaseFeatures:
    recurrence = analyze_recurrence(case)
    diagnostics = [obs.event for obs in unique_diagnostic_observations(case.diagnostics)]
    unique_faults = {event.fault_key for event in diagnostics}
    ecus = {event.ecu.strip().upper() for event in diagnostics}

    trigger_ratio: float | None = None
    related_change_ids: set[str] = set()
    if references is not None and unique_faults:
        covered = 0
        for ecu, dtc in unique_faults:
            if references.find_trigger(ecu, dtc) is not None:
                covered += 1
            related_change_ids.update(
                change.change_id for change in references.find_changes_for_dtc(ecu, dtc)
            )
        trigger_ratio = covered / len(unique_faults)

    supplier_ntf = any(
        finding.result == SupplierFindingResult.NTF for finding in case.supplier_findings
    )
    supplier_fault_found = any(
        finding.result == SupplierFindingResult.FAULT_FOUND for finding in case.supplier_findings
    )

    return CaseFeatures(
        diagnostic_session_count=len(case.diagnostic_sessions),
        diagnostic_event_count=len(diagnostics),
        unique_fault_count=len(unique_faults),
        ecu_count=len(ecus),
        has_replacement=recurrence.replacement is not None,
        has_pre_test=recurrence.has_pre_test,
        has_post_test=recurrence.has_post_test,
        recurrence_assessable=recurrence.assessable,
        has_recurrence=recurrence.has_recurrence,
        same_fault_count=len(recurrence.same_faults),
        new_fault_count=len(recurrence.new_faults),
        disappeared_fault_count=len(recurrence.disappeared_faults),
        software_event_count=len(case.software_events),
        supplier_ntf=supplier_ntf,
        supplier_fault_found=supplier_fault_found,
        trigger_coverage_ratio=trigger_ratio,
        related_release_change_count=len(related_change_ids),
    )
