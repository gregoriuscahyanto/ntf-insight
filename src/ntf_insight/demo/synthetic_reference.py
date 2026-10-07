"""Fictional engineering reference data used by the desktop demo."""

from __future__ import annotations

from datetime import date

from ntf_insight.domain.reference import ChangeKind, DTCTriggerDefinition, ECUChangeRecord
from ntf_insight.storage.reference_repositories import InMemoryReferenceRepository


def build_demo_reference_repository() -> InMemoryReferenceRepository:
    triggers = [
        DTCTriggerDefinition(
            definition_id="DEMO-TRIGGER-P26F100",
            ecu="CPC3",
            dtc_code="P26F100",
            dtc_text="Coolant pump performance",
            trigger_text="Synthetic example: monitored pump response is outside the expected range.",
            enable_conditions=["Synthetic engine/thermal enable condition"],
            reset_or_healing_conditions=["Synthetic monitor passes for a defined period"],
            source_ref="synthetic:smr-d:cpc3",
        ),
        DTCTriggerDefinition(
            definition_id="DEMO-TRIGGER-P260000",
            ecu="CPC3",
            dtc_code="P260000",
            dtc_text="Coolant pump control circuit",
            trigger_text="Synthetic example: electrical control-circuit monitor detects an implausible state.",
            source_ref="synthetic:smr-d:cpc3",
        ),
        DTCTriggerDefinition(
            definition_id="DEMO-TRIGGER-P260100",
            ecu="CPC3",
            dtc_code="P260100",
            dtc_text="Coolant pump control circuit low",
            trigger_text="Synthetic example: control-circuit level is below the expected range.",
            source_ref="synthetic:smr-d:cpc3",
        ),
        DTCTriggerDefinition(
            definition_id="DEMO-TRIGGER-U300316-MCM",
            ecu="MCM",
            dtc_code="U300316",
            dtc_text="Supply voltage too low",
            trigger_text="Synthetic example: ECU supply voltage falls below its diagnostic threshold.",
            source_ref="synthetic:smr-d:mcm",
        ),
        DTCTriggerDefinition(
            definition_id="DEMO-TRIGGER-U300316-ACM",
            ecu="ACM",
            dtc_code="U300316",
            dtc_text="Supply voltage too low",
            trigger_text="Synthetic example: ECU supply voltage falls below its diagnostic threshold.",
            source_ref="synthetic:smr-d:acm",
        ),
    ]

    changes = [
        ECUChangeRecord(
            change_id="DEMO-CPC3-SW-20",
            ecu="CPC3",
            kind=ChangeKind.SOFTWARE,
            from_version="DEMO-1.0",
            to_version="DEMO-2.0",
            release_date=date(2026, 1, 1),
            title="Synthetic coolant-pump diagnostic update",
            change_summary="Fictional example of a release changing the coolant-pump diagnostic monitor.",
            affected_dtcs=["P26F100"],
            affected_functions=["Coolant pump diagnosis"],
            source_ref="synthetic:release-history:cpc3",
        )
    ]
    return InMemoryReferenceRepository(triggers=triggers, changes=changes)
