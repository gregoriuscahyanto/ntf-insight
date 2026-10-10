"""Erklaerbare Pruefprioritaet fuer Cluster mit manuell markierten DTCs.

Zuerst clustern, DANACH die Fachmarkierungen abgleichen. Ein markierter
ECU:DTC-Schluessel veraendert niemals TF-IDF, Distanzen oder HDBSCAN.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Mapping, Sequence

from ntf_insight.analysis.autoexport_fin_patterns import FinPatternGroup

FaultKey = tuple[str, str]


@dataclass(frozen=True, slots=True)
class GroupDtcPriority:
    level: str
    affected_fins: int
    total_fins: int
    marked_faults: tuple[tuple[str, str, int], ...]

    @property
    def ratio(self) -> float:
        return self.affected_fins / self.total_fins if self.total_fins else 0.0

    @property
    def label(self) -> str:
        if self.level == "hoch":
            return "Hohe Prüfpriorität"
        if self.level == "hinweis":
            return "Pruefhinweis"
        return "Keine Markierung"


def review_priority(
    group: FinPatternGroup,
    faults_by_fin: Mapping[str, Sequence[FaultKey]],
    marked: set[FaultKey] | frozenset[FaultKey],
) -> GroupDtcPriority:
    """Group priority is coverage of manually highlighted DTCs, NOT a cause."""
    normalized = {
        (ecu.strip().upper(), dtc.strip().upper()) for ecu, dtc in marked
    }
    count_by_key: Counter[FaultKey] = Counter()
    affected = 0
    for fin, _similarity in group.members:
        hits = set(faults_by_fin.get(fin, ())) & normalized
        if hits:
            affected += 1
            count_by_key.update(hits)
    ratio = affected / group.fin_count if group.fin_count else 0.0
    level = (
        "hoch" if ratio >= 0.5 and affected > 0
        else "hinweis" if affected > 0
        else "keine"
    )
    return GroupDtcPriority(
        level=level, affected_fins=affected, total_fins=group.fin_count,
        marked_faults=tuple(
            (ecu, dtc, count)
            for (ecu, dtc), count in sorted(
                count_by_key.items(),
                key=lambda item: (-item[1], item[0]),
            )
        ),
    )
