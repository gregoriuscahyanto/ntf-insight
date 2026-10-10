"""Cluster regression: separate true QEC cases, diagnostic FINs, and source effects.

Only synthetic vehicles/codes; never upload real automotive source data.
"""

import os
from datetime import datetime

import pytest

from ntf_insight.analysis.case_clustering import (
    cluster_diagnostic_cases, compare_diagnostic_cases, signature_for,
)
from ntf_insight.analysis.case_projection import project_diagnostic_cases
from ntf_insight.analysis.case_similarity_explanation import explain_case_similarity
from ntf_insight.analysis.cluster_audit import audit_case_clusters
from ntf_insight.domain.case import NTFCase
from ntf_insight.domain.events import DiagnosticEvent, PartReplacement
from ntf_insight.domain.vehicle import Vehicle
from ntf_insight.storage.duckdb_store import DuckDBStore
from ntf_insight.storage.source_knowledge_store import SourceKnowledgeStore


def synthetic_case(name: str) -> NTFCase:
    fin = f"W1TTEST00000{name:0>5}"
    replacement = datetime(2026, 2, 28, 12)
    case = NTFCase(
        case_id=name, vehicle=Vehicle(vin=fin),
        component_type="Coolant Pump", component_profile_id="coolant_pump",
        replacements=[PartReplacement(
            vin=fin, component_type="Coolant Pump", occurred_at=replacement,
        )],
    )
    case.diagnostics.append(DiagnosticEvent(
        vin=fin, ecu="CPC3", dtc_code="P26F100",
        occurred_at=datetime(2026, 2, 20, 10),
        session_id="session-" + name,
        freeze_frame={"observed_at_diagnostic_test": True},
        source_ref=f"raw:synthetic#ecu:1:dtc:{name}",
    ))
    # Older, unrelated DTC codes dilute *full history* Jaccard. Do not
    # falsely erase these observations; allow users to compare input windows.
    for index in range(15):
        case.diagnostics.append(DiagnosticEvent(
            vin=fin, ecu="CPC3", dtc_code=f"{name}{index:03d}",
            occurred_at=datetime(2026, 1, 1, 10),
            source_ref=f"raw:synthetic#csv:{name}:{index}",
        ))
    return case


def test_qt_only_sensitivity_explains_historical_dtc_cluster_collapse() -> None:
    first, second = synthetic_case("A"), synthetic_case("B")
    baseline = cluster_diagnostic_cases([first, second])
    assert len(baseline.clusters) == 0
    match = compare_diagnostic_cases(first, second)
    assert match.eligible_for_cluster
    assert match.score is not None and match.score < 0.65
    assert match.shared_faults == (("CPC3", "P26F100"),)

    qt = cluster_diagnostic_cases([first, second], dtc_source="quicktest")
    recent = cluster_diagnostic_cases([first, second], lookback_days=30)
    csv = cluster_diagnostic_cases([first, second], dtc_source="autoexport")
    assert qt.clusters and recent.clusters
    assert not csv.clusters
    assert not compare_diagnostic_cases(
        first, second, dtc_source="autoexport"
    ).shared_faults

    qt_sign = signature_for(first, dtc_source="quicktest")
    assert qt_sign.faults == frozenset({("CPC3", "P26F100")})
    full_sign = signature_for(first)
    assert len(full_sign.faults) == 16
    assert qt_sign.faults <= full_sign.faults

    audit, excluded = audit_case_clusters([first, second], baseline)
    assert audit.cases == 2
    assert audit.pre_fault_cases == 2
    assert audit.with_pre_quicktest_dtc == 2
    assert audit.with_pre_autoexport_dtc == 2
    assert audit.total_pairs == 1
    assert audit.pairs_with_shared_dtc == 1
    assert audit.pairs_covered == 1
    assert audit.pairs_above_threshold == 0
    assert audit.eligible_pairs == 0
    assert excluded[0].reason == "Jaccard unter Mindestähnlichkeit"

    recent_audit, recent_excluded = audit_case_clusters(
        [first, second], recent, lookback_days=30,
    )
    assert recent_audit.clusters == 1
    assert recent_audit.assigned == 2
    assert recent_audit.eligible_pairs == 1
    assert recent_excluded == ()
    assert explain_case_similarity(
        first, second, lookback_days=30,
    ).match.score == compare_diagnostic_cases(
        first, second, lookback_days=30,
    ).score
    assert project_diagnostic_cases(
        [first, second], lookback_days=30,
    ).points != project_diagnostic_cases([first, second]).points
    # None of the sensitivity modes mutates the case history.
    assert len(first.diagnostics) == 16
    assert len(second.diagnostics) == 16


