"""FIN-first join of locally imported AutoExport and proven pre-swap QEC DTCs.

No extra vehicle is created when a VIN appears in both sources. QEC outcome,
supplier/SSL findings and post-swap diagnostics are NEVER clustering features.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Mapping, Sequence

from ntf_insight.analysis.diagnostic_observations import dtc_description_catalog
from ntf_insight.analysis.recurrence import relative_to_replacement
from ntf_insight.domain.case import NTFCase

FaultKey = tuple[str, str]


@dataclass(frozen=True, slots=True)
class QECFinEvidence:
    """Pre-swap evidence for QEC coolant-pump VINs, prepared locally."""

    pre_swap_faults: dict[str, tuple[FaultKey, ...]]
    labels: dict[FaultKey, str]
    case_links: dict[str, tuple[str, ...]]
    pump_swap_dates: dict[str, str]


@dataclass(frozen=True, slots=True)
class CombinedFinEvidence:
    """Single FIN population and features, independent of source row count."""

    fins: tuple[str, ...]
    faults: dict[str, tuple[FaultKey, ...]]
    labels: dict[FaultKey, str]
    case_links: dict[str, tuple[str, ...]]
    sources: dict[str, str]
    autoexport_fin_count: int
    qec_fin_count: int
    overlap_fin_count: int
    qec_only_fin_count: int


def qec_fin_evidence(cases: Sequence[NTFCase]) -> QECFinEvidence:
    """Get actual pre-pump-swap observations; keep same-day ambiguity out."""
    faults: dict[str, set[FaultKey]] = defaultdict(set)
    links: dict[str, set[str]] = defaultdict(set)
    anchors: dict[str, str] = {}
    pump_cases: list[NTFCase] = []
    for case in cases:
        if case.component_profile_id != "coolant_pump" or not case.qec_reference:
            continue
        fin = case.vin.strip().upper()
        links[fin].add(case.case_id)
        pump_cases.append(case)
        swap = case.investigated_replacement()
        if swap is None:
            continue
        date = swap.occurred_at.date().isoformat()
        if fin not in anchors or date < anchors[fin]:
            anchors[fin] = date
    # A FIN can have multiple QEC pump cases. Compare diagnostics with the
    # EARLIEST recorded investigated replacement: later case histories must
    # never reintroduce what could be post-swap evidence.
    from datetime import date
    earliest = {
        fin: date.fromisoformat(value)
        for fin, value in anchors.items()
    }
    for case in pump_cases:
        fin = case.vin.strip().upper()
        swap = case.investigated_replacement()
        if swap is None:
            continue
        for event in case.diagnostics:
            if (
                relative_to_replacement(event, swap) == "pre"
                and event.occurred_at.date() < earliest[fin]
            ):
                faults[fin].add(event.fault_key)
    return QECFinEvidence(
        pre_swap_faults={
            fin: tuple(sorted(values)) for fin, values in faults.items()
        },
        labels=dtc_description_catalog(pump_cases),
        case_links={fin: tuple(sorted(ids)) for fin, ids in links.items()},
        pump_swap_dates=anchors,
    )


def merge_fin_evidence(
    auto_fins: Sequence[str],
    auto_faults: Mapping[str, Sequence[FaultKey]],
    auto_labels: Mapping[FaultKey, str],
    qec: QECFinEvidence,
    *,
    only_pump_swap: bool = False,
) -> CombinedFinEvidence:
    """Union by FIN; QEC DTCs influence the SAME vector as AutoExport DTCs."""
    auto_set = {fin.strip().upper() for fin in auto_fins}
    qec_set = set(qec.case_links)
    permitted = (
        set(qec.pump_swap_dates)
        if only_pump_swap else auto_set | qec_set
    )
    # Include explicitly dated QEC VINs even if their AutoExport is missing.
    if only_pump_swap:
        permitted &= auto_set | qec_set
    actual_qec = permitted & qec_set
    overlap = auto_set & actual_qec
    merged: dict[str, tuple[FaultKey, ...]] = {}
    sources: dict[str, str] = {}
    for fin in sorted(permitted):
        from_auto = {
            (ecu.strip().upper(), dtc.strip().upper())
            for ecu, dtc in auto_faults.get(fin, ())
        }
        from_qec = set(qec.pre_swap_faults.get(fin, ()))
        # Unanchored QECs never contribute QEC post-swap/unknown features.
        merged[fin] = tuple(sorted(from_auto | from_qec))
        if from_auto and from_qec:
            sources[fin] = "AutoExport + QEC"
        elif from_auto:
            sources[fin] = "AutoExport"
        elif from_qec:
            sources[fin] = "QEC / QuickTest"
        else:
            sources[fin] = "Keine geeigneten DTCs"
    labels = {**qec.labels, **auto_labels}
    return CombinedFinEvidence(
        fins=tuple(sorted(permitted)),
        faults=merged,
        labels=labels,
        case_links={
            fin: qec.case_links[fin]
            for fin in sorted(actual_qec)
        },
        sources=sources,
        autoexport_fin_count=len(auto_set),
        qec_fin_count=len(actual_qec),
        overlap_fin_count=len(overlap),
        qec_only_fin_count=len(actual_qec - auto_set),
    )
