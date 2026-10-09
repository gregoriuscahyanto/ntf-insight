"""Overlapping ECU:DTC search groups, *not* confirmed NTF clusters.

A diagnostic observation can be shared between cases without indicating the
same root cause. In contrast to weighted Jaccard, this discovery view does not
penalize every unrelated DTC in large historical vehicle exports. It is an
explicit, auditable candidate search independent of Complete-Link colours.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from ntf_insight.analysis.case_clustering import (
    FaultKey,
    signature_for,
)
from ntf_insight.domain.case import NTFCase


@dataclass(frozen=True, slots=True)
class DtcCasePattern:
    """Cases sharing one exact, pre-intervention ECU:DTC observation."""

    component_key: str
    fault: FaultKey
    case_ids: tuple[str, ...]
    vehicle_count: int
    anchored_count: int

    @property
    def label(self) -> str:
        return f"{self.fault[0]}:{self.fault[1]}"

    @property
    def case_count(self) -> int:
        return len(self.case_ids)


def discover_case_dtc_patterns(
    cases: list[NTFCase],
    *,
    lookback_days: int | None = None,
    dtc_source: str = "all",
    min_cases: int = 2,
) -> tuple[DtcCasePattern, ...]:
    """Find reproducible, overlapping DTC patterns across real QEC cases.

    Cases are not synthesised from DTC rows, TIPS IDs or FINs. Every code counts
    once per QEC case regardless of repeated QuickTest/AutoExport rows. Different
    component families never form a shared group. A pattern does not require a
    shared repair history or a Complete-Link match; do not label it 'confirmed'.
    """
    if min_cases < 2:
        raise ValueError("Mindestens zwei Fälle pro DTC-Muster erforderlich.")
    if len({case.case_id for case in cases}) != len(cases):
        raise ValueError("Fall-IDs müssen eindeutig sein.")
    grouped: dict[tuple[str, FaultKey], set[str]] = defaultdict(set)
    case_by_id = {case.case_id: case for case in cases}
    for case in cases:
        sig = signature_for(
            case, lookback_days=lookback_days, dtc_source=dtc_source
        )
        for fault in sig.faults:
            grouped[(sig.component_key, fault)].add(case.case_id)

    patterns = []
    for (component_key, fault), case_ids in grouped.items():
        if len(case_ids) < min_cases:
            continue
        members = tuple(sorted(case_ids))
        patterns.append(DtcCasePattern(
            component_key=component_key,
            fault=fault,
            case_ids=members,
            vehicle_count=len({case_by_id[case_id].vin for case_id in members}),
            anchored_count=sum(
                case_by_id[case_id].investigated_replacement() is not None
                for case_id in members
            ),
        ))
    # Multi-FIN evidence first, then strength of population, stable tie breaks.
    return tuple(sorted(
        patterns,
        key=lambda p: (
            -(p.vehicle_count >= 2), -p.vehicle_count,
            -p.case_count, p.component_key, p.fault,
        ),
    ))
