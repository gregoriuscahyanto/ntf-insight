"""Budget-constrained, abstaining medoid selection over *real* QEC cases.

Engineering screening hypothesis, not a learned diagnostic/cause probability.
Membership uses exclusively pre-intervention diagnostic evidence; outcomes are
added to a post-hoc quality summary and never affect scores or representatives.

Compared to fixed Complete-Link 0.65 this method optimizes how many real,
reasonably similar cases can be reviewed through a limited sample of *actual*
cases, while allowing insufficient or ambiguous observations to abstain.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from math import log
from typing import Mapping

from ntf_insight.analysis.case_clustering import (
    DiagnosticSignature,
    FaultKey,
    signature_for,
)
from ntf_insight.analysis.qec_findings import qec_ssl_finding
from ntf_insight.analysis.recurrence import relative_to_replacement
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
class RepresentativePlan:
    clusters: tuple[RepresentativeCluster, ...]
    unassigned: tuple[str, ...]
    eligible_cases: tuple[str, ...]
    pair_scores: tuple[RepresentativePair, ...]
    budget: int
    minimum_similarity: float
    lookback_days: int | None
    dtc_source: str
    total_cases: int
    vehicle_count: int
    missing_pre_diagnostics: int
    without_swap_anchor: int

    @property
    def assigned_case_ids(self) -> frozenset[str]:
        return frozenset(
            case_id for group in self.clusters for case_id in group.case_ids
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


def _jaccard(a: frozenset, b: frozenset) -> float | None:
    if not a or not b:
        return None
    return len(a & b) / len(a | b)


def _source_preference(case: NTFCase, sig: DiagnosticSignature) -> int:
    """Tie breaker only. No supplier or *post-test* evidence is consulted."""
    return (
        min(len(sig.faults), 15)
        + 2 * bool(sig.complaint_tokens)
        + bool(sig.ecu_software)
        + bool(case.vehicle.model_series)
        + bool(case.vehicle.variant)
    )


def _build_pairs(
    signatures: Mapping[str, DiagnosticSignature],
    cases: Mapping[str, NTFCase],
    *,
    max_frequency: float,
) -> dict[frozenset[str], RepresentativePair]:
    from itertools import combinations

    ids = sorted(cases)
    component_counts = Counter(signatures[case_id].component_key for case_id in ids)
    fault_df: Counter[tuple[str, FaultKey]] = Counter()
    for case_id, sig in signatures.items():
        fault_df.update((sig.component_key, fault) for fault in sig.faults)

    idf = {
        (comp, fault): 1.0 + log((component_counts[comp] + 1) / (df + 1))
        for (comp, fault), df in fault_df.items()
    }
    pairs: dict[frozenset[str], RepresentativePair] = {}
    for left_id, right_id in combinations(ids, 2):
        a, b = signatures[left_id], signatures[right_id]
        shared = tuple(sorted(a.faults & b.faults))
        score = 0.0
        fault_sim = 0.0
        eligible = False
        reason = ""
        if a.component_key != b.component_key:
            reason = "Verschiedene Bauteilfamilien"
        elif not a.has_replacement_anchor or not b.has_replacement_anchor:
            reason = "Unzureichender Tauschanker"
        elif not a.faults or not b.faults:
            reason = "Kein beidseitiger Vor-Tausch-ECU:DTC"
        elif not shared:
            reason = "Kein gemeinsamer ECU:DTC"
        else:
            # IDF is measured only within the current component family.
            # A code occurring in ~42 % of all QEC cases must not by itself
            # trigger a 72-case cluster with unverified shared root cause.
            n = component_counts[a.component_key]
            informative = (
                len(shared) >= 2
                or any(fault_df[(a.component_key, fault)] / n <= max_frequency
                       for fault in shared)
            )
            if not informative:
                reason = "Nur häufige, unspezifische gemeinsame DTCs"
            else:
                series_a = (cases[left_id].vehicle.model_series or "").strip()
                series_b = (cases[right_id].vehicle.model_series or "").strip()
                if series_a and series_b and series_a.casefold() != series_b.casefold():
                    reason = "Abweichende bekannte Baureihe"
                else:
                    wa = sum(idf[(a.component_key, fault)] for fault in a.faults)
                    wb = sum(idf[(b.component_key, fault)] for fault in b.faults)
                    inter = sum(idf[(a.component_key, fault)] for fault in shared)
                    # Mix weighted Jaccard (noise penalty) and symmetric
                    # containment (large historical exports less punitive).
                    fault_sim = 0.35 * inter / (wa + wb - inter) + (
                        0.65 * inter / min(wa, wb)
                    )
                    extra = [
                        (0.15, _jaccard(a.complaint_tokens, b.complaint_tokens)),
                        (0.03, _jaccard(a.ecu_software, b.ecu_software)),
                        (0.02, _jaccard(a.vehicle_variant, b.vehicle_variant)),
                    ]
                    numerator = 0.80 * fault_sim
                    denominator = 0.80
                    for weight, value in extra:
                        if value is not None:
                            numerator += weight * value
                            denominator += weight
                    score = max(0.0, min(1.0, numerator / denominator))
                    eligible = True
                    reason = "Exakte gemeinsame ECU:DTC + informative Vorher-Evidenz"
        pairs[frozenset((left_id, right_id))] = RepresentativePair(
            left_id=left_id,
            right_id=right_id,
            similarity=round(score, 6),
            fault_similarity=round(fault_sim, 6),
            shared_faults=shared,
            eligible=eligible,
            reason=reason,
        )
    return pairs


def _assign(
    members: tuple[str, ...],
    medoids: tuple[str, ...],
    accepted_pairs: Mapping[frozenset[str], RepresentativePair],
) -> dict[str, tuple[str, float]]:
    """Nearest selected real case, otherwise abstain; deterministic tie breaks."""
    result = {}
    for case_id in members:
        if case_id in medoids:
            result[case_id] = (case_id, 1.0)
            continue
        choices = [
            (pair.similarity, medoid)
            for medoid in medoids
            if (pair := accepted_pairs.get(frozenset((case_id, medoid))))
            is not None
        ]
        if choices:
            value, medoid = sorted(
                choices, key=lambda item: (-item[0], item[1])
            )[0]
            result[case_id] = (medoid, value)
    return result


def select_representative_cases(
    cases: list[NTFCase],
    *,
    budget: int = 12,
    minimum_similarity: float = 0.35,
    lookback_days: int | None = None,
    dtc_source: str = "all",
    maximum_common_frequency: float = 0.35,
) -> RepresentativePlan:
    """Deterministic coverage-first k-medoids/facility-location screening.

    Not vanilla forced-partition PAM: only *qualified* edges are used, every
    chosen medoid is a real QEC case, and dissimilar/missing observations abstain.
    No invented groups/covered cases are created to reach a requested budget.
    Local medoid swaps reduce average distance only after respecting coverage.
    """
    if not 1 <= budget <= 100:
        raise ValueError("Untersuchungsbudget muss zwischen 1 und 100 liegen.")
    if not 0.0 < minimum_similarity <= 1.0:
        raise ValueError("Mindestähnlichkeit muss größer 0 und höchstens 1 sein.")
    if not 0.0 < maximum_common_frequency <= 1.0:
        raise ValueError("Grenze für häufige DTCs muss im Intervall (0, 1] liegen.")
    by_id = {case.case_id: case for case in cases}
    if len(by_id) != len(cases):
        raise ValueError("Die Fall-IDs müssen eindeutig sein.")
    signatures = {
        case_id: signature_for(
            by_id[case_id], lookback_days=lookback_days,
            dtc_source=dtc_source,
        )
        for case_id in sorted(by_id)
    }
    eligible_ids = tuple(sorted(
        case_id for case_id, sig in signatures.items()
        if sig.has_replacement_anchor and sig.faults
    ))
    eligible_set = set(eligible_ids)
    all_pairs = _build_pairs(
        signatures, by_id, max_frequency=maximum_common_frequency
    )
    accepted = {
        key: pair for key, pair in all_pairs.items()
        if pair.eligible and pair.similarity >= minimum_similarity
    }
    available = tuple(sorted({
        case_id for key in accepted for case_id in key
    } & eligible_set))
    selected: tuple[str, ...] = ()
    current = _assign(eligible_ids, selected, accepted)

    def objective(assignments: Mapping[str, tuple[str, float]]) -> tuple[int, float]:
        return (
            len(assignments),
            round(sum(value for _, value in assignments.values()), 9),
        )

    # Coverage-first facility selection. A new representative must extend
    # coverage; it cannot spend the investigation budget on a near-duplicate.
    for _ in range(min(budget, len(available))):
        best = None
        for candidate in available:
            if candidate in selected:
                continue
            proposal = _assign(
                eligible_ids, (*selected, candidate), accepted
            )
            marginal = len(proposal) - len(current)
            if marginal <= 0:
                continue
            cost = _source_preference(by_id[candidate], signatures[candidate])
            key = (marginal, objective(proposal)[1], cost)
            if best is None or key > best[0] or (
                key == best[0] and candidate < best[1]
            ):
                best = (key, candidate, proposal)
        if best is None:
            break
        selected = (*selected, best[1])
        current = best[2]

    # Fixed-count medoid swaps (two deterministic passes), prioritising
    # case coverage over compactness. No case is forcibly assigned.
    for _ in range(2):
        improvement = None
        baseline = objective(current)
        for old in selected:
            for candidate in available:
                if candidate in selected:
                    continue
                proposal_medoids = tuple(
                    candidate if item == old else item for item in selected
                )
                proposal = _assign(eligible_ids, proposal_medoids, accepted)
                goal = objective(proposal)
                if goal > baseline and (
                    improvement is None
                    or goal > improvement[0]
                    or (goal == improvement[0] and proposal_medoids < improvement[1])
                ):
                    improvement = (goal, proposal_medoids, proposal)
        if improvement is None:
            break
        selected, current = improvement[1], improvement[2]

    # A reported cluster must represent >=2 real cases. If a medoid has only
    # itself, drop it, reassign others, and do not misreport it as coverage.
    for _ in range(len(selected)):
        sizes = Counter(rep for rep, _ in current.values())
        singletons = {rep for rep in selected if sizes.get(rep, 0) < 2}
        if not singletons:
            break
        selected = tuple(rep for rep in selected if rep not in singletons)
        current = _assign(eligible_ids, selected, accepted)

    clusters = []
    for index, representative_id in enumerate(selected, 1):
        member_ids = tuple(sorted(
            case_id for case_id, (rep, _) in current.items()
            if rep == representative_id
        ))
        assert len(member_ids) >= 2
        members = tuple(
            RepresentativeMember(
                case_id=case_id,
                representative_case_id=representative_id,
                similarity=current[case_id][1],
                shared_faults=(
                    tuple(sorted(signatures[case_id].faults))
                    if case_id == representative_id
                    else accepted[frozenset((case_id, representative_id))].shared_faults
                ),
            ) for case_id in member_ids
        )
        common_faults = set(signatures[member_ids[0]].faults)
        for case_id in member_ids[1:]:
            common_faults &= signatures[case_id].faults

        inner = [
            (
                all_pairs[frozenset((left, right))].similarity
                if all_pairs[frozenset((left, right))].eligible else 0.0
            )
            for n, left in enumerate(member_ids)
            for right in member_ids[n + 1:]
        ]
        findings = [
            finding.text.casefold().strip()
            for case_id in member_ids
            if (finding := qec_ssl_finding(by_id[case_id])) is not None
        ]
        warnings = []
        if len(set(findings)) > 1:
            warnings.append("Unterschiedliche SSL-Endbefundtexte – fachlich prüfen")
        if not findings:
            warnings.append("Keine SSL-Endbefunde für nachgelagerte Validierung")
        if inner and min(inner) < minimum_similarity:
            warnings.append(
                "Nicht alle Fälle untereinander ausreichend ähnlich "
                "(nur Medoid-Zuordnung, kein Complete-Link)"
            )
        if len({by_id[case_id].vin for case_id in member_ids}) < 2:
            warnings.append("Nur eine FIN in der Gruppe; keine Fahrzeugreplikation")
        if len(common_faults) == 1:
            warnings.append("Nur ein ECU:DTC ist allen Mitgliedern gemeinsam")

        clusters.append(RepresentativeCluster(
            cluster_id=index,
            representative_case_id=representative_id,
            members=members,
            vehicle_count=len({by_id[case_id].vin for case_id in member_ids}),
            mean_similarity=round(
                sum(member.similarity for member in members) / len(members), 4
            ),
            weakest_representative_similarity=round(
                min(member.similarity for member in members), 4
            ),
            weakest_internal_similarity=round(min(inner), 4) if inner else None,
            common_faults=tuple(sorted(common_faults)),
            with_pre_quicktest=sum(
                any(
                    e.session_id and "#ecu:" in (e.source_ref or "")
                    and relative_to_replacement(
                        e, by_id[case_id].investigated_replacement()
                    ) == "pre"
                    and e.fault_key in signatures[case_id].faults
                    for e in by_id[case_id].diagnostics
                )
                for case_id in member_ids
            ),
            with_qec_ssl_finding=len(findings),
            review_warnings=tuple(warnings),
        ))
    covered = frozenset(
        case_id for group in clusters for case_id in group.case_ids
    )
    return RepresentativePlan(
        clusters=tuple(clusters),
        unassigned=tuple(sorted(set(by_id) - covered)),
        eligible_cases=eligible_ids,
        pair_scores=tuple(
            sorted(all_pairs.values(), key=lambda p: (p.left_id, p.right_id))
        ),
        budget=budget,
        minimum_similarity=minimum_similarity,
        lookback_days=lookback_days,
        dtc_source=dtc_source,
        total_cases=len(cases),
        vehicle_count=len({case.vin for case in cases}),
        missing_pre_diagnostics=sum(not sig.faults for sig in signatures.values()),
        without_swap_anchor=sum(
            not sig.has_replacement_anchor for sig in signatures.values()
        ),
    )