def test_cluster_audit_rejects_mismatched_filters_and_source_values() -> None:
    first, second = synthetic_case("A"), synthetic_case("B")
    current = cluster_diagnostic_cases(
        [first, second], lookback_days=30, dtc_source="quicktest",
    )
    with pytest.raises(ValueError, match="verschiedene Filter"):
        audit_case_clusters([first, second], current)
    with pytest.raises(ValueError, match="Quellmodus"):
        signature_for(first, dtc_source="unknown")
    with pytest.raises(ValueError, match="positiv"):
        signature_for(first, lookback_days=0)


def test_missing_dtc_is_not_misrepresented_as_qec_case_loss() -> None:
    a = synthetic_case("A")
    b = NTFCase(
        case_id="NO-READINGS", component_type="Coolant Pump",
        vehicle=Vehicle(vin="W1TTEST0000000009"),
        replacements=[PartReplacement(
            vin="W1TTEST0000000009", component_type="Coolant Pump",
            occurred_at=datetime(2026, 2, 28),
        )],
    )
    result = cluster_diagnostic_cases([a, b])
    projection = project_diagnostic_cases([a, b])
    audit, _ = audit_case_clusters([a, b], result)
    assert audit.cases == 2  # one QEC case did not disappear
    assert audit.pre_fault_cases == 1
    assert audit.no_diagnostic_basis == 1
    assert audit.without_any_dtc == 1
    assert len(projection.points) == 1
    assert projection.omitted_case_ids == ("NO-READINGS",)


def test_population_counts_not_conflated_with_qec_or_failures(tmp_path) -> None:
    store = SourceKnowledgeStore(DuckDBStore(tmp_path / "demo.duckdb"))
    rows = [
        {"category": "autoexport_dtc", "fin": "W1TTEST0000000001",
         "source_location": "csv:2", "data": {"EcuFaultNm": "P26F100"}},
        {"category": "autoexport_dtc", "fin": "W1TTEST0000000001",
         "source_location": "csv:3", "data": {"EcuFaultNm": "P26F100"}},
        {"category": "autoexport_dtc", "fin": "W1TTEST0000000002",
         "source_location": "csv:4", "data": {"EcuFaultNm": "P260000"}},
        {"category": "autoexport_repair", "fin": "W1TTEST0000000001",
         "source_location": "csv:5", "data": {"RepairTypeNmGerman": "Synthetic"}},
        {"category": "autoexport_tips", "fin": "W1TTEST0000000002",
         "source_location": "csv:6", "data": {"CaseId": "TIPS-01"}},
        {"category": "autoexport_tips", "fin": "W1TTEST0000000002",
         "source_location": "csv:7", "data": {"CaseId": "TIPS-01"}},
    ]
    store.save_records("b" * 64, "autoexport_rows", rows)
    store.save_records("c" * 64, "qec_details", [
        {"category": "qec_row", "source_location": "Schadteile QEC!2",
         "reference": "QEC-001", "fin": "W1TTEST0000000001", "data": {}},
        {"category": "qec_row", "source_location": "Schadteile QEC!3",
         "reference": "QEC-002", "fin": "W1TTEST0000000002", "data": {}},
        {"category": "qec_row", "source_location": "NTF-Cluster!8",
         "reference": "QEC-001", "fin": "W1TTEST0000000001", "data": {}},
    ])
    numbers = store.autoexport_population()
    assert numbers["autoexport_dtc_rows"] == 3
    assert numbers["autoexport_dtc_fins"] == 2
    assert numbers["autoexport_total_rows"] == 6
    assert numbers["autoexport_unique_fins"] == 2
    assert numbers["autoexport_tips_rows"] == 2
    assert numbers["autoexport_tips_fins"] == 1
    assert numbers["tips_distinct_case_ids"] == 1
    assert numbers["autoexport_repair_fins"] == 1
    assert numbers["qec_original_rows"] == 3
    assert numbers["qec_primary_rows"] == 2
    assert numbers["qec_primary_references"] == 2
    assert numbers["qec_primary_fins"] == 2


