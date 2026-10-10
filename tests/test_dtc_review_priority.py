"""Nur synthetische DTC-Fachmarkierungen, keine FINs aus Benutzerdaten."""
from __future__ import annotations

from ntf_insight.analysis.autoexport_fin_patterns import FinPatternGroup
from ntf_insight.analysis.dtc_review_priority import review_priority
from ntf_insight.storage.dtc_review_store import (
    DtcReviewStore, normalize_key,
)
from ntf_insight.storage.duckdb_store import DuckDBStore


def test_review_marks_are_local_and_survive_store_reinstantiation(tmp_path):
    db = DuckDBStore(tmp_path / "review-marks.duckdb")
    store = DtcReviewStore(db)
    assert store.list_marks() == {}
    store.mark(" cpc3 ", " synth-pump-1 ", relevant=True, note="Expert test")
    assert ("CPC3", "SYNTH-PUMP-1") in store.list_marks()
    assert store.list_marks()[("CPC3", "SYNTH-PUMP-1")].note == "Expert test"

    another_instance = DtcReviewStore(db)
    another_instance.mark(
        "CPC3", "SYNTH-PUMP-1", relevant=True, note="Updated review"
    )
    assert store.list_marks()[("CPC3", "SYNTH-PUMP-1")].note == (
        "Updated review"
    )
    another_instance.mark("CPC3", "SYNTH-PUMP-1", relevant=False)
    assert store.list_marks() == {}
    assert normalize_key(" cpc3 ", " synth-pump-1 ") == (
        "CPC3", "SYNTH-PUMP-1"
    )


def _group() -> FinPatternGroup:
    return FinPatternGroup(
        group_id=3,
        members=(
            ("FAKE-FIN-A", 1.0), ("FAKE-FIN-B", .9),
            ("FAKE-FIN-C", .8), ("FAKE-FIN-D", .7),
        ),
        representative_fin="FAKE-FIN-A",
        common_faults=(),
        qec_fin_count=0,
        median_similarity=.8,
    )


def test_priority_uses_unique_affected_fins_and_not_number_of_dtc_events():
    faults = {
        "FAKE-FIN-A": (("CPC3", "SYNTH-A"), ("CPC3", "SYNTH-B")),
        "FAKE-FIN-B": (("CPC3", "SYNTH-A"), ("CPC3", "SYNTH-A")),
        "FAKE-FIN-C": (("CPC3", "SYNTH-B"),),
        "FAKE-FIN-D": (("HU7", "OTHER"),),
    }
    group = _group()
    none = review_priority(group, faults, set())
    assert none.label == "Keine Markierung"
    assert none.affected_fins == 0

    partial = review_priority(group, faults, {("CPC3", "SYNTH-A")})
    assert partial.level == "hoch"
    assert partial.affected_fins == 2
    assert partial.marked_faults == (("CPC3", "SYNTH-A", 2),)

    one = review_priority(group, faults, {("HU7", "OTHER")})
    assert one.level == "hinweis"
    assert one.affected_fins == 1

    both = review_priority(
        group, faults, {("CPC3", "SYNTH-A"), ("CPC3", "SYNTH-B")}
    )
    assert both.level == "hoch"
    assert both.affected_fins == 3
    assert both.marked_faults == (
        ("CPC3", "SYNTH-A", 2),
        ("CPC3", "SYNTH-B", 2),
    )
    assert review_priority(group, faults, {("OTHER", "SYNTH-A")}).level == "keine"


def test_source_autoexport_dtc_overview_includes_fins_without_qec(tmp_path):
    from ntf_insight.storage.source_knowledge_store import SourceKnowledgeStore

    db = DuckDBStore(tmp_path / "autoexport-marks.duckdb")
    sources = SourceKnowledgeStore(db)
    rows = [
        {"category": "autoexport_dtc", "fin": fin, "data": {
            "EcuNm": "CPC_NG", "EcuFaultNm": "SYNTH-U02",
            "EcuFaultTxt": "Synthetic coolant circuit fault",
        }}
        for fin in (
            "W1TTEST0000000001", "W1TTEST0000000002",
            "W1TTEST0000000002",
        )
    ]
    sources.save_records("a" * 64, "autoexport_rows", rows)
    overview = sources.autoexport_dtc_overview()
    assert overview == {
        ("CPC_NG", "SYNTH-U02"): (
            2, 3, "Synthetic coolant circuit fault",
        )
    }
