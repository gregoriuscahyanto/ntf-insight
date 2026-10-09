"""Explicit, provenance-preserving manual TIPS↔QEC review using synthetic FINs."""
from __future__ import annotations

from datetime import datetime

import pytest

from ntf_insight.analysis.tips_case_matching import (
    confirm_tips_link,
    suggest_tips_links,
)
from ntf_insight.domain.case import NTFCase
from ntf_insight.domain.events import PartReplacement
from ntf_insight.domain.vehicle import Vehicle
from ntf_insight.storage.duckdb_store import DuckDBStore
from ntf_insight.storage.source_knowledge_store import SourceKnowledgeStore

FIN = "W1TTEST0000000001"
OTHER = "W1TTEST0000000002"


def qec(case_id: str, fin: str, when: str) -> NTFCase:
    return NTFCase(
        case_id=case_id, vehicle=Vehicle(vin=fin),
        component_type="Coolant Pump", component_profile_id="coolant_pump",
        replacements=[
            PartReplacement(
                vin=fin, event_id=f"r-{case_id}",
                component_type="Coolant Pump",
                occurred_at=datetime.fromisoformat(when),
            )
        ],
        investigated_replacement_id=f"r-{case_id}",
    )


def prepare(tmp_path):
    store = DuckDBStore(tmp_path / "local.duckdb")
    cases = [
        qec("QEC-1", FIN, "2026-05-03T12:00:00"),
        qec("QEC-2", FIN, "2026-06-05T12:00:00"),
    ]
    store.save_cases(cases)
    knowledge = SourceKnowledgeStore(store)
    knowledge.save_records("a" * 64, "autoexport_rows", [
        {
            "category": "autoexport_tips", "fin": FIN,
            "source_location": "csv:row:1", "reference": "TIPS-001",
            "label": "2026-04-25",
            "data": {
                "Fin": FIN, "CaseId": "TIPS-001",
                "CreationDate": "2026-04-25",
                "InitialWorkshopMessageCustomerComplaint":
                    "Synthetische Beanstandung vor Tausch",
                "InitialWorkshopMessageWorkshopFindings":
                    "Synthetischer Werkstattbefund",
                "InitialWorkshopMessagePerformedActions":
                    "Synthetische spaetere Massnahme",
            },
        },
        {
            "category": "autoexport_tips", "fin": OTHER,
            "source_location": "csv:row:2", "reference": "TIPS-002",
            "label": "2026-04-22",
            "data": {
                "Fin": OTHER, "CaseId": "TIPS-002", "CreationDate": "2026-04-22",
            },
        },
        {
            "category": "autoexport_tips", "fin": FIN,
            "source_location": "csv:row:3", "reference": "TIPS-001",
            "label": "2026-04-25",
            "data": {
                "Fin": FIN, "CaseId": "TIPS-001",
                "CreationDate": "2026-04-25",
                "InitialWorkshopMessageCustomerComplaint":
                    "Synthetische Beanstandung vor Tausch",
            },
        },
    ])
    return store, cases, knowledge


def test_same_fin_multiple_qec_requires_explicit_review_and_keeps_nonqec(tmp_path) -> None:
    store, cases, knowledge = prepare(tmp_path)
    suggestions = suggest_tips_links(cases, knowledge)
    assert len(suggestions) == 3  # 2 candidate QEC cases and one unlinked VIN
    both = [s for s in suggestions if s.tips_case_id == "TIPS-001"]
    assert len(both) == 2
    assert all(s.can_confirm and "mehrere QEC" in s.status for s in both)
    assert any(
        s.tips_case_id == "TIPS-002" and not s.can_confirm
        and s.status == "Ohne QEC-Fall" for s in suggestions
    )
    assert knowledge.count_rows("autoexport_tips") == 3

    selected = next(x for x in both if x.qec_case_id == "QEC-1")
    linked = confirm_tips_link(store, selected)
    assert linked.case_id == "QEC-1"
    assert linked.tips_observations[0].tips_case_id == "TIPS-001"
    assert linked.tips_observations[0].complaint.startswith("Synthetische")
    assert linked.tips_observations[0].source_ref.startswith("raw:" + "a" * 64)
    assert linked.tips_observations[0].manually_confirmed is True
    assert len(store.get_case("QEC-2").tips_observations) == 0
    assert knowledge.count_rows("autoexport_tips") == 3
    fresh = suggest_tips_links(store.load_cases(), knowledge)
    assert any(s.qec_case_id == "QEC-1" and s.status == "Bereits verknüpft"
               for s in fresh)
    assert any(s.qec_case_id == "QEC-2"
               and s.status == "Anderem QEC-Fall zugeordnet"
               and not s.can_confirm for s in fresh)

    with pytest.raises(ValueError, match="bereits"):
        confirm_tips_link(store, selected)
    with pytest.raises(ValueError, match="Kein manuell"):
        confirm_tips_link(store, next(x for x in fresh
                                      if x.tips_case_id == "TIPS-002"))


def test_mismatched_source_fin_cannot_be_forced_into_qec_case(tmp_path) -> None:
    store, cases, knowledge = prepare(tmp_path)
    candidate = next(c for c in suggest_tips_links(cases, knowledge)
                     if c.qec_case_id == "QEC-1")
    # Snapshot changes after the proposal (e.g. another operator), backend
    # revalidates source and destination identity inside the transaction.
    case = store.get_case("QEC-1")
    case.vehicle.vin = OTHER
    store.save_case(case)
    with pytest.raises(ValueError, match="FIN"):
        confirm_tips_link(store, candidate)
    assert not store.get_case("QEC-1").tips_observations
    assert knowledge.count_rows("autoexport_tips") == 3


def test_out_of_window_tips_remains_unlinked_review_only(tmp_path) -> None:
    store, cases, knowledge = prepare(tmp_path)
    stale = qec("QEC-ANCIENT", OTHER, "2023-01-01T12:00:00")
    cases.append(stale)
    store.save_case(stale)
    review = suggest_tips_links(cases, knowledge)
    candidate = next(c for c in review
                     if c.qec_case_id == "QEC-ANCIENT")
    assert candidate.status == "Außerhalb Zuordnungsfenster"
    assert not candidate.can_confirm
    with pytest.raises(ValueError, match="Kein manuell"):
        confirm_tips_link(store, candidate)


def test_invalid_dates_and_duplicate_tips_rows_not_extra_episodes(tmp_path) -> None:
    store, cases, knowledge = prepare(tmp_path)
    knowledge.save_records("b" * 64, "autoexport_rows", [
        {"category": "autoexport_tips", "fin": FIN,
         "source_location": "csv:row:bad", "data": {
            "Fin": FIN, "CaseId": "TIPS-INVALID", "CreationDate": "garbage",
         }},
    ])
    assert len(suggest_tips_links(cases, knowledge)) == 3
