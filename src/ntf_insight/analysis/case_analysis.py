"""Unified case-analysis service used by GUI, batch jobs and later reports."""

from __future__ import annotations

from dataclasses import dataclass

from ntf_insight.analysis.data_quality import DataQualityReport, assess_data_quality
from ntf_insight.analysis.evidence_engine import EvidenceBundle, generate_case_evidence
from ntf_insight.analysis.features import CaseFeatures, extract_case_features
from ntf_insight.analysis.recurrence import RecurrenceResult, analyze_recurrence
from ntf_insight.analysis.timeline import TimelineEntry, build_timeline
from ntf_insight.domain.case import NTFCase
from ntf_insight.storage.reference_repositories import ReferenceRepository


@dataclass(frozen=True, slots=True)
class CaseAnalysis:
    case_id: str
    recurrence: RecurrenceResult
    quality: DataQualityReport
    features: CaseFeatures
    evidence: EvidenceBundle
    timeline: tuple[TimelineEntry, ...]


def analyze_case(
    case: NTFCase,
    references: ReferenceRepository | None = None,
) -> CaseAnalysis:
    """Run all currently available deterministic analysis layers for one case."""
    return CaseAnalysis(
        case_id=case.case_id,
        recurrence=analyze_recurrence(case),
        quality=assess_data_quality(case, references),
        features=extract_case_features(case, references),
        evidence=generate_case_evidence(case, references),
        timeline=tuple(build_timeline(case)),
    )
