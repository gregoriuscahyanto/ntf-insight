"""Validated manual case/event management with immutable audit revisions."""

from __future__ import annotations

import getpass
from collections.abc import Mapping
from typing import TypeAlias

from pydantic import ValidationError

from ntf_insight.domain.case import NTFCase
from ntf_insight.domain.events import (
    CaseEvent,
    DiagnosticEvent,
    DiagnosticSession,
    ECUStateObservation,
    PartReplacement,
    RepairEvent,
    SoftwareEvent,
    SupplierFinding,
)
from ntf_insight.domain.manual import ManualAction, ManualChange
from ntf_insight.storage.duckdb_store import DuckDBStore


EventType: TypeAlias = type[CaseEvent]

EVENT_TYPES: Mapping[str, EventType] = {
    "diagnostic_session": DiagnosticSession,
    "diagnostic": DiagnosticEvent,
    "replacement": PartReplacement,
    "repair": RepairEvent,
    "software": SoftwareEvent,
    "ecu_state": ECUStateObservation,
    "supplier": SupplierFinding,
}

EVENT_LISTS: Mapping[str, str] = {
    "diagnostic_session": "diagnostic_sessions",
    "diagnostic": "diagnostics",
    "replacement": "replacements",
    "repair": "repairs",
    "software": "software_events",
    "ecu_state": "ecu_states",
    "supplier": "supplier_findings",
}


class ManualEntryError(ValueError):
    """An invalid or ambiguous manual edit was rejected."""


def _validate_event(kind: str, event: CaseEvent, case: NTFCase) -> CaseEvent:
    model = EVENT_TYPES.get(kind)
    if model is None:
        raise ManualEntryError(f"Unbekannter Ereignistyp: {kind}")
    if not isinstance(event, model):
        raise ManualEntryError("Ereignismodell passt nicht zur Ereignisart.")
    try:
        event = model.model_validate(event.model_dump())
    except ValidationError as exc:
        raise ManualEntryError(str(exc)) from exc
    if event.vin != case.vin:
        raise ManualEntryError("Ereignis-FIN stimmt nicht mit der Fall-FIN überein.")
    if isinstance(event, (DiagnosticEvent, ECUStateObservation)):
        if event.session_id and not any(
            item.session_id == event.session_id for item in case.diagnostic_sessions
        ):
            raise ManualEntryError("Die ausgewählte Kurztest-Sitzung existiert nicht.")
    if isinstance(event, (DiagnosticEvent, ECUStateObservation, SoftwareEvent)):
        if not event.ecu.strip():
            raise ManualEntryError("Steuergerät darf nicht leer sein.")
    if isinstance(event, DiagnosticEvent) and not event.dtc_code.strip():
        raise ManualEntryError("DTC-Code darf nicht leer sein.")
    if isinstance(event, PartReplacement) and not event.component_type.strip():
        raise ManualEntryError("Bauteil darf nicht leer sein.")
    return event


class ManualCaseService:
    """Write through to DuckDB; never mutate demo cases or original source artifacts."""

    def __init__(self, store: DuckDBStore, actor: str | None = None) -> None:
        self.store = store
        self.actor = actor or getpass.getuser()

    def _get_persisted(self, case_id: str) -> NTFCase:
        case = self.store.get_case(case_id)
        if case is None:
            raise ManualEntryError(
                "Dieser Fall ist nur in den Demo-Daten vorhanden oder existiert nicht. "
                "Bitte zuerst einen echten Fall anlegen."
            )
        return case

    def create_case(self, case: NTFCase) -> NTFCase:
        case_id = case.case_id.strip()
        vin = case.vin.strip()
        component = case.component_type.strip()
        if not case_id or not vin or not component:
            raise ManualEntryError("Fall-ID, FIN und Bauteil sind Pflichtfelder.")
        if self.store.get_case(case_id) is not None:
            raise ManualEntryError(f"Die Fall-ID {case_id} ist bereits vergeben.")
        normalized = case.model_copy(deep=True)
        normalized.case_id = case_id
        normalized.component_type = component
        normalized.vehicle = normalized.vehicle.model_copy(update={"vin": vin})
        normalized = NTFCase.model_validate(normalized.model_dump())
        change = ManualChange(
            case_id=case_id,
            action=ManualAction.CREATE_CASE,
            entity_type="case",
            actor=self.actor,
            after_json=normalized.model_dump_json(),
        )
        self.store.save_manual_revision(normalized, change)
        return normalized

    def add_event(
        self,
        case_id: str,
        kind: str,
        event: CaseEvent,
        *,
        set_replacement_anchor: bool = False,
    ) -> NTFCase:
        case = self._get_persisted(case_id)
        event = _validate_event(kind, event, case)
        if any(
            item.event_id == event.event_id
            for attr in EVENT_LISTS.values()
            for item in getattr(case, attr)
        ):
            raise ManualEntryError("Die Ereignis-ID existiert bereits.")
        change = ManualChange(
            case_id=case_id,
            action=ManualAction.ADD_EVENT,
            entity_type=kind,
            event_id=event.event_id,
            actor=self.actor,
            after_json="{}",
        )
        event = event.model_copy(
            update={"source_ref": f"manual:{change.change_id}"}
        )
        getattr(case, EVENT_LISTS[kind]).append(event)
        if kind == "replacement" and isinstance(event, PartReplacement):
            if (
                set_replacement_anchor
                or (
                    case.investigated_replacement_id is None
                    and event.component_type.casefold() == case.component_type.casefold()
                    and len([
                        r for r in case.replacements
                        if r.component_type.casefold() == case.component_type.casefold()
                    ]) == 1
                )
            ):
                case.investigated_replacement_id = event.event_id
        change = change.model_copy(update={"after_json": event.model_dump_json()})
        self.store.save_manual_revision(case, change)
        return case

    def correct_event(
        self,
        case_id: str,
        kind: str,
        event_id: str,
        corrected: CaseEvent,
    ) -> NTFCase:
        case = self._get_persisted(case_id)
        corrected = _validate_event(kind, corrected, case)
        if corrected.event_id != event_id:
            raise ManualEntryError("Ereignis-ID darf bei Korrekturen nicht geändert werden.")
        events = getattr(case, EVENT_LISTS[kind], None)
        if events is None:
            raise ManualEntryError("Unbekannter Ereignistyp.")
        index = next(
            (index for index, item in enumerate(events) if item.event_id == event_id),
            None,
        )
        if index is None:
            raise ManualEntryError("Das zu korrigierende Ereignis existiert nicht.")
        original = events[index]
        if isinstance(original, DiagnosticSession) and isinstance(corrected, DiagnosticSession):
            if original.session_id != corrected.session_id:
                raise ManualEntryError("Die Kurztest-Sitzungs-ID darf nicht geändert werden.")
        change = ManualChange(
            case_id=case_id,
            action=ManualAction.CORRECT_EVENT,
            entity_type=kind,
            event_id=event_id,
            actor=self.actor,
            before_json=original.model_dump_json(),
            after_json="{}",
            source_ref=original.source_ref,
        )
        corrected = corrected.model_copy(
            update={"source_ref": f"manual:correction:{change.change_id}"}
        )
        events[index] = corrected
        change = change.model_copy(update={"after_json": corrected.model_dump_json()})
        self.store.save_manual_revision(case, change)
        return case
