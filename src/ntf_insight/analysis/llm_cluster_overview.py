"""Sachnummerngebundene Sicht auf bereits importierte zweite LLM-Analysen.

Keine neue Kausalzuordnung oder Clusterberechnung: Die Darstellung übernimmt
nur validiert importierte Fall-/Clusterergebnisse für die AKTUELLE QEC-Kohorte.
Andere Projektfälle und unbekannte LLM-Fälle bleiben unsichtbar.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import json
from typing import Mapping, Sequence


@dataclass(frozen=True)
class LlmClusterCase:
    case_id: str
    pseudonym: str
    fin: str
    cluster_id: str | None
    ntf: str
    cause: str
    confidence: str
    review_status: str
    recurrence: str
    payload: dict


@dataclass(frozen=True)
class LlmClusterGroup:
    cluster_id: str
    title: str
    count: int
    confidence: str
    hypothesis: str
    cause_counts: tuple[tuple[str, int], ...]
    evidence: tuple[dict, ...]


@dataclass(frozen=True)
class LlmClusterOverview:
    cases: tuple[LlmClusterCase, ...]
    groups: tuple[LlmClusterGroup, ...]
    causes: tuple[tuple[str, int], ...]
    ungrouped: int
    supplier_hypotheses: int
    unknown_causes: int

    @property
    def total_cases(self) -> int:
        return len(self.cases)


def _cause(value: object) -> str:
    text = str(value or "").strip()
    return text if text and text != "—" else "Nicht zuordenbar"


def _supplier_hypothesis(cause: str) -> bool:
    """Eine explizite Verneinung ist KEINE Lieferantenhypothese."""
    value = cause.casefold()
    return "lieferant" in value and not any(
        negation in value for negation in (
            "kein lieferant", "nicht lieferant", "nicht beim lieferanten",
            "lieferant ausgeschlossen", "lieferant unwahrscheinlich",
            "keine lieferanten", "nicht durch lieferant",
        )
    )


def build_llm_cluster_overview(
    cluster_payloads: Sequence[dict],
    finding_rows: Sequence[tuple[str, str | None, str, str]],
    current_cases: Mapping[str, dict],
) -> LlmClusterOverview:
    """Only imported second-round cases for this profile+part's QEC cohort."""
    cases: list[LlmClusterCase] = []
    seen: set[str] = set()
    for case_id, cluster_id, raw, review in finding_rows:
        if case_id not in current_cases or case_id in seen:
            continue
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            continue
        source = current_cases[case_id]
        cases.append(LlmClusterCase(
            case_id=case_id,
            pseudonym=str(payload.get("fall_id") or ""),
            fin=str(source.get("fin") or ""),
            cluster_id=str(cluster_id) if cluster_id else None,
            ntf=str(payload.get("ntf_bewertung") or "Nicht bewertet"),
            cause=_cause(payload.get("verursachungsbereich")),
            confidence=str(payload.get("sicherheit_zuordnung") or "Offen"),
            review_status=str(review or "Offen"),
            recurrence=str(payload.get("fehlerwiederkehr") or "Nicht beurteilbar"),
            payload=payload,
        ))
        seen.add(case_id)
    cases.sort(key=lambda item: (item.cluster_id or "zzz", item.case_id))
    group_counts = Counter(item.cluster_id for item in cases if item.cluster_id)
    by_group = {
        cluster_id: [item for item in cases if item.cluster_id == cluster_id]
        for cluster_id in group_counts
    }
    groups = []
    for payload in cluster_payloads:
        cluster_id = str(payload.get("cluster_id") or "")
        if not cluster_id or not group_counts.get(cluster_id):
            continue
        causes = Counter(item.cause for item in by_group[cluster_id])
        groups.append(LlmClusterGroup(
            cluster_id=cluster_id,
            title=str(payload.get("titel") or cluster_id),
            count=group_counts[cluster_id],
            confidence=str(payload.get("sicherheit") or "Offen"),
            hypothesis=str(payload.get("technische_hypothese") or ""),
            cause_counts=tuple(sorted(
                causes.items(), key=lambda item: (-item[1], item[0])
            )),
            evidence=tuple(
                item for item in (payload.get("belege") or [])
                if isinstance(item, dict)
            ),
        ))
    groups.sort(key=lambda item: (-item.count, item.cluster_id))
    causes = Counter(item.cause for item in cases)
    return LlmClusterOverview(
        cases=tuple(cases),
        groups=tuple(groups),
        causes=tuple(sorted(causes.items(), key=lambda item: (-item[1], item[0]))),
        ungrouped=sum(not item.cluster_id for item in cases),
        supplier_hypotheses=sum(
            _supplier_hypothesis(item.cause) for item in cases
        ),
        unknown_causes=sum(
            item.cause.casefold() in {"nicht zuordenbar", "unbekannt", "offen"}
            or item.confidence == "Offen" for item in cases
        ),
    )


def evidence_lines(entries: Sequence[dict], *, max_entries: int = 12) -> str:
    """Cite only actual source positions; never invent document evidence."""
    rendered = []
    for entry in entries[:max_entries]:
        ref = str(entry.get("quelle") or "Quelle")
        ident = str(entry.get("quelle_id") or "")
        position = str(entry.get("fundstelle") or "")
        status = str(entry.get("belegstatus") or "Nicht verifiziert")
        assertion = str(entry.get("aussage") or "")
        rendered.append(
            f"• {ref}{' / ' + ident if ident else ''}"
            f"{' · ' + position if position else ''} ({status})"
            f"{': ' + assertion if assertion else ''}"
        )
    if len(entries) > max_entries:
        rendered.append(f"… {len(entries) - max_entries} weitere Belege")
    return "\n".join(rendered) if rendered else "Keine konkreten Belege angegeben."
