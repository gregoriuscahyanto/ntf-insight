"""Internal consistency checks for assembled NTF cases."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from ntf_insight.domain.case import NTFCase


class IntegritySeverity(StrEnum):
    WARNING = "Warning"
    ERROR = "Error"


@dataclass(frozen=True, slots=True)
class IntegrityIssue:
    code: str
    severity: IntegritySeverity
    message: str


@dataclass(frozen=True, slots=True)
class CaseIntegrityReport:
    case_id: str
    issues: tuple[IntegrityIssue, ...]

    @property
    def is_valid(self) -> bool:
        return not any(issue.severity == IntegritySeverity.ERROR for issue in self.issues)

    @property
    def error_count(self) -> int:
        return sum(issue.severity == IntegritySeverity.ERROR for issue in self.issues)


def validate_case_integrity(case: NTFCase) -> CaseIntegrityReport:
    issues: list[IntegrityIssue] = []

    event_groups = [
        ("diagnostic session", case.diagnostic_sessions),
        ("diagnostic event", case.diagnostics),
        ("ECU state", case.ecu_states),
        ("repair event", case.repairs),
        ("replacement", case.replacements),
        ("software event", case.software_events),
        ("supplier finding", case.supplier_findings),
    ]

    event_ids: list[str] = []
    for label, events in event_groups:
        for event in events:
            event_ids.append(event.event_id)
            if event.vin != case.vin:
                issues.append(
                    IntegrityIssue(
                        code="EVENT_VIN_MISMATCH",
                        severity=IntegritySeverity.ERROR,
                        message=(
                            f"{label} {event.event_id} belongs to VIN {event.vin}, "
                            f"but case {case.case_id} belongs to {case.vin}."
                        ),
                    )
                )

    if len(event_ids) != len(set(event_ids)):
        issues.append(
            IntegrityIssue(
                code="DUPLICATE_EVENT_ID",
                severity=IntegritySeverity.ERROR,
                message="The case contains duplicate event IDs.",
            )
        )

    session_ids = {session.session_id for session in case.diagnostic_sessions}
    for event in case.diagnostics:
        if event.session_id and event.session_id not in session_ids:
            issues.append(
                IntegrityIssue(
                    code="UNKNOWN_DIAGNOSTIC_SESSION",
                    severity=IntegritySeverity.ERROR,
                    message=(
                        f"Diagnostic event {event.event_id} references unknown session "
                        f"{event.session_id}."
                    ),
                )
            )
    for state in case.ecu_states:
        if state.session_id and state.session_id not in session_ids:
            issues.append(
                IntegrityIssue(
                    code="UNKNOWN_ECU_STATE_SESSION",
                    severity=IntegritySeverity.ERROR,
                    message=(
                        f"ECU state {state.event_id} references unknown session "
                        f"{state.session_id}."
                    ),
                )
            )

    if case.investigated_replacement_id:
        anchor = next(
            (
                event
                for event in case.replacements
                if event.event_id == case.investigated_replacement_id
            ),
            None,
        )
        if anchor is None:
            issues.append(
                IntegrityIssue(
                    code="UNKNOWN_REPLACEMENT_ANCHOR",
                    severity=IntegritySeverity.ERROR,
                    message=(
                        f"Explicit replacement anchor {case.investigated_replacement_id} "
                        "does not exist in the case."
                    ),
                )
            )
        elif anchor.component_type.casefold() != case.component_type.casefold():
            issues.append(
                IntegrityIssue(
                    code="REPLACEMENT_COMPONENT_MISMATCH",
                    severity=IntegritySeverity.ERROR,
                    message=(
                        f"Replacement anchor is {anchor.component_type}, while the case "
                        f"investigates {case.component_type}."
                    ),
                )
            )

    return CaseIntegrityReport(case_id=case.case_id, issues=tuple(issues))
