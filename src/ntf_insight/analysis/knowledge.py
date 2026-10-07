"""Link observed vehicle diagnostics to versioned engineering reference knowledge."""

from __future__ import annotations

from dataclasses import dataclass

from ntf_insight.domain.events import DiagnosticEvent
from ntf_insight.domain.reference import DTCTriggerDefinition, ECUChangeRecord
from ntf_insight.storage.reference_repositories import ReferenceRepository


@dataclass(frozen=True, slots=True)
class DiagnosticKnowledge:
    event: DiagnosticEvent
    trigger: DTCTriggerDefinition | None
    related_changes: tuple[ECUChangeRecord, ...]

    @property
    def has_trigger_definition(self) -> bool:
        return self.trigger is not None

    @property
    def has_related_release_change(self) -> bool:
        return bool(self.related_changes)


def enrich_diagnostic(
    event: DiagnosticEvent,
    references: ReferenceRepository,
) -> DiagnosticKnowledge:
    """Return reference knowledge applicable to one observed DTC."""
    return DiagnosticKnowledge(
        event=event,
        trigger=references.find_trigger(event.ecu, event.dtc_code),
        related_changes=tuple(references.find_changes_for_dtc(event.ecu, event.dtc_code)),
    )
