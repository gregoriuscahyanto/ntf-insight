"""Read-only, disjoint reasons for excluded QEC pre-pump-swap diagnostics."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from ntf_insight.analysis.case_clustering import (
    _in_diagnostic_window, _matches_dtc_source, signature_for,
)
from ntf_insight.analysis.cluster_workspace_engine import (
    ClusterParameters, UnifiedClusterResult,
)
from ntf_insight.domain.case import NTFCase


@dataclass(frozen=True, slots=True)
class ExclusionReasons:
    no_swap_anchor: int = 0
    no_imported_dtc: int = 0
    no_selected_source: int = 0
    no_pre_swap_dtc: int = 0
    filtered_by_frequency: int = 0
    other: int = 0

    @property
    def total(self) -> int:
        return sum((
            self.no_swap_anchor,
            self.no_imported_dtc,
            self.no_selected_source,
            self.no_pre_swap_dtc,
            self.filtered_by_frequency,
            self.other,
        ))

    @property
    def text(self) -> str:
        return (
            "Warum vor dem Tausch nicht auswertbar? "
            f"{self.no_swap_anchor} ohne belegten Pumpentausch-Anker · "
            f"{self.no_imported_dtc} ohne verknüpfte DTC-Beobachtung · "
            f"{self.no_selected_source} ohne DTC aus gewählter Quelle · "
            f"{self.no_pre_swap_dtc} ohne zeitlich geeigneten Vor-Tausch-DTC · "
            f"{self.filtered_by_frequency} nur durch Häufigkeitsfilter "
            f"ausgeschlossen · {self.other} sonstige Fälle. "
            "Die Angaben gelten für die aktuelle Auswahl. "
            "Fehlende Vor-Tausch-Evidenz beweist nicht, "
            "dass keine Werkstattdiagnose stattfand."
        )


def exclusion_reasons(
    cases: Sequence[NTFCase],
    result: UnifiedClusterResult,
) -> ExclusionReasons:
    """Explain the EXACT locally excluded case IDs; no VINs leave the GUI."""
    by_id = {case.case_id: case for case in cases}
    excluded = result.excluded_case_ids
    if any(case_id not in by_id for case_id in excluded):
        raise ValueError("Ausschlussprüfung verwendet einen anderen QEC-Bestand.")
    params: ClusterParameters = result.parameters
    buckets = {
        "no_swap_anchor": 0,
        "no_imported_dtc": 0,
        "no_selected_source": 0,
        "no_pre_swap_dtc": 0,
        "filtered_by_frequency": 0,
        "other": 0,
    }
    for case_id in excluded:
        case = by_id[case_id]
        replacement = case.investigated_replacement()
        if replacement is None:
            bucket = "no_swap_anchor"
        elif not case.diagnostics:
            bucket = "no_imported_dtc"
        else:
            in_source = [
                d for d in case.diagnostics
                if _matches_dtc_source(d, params.dtc_source)
            ]
            if not in_source:
                bucket = "no_selected_source"
            elif not any(
                _in_diagnostic_window(
                    d, case, lookback_days=params.lookback_days
                )
                for d in in_source
            ):
                bucket = "no_pre_swap_dtc"
            elif params.common_dtc_cutoff is not None and signature_for(
                case, dtc_source=params.dtc_source,
                lookback_days=params.lookback_days,
            ).faults:
                bucket = "filtered_by_frequency"
            else:
                bucket = "other"
        buckets[bucket] += 1
    breakdown = ExclusionReasons(**buckets)
    if breakdown.total != len(excluded):
        raise ValueError("Ausschlussgründe passen nicht zum Ergebnisbestand.")
    return breakdown
