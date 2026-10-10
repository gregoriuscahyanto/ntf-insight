"""Explain diagnostic cluster membership using ONLY pre-replacement inputs.

The explanations describe observed feature overlaps, not causal feature
attributions, independent defect confirmations or supplier responsibility.
All QEC/VIN/DTC-level contents remain in the local GUI.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Mapping, Sequence

from ntf_insight.analysis.case_clustering import FaultKey, signature_for
from ntf_insight.analysis.diagnostic_observations import dtc_description_catalog
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
        return "\n\n".join(self.lines)

    def evidence_for(self, case_id: str) -> str:
        return dict(self.per_case).get(case_id, "Keine Einzelfallevidenz.")


def _format_fault(fault: FaultKey) -> str:
    return f"{fault[0]}:{fault[1]}"


def _described_fault(
    fault: FaultKey, descriptions: Mapping[FaultKey, str],
) -> str:
    """DTC-Explorer text is a label, NOT clustering or repair evidence."""
    label = descriptions.get(fault, "").strip()
    return f"{_format_fault(fault)} — {label}" if label else _format_fault(fault)


def _fault_list(
    faults: list[FaultKey], descriptions: Mapping[FaultKey, str],
) -> str:
    """Display ALL original codes and only documented description texts."""
    return "\n".join(
        f"• {_described_fault(fault, descriptions)}"
        for fault in faults
    )


def explain_cluster(
    cases: Sequence[NTFCase],
    group: UnifiedCluster,
    parameters: ClusterParameters,
    eligible_case_ids: Sequence[str],
    *,
    strict_review: bool = False,
    dtc_texts: Mapping[FaultKey, str] | None = None,
) -> ClusterExplanation:
    """Explain overlapping original diagnostic features for real group members.

    The active DTC source, before-replacement time window, and cohort-specific
    prevalence screen match the run. Neither QEC supplier outcomes nor SSL
    final findings are inspected. This is a descriptive explanation, not an
    exact decomposition of TF-IDF weights or an HDBSCAN causal attribution.
    """
    by_id = {case.case_id: case for case in cases}
    # This lookup can use any locally recorded observation, as in the
    # DTC-Explorer. It ONLY annotates codes already established by the
    # strictly pre-swap signatures below. A later label cannot make a
    # post-swap event an input feature.
    descriptions = (
        dtc_texts if dtc_texts is not None
        else dtc_description_catalog(cases)
    )
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
    common = sorted(
        (fault for fault, count in counts.items() if count == total),
        key=lambda fault: (fault[0] != "CPC3", fault),
    )
    additional = sorted(
        (
            (fault, count) for fault, count in counts.items()
            if 2 <= count < total and count / total >= 0.5
        ),
        key=lambda item: (-item[1], item[0][0] != "CPC3", item[0]),
    )

    label = "Prüfgruppe" if strict_review else "Cluster"
    letter = "K" if strict_review else "C"
    heading = (
        f"Warum gehören diese {total} Fälle zu "
        f"{label} {letter}{group.cluster_id}?"
    )
    lines = ["1. Was haben diese Fälle gemeinsam?"]
    if common:
        lines.append(
            f"In allen {total} Fällen sind dieselben {len(common)} "
            "Steuergerät-Fehlercode-Kombinationen dokumentiert. "
            "ECU:DTC bedeutet Steuergerät:Fehlercode. "
            "Die Codes sind vor dem untersuchten Pumpentausch erfasst worden:\n"
            + _fault_list(common, descriptions)
        )
    else:
        lines.append(
            "Kein einzelner Steuergerät-Fehlercode (ECU:DTC) kommt "
            f"in allen {total} Fällen vor. Die App berücksichtigt daher "
            "die Kombination verschiedener Diagnosemerkmale."
        )

    if additional:
        entries = "\n".join(
            f"• {_described_fault(fault, descriptions)} "
            f"– bei {count} von {total} Fällen"
            for fault, count in additional
        )
        lines.append(
            "Diese weiteren Fehlercodes kommen häufig vor, aber "
            "nicht in allen Fällen:\n" + entries
        )

    if any(fault in descriptions for fault in (
        *common, *(fault for fault, _ in additional),
    )):
        lines.append(
            "Die Klartexte stammen aus lokal vorhandenen Diagnosebeobachtungen "
            "(wie im DTC-Explorer). Sie erläutern nur die Fehlercodes; "
            "sie werden nicht zur Clusterbildung verwendet. "
            "Der Beschreibungstext kann aus einem anderen Diagnosezeitpunkt stammen."
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
        lines.append(
            "Auch diese Wörter aus dokumentierten Kundenbeanstandungen "
            "wiederholen sich:\n"
            + "\n".join(
                f"• {token} – bei {count} von {total} Fällen"
                for token, count in shared_complaints
            )
        )

    if not common:
        # Shared ECU software is context, not proof of a technical defect.
        software_counts = Counter(
            sw for cid in members for sw in signatures[cid].ecu_software
        )
        software = sorted(
            ((sw, count) for sw, count in software_counts.items()
             if count >= 2 and count / total >= 0.5),
            key=lambda item: (-item[1], item[0]),
        )
        if software:
            lines.append(
                "Diese vor dem Tausch dokumentierten Softwarestände "
                "wiederholen sich:\n"
                + "\n".join(
                    f"• {value} – bei {count} von {total} Fällen"
                    for value, count in software
                )
            )
        elif not additional and not shared_complaints:
            lines.append(
                "Es gibt keine stark übereinstimmenden Einzelmerkmale. "
                "Die Gruppierung stützt sich auf das gesamte Diagnosebild "
                "und sollte besonders vorsichtig geprüft werden."
            )

    lines.append("2. Weshalb fasst die App diese Fälle zusammen?")
    if parameters.method in {"leaf", "eom"} and not strict_review:
        variant = "Leaf" if parameters.method == "leaf" else "EOM"
        lines.append(
            f"Das Verfahren HDBSCAN ({variant}) sucht Bereiche mit "
            "ähnlichen Diagnosefällen; das nennt man Dichtegruppen. "
            "Es betrachtet die unterschiedlich stark gewichteten "
            "Vor-Tausch-Merkmale gemeinsam: insbesondere Fehlercodes "
            "und Steuergeräte, daneben Kundenbeanstandungen, "
            "Softwarestände und Fahrzeugvarianten. "
            "Ein einziger gleicher Fehlercode entscheidet nicht "
            "allein über die Zuordnung."
        )
    elif parameters.method == "complete_legacy" and not strict_review:
        lines.append(
            "Complete-Link mit gewichtetem DTC-Jaccard vergleicht "
            "die Mengen dokumentierter Diagnosemerkmale und ihre "
            "Übereinstimmung. Dieses Ähnlichkeitsmaß ist nicht "
            "unmittelbar mit der HDBSCAN-Bewertung gleichzusetzen."
        )
    else:
        lines.append(
            "Complete-Link Cosinus vergleicht jeden Fall mit jedem "
            "anderen Fall in der Gruppe. Die berechnete paarweise "
            "Diagnoseähnlichkeit muss mindestens "
            f"{parameters.minimum_similarity:.0%} betragen. "
            "Das ist eine Ähnlichkeitsschwelle, keine Aussage über "
            "die Wahrscheinlichkeit eines Pumpendefekts."
        )

    lines.append("3. Wie einheitlich ist diese Gruppe?")
    if group.weak_pair_count and group.internal_pair_count:
        lines.append(
            f"Es wurden {group.internal_pair_count} Fallpaare verglichen "
            f"(jeweils zwei Fälle). Davon erreichen "
            f"{group.weak_pair_count} Paare weniger als 45 % "
            "Cosinus-Ähnlichkeit. Die Prozentzahl beschreibt nur "
            "die Ähnlichkeit der Diagnosemerkmale, nicht die "
            "Wahrscheinlichkeit eines Defekts. "
            "Achtung: Die Gruppe ist diagnostisch uneinheitlich; "
            "nicht alle Fälle passen gut zueinander."
        )
    elif group.weak_pair_count == 0 and group.internal_pair_count:
        lines.append(
            f"Keines der {group.internal_pair_count} Fallpaare liegt "
            "unter 45 % Cosinus-Ähnlichkeit. Auch das beweist "
            "keine identische technische Ursache."
        )
    else:
        lines.append(
            "Hier liegt keine direkt vergleichbare Cosinus-Paarprüfung "
            "mit der 45-%-Grenze vor. Die Zuordnung beruht "
            "auf der oben beschriebenen Methode."
        )
    if not common:
        lines.append(
            "Zusätzliche Vorsicht: Es gibt keinen einzigen "
            "ECU:DTC-Code, der alle Fälle gemeinsam verbindet. "
            "Eine technische Ursache darf deshalb nicht "
            "von einem Fall auf alle anderen übertragen werden."
        )
    if total != group.vehicle_count:
        lines.append(
            f"Die {total} QEC-Fälle stammen von {group.vehicle_count} "
            "verschiedenen Fahrzeugen (FINs). Mehrere Fälle "
            "derselben FIN sind keine unabhängigen Fahrzeuge."
        )
    if excluded_faults:
        lines.append(
            "Der eingeschaltete DTC-Häufigkeitsfilter entfernt "
            "besonders weit verbreitete Fehlercodes aus "
            "den Merkmalen, mit denen die Gruppen berechnet wurden."
        )
    lines.append(
        "Wichtig: Die App erklärt, welche Diagnosedaten ähnlich sind. "
        "Sie bestätigt damit weder eine gemeinsame Ursache in "
        "der Kühlmittelpumpe noch eine Verantwortung des Lieferanten. "
        "Dafür wären zusätzliche technische Nachweise erforderlich."
    )

    representative = fault_sets[group.representative_case_id]
    per_case = []
    for cid in members:
        if cid == group.representative_case_id:
            reason = (
                "Repräsentativer Fall (Medoid): Dieser Fall dient "
                "als Vergleichsbeispiel für die Gruppe."
            )
        else:
            shared = sorted(
                fault_sets[cid] & representative,
                key=lambda fault: (fault[0] != "CPC3", fault),
            )
            reason = (
                f"{len(shared)} gleiche ECU:DTC wie der Repräsentant: "
                + ", ".join(_format_fault(fault) for fault in shared)
                if shared else
                "Kein identischer ECU:DTC zum Repräsentanten; "
                "die App berücksichtigt weitere Merkmale und "
                "die Struktur der Gruppe."
            )
        per_case.append((cid, reason))
    return ClusterExplanation(
        heading=heading, lines=tuple(lines), per_case=tuple(per_case),
    )
