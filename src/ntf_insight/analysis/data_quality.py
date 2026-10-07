"""Data-quality checks for case analysis readiness."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from ntf_insight.domain.case import NTFCase
from ntf_insight.storage.reference_repositories import ReferenceRepository


class QualityStatus(StrEnum):
    OK = "OK"
    WARNING = "Warning"
    MISSING = "Missing"


@dataclass(frozen=True, slots=True)
class QualityCheck:
    code: str
    label: str
    status: QualityStatus
    detail: str


@dataclass(frozen=True, slots=True)
class DataQualityReport:
    case_id: str
    checks: tuple[QualityCheck, ...]
    trigger_coverage_count: int
    unique_fault_count: int

    @property
    def issue_count(self) -> int:
        return sum(check.status != QualityStatus.OK for check in self.checks)

    @property
    def trigger_coverage_ratio(self) -> float | None:
        if self.unique_fault_count == 0:
            return None
        return self.trigger_coverage_count / self.unique_fault_count

    def status_for(self, code: str) -> QualityStatus | None:
        match = next((check for check in self.checks if check.code == code), None)
        return match.status if match else None


def assess_data_quality(
    case: NTFCase,
    references: ReferenceRepository | None = None,
) -> DataQualityReport:
    """Assess whether a case contains enough evidence for downstream analyses."""
    replacement = case.investigated_replacement()
    pre_sessions = []
    post_sessions = []
    if replacement is not None:
        pre_sessions = [s for s in case.diagnostic_sessions if s.occurred_at < replacement.occurred_at]
        post_sessions = [s for s in case.diagnostic_sessions if s.occurred_at > replacement.occurred_at]

    checks: list[QualityCheck] = []
    checks.append(
        QualityCheck(
            code="replacement_anchor",
            label="Replacement anchor",
            status=QualityStatus.OK if replacement else QualityStatus.MISSING,
            detail="Investigated component replacement is known." if replacement else "No investigated component replacement is available.",
        )
    )
    checks.append(
        QualityCheck(
            code="replacement_mileage",
            label="Replacement mileage",
            status=(QualityStatus.OK if replacement and replacement.mileage_km is not None else QualityStatus.WARNING),
            detail=(
                f"{replacement.mileage_km} km" if replacement and replacement.mileage_km is not None
                else "Mileage at replacement is missing; distance-to-recurrence cannot be calculated reliably."
            ),
        )
    )
    checks.append(
        QualityCheck(
            code="pre_test",
            label="Pre-replacement short test",
            status=QualityStatus.OK if pre_sessions else QualityStatus.MISSING,
            detail=f"{len(pre_sessions)} diagnostic session(s) before replacement." if pre_sessions else "No known diagnostic session before replacement.",
        )
    )
    checks.append(
        QualityCheck(
            code="post_test",
            label="Post-replacement short test",
            status=QualityStatus.OK if post_sessions else QualityStatus.MISSING,
            detail=f"{len(post_sessions)} diagnostic session(s) after replacement." if post_sessions else "No known diagnostic session after replacement.",
        )
    )
    checks.append(
        QualityCheck(
            code="supplier_finding",
            label="Supplier / return finding",
            status=QualityStatus.OK if case.supplier_findings else QualityStatus.WARNING,
            detail=(
                f"{len(case.supplier_findings)} finding(s) available."
                if case.supplier_findings
                else "No returned-part/supplier finding available."
            ),
        )
    )
    checks.append(
        QualityCheck(
            code="software_history",
            label="Vehicle software history",
            status=QualityStatus.OK if case.software_events else QualityStatus.WARNING,
            detail=(
                f"{len(case.software_events)} software event(s) available."
                if case.software_events
                else "No vehicle-specific ECU software/update event available."
            ),
        )
    )

    unique_faults = {event.fault_key for event in case.diagnostics}
    trigger_coverage = 0
    if references is not None:
        trigger_coverage = sum(
            references.find_trigger(ecu, dtc) is not None for ecu, dtc in unique_faults
        )
        if unique_faults:
            if trigger_coverage == len(unique_faults):
                trigger_status = QualityStatus.OK
            elif trigger_coverage == 0:
                trigger_status = QualityStatus.WARNING
            else:
                trigger_status = QualityStatus.WARNING
            trigger_detail = f"{trigger_coverage}/{len(unique_faults)} unique DTCs have a trigger definition."
        else:
            trigger_status = QualityStatus.WARNING
            trigger_detail = "No DTC observations available to match against the trigger catalog."
    else:
        trigger_status = QualityStatus.WARNING
        trigger_detail = "No DTC trigger catalog is loaded."

    checks.append(
        QualityCheck(
            code="trigger_coverage",
            label="DTC trigger coverage",
            status=trigger_status,
            detail=trigger_detail,
        )
    )

    return DataQualityReport(
        case_id=case.case_id,
        checks=tuple(checks),
        trigger_coverage_count=trigger_coverage,
        unique_fault_count=len(unique_faults),
    )
