"""Explain diagnostic cluster membership using ONLY pre-replacement inputs.

The explanations describe observed feature overlaps, not causal feature
attributions, independent defect confirmations or supplier responsibility.
All QEC/VIN/DTC-level contents remain in the local GUI.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Sequence

from ntf_insight.analysis.case_clustering import FaultKey, signature_for
from ntf_insight.analysis.cluster_workspace_engine import (
    ClusterParameters, UnifiedCluster,
)
from ntf_insight.domain.case import NTFCase


@dataclass(frozen=True, slots=True)
class ClusterExplanation:
    """Local-only, human-readable context for one selected cluster."""

    heading: str
    lines: tuple[str, ...]
    per_case: tuple[tuple[str, str], ...]

    @property
    def text(self) -> str:
        return "\n".join(self.lines)

    def evidence_for(self, case_id: str) -> str:
        return dict(self.per_case).get(case_id, "Keine Einzelfallevidenz.")


def _format_fault(fault: FaultKey) -> str:
    return f"{fault[0]}:{fault[1]}"


def _compact_faults(faults: list[FaultKey], limit: int = 4) -> str:
    selected = ", ".join(_format_fault(fault) for fault in faults[:limit])
    extra = len(faults) - limit
    return selected + (f" (+{extra} weitere)" if extra > 0 else "")


def explain_cluster(
    cases: Sequence[NTFCase],
    group: UnifiedCluster,
    parameters: ClusterParameters,
    eligible_case_ids: Sequence[str],
    *,
    strict_review: bool = False,
) -> ClusterExplanation:
    """Explain overlapping original diagnostic features for real group members.

    The active DTC source, before-replacement time window, and cohort-specific
    prevalence screen match the run. Neither QEC supplier outcomes nor SSL
    final findings are inspected. This is a descriptive explanation, not an
    exact decomposition of TF-IDF weights or an HDBSCAN causal attribution.
    """
    by_id = {case.case_id: case for case in cases}
    members = tuple(group.case_ids)
    if not members or any(cid not in by_id for cid in members):
        raise ValueError("Cluster-Erklärung: Fälle fehlen in der lokalen Datenbasis.")
    if group.representative_case_id not in members:
        raise ValueError("Cluster-Erklärung: Repräsentant gehört nicht zur Gruppe.")
    eligible = set(eligible_case_ids)
    if not set(members).issubset(eligible):
        raise ValueError("Cluster-Erklärung: Gruppe gehört zu anderer Datenbasis.")

    signatures = {
        cid: signature_for(
            by_id[cid], dtc_source=parameters.dtc_source,
            lookback_days=parameters.lookback_days,
        )
        for cid in (eligible if parameters.common_dtc_cutoff is not None else members)
    }
    excluded_faults: frozenset[FaultKey] = frozenset()
    if parameters.common_dtc_cutoff is not None:
        prevalence = Counter(
            fault for cid in eligible for fault in signatures[cid].faults
        )
        excluded_faults = frozenset(
            fault for fault, count in prevalence.items()
            if count / len(eligible) >= parameters.common_dtc_cutoff
        ) if eligible else frozenset()

    fault_sets = {
        cid: signatures[cid].faults - excluded_faults for cid in members
    }
    counts: Counter[FaultKey] = Counter(
        fault for cid in members for fault in fault_sets[cid]
    )
    total = len(members)
    common = sorted(fault for fault, count in counts.items() if count == total)
    additional = sorted(
        (
            (fault, count) for fault, count in counts.items()
            if 2 <= count < total and count / total >= 0.5
        ),
        key=lambda item: (-item[1], item[0][0] != "CPC3", item[0]),
    )

    label = "Prüfgruppe" if strict_review else "Cluster"
    heading = f"Warum sind diese {total} Fälle in {label} {'K' if strict_review else 'C'}{group.cluster_id}?"
    lines = []
    if common:
        lines.append(
            f"Identische ECU:DTC in allen {total} Fällen: "
            f"{_compact_faults(common)}."
        )
    else:
        lines.append(
            "Kein identischer ECU:DTC ist in allen Fällen vorhanden. "
            "Die Fälle sind nur aufgrund kombinierter Diagnosemerkmale "
            "und der Gruppierungsregel zusammengefasst."
        )
    if additional:
        shortlist = ", ".join(
            f"{_format_fault(fault)} ({count}/{total})"
            for fault, count in additional[:4]
        )
        lines.append(
            "Weitere häufige, aber nicht durchgängige DTCs: "
            + shortlist
            + (f" (+{len(additional) - 4} weitere)." if len(additional) > 4 else ".")
        )

    complaints = Counter(
        token for cid in members for token in signatures[cid].complaint_tokens
    )
    shared_complaints = [
        (token, count) for token, count in complaints.items()
        if count >= 2 and count / total >= 0.5
    ]
    shared_complaints.sort(key=lambda item: (-item[1], item[0]))
    if shared_complaints:
        snippets = ", ".join(
            f"{token} ({count}/{total})"
            for token, count in shared_complaints[:3]
        )
        lines.append(f"Ähnliche dokumentierte Beanstandungsbegriffe: {snippets}.")

    if parameters.method in {"leaf", "eom"} and not strict_review:
        lines.append(
            "HDBSCAN bildet Dichtegruppen aus mehreren gewichteten Vor-Tausch-"
            "Merkmalen (insbesondere ECU:DTC). Einzelne identische DTCs "
            "bestimmen die Clusterzuordnung nicht allein."
        )
    elif parameters.method == "complete_legacy" and not strict_review:
        lines.append(
            "Complete-Link DTC-Jaccard gruppiert nach einer gesonderten "
            "gewichteten Diagnose-Set-Ähnlichkeit."
        )
    else:
        lines.append(
            "Complete-Link Cosinus gruppiert nur Fälle, deren paarweise "
            "Diagnoseähnlichkeit die gewählte Schwelle erreicht."
        )

    if group.weak_pair_count:
        lines.append(
            f"Achtung: {group.weak_pair_count}/{group.internal_pair_count} "
            "Fallpaare haben einen Cosinusindex unter 45 %. "
            "Die Gruppe ist diagnostisch uneinheitlich."
        )
    elif not common:
        lines.append(
            "Achtung: Ohne gemeinsamen DTC-Kern ist eine Übertragung "
            "technischer Ursachen besonders unsicher."
        )
    if total != group.vehicle_count:
        lines.append(
            f"{total} QEC-Fälle stammen von {group.vehicle_count} "
            "verschiedenen FINs; Mehrfachfälle derselben FIN sind "
            "keine unabhängigen Fahrzeuge."
        )
    if excluded_faults:
        lines.append(
            "Der aktivierte Häufigkeitsfilter hat verbreitete ECU:DTCs "
            "aus den Clustering-Merkmalen entfernt."
        )
    lines.append(
        "Wichtig: Diagnoseähnlichkeit ist kein Nachweis einer identischen "
        "Pumpenursache oder einer Lieferantenverantwortung."
    )

    representative = fault_sets[group.representative_case_id]
    per_case = []
    for cid in members:
        if cid == group.representative_case_id:
            reason = "Repräsentativer Fall der Gruppe (Medoid)."
        else:
            shared = sorted(fault_sets[cid] & representative)
            reason = (
                f"{len(shared)} gleiche ECU:DTC wie der Repräsentant: "
                f"{_compact_faults(shared, limit=3)}"
                if shared else
                "Kein identischer ECU:DTC zum Repräsentanten; "
                "andere Merkmale und die Clusterstruktur können verbinden."
            )
        per_case.append((cid, reason))
    return ClusterExplanation(
        heading=heading, lines=tuple(lines), per_case=tuple(per_case),
    )
