"""Component-agnostic analysis services."""

from ntf_insight.analysis.dataset import build_case_feature_frame
from ntf_insight.analysis.data_quality import DataQualityReport, QualityCheck, QualityStatus, assess_data_quality
from ntf_insight.analysis.evidence_engine import EvidenceBundle, generate_case_evidence
from ntf_insight.analysis.features import CaseFeatures, extract_case_features
from ntf_insight.analysis.knowledge import DiagnosticKnowledge, enrich_diagnostic
from ntf_insight.analysis.recurrence import RecurrenceResult, analyze_recurrence, format_faults
from ntf_insight.analysis.similarity import SimilarityResult, all_pairwise_similarities, compare_cases
from ntf_insight.analysis.supplier_metrics import SupplierSummary, build_supplier_summaries
from ntf_insight.analysis.timeline import TimelineEntry, build_timeline

__all__ = [
    "CaseFeatures",
    "DataQualityReport",
    "DiagnosticKnowledge",
    "EvidenceBundle",
    "QualityCheck",
    "QualityStatus",
    "RecurrenceResult",
    "SimilarityResult",
    "SupplierSummary",
    "TimelineEntry",
    "all_pairwise_similarities",
    "analyze_recurrence",
    "assess_data_quality",
    "build_case_feature_frame",
    "build_supplier_summaries",
    "build_timeline",
    "compare_cases",
    "enrich_diagnostic",
    "extract_case_features",
    "format_faults",
    "generate_case_evidence",
]
