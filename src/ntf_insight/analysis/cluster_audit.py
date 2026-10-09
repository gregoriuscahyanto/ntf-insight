"""Explain why diagnostic observations become scatter points and cluster members.

No new clustering logic: this module audits *exactly* the signatures and
pair comparisons chosen in the UI. All counts are deterministic and use only
source metadata, never supplier findings as predictors.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import median

from ntf_insight.analysis.case_clustering import (
    CaseClusterResult,
    _matches_dtc_source,
    signature_for,
)
from ntf_insight.analysis.recurrence import relative_to_replacement
from ntf_insight.domain.case import NTFCase


@dataclass(frozen=True, slots=True)
class ClusterAudit:
    cases: int
    anchored: int
    pre_fault_cases: int
    complaint_only_cases: int
    no_diagnostic_basis: int
    without_any_dtc: int
    with_dtc_but_no_pre_fault: int
    with_pre_quicktest_dtc: int
    with_pre_autoexport_dtc: int
    median_pre_faults: float
    total_pairs: int
    comparable_pairs: int
    pairs_with_shared_dtc: int
    pairs_with_both_anchors: int
    pairs_covered: int
    pairs_above_threshold: int
    eligible_pairs: int
    assigned: int
    clusters: int


@dataclass(frozen=True, slots=True)
class RejectedCandidate:
    left_id: str
    right_id: str
    score: float
    coverage: float
    shared_faults: int
    reason: str


def _gate_reason(match, threshold: float) -> str:
    if match.score is None:
        return "Keine vergleichbare Diagnosebasis"
    if not match.shared_faults:
        return "Keine gemeinsame ECU:DTC-Kombination"
    if not match.eligible_for_cluster:
        if match.coverage < 0.50:
            return "Merkmalsabdeckung unter 50 %"
        return "Mindestens ein Tauschanker fehlt"
    if match.score < threshold:
        return "Jaccard unter Mindestähnlichkeit"
    return "Paar zulässig, Complete-Link-Gruppenregel beachten"


def audit_case_clusters(
    cases: list[NTFCase],
    result: CaseClusterResult,
    *,
    lookback_days: int | None = None,
    dtc_source: str = "all",
) -> tuple[ClusterAudit, tuple[RejectedCandidate, ...]]:
    """Audit current family/filtered source, not the unrelated whole repository.

    Filters must exactly match the already generated CaseClusterResult; this
    prevents a misleading report from a different diagnostic scenario.
    """
    if (lookback_days, dtc_source) != (result.lookback_days, result.dtc_source):
        raise ValueError("Clusteranalyse und Prüftabelle benutzen verschiedene Filter.")
    by_id = {case.case_id: case for case in cases}
    if len(by_id) != len(cases):
        raise ValueError("Fall-IDs müssen eindeutig sein.")
    ids = set(by_id)
    signatures = {
        case.case_id: signature_for(
            case, lookback_days=lookback_days, dtc_source=dtc_source
        ) for case in cases
    }
    scoped_pre = {}
    before_qt = set()
    before_auto = set()
    for case in cases:
        replacement = case.investigated_replacement()
        events = [
            event for event in case.diagnostics
            if (
                replacement is None
                or relative_to_replacement(event, replacement) == "pre"
            )
            and (
                lookback_days is None or replacement is None
                or 0 <= (replacement.occurred_at - event.occurred_at).total_seconds()
                   <= lookback_days * 86400
            )
        ]
        for event in events:
            if _matches_dtc_source(event, "quicktest"):
                before_qt.add(case.case_id)
            elif _matches_dtc_source(event, "autoexport"):
                before_auto.add(case.case_id)
        scoped_pre[case.case_id] = events

    scoped_pairs = [
        match for match in result.matches
        if match.left_case_id in ids and match.right_case_id in ids
    ]
    rejected = [
        RejectedCandidate(
            left_id=match.left_case_id,
            right_id=match.right_case_id,
            score=match.score,
            coverage=match.coverage,
            shared_faults=len(match.shared_faults),
            reason=_gate_reason(match, result.threshold),
        )
        for match in scoped_pairs
        if match.score is not None
        and match.shared_faults
        and not (
            match.eligible_for_cluster and match.score >= result.threshold
        )
    ]
    rejected.sort(
        key=lambda r: (-(r.score * r.coverage), -r.score, r.left_id, r.right_id)
    )
    covered = [
        m for m in scoped_pairs if m.shared_faults and m.coverage >= 0.50
    ]
    score_pass = [
        m for m in covered
        if m.score is not None and m.score >= result.threshold
    ]
    assigned = {
        case_id for cluster in result.clusters
        for case_id in cluster.case_ids if case_id in ids
    }
    clusters = sum(
        len(set(cluster.case_ids) & ids) >= 2 for cluster in result.clusters
    )
    audit = ClusterAudit(
        cases=len(cases),
        anchored=sum(bool(sig.has_replacement_anchor) for sig in signatures.values()),
        pre_fault_cases=sum(bool(sig.faults) for sig in signatures.values()),
        complaint_only_cases=sum(
            bool(not sig.faults and sig.complaint_tokens)
            for sig in signatures.values()
        ),
        no_diagnostic_basis=sum(
            not (sig.faults or sig.complaint_tokens) for sig in signatures.values()
        ),
        without_any_dtc=sum(not case.diagnostics for case in cases),
        with_dtc_but_no_pre_fault=sum(
            bool(case.diagnostics) and not signatures[case.case_id].faults
            for case in cases
        ),
        with_pre_quicktest_dtc=len(before_qt),
        with_pre_autoexport_dtc=len(before_auto),
        median_pre_faults=(
            float(median(len(sig.faults) for sig in signatures.values()))
            if signatures else 0.0
        ),
        total_pairs=len(scoped_pairs),
        comparable_pairs=sum(match.score is not None for match in scoped_pairs),
        pairs_with_shared_dtc=sum(bool(m.shared_faults) for m in scoped_pairs),
        pairs_with_both_anchors=sum(
            bool(m.shared_faults)
            and signatures[m.left_case_id].has_replacement_anchor
            and signatures[m.right_case_id].has_replacement_anchor
            for m in scoped_pairs
        ),
        pairs_covered=len(covered),
        pairs_above_threshold=len(score_pass),
        eligible_pairs=sum(
            bool(m.eligible_for_cluster)
            and m.score is not None
            and m.score >= result.threshold
            for m in scoped_pairs
        ),
        assigned=len(assigned),
        clusters=clusters,
    )
    return audit, tuple(rejected[:30])
