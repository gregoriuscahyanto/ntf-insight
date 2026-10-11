"""Nur synthetische FINs und QEC-Endbefunde, niemals Original-QEC-Dateien."""
from __future__ import annotations

from datetime import datetime

from ntf_insight.analysis.qec_end_finding_filter import (
    MISSING_END_FINDING, finding_counts, finding_for, part_numbers,
    selected_qec_cases, source_coverage,
)
from ntf_insight.analysis.combined_fin_evidence import (
    merge_fin_evidence, qec_fin_evidence,
)
from ntf_insight.domain.events import DiagnosticEvent
from test_hdbscan_clustering import synthetic


def _case(index: int, finding: str | None, part: str | None, *, swap=True):
    case = synthetic(
        f"QEC-TEST-{index}", "X", index,
        vin=f"W1TTEST000000{index:04d}", swap=swap,
    )
    case.qec_reference = f"FAKE-REF-{index}"
    case.qec_ssl_end_finding = finding
    case.qec_part_number = part
    return case


def test_end_finding_exact_multiple_and_substring_compose_without_metadata_leak():
    cases = [
        _case(1, "Pumpenfunktion beanstandet", "FAKE-PART-A"),
        _case(2, "NTF: Kein Fehler nachweisbar", "FAKE-PART-A"),
        _case(3, "Elektrischer Fehler", "FAKE-PART-B"),
        _case(4, "NTF: Kein Fehler nachweisbar", "FAKE-PART-B"),
        _case(5, None, "FAKE-PART-B"),
    ]
    assert finding_counts(cases) == {
        "NTF: Kein Fehler nachweisbar": 2,
        MISSING_END_FINDING: 1,
        "Elektrischer Fehler": 1,
        "Pumpenfunktion beanstandet": 1,
    }
    assert finding_for(cases[-1]) == MISSING_END_FINDING
    assert len(selected_qec_cases(cases)) == 5
    selected = selected_qec_cases(
        cases, exact_findings=(
            "Pumpenfunktion beanstandet",
            "NTF: Kein Fehler nachweisbar",
        ),
    )
    assert {case.case_id for case in selected} == {
        "QEC-TEST-1", "QEC-TEST-2", "QEC-TEST-4",
    }
    matched = selected_qec_cases(
        cases, exact_findings=(
            "Pumpenfunktion beanstandet",
            "NTF: Kein Fehler nachweisbar",
        ), search="KEIN fehler",
    )
    assert {case.case_id for case in matched} == {
        "QEC-TEST-2", "QEC-TEST-4",
    }
    assert selected_qec_cases(cases, search="not-existing") == ()
    cases[0].qec_ssl_end_code = "SYNTH-CODE-555"
    assert selected_qec_cases(cases, search="code-555") == (cases[0],)
    assert len(selected_qec_cases(
        cases, exact_findings=(MISSING_END_FINDING,),
    )) == 1
    assert part_numbers(cases) == ("FAKE-PART-B", "FAKE-PART-A")


def test_qec_fins_scope_includes_missing_pump_swap_date_and_overlap_once():
    first = _case(1, "NTF Test", "FAKE-PART", swap=False)
    second = _case(2, "NTF Test", "FAKE-PART")
    evidence = qec_fin_evidence([first, second])
    assert len(evidence.case_links) == 2
    assert first.vin not in evidence.pump_swap_dates
    union = merge_fin_evidence(
        (first.vin, "W1TTEST0000009999"),
        {first.vin: (("CPC3", "SYNTH-A"),)},
        {}, evidence, only_qec=True,
    )
    assert union.fins == (first.vin, second.vin)
    assert union.qec_fin_count == 2
    assert union.overlap_fin_count == 1
    assert first.vin in union.faults
    assert "W1TTEST0000009999" not in union.fins


def test_end_finding_filter_never_weakens_first_pump_swap_anchor():
    before = _case(1, "Synthetischer Befund Alpha", "FAKE-PART")
    later = _case(1, "Synthetischer Befund Beta", "FAKE-PART")
    later.case_id = "QEC-LATER"
    later.qec_reference = "QEC-LATER"
    later.replacements[0].occurred_at = datetime(2026, 7, 10)
    later.diagnostics.append(DiagnosticEvent(
        vin=later.vin, ecu="CPC3", dtc_code="POST-FIRST-SWAP",
        occurred_at=datetime(2026, 6, 1),
        source_ref="raw:synth#post",
    ))
    global_dates = qec_fin_evidence([before, later]).pump_swap_dates
    selection = selected_qec_cases(
        [before, later], search="Befund Beta",
    )
    assert len(selection) == 1
    filtered = qec_fin_evidence(
        selection, global_pump_swap_dates=global_dates,
    )
    assert filtered.pump_swap_dates == global_dates
    assert ("CPC3", "POST-FIRST-SWAP") not in filtered.pre_swap_faults.get(
        later.vin, ()
    )


def test_source_donuts_count_overlapping_fins_once_each():
    a, b, c = (
        "W1TTEST0000000001",
        "W1TTEST0000000002",
        "W1TTEST0000000003",
    )
    qec_cases = [_case(1, "NTF Test", "FAKE-PART"),
                 _case(1, "Other Test", "FAKE-PART"),
                 _case(2, "NTF Test", "FAKE-PART-2")]
    stats = source_coverage(
        (a, b, c), qec_cases, part_number="FAKE-PART",
        tips_fins=(a, b, b),
        quicktest_fins=(a, c, c),
    )
    assert stats.total_fins == 3
    assert stats.part_number_fins == 1
    assert stats.qec_fins == 2
    assert stats.tips_fins == 2
    assert stats.quicktest_fins == 2
    assert stats.qec_case_count == 3
    assert sum((
        stats.part_number_fins, stats.qec_fins,
        stats.tips_fins, stats.quicktest_fins,
    )) > stats.total_fins  # overlapping source memberships, not a pie!
