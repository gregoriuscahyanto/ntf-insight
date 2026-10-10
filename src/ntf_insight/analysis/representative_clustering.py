"""Homogeneous pre-intervention diagnostic clusters with real-case medoids.

An evidence-qualified Complete-Link merger only joins groups when EVERY pair
of members passes the same minimum similarity and the entire group retains
informative exact ECU:DTC evidence. No chosen cluster count, no coverage-first
star clusters, no implied common root cause or automated repair transfer.

QEC SSL/end findings are examined *after* clustering for review warnings only.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from math import log
from statistics import mean
from typing import Mapping

from ntf_insight.analysis.case_clustering import (
    DiagnosticSignature,
    FaultKey,
    _in_diagnostic_window,
    _matches_dtc_source,
    signature_for,
)
from ntf_insight.analysis.qec_findings import qec_ssl_finding
from ntf_insight.domain.case import NTFCase


@dataclass(frozen=True, slots=True)
class RepresentativeMember:
    case_id: str
    representative_case_id: str
    similarity: float
    shared_faults: tuple[FaultKey, ...]


@dataclass(frozen=True, slots=True)
class RepresentativeCluster:
    cluster_id: int
    representative_case_id: str
    members: tuple[RepresentativeMember, ...]
    vehicle_count: int
    mean_similarity: float
    weakest_representative_similarity: float
    weakest_internal_similarity: float | None
    common_faults: tuple[FaultKey, ...]
    with_pre_quicktest: int
    with_qec_ssl_finding: int
    review_warnings: tuple[str, ...]

    @property
    def case_ids(self) -> tuple[str, ...]:
        return tuple(member.case_id for member in self.members)

    @property
    def case_count(self) -> int:
        return len(self.members)


@dataclass(frozen=True, slots=True)
class RepresentativePair:
    left_id: str
    right_id: str
    similarity: float
    fault_similarity: float
    shared_faults: tuple[FaultKey, ...]
    eligible: bool
    reason: str

    @property
    def key(self) -> frozenset[str]:
        return frozenset((self.left_id, self.right_id))


@dataclass(frozen=True, slots=True)
class UnassignedCase:
    case_id: str
    reason: str
    nearest_diagnostic_case_id: str | None
    nearest_similarity: float | None


@dataclass(frozen=True, slots=True)
class RepresentativePlan:
    clusters: tuple[RepresentativeCluster, ...]
    unassigned: tuple[str, ...]
    unassigned_reasons: tuple[UnassignedCase, ...]
    eligible_cases: tuple[str, ...]
    pair_scores: tuple[RepresentativePair, ...]
    minimum_similarity: float
    lookback_days: int | None
    dtc_source: str
    total_cases: int
    vehicle_count: int
    missing_pre_diagnostics: int
    without_swap_anchor: int
    common_dtc_limit: float
    screening_population: int

    @property
    def assigned_case_ids(self) -> frozenset[str]:
        return frozenset(
            item.case_id for cluster in self.clusters for item in cluster.members
        )

    @property
    def covered_count(self) -> int:
        return len(self.assigned_case_ids)

    @property
    def coverage(self) -> float:
        return self.covered_count / self.total_cases if self.total_cases else 0.0

    @property
    def representative_ids(self) -> tuple[str, ...]:
        return tuple(cluster.representative_case_id for cluster in self.clusters)


def _jaccard(left: frozenset, right: frozenset) -> float | None:
    if not left or not right:
        return None
    return len(left & right) / len(left | right)


def _has_pre_quicktest(case: NTFCase, *, lookback_days: int | None) -> bool:
    return any(
        _matches_dtc_source(event, "quicktest")
        and _in_diagnostic_window(event, case, lookback_days=lookback_days)
        for event in case.diagnostics
    )


def _case_quality(
    case: NTFCase, signature: DiagnosticSignature, *,
    lookback_days: int | None,
) -> tuple[int, int, int, int]:
    """Tie-break medoids using independent *pre-intervention* documentation.

    Unlike the previous prototype, more unrelated DTCs do NOT imply quality.
    Neither supplier results nor SSL findings influence medoid selection.
    """
    return (
        int(_has_pre_quicktest(case, lookback_days=lookback_days)),
        int(bool(signature.complaint_tokens)),
        int(bool(signature.ecu_software)),
        int(bool(case.vehicle.model_series and case.vehicle.variant)),
    )


def _build_pairs(
    signatures: Mapping[str, DiagnosticSignature],
    cases: Mapping[str, NTFCase],
    *,
    max_frequency: float,
) -> tuple[
    dict[frozenset[str], RepresentativePair],
    dict[tuple[str, FaultKey], float],
]:
    """Use documented pre-DTC QEC cases as the rarity denominator.

    Missing diagnostics are *not evidence* that a code is rare; counting them
    was biasing a frequently reported communication DTC downward.
    """
    from itertools import combinations

    eligible = [
        case_id for case_id, sig in signatures.items()
        if sig.has_replacement_anchor and sig.faults
    ]
    component_populations = Counter(
        signatures[case_id].component_key for case_id in eligible
    )
    frequency: Counter[tuple[str, FaultKey]] = Counter()
    for case_id in eligible:
        sig = signatures[case_id]
        frequency.update((sig.component_key, fault) for fault in sig.faults)
    rarity = {
        (component, fault): count / component_populations[component]
        for (component, fault), count in frequency.items()
    }
    idf = {
        (component, fault): 1.0 + log(
            (component_populations[component] + 1) / (count + 1)
        )
        for (component, fault), count in frequency.items()
    }
    pairs = {}
    for left_id, right_id in combinations(sorted(cases), 2):
        a, b = signatures[left_id], signatures[right_id]
        shared = tuple(sorted(a.faults & b.faults))
        score = 0.0
        fault_similarity = 0.0
        reason = ""
        eligible_pair = False
        if a.component_key != b.component_key:
            reason = "Verschiedene Bauteilfamilien"
        elif not a.has_replacement_anchor or not b.has_replacement_anchor:
            reason = "Tauschanker fehlt"
        elif not a.faults or not b.faults:
            reason = "Kein beidseitiger Vor-Tausch-ECU:DTC"
        elif not shared:
            reason = "Kein gemeinsamer ECU:DTC"
        elif not (len(shared) >= 2 or any(
            rarity[(a.component_key, fault)] <= max_frequency
            for fault in shared
        )):
            reason = "Nur ein häufig vorkommender gemeinsamer DTC"
        else:
            series_a = (cases[left_id].vehicle.model_series or "").strip().casefold()
            series_b = (cases[right_id].vehicle.model_series or "").strip().casefold()
            if series_a and series_b and series_a != series_b:
                reason = "Unterschiedliche bekannte Baureihe"
            else:
                a_weight = sum(idf[(a.component_key, fault)]
                               for fault in a.faults)
                b_weight = sum(idf[(a.component_key, fault)]
                               for fault in b.faults)
                shared_weight = sum(idf[(a.component_key, fault)]
                                    for fault in shared)
                weighted_jaccard = shared_weight / (
                    a_weight + b_weight - shared_weight
                )
                containment = shared_weight / min(a_weight, b_weight)
                # A large DTC-history difference cannot be entirely ignored.
                # More emphasis on symmetric Jaccard than the old 35%/65%.
                fault_similarity = 0.60 * weighted_jaccard + 0.40 * containment
                others = (
                    (0.15, _jaccard(a.complaint_tokens, b.complaint_tokens)),
                    (0.03, _jaccard(a.ecu_software, b.ecu_software)),
                    (0.02, _jaccard(a.vehicle_variant, b.vehicle_variant)),
                )
                numerator = 0.80 * fault_similarity
                denominator = 0.80
                for weight, value in others:
                    if value is not None:
                        numerator += weight * value
                        denominator += weight
                score = max(0.0, min(1.0, numerator / denominator))
                eligible_pair = True
                reason = "Gemeinsame informative Vorher-ECU:DTC-Basis"
        pair = RepresentativePair(
            left_id, right_id, round(score, 6),
            round(fault_similarity, 6), shared, eligible_pair, reason,
        )
        pairs[pair.key] = pair
    return pairs, rarity


def _common_core(
    ids: tuple[str, ...],
    signatures: Mapping[str, DiagnosticSignature],
    rarity: Mapping[tuple[str, FaultKey], float],
    max_frequency: float,
) -> tuple[FaultKey, ...]:
    if not ids:
        return ()
    common = set(signatures[ids[0]].faults)
    for case_id in ids[1:]:
        common.intersection_update(signatures[case_id].faults)
        if not common:
            break
    if not common or not (
        len(common) >= 2
        or any(
            rarity[(signatures[ids[0]].component_key, fault)] <= max_frequency
            for fault in common
        )
    ):
        return ()
    return tuple(sorted(common))


def select_representative_cases(
    cases: list[NTFCase],
    *,
    minimum_similarity: float = 0.60,
    lookback_days: int | None = None,
    dtc_source: str = "all",
    maximum_common_frequency: float = 0.35,
) -> RepresentativePlan:
    """Automatically form homogeneous Complete-Link groups; no K/budget cap.

    Pair-eligibility is mandatory for every distinct member pair. Every group
    also has a common exact diagnostic core. Thus a weak A-to-C relationship
    cannot be admitted merely because A and C both resemble the medoid B.
    The medoid is the real case with the best worst-member similarity (then
    mean member similarity, prediagnostic documentation and stable case ID).
    """
    if not 0.0 < minimum_similarity <= 1.0:
        raise ValueError("Mindestähnlichkeit muss größer 0 und höchstens 1 sein.")
    if not 0.0 < maximum_common_frequency <= 1.0:
        raise ValueError("Grenze für häufige DTCs muss im Intervall (0, 1] liegen.")
    by_id = {case.case_id: case for case in cases}
    if len(by_id) != len(cases):
        raise ValueError("QEC-Fall-IDs müssen eindeutig sein.")
    sigs = {
        case_id: signature_for(
            by_id[case_id], lookback_days=lookback_days, dtc_source=dtc_source,
        )
        for case_id in sorted(by_id)
    }
    eligible = tuple(
        case_id for case_id, sig in sigs.items()
        if sig.has_replacement_anchor and sig.faults
    )
    pairs, rarity = _build_pairs(
        sigs, by_id, max_frequency=maximum_common_frequency,
    )
    accepted = [
        pair for pair in pairs.values()
        if pair.eligible and pair.similarity >= minimum_similarity
    ]
    accepted.sort(
        key=lambda pair: (-pair.similarity, pair.left_id, pair.right_id)
    )
    # One deterministic greedy Complete-Link agglomeration; the number of
    # qualifying groups is determined by the data, not by a chosen K.
    members = {case_id: (case_id,) for case_id in eligible}
    root = {case_id: case_id for case_id in eligible}
    for candidate in accepted:
        a_root = root[candidate.left_id]
        b_root = root[candidate.right_id]
        if a_root == b_root:
            continue
        proposed = tuple(sorted(set(members[a_root]) | set(members[b_root])))
        if not _common_core(
            proposed, sigs, rarity, maximum_common_frequency
        ):
            continue
        complete = all(
            (comparison := pairs[frozenset((left, right))]).eligible
            and comparison.similarity >= minimum_similarity
            for i, left in enumerate(proposed)
            for right in proposed[i + 1:]
        )
        if not complete:
            continue
        kept, discarded = sorted((a_root, b_root))
        members[kept] = proposed
        del members[discarded]
        for case_id in proposed:
            root[case_id] = kept

    groups = [ids for ids in members.values() if len(ids) >= 2]
    # Prioritize larger robust core groups, without making group size itself
    # an evidence criterion or a constraint on total number of clusters.
    groups.sort(key=lambda group: (-len(group), group))
    clusters = []
    for cluster_id, ids in enumerate(groups, 1):
        def medoid_sort_key(case_id: str) -> tuple:
            neighbor_values = [
                pairs[frozenset((case_id, other))].similarity
                for other in ids if other != case_id
            ]
            return (
                -min(neighbor_values),
                -mean(neighbor_values),
                tuple(-q for q in _case_quality(
                    by_id[case_id], sigs[case_id],
                    lookback_days=lookback_days,
                )),
                case_id,
            )

        representative = min(ids, key=medoid_sort_key)
        others = [
            pairs[frozenset((representative, other))].similarity
            for other in ids if other != representative
        ]
        internal = [
            pairs[frozenset((left, right))].similarity
            for i, left in enumerate(ids) for right in ids[i + 1:]
        ]
        core = _common_core(ids, sigs, rarity, maximum_common_frequency)
        assert core and internal and min(internal) >= minimum_similarity
        members_for_group = tuple(
            RepresentativeMember(
                case_id=case_id,
                representative_case_id=representative,
                similarity=(
                    1.0 if case_id == representative
                    else pairs[frozenset((case_id, representative))].similarity
                ),
                shared_faults=(
                    () if case_id == representative
                    else pairs[frozenset((case_id, representative))].shared_faults
                ),
            )
            for case_id in ids
        )
        source_findings = [
            qec_ssl_finding(by_id[case_id]) for case_id in ids
        ]
        documented = [
            finding.text.casefold().strip()
            for finding in source_findings if finding is not None
        ]
        vins = {by_id[case_id].vin for case_id in ids}
        notes = []
        if len(set(documented)) > 1:
            notes.append("Unterschiedliche SSL-Rohtexte; fachlich gegenprüfen")
        if len(documented) < len(ids):
            notes.append(
                f"Nur {len(documented)}/{len(ids)} Fälle mit SSL-Endbefund"
            )
        if len(vins) == 1:
            notes.append("Nur eine FIN: keine fahrzeugübergreifende Bestätigung")
        if len(core) == 1:
            notes.append("Nur ein gemeinsamer ECU:DTC als Kernevidenz")
        elif all(
            rarity[(sigs[ids[0]].component_key, fault)] > maximum_common_frequency
            for fault in core
        ):
            notes.append("Gemeinsame Kerndiagnose nur aus häufigen DTCs")
        if not all(
            by_id[case_id].vehicle.model_series for case_id in ids
        ):
            notes.append("Baureihe nicht für alle Mitglieder dokumentiert")
        if any(
            not _has_pre_quicktest(by_id[case_id], lookback_days=lookback_days)
            for case_id in ids
        ):
            notes.append("Nicht alle Fälle besitzen einen Vorher-QuickTest")
        clusters.append(RepresentativeCluster(
            cluster_id=cluster_id,
            representative_case_id=representative,
            members=members_for_group,
            vehicle_count=len(vins),
            # Exclude 100% self comparison; show actual comparisons to rep.
            mean_similarity=round(mean(others), 4),
            weakest_representative_similarity=round(min(others), 4),
            weakest_internal_similarity=round(min(internal), 4),
            common_faults=core,
            with_pre_quicktest=sum(
                _has_pre_quicktest(by_id[case_id], lookback_days=lookback_days)
                for case_id in ids
            ),
            with_qec_ssl_finding=len(documented),
            review_warnings=tuple(notes),
        ))
    covered = frozenset(
        case_id for group in clusters for case_id in group.case_ids
    )
    unassigned = tuple(sorted(set(by_id) - covered))
    reasons = []
    for case_id in unassigned:
        sig = sigs[case_id]
        options = sorted(
            (
                (pair.similarity, other, pair)
                for pair in pairs.values()
                if pair.eligible
                and case_id in (pair.left_id, pair.right_id)
                for other in (
                    [pair.right_id] if pair.left_id == case_id
                    else [pair.left_id]
                )
            ),
            key=lambda option: (-option[0], option[1]),
        )
        if not sig.has_replacement_anchor:
            reason = "Kein eindeutig dokumentierter Tauschanker"
        elif not sig.faults:
            reason = "Keine belegte ECU:DTC-Diagnose vor Tausch"
        elif not options:
            reason = "Kein zulässiger informativer ECU:DTC-Paarvergleich"
        elif options[0][0] < minimum_similarity:
            reason = "Beste Paarähnlichkeit unter Mindestindex"
        else:
            reason = (
                "Einzelpaar passend, aber keine homogene Gruppe mit "
                "gemeinsamem DTC-Kern und ausreichender Paarähnlichkeit"
            )
        reasons.append(UnassignedCase(
            case_id=case_id,
            reason=reason,
            nearest_diagnostic_case_id=options[0][1] if options else None,
            nearest_similarity=options[0][0] if options else None,
        ))
    return RepresentativePlan(
        clusters=tuple(clusters),
        unassigned=unassigned,
        unassigned_reasons=tuple(reasons),
        eligible_cases=eligible,
        pair_scores=tuple(sorted(
            pairs.values(), key=lambda pair: (pair.left_id, pair.right_id),
        )),
        minimum_similarity=minimum_similarity,
        lookback_days=lookback_days,
        dtc_source=dtc_source,
        total_cases=len(cases),
        vehicle_count=len({case.vin for case in cases}),
        missing_pre_diagnostics=sum(not sig.faults for sig in sigs.values()),
        without_swap_anchor=sum(
            not sig.has_replacement_anchor for sig in sigs.values()
        ),
        common_dtc_limit=maximum_common_frequency,
        screening_population=len(eligible),
    )
