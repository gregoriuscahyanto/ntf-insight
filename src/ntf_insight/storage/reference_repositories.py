"""Repositories for engineering reference knowledge."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from typing import Protocol

from ntf_insight.domain.reference import DTCTriggerDefinition, ECUChangeRecord


class ReferenceRepository(Protocol):
    def list_triggers(self) -> list[DTCTriggerDefinition]: ...
    def list_changes(self) -> list[ECUChangeRecord]: ...
    def find_triggers(self, ecu: str, dtc_code: str) -> list[DTCTriggerDefinition]: ...
    def find_trigger(self, ecu: str, dtc_code: str) -> DTCTriggerDefinition | None: ...
    def find_changes_for_dtc(self, ecu: str, dtc_code: str) -> list[ECUChangeRecord]: ...


class InMemoryReferenceRepository:
    """Reference repository supporting multiple definitions per ECU/DTC pair."""

    def __init__(
        self,
        triggers: Iterable[DTCTriggerDefinition] = (),
        changes: Iterable[ECUChangeRecord] = (),
    ) -> None:
        self._triggers = list(triggers)
        self._changes = list(changes)
        index: dict[tuple[str, str], list[DTCTriggerDefinition]] = defaultdict(list)
        for item in self._triggers:
            index[item.fault_key].append(item)
        self._trigger_index = dict(index)

    def list_triggers(self) -> list[DTCTriggerDefinition]:
        return list(self._triggers)

    def list_changes(self) -> list[ECUChangeRecord]:
        return list(self._changes)

    def find_triggers(self, ecu: str, dtc_code: str) -> list[DTCTriggerDefinition]:
        key = (ecu.strip().upper(), dtc_code.strip().upper())
        return list(self._trigger_index.get(key, ()))

    def find_trigger(self, ecu: str, dtc_code: str) -> DTCTriggerDefinition | None:
        matches = self.find_triggers(ecu, dtc_code)
        return matches[0] if matches else None

    def find_changes_for_dtc(self, ecu: str, dtc_code: str) -> list[ECUChangeRecord]:
        ecu_key = ecu.strip().upper()
        dtc_key = dtc_code.strip().upper()
        return [
            change
            for change in self._changes
            if change.ecu.strip().upper() == ecu_key
            and dtc_key in {code.strip().upper() for code in change.affected_dtcs}
        ]
