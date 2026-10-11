"""Explizite, reproduzierbare ECU-/DTC-Merkmalsauswahl für FIN-Cluster.

Die Regeln werden erst NACH der zeitlichen Freigabe von Diagnosen angewendet.
Original-DTCs und Fahrzeughistorien bleiben unverändert.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

FaultKey = tuple[str, str]


@dataclass(frozen=True)
class ClusterDtcFilter:
    include_ecus: frozenset[str] = frozenset()
    exclude_ecus: frozenset[str] = frozenset()
    include_faults: frozenset[FaultKey] = frozenset()
    exclude_faults: frozenset[FaultKey] = frozenset()
    include_findings: frozenset[str] = frozenset()
    exclude_findings: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        for name in ("include_findings", "exclude_findings"):
            object.__setattr__(
                self, name,
                frozenset(" ".join(str(value).split()).casefold()
                          for value in getattr(self, name)),
            )
        for name in ("include_ecus", "exclude_ecus"):
            object.__setattr__(
                self, name,
                frozenset(value.strip().upper() for value in getattr(self, name)),
            )
        for name in ("include_faults", "exclude_faults"):
            object.__setattr__(
                self, name,
                frozenset(
                    (ecu.strip().upper(), dtc.strip().upper())
                    for ecu, dtc in getattr(self, name)
                ),
            )

    def accepts(self, ecu: str, dtc: str) -> bool:
        key = (ecu.strip().upper(), dtc.strip().upper())
        if key[0] in self.exclude_ecus or key in self.exclude_faults:
            return False
        if self.include_ecus or self.include_faults:
            return key[0] in self.include_ecus or key in self.include_faults
        return True

    def filter_signatures(
        self, faults: Mapping[str, Sequence[FaultKey]],
    ) -> dict[str, tuple[FaultKey, ...]]:
        return {
            fin: tuple(sorted({
                (ecu.strip().upper(), dtc.strip().upper())
                for ecu, dtc in values
                if self.accepts(ecu, dtc)
            }))
            for fin, values in faults.items()
        }

    @property
    def dtc_active(self) -> bool:
        return bool(
            self.include_ecus or self.exclude_ecus
            or self.include_faults or self.exclude_faults
        )

    @property
    def finding_active(self) -> bool:
        return bool(self.include_findings or self.exclude_findings)

    @property
    def active(self) -> bool:
        return self.dtc_active or self.finding_active
