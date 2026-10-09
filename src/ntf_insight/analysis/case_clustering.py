"""Explainable diagnostic case similarity and cautious small-sample clustering.

Feature extraction stops at the investigated replacement. Repair outcomes, supplier
findings and the post-replacement history are excluded from similarity to prevent
using information unavailable when looking for a solution to an unresolved case.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from ntf_insight.analysis.recurrence import relative_to_replacement
from ntf_insight.components.registry import list_component_profiles
from ntf_insight.domain.case import NTFCase

FaultKey = tuple[str, str]

# Weights are transparent initial engineering hypotheses, NOT learned/calibrated values.
VIEW_WEIGHTS = {
    "faults": 0.50,
    "codes": 0.20,
    "ecus": 0.10,
    "complaint": 0.13,
    "software": 0.04,
    "variant": 0.03,
}

STOPWORDS = frozenset({
    "und", "oder", "der", "die", "das", "dem", "den", "des", "ein",
    "eine", "einen", "einem", "einer", "ist", "sind", "war", "hat",
    "haben", "mit", "bei", "auf", "von", "zum", "zur", "aus", "nicht",
    "nach", "vor", "als", "für", "fuer", "wird", "werden", "bei", "ohne",
    "am", "im", "an", "in", "es", "beim", "fahrzeug", "kunde", "kunden",
    "fehler", "problem", "beanstandung", "meldung", "tritt", "auftritt",
})


@dataclass(frozen=True, slots=True)
class DiagnosticSignature:
    case_id: str
    component_key: str
    faults: frozenset[FaultKey]
    codes: frozenset[str]
    ecus: frozenset[str]
    complaint_tokens: frozenset[str]
    ecu_software: frozenset[str]
    vehicle_variant: frozenset[str]
    has_replacement_anchor: bool

    def views(self) -> dict[str, frozenset]:
        return {
            "faults": self.faults,
            "codes": self.codes,
            "ecus": self.ecus,
            "complaint": self.complaint_tokens,
            "software": self.ecu_software,
            "variant": self.vehicle_variant,
        }


@dataclass(frozen=True, slots=True)
class CaseMatch:
    left_case_id: str
    right_case_id: str
    score: float | None
    coverage: float
    shared_faults: tuple[FaultKey, ...]
    shared_ecus: tuple[str, ...]
    shared_complaint: tuple[str, ...]
    shared_software: tuple[str, ...]
    reason: str
    eligible_for_cluster: bool


@dataclass(frozen=True, slots=True)
class CaseCluster:
    cluster_id: int
    case_ids: tuple[str, ...]
    common_faults: tuple[FaultKey, ...]


@dataclass(frozen=True, slots=True)
class CaseClusterResult:
    clusters: tuple[CaseCluster, ...]
    unassigned: tuple[str, ...]
    matches: tuple[CaseMatch, ...]
    threshold: float

    def cluster_for(self, case_id: str) -> int | None:
        for cluster in self.clusters:
            if case_id in cluster.case_ids:
                return cluster.cluster_id
        return None


@dataclass(frozen=True, slots=True)
class ClusterInsight:
    """Human-readable cluster profile, distinct from any causal diagnosis."""

    cluster_id: int
    case_count: int
    vehicle_count: int
    representative_case_id: str
    common_faults: tuple[FaultKey, ...]
    weakest_pair_similarity: float
    mean_similarity: float
    mean_feature_coverage: float
    cases_with_pre_and_post_test: int


def cluster_insights(
    result: CaseClusterResult,
    cases: list[NTFCase],
) -> tuple[ClusterInsight, ...]:
    """Profile formed clusters without using post-repair outcomes for membership.

    Representative = observed case with highest average score x feature
    coverage to other cluster members, deterministic tie-break by case ID.
    The representative is not a recommended repair or a mean/synthetic case.
    """
    by_id = {case.case_id: case for case in cases}
    pairs = {
        frozenset((match.left_case_id, match.right_case_id)): match
        for match in result.matches
    }
    insights = []
    for cluster in result.clusters:
        members = cluster.case_ids
        pair_matches = [
            pairs[frozenset((left, right))]
            for index, left in enumerate(members)
            for right in members[index + 1:]
        ]
        weighted_neighbour_scores = {
            case_id: sum(
                (pair.score or 0.0) * pair.coverage
                for pair in pair_matches
                if case_id in (pair.left_case_id, pair.right_case_id)
            ) / max(1, len(members) - 1)
            for case_id in members
        }
        representative = min(
            members,
            key=lambda case_id: (-weighted_neighbour_scores[case_id], case_id),
        )
        followup = sum(
            (
                (observation := resolution_observation(by_id[case_id])).has_pre_test
                and observation.has_post_test
            )
            for case_id in members
        )
        insights.append(ClusterInsight(
            cluster_id=cluster.cluster_id,
            case_count=len(members),
            vehicle_count=len({by_id[case_id].vin for case_id in members}),
            representative_case_id=representative,
            common_faults=cluster.common_faults,
            weakest_pair_similarity=round(min(pair.score or 0.0 for pair in pair_matches), 4),
            mean_similarity=round(
                sum(pair.score or 0.0 for pair in pair_matches) / len(pair_matches), 4
            ),
            mean_feature_coverage=round(
                sum(pair.coverage for pair in pair_matches) / len(pair_matches), 4
            ),
            cases_with_pre_and_post_test=followup,
        ))
    return tuple(insights)


def case_match_explanation(
    focused: NTFCase,
    other: NTFCase,
    match: CaseMatch,
) -> str:
    """Explain both shared and dissimilar diagnostic evidence for a neighbour."""
    first = signature_for(focused)
    second = signature_for(other)
    shared = ", ".join(
        f"{ecu}:{code}" for ecu, code in match.shared_faults
    ) or "Keine gemeinsamen ECU:DTC-Kombinationen"
    focus_only = sorted(first.faults - second.faults)
    other_only = sorted(second.faults - first.faults)

    def compact(faults: list[FaultKey]) -> str:
        if not faults:
            return "Keine"
        preview = ", ".join(
            f"{ecu}:{code}" for ecu, code in faults[:8]
        )
        return preview + (f" (+{len(faults) - 8} weitere)" if len(faults) > 8 else "")

    return (
        f"Gemeinsames Diagnosebild: {shared}\n"
        f"Nur im gewählten Fall: {compact(focus_only)}\n"
        f"Nur im Vergleichsfall: {compact(other_only)}\n"
        f"Gemeinsame Beanstandungsbegriffe: "
        f"{', '.join(match.shared_complaint) or 'Keine beidseitig bekannten'}\n"
        f"Gemeinsame Softwarestände: "
        f"{', '.join(match.shared_software[:6]) or 'Keine belegten'}\n"
        f"Ähnlichkeit: {match.score:.0%} · "
        f"vergleichbare Merkmalsabdeckung: {match.coverage:.0%}\n"
        f"{match.reason}\n"
        "Ähnlichkeit ist keine Ursachen- oder Reparaturwahrscheinlichkeit."
    )


@dataclass(frozen=True, slots=True)
class ResolutionObservation:
    measures: tuple[str, ...]
    outcome: str
    has_post_test: bool
    has_pre_test: bool


def _tokens(texts: Iterable[str]) -> frozenset[str]:
    text = " ".join(texts).casefold()
    return frozenset(
        word
        for word in re.findall(r"[^\W\d_]{3,}", text, flags=re.UNICODE)
        if word not in STOPWORDS
    )


def _in_diagnostic_window(event, case: NTFCase) -> bool:
    replacement = case.investigated_replacement()
    if replacement is None:
        # Unanchored cases can be explored, but the UI must mark that fact.
        return True
    return relative_to_replacement(event, replacement) == "pre"


def _component_key(case: NTFCase) -> str:
    if case.component_profile_id:
        return case.component_profile_id.strip().casefold()
    name = case.component_type.strip().casefold()
    for profile in list_component_profiles():
        known = {profile.profile_id.casefold(), profile.display_name.casefold()}
        known.update(alias.casefold() for alias in profile.aliases)
        if name in known:
            return profile.profile_id.casefold()
    return name


def signature_for(case: NTFCase) -> DiagnosticSignature:
    events = [
        event for event in case.diagnostics
        if _in_diagnostic_window(event, case)
    ]
    faults = frozenset(event.fault_key for event in events)
    complaints = [
        repair.complaint
        for repair in case.repairs
        if repair.complaint and _in_diagnostic_window(repair, case)
    ]
    ecu_software = frozenset(
        f"{state.ecu.strip().upper()}:{state.software_version.strip().upper()}"
        for state in case.ecu_states
        if (
            state.software_version
            and _in_diagnostic_window(state, case)
        )
    )
    context = frozenset(
        value.strip().casefold()
        for value in (case.vehicle.model_series, case.vehicle.variant)
        if value and value.strip()
    )
    component_key = _component_key(case)
    return DiagnosticSignature(
        case_id=case.case_id,
        component_key=component_key,
        faults=faults,
        codes=frozenset(code for _, code in faults),
        ecus=frozenset(ecu for ecu, _ in faults),
        complaint_tokens=_tokens(complaints),
        ecu_software=ecu_software,
        vehicle_variant=context,
        has_replacement_anchor=case.investigated_replacement() is not None,
    )


def _jaccard(left: frozenset, right: frozenset) -> float:
    return len(left & right) / len(left | right)


def compare_signatures(left: DiagnosticSignature, right: DiagnosticSignature) -> CaseMatch:
    empty = dict(
        left_case_id=left.case_id,
        right_case_id=right.case_id,
        coverage=0.0,
        shared_faults=(),
        shared_ecus=(),
        shared_complaint=(),
        shared_software=(),
        eligible_for_cluster=False,
    )
    if left.case_id == right.case_id:
        return CaseMatch(score=1.0, reason="Gleicher Fall", **empty)

    if left.component_key != right.component_key:
        return CaseMatch(
            score=None,
            reason="Verschiedene Bauteilfamilien; kein automatischer Vergleich",
            **empty,
        )

    left_views = left.views()
    right_views = right.views()
    paired = [
        (name, VIEW_WEIGHTS[name], left_views[name], right_views[name])
        for name in VIEW_WEIGHTS
        if left_views[name] and right_views[name]
    ]
    covered_weight = sum(weight for _, weight, _, _ in paired)
    shared_faults = tuple(sorted(left.faults & right.faults))
    shared_ecus = tuple(sorted(left.ecus & right.ecus))
    shared_complaint = tuple(sorted(left.complaint_tokens & right.complaint_tokens))
    shared_software = tuple(sorted(left.ecu_software & right.ecu_software))

    # Vehicle variant/ECU alone cannot establish diagnostic similarity.
    has_diagnostic_basis = bool(
        (left.faults and right.faults)
        or (left.complaint_tokens and right.complaint_tokens)
    )
    if not has_diagnostic_basis or covered_weight == 0:
        return CaseMatch(
            score=None, reason="Zu wenig vergleichbare Diagnoseinformationen",
            **empty,
        )

    score = sum(
        weight * _jaccard(a, b) for _, weight, a, b in paired
    ) / covered_weight

    has_meaningful_overlap = bool(shared_faults or len(shared_complaint) >= 2)
    # Strict gate: do not form a cluster based on an ECU/variant or scant text.
    eligible = (
        bool(shared_faults)
        and covered_weight >= 0.50
        and left.has_replacement_anchor
        and right.has_replacement_anchor
    )

    if shared_faults:
        reason = "Gemeinsame DTCs: " + ", ".join(f"{ecu}:{code}" for ecu, code in shared_faults)
    elif shared_complaint:
        reason = "Gemeinsame Beanstandungsbegriffe: " + ", ".join(shared_complaint)
    else:
        reason = "Keine gemeinsamen Diagnosemerkmale"

    if not has_meaningful_overlap:
        reason += " · schwache diagnostische Evidenz"
    if not left.has_replacement_anchor or not right.has_replacement_anchor:
        reason += (
            " · ohne dokumentierten Tauschanker nur Ähnlichkeitssuche, "
            "keine automatische Clusterzuordnung"
        )

    return CaseMatch(
        left_case_id=left.case_id,
        right_case_id=right.case_id,
        score=round(score, 4),
        coverage=round(covered_weight, 4),
        shared_faults=shared_faults,
        shared_ecus=shared_ecus,
        shared_complaint=shared_complaint,
        shared_software=shared_software,
        reason=reason,
        eligible_for_cluster=eligible,
    )


def compare_diagnostic_cases(left: NTFCase, right: NTFCase) -> CaseMatch:
    return compare_signatures(signature_for(left), signature_for(right))


def all_diagnostic_matches(cases: list[NTFCase]) -> list[CaseMatch]:
    signatures = [signature_for(case) for case in sorted(cases, key=lambda c: c.case_id)]
    matches = [
        compare_signatures(a, b)
        for index, a in enumerate(signatures)
        for b in signatures[index + 1:]
    ]
    return sorted(
        matches,
        key=lambda m: (-(m.score if m.score is not None else -1.0), m.left_case_id, m.right_case_id),
    )


def matches_for(case_id: str, matches: Iterable[CaseMatch]) -> list[CaseMatch]:
    return sorted(
        (m for m in matches if case_id in (m.left_case_id, m.right_case_id)
         and m.score is not None),
        key=lambda m: (
            -(m.score * m.coverage),
            -m.score,
            m.left_case_id,
            m.right_case_id,
        ),
    )


def cluster_diagnostic_cases(
    cases: list[NTFCase],
    *,
    threshold: float = 0.65,
) -> CaseClusterResult:
    """Deterministic complete-link hierarchical grouping.

    Unlike single-link connected components, every pair within a returned cluster
    must meet the selected similarity threshold and evidence gate.
    Singletons stay unassigned, not force-labelled.
    """
    if not 0 < threshold <= 1:
        raise ValueError("Cluster-Schwelle muss zwischen 0 (exklusiv) und 1 liegen.")

    by_id = {case.case_id: case for case in cases}
    if len(by_id) != len(cases):
        raise ValueError("Fall-IDs müssen eindeutig sein.")

    ids = sorted(by_id)
    signatures = {case_id: signature_for(by_id[case_id]) for case_id in ids}
    matches = [
        compare_signatures(signatures[left], signatures[right])
        for index, left in enumerate(ids) for right in ids[index + 1:]
    ]
    matches.sort(key=lambda m: (
        -(m.score if m.score is not None else -1.0),
        m.left_case_id, m.right_case_id,
    ))
    lookup = {
        frozenset((match.left_case_id, match.right_case_id)): match
        for match in matches
    }
    # Greedy complete-link agglomeration. Candidate pairs are visited once from
    # strongest to weakest; a merge is allowed only when ALL cross-pairs meet
    # the threshold and have explicit matching diagnostic evidence.
    groups: dict[str, set[str]] = {case_id: {case_id} for case_id in ids}
    membership: dict[str, str] = {case_id: case_id for case_id in ids}

    for match in matches:
        if not match.eligible_for_cluster or match.score is None or match.score < threshold:
            continue
        left_group = membership[match.left_case_id]
        right_group = membership[match.right_case_id]
        if left_group == right_group:
            continue
        left_members = groups[left_group]
        right_members = groups[right_group]
        can_merge = all(
            (pair := lookup[frozenset((left, right))]).eligible_for_cluster
            and pair.score is not None
            and pair.score >= threshold
            for left in left_members
            for right in right_members
        )
        if not can_merge:
            continue
        keep, remove = sorted((left_group, right_group))
        merged = groups[keep] | groups.pop(remove)
        groups[keep] = merged
        for case_id in merged:
            membership[case_id] = keep

    multi = sorted(
        (tuple(sorted(group)) for group in groups.values() if len(group) >= 2),
        key=lambda group: (-len(group), group),
    )
    clusters = []
    for index, group in enumerate(multi, start=1):
        common = set(signatures[group[0]].faults)
        for case_id in group[1:]:
            common &= signatures[case_id].faults
        clusters.append(
            CaseCluster(index, group, tuple(sorted(common)))
        )
    return CaseClusterResult(
        clusters=tuple(clusters),
        unassigned=tuple(
            sorted(next(iter(group)) for group in groups.values() if len(group) == 1)
        ),
        matches=tuple(matches),
        threshold=threshold,
    )


def resolution_observation(case: NTFCase) -> ResolutionObservation:
    """Describe DTC outcome relative to the LAST documented intervention.

    Never equate an absent recurrence with a proven successful repair.
    In particular, a post-swap test taken before a later wiring repair must not
    be presented as evidence of that wiring repair's effectiveness.
    """
    measures: list[str] = []
    for replacement in case.replacements:
        measures.append(f"Bauteiltausch: {replacement.component_type}")
    for repair in case.repairs:
        if repair.action:
            measures.append(f"Werkstatt: {repair.action.strip()}")
    for update in case.software_events:
        action = update.action or update.software_version
        if action:
            measures.append(f"Software {update.ecu}: {action.strip()}")

    interventions = [
        *case.replacements,
        *(repair for repair in case.repairs if repair.action),
        *case.software_events,
    ]
    latest = max(interventions, key=lambda item: item.occurred_at, default=None)
    if latest is None:
        return ResolutionObservation(
            measures=tuple(dict.fromkeys(measures)),
            outcome="Keine dokumentierte Maßnahme mit überprüfbarem Nachtest",
            has_pre_test=False,
            has_post_test=False,
        )

    has_pre_test = any(
        relative_to_replacement(session, latest) == "pre"
        for session in case.diagnostic_sessions
    )
    has_post_test = any(
        relative_to_replacement(session, latest) == "post"
        for session in case.diagnostic_sessions
    )
    pre_faults = {
        event.fault_key for event in case.diagnostics
        if relative_to_replacement(event, latest) == "pre"
    }
    post_faults = {
        event.fault_key for event in case.diagnostics
        if relative_to_replacement(event, latest) == "post"
    }

    if not has_post_test:
        outcome = "Kein Kurztest nach der letzten dokumentierten Maßnahme"
    elif not has_pre_test or not pre_faults:
        outcome = "Wirksamkeit nicht überprüfbar (Vorher-Test oder Ausgangs-DTC fehlt)"
    elif pre_faults & post_faults:
        outcome = "Derselbe DTC nach letzter Maßnahme erneut beobachtet"
    elif post_faults - pre_faults:
        outcome = (
            "Ausgangs-DTC nicht erneut beobachtet, aber neuer DTC nach "
            "der Maßnahme; keine bestätigte Lösung"
        )
    else:
        outcome = "Ausgangs-DTC im dokumentierten Nachtest nicht erneut beobachtet"

    return ResolutionObservation(
        measures=tuple(dict.fromkeys(measures)),
        outcome=outcome,
        has_post_test=has_post_test,
        has_pre_test=has_pre_test,
    )
