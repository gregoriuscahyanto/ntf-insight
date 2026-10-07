"""Assemble normalized parser outputs into NTF cases without guessing ambiguous joins."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from ntf_insight.domain.case import NTFCase
from ntf_insight.ingestion.models import (
    ImportIssue,
    ImportSeverity,
    ParsedReplacementData,
    ParsedShortTest,
    ParsedSupplierFindingData,
    ParsedVehicleSoftwareData,
    ParsedWorkshopData,
)


@dataclass(slots=True)
class AssemblyResult:
    cases: list[NTFCase]
    issues: list[ImportIssue] = field(default_factory=list)


class CaseAssembler:
    """Attach normalized records to existing case seeds.

    Incoming event models carry a VIN. If one VIN maps to multiple active cases, callers must
    provide an explicit case_id; otherwise the assembler records an ambiguity error instead of
    guessing.
    """

    def __init__(self, cases: list[NTFCase]) -> None:
        self._cases = {case.case_id: case.model_copy(deep=True) for case in cases}
        self._by_vin: dict[str, list[str]] = defaultdict(list)
        for case in self._cases.values():
            self._by_vin[case.vin].append(case.case_id)
        self.issues: list[ImportIssue] = []

    def _resolve(self, vin: str, case_id: str | None = None) -> NTFCase | None:
        if case_id is not None:
            case = self._cases.get(case_id)
            if case is None:
                self.issues.append(
                    ImportIssue(
                        severity=ImportSeverity.ERROR,
                        code="UNKNOWN_CASE_ID",
                        message=f"Case {case_id} does not exist for incoming VIN {vin}.",
                    )
                )
                return None
            if case.vin != vin:
                self.issues.append(
                    ImportIssue(
                        severity=ImportSeverity.ERROR,
                        code="CASE_VIN_MISMATCH",
                        message=f"Case {case_id} belongs to VIN {case.vin}, not {vin}.",
                    )
                )
                return None
            return case

        matches = self._by_vin.get(vin, [])
        if not matches:
            self.issues.append(
                ImportIssue(
                    severity=ImportSeverity.ERROR,
                    code="UNKNOWN_VIN",
                    message=f"No case exists for incoming VIN {vin}.",
                )
            )
            return None
        if len(matches) > 1:
            self.issues.append(
                ImportIssue(
                    severity=ImportSeverity.ERROR,
                    code="AMBIGUOUS_VIN_CASE",
                    message=(
                        f"VIN {vin} belongs to multiple cases ({', '.join(sorted(matches))}); "
                        "an explicit case_id is required."
                    ),
                )
            )
            return None
        return self._cases[matches[0]]

    def attach_short_test(self, parsed: ParsedShortTest, case_id: str | None = None) -> None:
        case = self._resolve(parsed.session.vin, case_id)
        if case is None:
            return
        case.diagnostic_sessions.append(parsed.session)
        case.diagnostics.extend(parsed.diagnostics)
        case.ecu_states.extend(parsed.ecu_states)
        self.issues.extend(parsed.issues)

    def attach_replacements(
        self, parsed: ParsedReplacementData, case_id: str | None = None
    ) -> None:
        for event in parsed.replacements:
            case = self._resolve(event.vin, case_id)
            if case is not None:
                case.replacements.append(event)
        self.issues.extend(parsed.issues)

    def attach_supplier_findings(
        self, parsed: ParsedSupplierFindingData, case_id: str | None = None
    ) -> None:
        for event in parsed.findings:
            case = self._resolve(event.vin, case_id)
            if case is not None:
                case.supplier_findings.append(event)
        self.issues.extend(parsed.issues)

    def attach_workshop_history(
        self, parsed: ParsedWorkshopData, case_id: str | None = None
    ) -> None:
        for event in parsed.repairs:
            case = self._resolve(event.vin, case_id)
            if case is not None:
                case.repairs.append(event)
        self.issues.extend(parsed.issues)

    def attach_vehicle_software(
        self, parsed: ParsedVehicleSoftwareData, case_id: str | None = None
    ) -> None:
        for event in parsed.software_events:
            case = self._resolve(event.vin, case_id)
            if case is not None:
                case.software_events.append(event)
        for state in parsed.ecu_states:
            case = self._resolve(state.vin, case_id)
            if case is not None:
                case.ecu_states.append(state)
        self.issues.extend(parsed.issues)

    def result(self) -> AssemblyResult:
        return AssemblyResult(
            cases=sorted(self._cases.values(), key=lambda case: case.case_id),
            issues=list(self.issues),
        )
