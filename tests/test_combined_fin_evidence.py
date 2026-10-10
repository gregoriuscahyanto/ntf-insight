"""Synthetic-only regression: one VIN-level cluster space uses BOTH inputs."""
from __future__ import annotations

from datetime import datetime

from ntf_insight.analysis.autoexport_fin_patterns import cluster_autoexport_fins
from ntf_insight.analysis.combined_fin_evidence import (
    merge_fin_evidence, qec_fin_evidence,
)
from ntf_insight.domain.events import DiagnosticEvent
from test_hdbscan_clustering import synthetic


def _qec(case_id: str, fin: str, *, swap: bool = True):
    case = synthetic(case_id, "COMMON", int(fin[-4:]), vin=fin, swap=swap)
    case.qec_reference = case_id
    return case


def test_combined_fin_population_deduplicates_overlap_and_uses_qec_dtcs():
    shared = "CPC3", "CODE-COMMON-ROOT-A"
    a, b, c, d, e = [
        f"W1TTEST000000{i:04d}" for i in range(1, 6)
    ]
    ca = _qec("QEC-A", a)
    cd = _qec("QEC-D", d)
    ce = _qec("QEC-E", e, swap=False)
    ca.diagnostics.append(DiagnosticEvent(
        vin=a, ecu="CPC3", dtc_code="AFTER-SWAP",
        occurred_at=datetime(2026, 6, 1),
        source_ref="raw:synthetic#csv:after",
        dtc_text="Later symptom - annotation only",
    ))
    evidence = qec_fin_evidence([ca, cd, ce])
    assert set(evidence.case_links) == {a, d, e}
    assert a in evidence.pump_swap_dates
    assert e not in evidence.pump_swap_dates
    assert shared in evidence.pre_swap_faults[a]
    assert shared in evidence.pre_swap_faults[d]
    assert e not in evidence.pre_swap_faults
    assert ("CPC3", "AFTER-SWAP") not in evidence.pre_swap_faults[a]

    combined = merge_fin_evidence(
        (a, b, c),
        {
            a: (("HU7", "AUTO-SHARED"),),
            b: (("HU7", "AUTO-SHARED"),),
            c: (("HU7", "OTHER"),),
        },
        {("HU7", "AUTO-SHARED"): "AutoExport label"},
        evidence,
    )
    assert combined.fins == (a, b, c, d, e)
    assert combined.autoexport_fin_count == 3
    assert combined.qec_fin_count == 3
    assert combined.overlap_fin_count == 1
    assert combined.qec_only_fin_count == 2
    assert shared in combined.faults[a] and ("HU7", "AUTO-SHARED") in combined.faults[a]
    assert combined.sources[a] == "AutoExport + QEC"
    assert combined.sources[d] == "QEC / QuickTest"
    assert combined.sources[e] == "Keine geeigneten DTCs"
    assert ("CPC3", "AFTER-SWAP") not in combined.faults[a]
    result = cluster_autoexport_fins(
        combined.fins, combined.faults, combined.labels,
        combined.case_links,
    )
    assert result.total_fins == 5
    assert result.dtc_fins == 4
    assert result.qec_links[a] == ("QEC-A",)
    assert result.qec_links[d] == ("QEC-D",)
    assert len(result.no_dtc_fins) == 1


def test_strict_pump_mode_excludes_unanchored_and_keeps_qec_only_fin():
    a, b, c = [f"W1TTEST000000{i:04d}" for i in range(1, 4)]
    a_case = _qec("QEC-A", a)
    c_case = _qec("QEC-C", c)
    evidence = qec_fin_evidence([a_case, c_case])
    assert c in evidence.pump_swap_dates
    strict = merge_fin_evidence(
        (a, b),
        {a: (("CPC3", "PRE-AUTO"),), b: (("CPC3", "UNANCHORED"),)},
        {}, evidence, only_pump_swap=True,
    )
    assert strict.fins == (a, c)
    assert strict.qec_only_fin_count == 1
    assert ("CPC3", "PRE-AUTO") in strict.faults[a]
    assert ("CPC3", "CODE-COMMON-ROOT-A") in strict.faults[c]
    assert b not in strict.faults


def test_two_qec_cases_one_fin_count_once_and_no_later_repair_features():
    fin = "W1TTEST0000000001"
    before = _qec("QEC-ONE", fin)
    later = _qec("QEC-TWO", fin)
    later.replacements[0].occurred_at = datetime(2026, 7, 10)
    later.diagnostics.append(DiagnosticEvent(
        vin=fin, ecu="CPC3", dtc_code="AFTER-EARLIEST-REPAIR",
        occurred_at=datetime(2026, 6, 1),
        source_ref="raw:synthetic#csv:late",
    ))
    evidence = qec_fin_evidence([before, later])
    assert evidence.case_links[fin] == ("QEC-ONE", "QEC-TWO")
    assert evidence.pump_swap_dates[fin] == "2026-05-10"
    assert ("CPC3", "AFTER-EARLIEST-REPAIR") not in evidence.pre_swap_faults[fin]
    merged = merge_fin_evidence(
        (fin,), {}, {}, evidence,
    )
    assert merged.fins == (fin,)
    assert len(merged.case_links[fin]) == 2
    assert merged.qec_fin_count == 1
    assert merged.overlap_fin_count == 1


def test_qec_outcomes_and_supplier_findings_never_become_dtc_features():
    fin = "W1TTEST0000000001"
    case = _qec("QEC-A", fin)
    before = qec_fin_evidence([case])
    case.qec_ssl_end_finding = "Synthetic supplier concluded NTF"
    case.qec_status = "Synthetic closed"
    after = qec_fin_evidence([case])
    assert after.pre_swap_faults == before.pre_swap_faults
    assert after.pump_swap_dates == before.pump_swap_dates
