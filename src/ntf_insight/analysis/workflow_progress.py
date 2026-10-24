"""Kompakte, komponentenunabhängige Fortschrittsberechnung für den QEC-Workflow.

Ein Ampelstatus ist ausschließlich ein Bearbeitungsstatus, kein technisches
Fehlerurteil und keine Lieferanten-Schuldzuweisung.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping


def norm_sachnummer(value: str) -> str:
    """Gleiche Sachnummer trotz Leerzeichen, Bindestrichen und Punkten."""
    return "".join(character for character in str(value).casefold() if character.isalnum())


def filter_part_rows(rows: Iterable[Mapping], sachnummer: str) -> list[dict]:
    query = norm_sachnummer(sachnummer)
    if not query:
        return [dict(row) for row in rows]
    return [
        dict(row) for row in rows
        if norm_sachnummer(str(row.get("part_number", ""))) == query
    ]


@dataclass(frozen=True, slots=True)
class WorkflowProgress:
    cases: int
    fins: int
    downloaded: int
    with_tp: int
    ntf: int
    not_ntf: int
    open: int
    quicktest_fins: int
    handed_off: int

    @classmethod
    def from_rows(
        cls,
        rows: Iterable[Mapping],
        quicktest_fins: Iterable[str] = (),
        handed_off_fins: Iterable[str] = (),
        *,
        sachnummer: str = "",
    ) -> "WorkflowProgress":
        matched = filter_part_rows(rows, sachnummer)
        fins = {row["fin"] for row in matched}
        return cls(
            cases=len(matched),
            fins=len(fins),
            downloaded=len({row["fin"] for row in matched if row.get("report")}),
            with_tp=len({row["fin"] for row in matched if row.get("tp_dashboard")}),
            ntf=sum(row.get("decision") == "NTF" for row in matched),
            not_ntf=sum(row.get("decision") == "Kein NTF" for row in matched),
            open=sum(row.get("decision") not in {"NTF", "Kein NTF"} for row in matched),
            quicktest_fins=len(fins.intersection(set(quicktest_fins))),
            handed_off=len(fins.intersection(set(handed_off_fins))),
        )

    @property
    def completion(self) -> int:
        """Datenabdeckung; keine Behauptung, die Ursachenanalyse sei abgeschlossen."""
        if not self.cases or not self.fins:
            return 0
        shares = (
            1.0,  # QEC-Kohorte liegt vor
            self.downloaded / self.fins,
            (self.ntf + self.not_ntf) / self.cases,
            self.quicktest_fins / self.fins,
            self.with_tp / self.fins,
        )
        return round(100 * sum(shares) / len(shares))

    @property
    def next_step(self) -> str:
        if not self.cases:
            return "qec"
        if self.downloaded < self.fins:
            return "befund"
        if self.open:
            return "entscheidung"
        if self.ntf and not self.handed_off:
            return "ntf"
        if self.quicktest_fins < self.fins or self.with_tp < self.fins:
            return "diagnose"
        return "cluster"

    def statuses(self) -> dict[str, str]:
        def progress(complete: int, total: int) -> str:
            if not total or not complete:
                return "off"
            return "ready" if complete >= total else "progress"

        return {
            "qec": "ready" if self.cases else "off",
            "befund": progress(self.downloaded, self.fins),
            "entscheidung": progress(self.ntf + self.not_ntf, self.cases),
            "kein_ntf": "progress" if self.not_ntf else "off",
            "ntf": "ready" if self.handed_off else ("progress" if self.ntf else "off"),
            "diagnose": progress(
                self.quicktest_fins + self.with_tp, 2 * self.fins,
            ),
            # Freigabe zur Clusterung bedeutet noch nicht: Cluster analysiert.
            "cluster": "progress" if self.handed_off else "off",
        }
