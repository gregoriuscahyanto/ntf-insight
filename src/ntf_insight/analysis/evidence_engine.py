"""Rule-based evidence generation.

The engine produces explainable evidence rather than an automatic final verdict.
Weights are provisional engineering heuristics and can be calibrated on real cases.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from ntf_insight.analysis.recurrence import analyze_recurrence
from ntf_insight.domain.case import NTFCase
from ntf_insight.domain.enums import (
    EvidenceDirection,
    RootCauseCategory,
    SupplierFindingResult,
)
from ntf_insight.domain.evidence import Evidence
from ntf_insight.storage.reference_repositories import ReferenceRepository


@dataclass(frozen=True, slots=True)
class EvidenceBundle:
    case_id: str
    evidence: tuple[Evidence, ...]

    def balance_by_category(self) -> dict[RootCauseCategory, float]:
        scores: dict[RootCauseCategory, float] = defaultdict(float)
        for item in self.evidence:
            if item.category_hint is None:
                continue
            if item.direction == EvidenceDirection.SUPPORTS:
                scores[item.category_hint] += item.weight
            elif item.direction == EvidenceDirection.CONTRADICTS:
                scores[item.category_hint] -= item.weight
        return dict(scores)


def generate_case_evidence(
    case: NTFCase,
    references: ReferenceRepository | None = None,
) -> EvidenceBundle:
    """Generate generic evidence from normalized case and reference data."""
    items: list[Evidence] = []
    recurrence = analyze_recurrence(case)

    if recurrence.assessable and recurrence.has_recurrence:
        faults = ", ".join(f"{ecu}:{dtc}" for ecu, dtc in sorted(recurrence.same_faults))
        items.append(
            Evidence(
                code="SAME_FAULT_AFTER_REPLACEMENT",
                description=f"Same fault(s) reappear after component replacement: {faults}.",
                direction=EvidenceDirection.CONTRADICTS,
                category_hint=RootCauseCategory.COMPONENT_SUPPLIER,
                weight=2.0,
            )
        )

    if recurrence.assessable and recurrence.pre_faults and not recurrence.same_faults:
        faults = ", ".join(
            f"{ecu}:{dtc}" for ecu, dtc in sorted(recurrence.disappeared_faults)
        )
        items.append(
            Evidence(
                code="FAULT_NOT_SEEN_IN_KNOWN_POST_TEST",
                description=(
                    "Pre-replacement fault(s) are not observed in known post-test(s): "
                    f"{faults}."
                ),
                direction=EvidenceDirection.SUPPORTS,
                category_hint=RootCauseCategory.COMPONENT_SUPPLIER,
                weight=0.75,
            )
        )

    if recurrence.assessable and recurrence.new_faults:
        faults = ", ".join(f"{ecu}:{dtc}" for ecu, dtc in sorted(recurrence.new_faults))
        items.append(
            Evidence(
                code="NEW_FAULT_AFTER_REPLACEMENT",
                description=(
                    f"New fault(s) appear after replacement: {faults}. "
                    "Check installation/process context."
                ),
                direction=EvidenceDirection.NEUTRAL,
                category_hint=RootCauseCategory.WORKSHOP_PROCESS,
                weight=0.5,
            )
        )

    for finding in case.supplier_findings:
        if finding.result == SupplierFindingResult.FAULT_FOUND:
            items.append(
                Evidence(
                    code="RETURN_PART_FAULT_REPRODUCED",
                    description="Returned-part/supplier finding reports a reproduced fault.",
                    direction=EvidenceDirection.SUPPORTS,
                    category_hint=RootCauseCategory.COMPONENT_SUPPLIER,
                    source_ref=finding.source_ref,
                    weight=3.0,
                )
            )
        elif finding.result == SupplierFindingResult.NTF:
            items.append(
                Evidence(
                    code="RETURN_PART_NTF",
                    description=(
                        "Returned-part/supplier finding is NTF; this weakens but does not "
                        "exclude a component cause."
                    ),
                    direction=EvidenceDirection.CONTRADICTS,
                    category_hint=RootCauseCategory.COMPONENT_SUPPLIER,
                    source_ref=finding.source_ref,
                    weight=1.0,
                )
            )

    if references is not None:
        semantic_ecus: dict[str, set[str]] = defaultdict(set)
        related_changes = {}
        for event in case.diagnostics:
            triggers = references.find_triggers(event.ecu, event.dtc_code)
            for trigger in triggers:
                for tag in trigger.semantic_tags:
                    semantic_ecus[tag].add(event.ecu.strip().upper())
            for change in references.find_changes_for_dtc(event.ecu, event.dtc_code):
                related_changes[change.change_id] = change

        supply_ecus = semantic_ecus.get("supply_voltage", set())
        if len(supply_ecus) >= 2:
            items.append(
                Evidence(
                    code="MULTI_ECU_SUPPLY_VOLTAGE",
                    description=(
                        "Supply-voltage diagnostic signals occur in multiple ECUs: "
                        + ", ".join(sorted(supply_ecus))
                        + "."
                    ),
                    direction=EvidenceDirection.SUPPORTS,
                    category_hint=RootCauseCategory.ELECTRICAL_SUPPLY,
                    weight=2.0,
                )
            )

        for change in related_changes.values():
            items.append(
                Evidence(
                    code="RELATED_HW_SW_CHANGE",
                    description=(
                        f"Documented {change.kind} change for {change.ecu} affects an "
                        "observed DTC"
                        + (f": {change.title}" if change.title else ".")
                    ),
                    direction=EvidenceDirection.NEUTRAL,
                    category_hint=RootCauseCategory.ECU_SOFTWARE,
                    source_ref=change.source_ref,
                    weight=0.5,
                )
            )

        for state in case.ecu_states:
            matching_changes = [
                change
                for change in related_changes.values()
                if change.ecu.strip().upper() == state.ecu.strip().upper()
                and change.to_version
                and state.software_version
                and change.to_version.strip().upper() == state.software_version.strip().upper()
            ]
            if matching_changes:
                items.append(
                    Evidence(
                        code="VEHICLE_HAS_RELEVANT_SW_STATE",
                        description=(
                            f"Observed vehicle state contains {state.ecu} {state.software_version}, "
                            "matching a documented release that affects an observed DTC."
                        ),
                        direction=EvidenceDirection.NEUTRAL,
                        category_hint=RootCauseCategory.ECU_SOFTWARE,
                        source_ref=state.source_ref,
                        weight=0.75,
                    )
                )

        for software_event in case.software_events:
            matching_changes = [
                change
                for change in related_changes.values()
                if change.ecu.strip().upper() == software_event.ecu.strip().upper()
                and change.to_version
                and software_event.software_version
                and change.to_version.strip().upper()
                == software_event.software_version.strip().upper()
            ]
            if matching_changes:
                items.append(
                    Evidence(
                        code="VEHICLE_RECEIVED_RELEVANT_SW_CHANGE",
                        description=(
                            f"Vehicle software event reaches {software_event.ecu} "
                            f"{software_event.software_version}, matching a documented "
                            "change that affects an observed DTC."
                        ),
                        direction=EvidenceDirection.SUPPORTS,
                        category_hint=RootCauseCategory.ECU_SOFTWARE,
                        source_ref=software_event.source_ref,
                        weight=1.5,
                    )
                )

    return EvidenceBundle(case_id=case.case_id, evidence=tuple(items))
