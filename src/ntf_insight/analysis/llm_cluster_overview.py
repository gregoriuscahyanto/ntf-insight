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
    recurrence_source: str
    recurrence_signal: bool
    symptoms: tuple[str, ...]
    proof_profiles: tuple[str, ...]
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
    symptoms: tuple[tuple[str, int], ...]
    proof_profiles: tuple[tuple[str, int], ...]
    structurally_classified: int
    legacy_without_symptom_fields: int
    ungrouped: int
    supplier_hypotheses: int
    unknown_causes: int
    recurrence_signals: int

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


def _recurrence_for_display(payload: dict) -> tuple[str, str, bool]:
    """Alte Ergebnis-JSONs zeigen historische Aussagen, ohne sie zu beweisen.

    Der LLM-Freitext ist weder DTC-Löschhistorie noch eine neue
    fachliche Verifikation. Keine automatischen Kausalbehauptungen.
    """
    structured = payload.get("fehlerwiederkehr")
    if structured:
        return (
            str(structured),
            str(payload.get("begruendung_fehlerwiederkehr") or
                "Als strukturiertes LLM-Ergebnis gemeldet; fachlich zu prüfen."),
            structured in {
                "Nach Tausch erneut nachgewiesen", "Hinweise auf Wiederkehr",
            },
        )
    topics = " | ".join(str(x).casefold() for x in payload.get("themen") or [])
    if ("gleicher dtc nach tausch" in topics and
            "ereignis-km über tauschstand" in topics):
        return (
            "Gleicher DTC nach Tausch · LLM-Hinweis",
            "Aus Themenliste der gelieferten alten JSON übernommen. "
            "Fahrzeug-DTC nach dem Tausch gemeldet, Quelle nicht hier "
            "nachverifiziert; neue Pumpe / Schadteilursache unbewiesen.",
            True,
        )
    if ("gleicher code nach tausch gespeichert" in topics and
            "wiederauftreten unbewiesen" in topics):
        return (
            "DTC-Historie · Wiederkehr nicht belegt",
            "Die alte LLM-Ergebnis-JSON bewertet den nach Tausch "
            "gespeicherten DTC als möglicherweise historisch. "
            "Ohne neuen Ereignisnachweis keine Wiederkehr annehmen.",
            False,
        )
    if "neuer auftretens-km" in topics and "dtc nach tausch" in topics:
        return (
            "Neuer DTC nach Tausch · Vergleich offen",
            "Die alte JSON beschreibt einen neuen DTC-Ereigniskilometerstand "
            "nach Tausch, aber nicht zwingend denselben ursprünglichen "
            "Fehler. Keine belegte Wiederkehr derselben Störung.",
            False,
        )
    return (
        "Nicht strukturiert ausgewertet",
        "Die gelieferte JSON enthält kein separates Feld fehlerwiederkehr. "
        "Nicht gleichzusetzen mit belegter Fehlerfreiheit nach Tausch.",
        False,
    )


def _symptom_groups(payload: dict) -> tuple[str, ...]:
    """Neue Multi-Labels oder wortgetreue Legacy-Themen, keine neue Ursache.

    Alte LLM-Dateien enthalten bereits konkrete Werkstatt-/DTC-Themen.
    Diese werden als LEGACY-TEXT sichtbar, nicht als extern verifizierter
    oder auf neue Taxonomie umgebuchter Fehlernachweis.
    """
    structured = payload.get("fehlerbilder") or []
    if structured:
        labels = {
            str(row.get("kategorie") or "").strip()
            for row in structured if isinstance(row, dict)
        }
        return tuple(sorted(label for label in labels if label)) or ("Unbekannt",)
    topics = payload.get("themen") or []
    meaningful = set()
    for raw in topics:
        item = str(raw or "").strip()
        text = item.casefold()
        if not item or text in {
            "kein reproduzierbarer laborfehler",
            "zuordnungs-/datenqualitätsprüfung",
            "nicht als hauptschadteil markiert",
            "ars unvollständig",
        }:
            continue
        # Direkt den im alten Ergebnis dokumentierten Originalbegriff
        # anzeigen, keine automatische Hersteller-/Lieferantenschuld.
        meaningful.add(item + " (Alt-LLM)")
    return tuple(sorted(meaningful)) if meaningful else (
        "Nicht spezifiziert (Alt-LLM)",
    )


def _proof_groups(payload: dict) -> tuple[str, ...]:
    structured = payload.get("nachweisprofil") or []
    if structured:
        return tuple(sorted({str(value) for value in structured if value}))
    topics = [str(t).casefold() for t in payload.get("themen") or []]
    groups = set()
    if any("werkstatttext" in text for text in topics):
        groups.add("Werkstattangabe (Alt-LLM)")
    if any("objektiver dtc vor tausch" in text for text in topics):
        groups.add("Diagnosehinweis vor Tausch (Alt-LLM)")
    if any("kein reproduzierbarer laborfehler" in text for text in topics):
        groups.add("Labor nicht reproduziert (Alt-LLM)")
    if any("dtc nach tausch" in text for text in topics):
        groups.add("DTC nach Tausch (Alt-LLM)")
    return tuple(sorted(groups)) if groups else (
        "Keine strukturierte Nachweiszuordnung (Alt-LLM)",
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
        recurrence, recurrence_source, recurrence_signal = (
            _recurrence_for_display(payload)
        )
        symptoms = _symptom_groups(payload)
        proofs = _proof_groups(payload)
        cases.append(LlmClusterCase(
            case_id=case_id,
            pseudonym=str(payload.get("fall_id") or ""),
            fin=str(source.get("fin") or ""),
            cluster_id=str(cluster_id) if cluster_id else None,
            ntf=str(payload.get("ntf_bewertung") or "Nicht bewertet"),
            cause=_cause(payload.get("verursachungsbereich")),
            confidence=str(payload.get("sicherheit_zuordnung") or "Offen"),
            review_status=str(review or "Offen"),
            recurrence=recurrence,
            recurrence_source=recurrence_source,
            recurrence_signal=recurrence_signal,
            symptoms=symptoms,
            proof_profiles=proofs,
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
    symptoms = Counter(
        label for item in cases for label in item.symptoms
    )
    proof_profiles = Counter(
        label for item in cases for label in item.proof_profiles
    )
    def counts(values: Counter) -> tuple[tuple[str, int], ...]:
        return tuple(sorted(
            values.items(), key=lambda item: (-item[1], item[0]),
        ))
    return LlmClusterOverview(
        cases=tuple(cases),
        groups=tuple(groups),
        causes=counts(causes),
        symptoms=counts(symptoms),
        proof_profiles=counts(proof_profiles),
        structurally_classified=sum(
            bool(item.payload.get("fehlerbilder")) for item in cases
        ),
        legacy_without_symptom_fields=sum(
            not item.payload.get("fehlerbilder") for item in cases
        ),
        ungrouped=sum(not item.cluster_id for item in cases),
        supplier_hypotheses=sum(
            _supplier_hypothesis(item.cause) for item in cases
        ),
        unknown_causes=sum(
            item.cause.casefold() in {"nicht zuordenbar", "unbekannt", "offen"}
            or item.confidence == "Offen" for item in cases
        ),
        recurrence_signals=sum(item.recurrence_signal for item in cases),
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
