"""Link observed vehicle diagnostics to versioned engineering reference knowledge."""

from __future__ import annotations

from dataclasses import dataclass

from ntf_insight.domain.events import DiagnosticEvent
from ntf_insight.domain.reference import DTCTriggerDefinition, ECUChangeRecord
from ntf_insight.storage.reference_repositories import ReferenceRepository


@dataclass(frozen=True, slots=True)
class DiagnosticKnowledge:
    event: DiagnosticEvent
    triggers: tuple[DTCTriggerDefinition, ...]
    related_changes: tuple[ECUChangeRecord, ...]

    @property
    def has_trigger_definition(self) -> bool:
        return bool(self.triggers)

    @property
    def primary_trigger(self) -> DTCTriggerDefinition | None:
        return self.triggers[0] if self.triggers else None

    @property
    def has_related_release_change(self) -> bool:
        return bool(self.related_changes)


def enrich_diagnostic(
    event: DiagnosticEvent,
    references: ReferenceRepository,
) -> DiagnosticKnowledge:
    """Return all reference knowledge currently matching one observed DTC."""
    return DiagnosticKnowledge(
        event=event,
        triggers=tuple(references.find_triggers(event.ecu, event.dtc_code)),
        related_changes=tuple(references.find_changes_for_dtc(event.ecu, event.dtc_code)),
    )