@pytest.mark.parametrize("kind", ["quicktest", "autoexport"])
def test_scatter_filters_recompute_comparable_clusters_and_coordinates(
    kind: str,
) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from ntf_insight.app.widgets.case_scatter_plot import CaseScatterPanel

    app = QApplication.instance() or QApplication([])
    first, second = synthetic_case("A"), synthetic_case("B")
    panel = CaseScatterPanel(
        [first, second],
        cluster_diagnostic_cases([first, second]),
        population_metrics={
            "autoexport_dtc_fins": 9,
            "autoexport_tips_rows": 7,
            "tips_distinct_case_ids": 5,
        },
    )
    assert "9 FIN" in panel.population_summary.text()
    assert panel.audit_model.rowCount() >= 15
    baseline_features = panel.projection.feature_count
    index = panel.dtc_source.findData(kind)
    panel.dtc_source.setCurrentIndex(index)
    assert panel.result.dtc_source == kind
    assert panel.result.lookback_days is None
    assert panel.audit_model.rowCount() >= 15
    if kind == "quicktest":
        assert panel.result.clusters
        # With just two cases, a one-component SVD can have identical
        # projected coordinates despite different feature matrices.
        # Audit the *real input dimensions*, not assumed pixel positions.
        assert panel.projection.feature_count < baseline_features
    else:
        assert not panel.result.clusters
        assert not panel.rejected_model.rowCount()

    panel.lookback.setCurrentIndex(panel.lookback.findData(30))
    assert panel.result.lookback_days == 30
    assert "30 Tage" in panel.audit_note.text()
    # Only cluster threshold changes label, not source-specific position.
    coords = [(p.x, p.y) for p in panel.projection.points]
    panel.threshold.setValue(0.9)
    assert coords == [(p.x, p.y) for p in panel.projection.points]
    panel.close()
    app.processEvents()


def test_autoexport_unique_fins_deduplicated_across_files_and_categories(tmp_path):
    """Totals describe successfully imported VINs, not number of QEC claims."""
    store = SourceKnowledgeStore(DuckDBStore(tmp_path / "local.duckdb"))
    rows_one = [
        {"category": "autoexport_dtc", "source_location": "csv:2",
         "fin": "W1TTEST0000000001", "data": {}},
        {"category": "autoexport_dtc", "source_location": "csv:3",
         "fin": "W1TTEST0000000001", "data": {}},
        {"category": "autoexport_dtc", "source_location": "csv:4",
         "fin": "W1TTEST0000000002", "data": {}},
    ]
    rows_two = [
        {"category": "autoexport_repair", "source_location": "csv:2",
         "fin": "W1TTEST0000000001", "data": {}},
        {"category": "autoexport_tips", "source_location": "csv:3",
         "fin": "W1TTEST0000000003", "data": {"CaseId": "TEST-1"}},
        {"category": "autoexport_tips", "source_location": "csv:4",
         "fin": None, "data": {"CaseId": "TEST-2"}},
    ]
    store.save_records("a" * 64, "autoexport_rows", rows_one)
    store.save_records("b" * 64, "autoexport_rows", rows_two)
    population = store.autoexport_population()
    assert population["autoexport_total_rows"] == 6
    assert population["autoexport_unique_fins"] == 3
    assert population["autoexport_dtc_fins"] == 2
    assert population["autoexport_repair_fins"] == 1
    assert population["autoexport_tips_fins"] == 1
    # Imported raw DTC observations are NEVER independent QEC pump cases.
    assert population["qec_primary_rows"] == 0
    assert population["qec_primary_fins"] == 0
