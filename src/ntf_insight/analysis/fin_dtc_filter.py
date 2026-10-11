"""Explizite ECU-/DTC-Regeln ausschließlich für Diagnose-Clustermerkmale.

Die Originalbeobachtungen, Vorher-/Nachher-Vergleiche und DTC-Markierungen
bleiben unangetastet. Ausschlüsse haben Vorrang; mehrere positive
Steuergeräte- und ECU:DTC-Auswahlen sind eine ODER-Verknüpfung.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

FaultKey = tuple[str, str]


def _ecu(value: str) -> str:
    return str(value).strip().upper()


def _fault(value: FaultKey) -> FaultKey:
    return _ecu(value[0]), _ecu(value[1])


@dataclass(frozen=True, slots=True)
class DtcClusterFilter:
    """Leer bedeutet: alle zulässigen DTCs, ohne manuelle Einschränkung."""

    include_ecus: frozenset[str] = frozenset()
    include_faults: frozenset[FaultKey] = frozenset()
    exclude_ecus: frozenset[str] = frozenset()
    exclude_faults: frozenset[FaultKey] = frozenset()

    @classmethod
    def from_sets(
        cls,
        *,
        include_ecus: Sequence[str] = (),
        include_faults: Sequence[FaultKey] = (),
        exclude_ecus: Sequence[str] = (),
        exclude_faults: Sequence[FaultKey] = (),
    ) -> DtcClusterFilter:
        def ecus(values: Sequence[str]) -> frozenset[str]:
            return frozenset(
                normalized for value in values
                if (normalized := _ecu(value))
            )

        def faults(values: Sequence[FaultKey]) -> frozenset[FaultKey]:
            return frozenset(
                normalized for value in values
                if all(normalized := _fault(value))
            )

        return cls(
            include_ecus=ecus(include_ecus),
            include_faults=faults(include_faults),
            exclude_ecus=ecus(exclude_ecus),
            exclude_faults=faults(exclude_faults),
        )

    @property
    def active(self) -> bool:
        return bool(
            self.include_ecus or self.include_faults
            or self.exclude_ecus or self.exclude_faults
        )

    def allows(self, ecu: str, dtc: str) -> bool:
        """Positiv-ECUs ODER positive ECU:DTCs; Ausschlüsse zuerst."""
        key = _fault((ecu, dtc))
        if not all(key):
            return False
        if key[0] in self.exclude_ecus or key in self.exclude_faults:
            return False
        if self.include_ecus or self.include_faults:
            return key[0] in self.include_ecus or key in self.include_faults
        return True

    def filter_faults(
        self, signatures: Mapping[str, Sequence[FaultKey]],
    ) -> dict[str, tuple[FaultKey, ...]]:
        """Jede FIN bleibt erhalten, auch wenn alle Merkmale wegfallen."""
        return {
            fin: tuple(sorted({
                normalized
                for raw in entries
                if (normalized := _fault(raw))
                and self.allows(*normalized)
            }))
            for fin, entries in signatures.items()
        }

    def summary(self) -> str:
        if not self.active:
            return "Alle zulässigen Steuergeräte und DTCs"
        return (
            f"Nur: {len(self.include_ecus)} Steuergeräte, "
            f"{len(self.include_faults)} ECU:DTCs · "
            f"Ausschließen: {len(self.exclude_ecus)} Steuergeräte, "
            f"{len(self.exclude_faults)} ECU:DTCs"
        )
