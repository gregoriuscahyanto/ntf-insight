"""No real FINs: scalable, exact-key AutoExport pattern grouping regression."""
from __future__ import annotations

from ntf_insight.analysis.autoexport_fin_patterns import (
    MIN_FIN_SIMILARITY, cluster_autoexport_fins,
)
from ntf_insight.storage.duckdb_store import DuckDBStore
from ntf_insight.storage.source_knowledge_store import SourceKnowledgeStore


def _synthetic_population():
    group_a = [f"W1TTEST000000{i:04d}" for i in range(10)]
    group_b = [f"W1TTEST000001{i:04d}" for i in range(10)]
    no_dtc = ["W1TTEST0000090000", "W1TTEST0000090001"]
    noise = "W1TTEST0000090002"
    codes = {}
    for group, fins in (("A", group_a), ("B", group_b)):
        for i, fin in enumerate(fins):
            codes[fin] = [
                ("CPC3", f"SYNT-{group}"),
                ("HU7", f"SYNT-{group}-REPEATED"),
                ("CPC3", f"SYNT-{group}"),  # duplicate DTC same FIN
                ("HU7", f"FIN-UNIQUE-{group}-{i}"),
            ]
    codes[noise] = [("CPC3", "ONLY-THIS-FIN")]
    return group_a + group_b + no_dtc + [noise], codes, group_a, group_b, noise


def test_all_imported_fins_eligible_only_with_repeated_dtc_features():
    fins, codes, first, second, noise = _synthetic_population()
    result = cluster_autoexport_fins(
        fins, codes, {("CPC3", "SYNT-A"): "Synthetic A label"},
        {first[0]: ("QEC-TEST-A",), second[0]: ("QEC-TEST-B",)},
    )
    assert result.total_fins == 23
    assert result.dtc_fins == 21
    assert result.no_dtc_fins == (
        "W1TTEST0000090000", "W1TTEST0000090001",
    )
    assert result.unassigned_fins == (noise,)
    assert len(result.groups) == 2
    assert result.assigned_fins == 20
    assert result.feature_count == 4
    assert all(g.fin_count == 10 for g in result.groups)
    assert {frozenset(fin for fin, _ in g.members) for g in result.groups} == {
        frozenset(first), frozenset(second),
    }
    assert sum(g.qec_fin_count for g in result.groups) == 2
    assert any(
        (ecu, dtc, n, text) == ("CPC3", "SYNT-A", 10, "Synthetic A label")
        for g in result.groups for ecu, dtc, n, text in g.common_faults
    )
    assert all(g.median_similarity >= MIN_FIN_SIMILARITY for g in result.groups)
    assert (
        result.assigned_fins + len(result.no_dtc_fins)
        + len(result.unassigned_fins)
    ) == result.total_fins
    # Repeated raw DTCs and changing input order cannot manufacture vehicles.
    duplicate = cluster_autoexport_fins(
        list(reversed(fins)), {fin: list(reversed(events)) for fin, events in codes.items()},
        {("CPC3", "SYNT-A"): "Synthetic A label"},
        {first[0]: ("QEC-TEST-A",), second[0]: ("QEC-TEST-B",)},
    )
    assert duplicate == result


def test_only_shared_codes_do_not_imply_any_confirmed_defect():
    a, b, c = "W1TTEST0000000001", "W1TTEST0000000002", "W1TTEST0000000003"
    result = cluster_autoexport_fins(
        (a, b, c), {a: [("CPC3", "UNIQUE-A")],
                    b: [("CPC3", "UNIQUE-B")],
                    c: [("CPC3", "UNIQUE-C")]},
    )
    assert result.total_fins == 3
    assert result.dtc_fins == 3
    assert result.groups == ()
    assert len(result.unassigned_fins) == 3


def test_thousands_of_fins_without_pairwise_quadratic_distance_matrix():
    """3k FINs with just two repeated patterns must remain practical."""
    fins = [f"W1TTEST000{i:08d}" for i in range(3000)]
    faults = {
        fin: [("CPC3", "TEST-GROUP-A" if i < 1500 else "TEST-GROUP-B")]
        for i, fin in enumerate(fins)
    }
    result = cluster_autoexport_fins(fins, faults)
    assert result.total_fins == 3000
    assert result.dtc_fins == 3000
    assert result.assigned_fins == 3000
    assert len(result.groups) == 2
    assert result.feature_count == 2
    assert result.initial_group_count == 2


def test_store_yields_vehicle_codes_deduplicated_across_original_rows(tmp_path):
    store = SourceKnowledgeStore(DuckDBStore(tmp_path / "fin-patterns.duckdb"))
    f1, f2, f3 = (
        "W1TTEST0000000001", "W1TTEST0000000002", "W1TTEST0000000003"
    )
    store.save_records("a" * 64, "autoexport_rows", [
        {"category": "autoexport_dtc", "fin": f1, "data": {
            "EcuNm": "CPC3", "EcuFaultNm": "U123456",
            "EcuFaultTxt": "Synthetic control unit communication"}},
        {"category": "autoexport_dtc", "fin": f1, "data": {
            "EcuNm": " cpc3 ", "EcuFaultNm": "u123456",
            "EcuFaultTxt": None}},
        {"category": "autoexport_dtc", "fin": f2, "data": {
            "EcuNm": "CPC3", "EcuFaultNm": "U123456",
            "EcuFaultTxt": "Synthetic control unit communication"}},
        {"category": "autoexport_repair", "fin": f3, "data": {
            "RepairTypeNmGerman": "Synthetic workshop action"}},
        {"category": "autoexport_dtc", "fin": f2, "data": {
            "EcuNm": "CPC3", "EcuFaultNm": None}},
    ])
    all_fins, signatures, labels = store.autoexport_fin_dtc_signatures()
    assert all_fins == (f1, f2, f3)
    assert signatures == {
        f1: (("CPC3", "U123456"),),
        f2: (("CPC3", "U123456"),),
    }
    assert labels[("CPC3", "U123456")] == (
        "Synthetic control unit communication"
    )
    assert f3 not in signatures


def test_pump_date_scope_includes_only_confirmed_fins_and_earlier_dtc_days(tmp_path):
    """No generic RepairDt or same-day DTC is evidence of pre-pump diagnostics."""
    store = SourceKnowledgeStore(DuckDBStore(tmp_path / "anchored-fin.duckdb"))
    a, b, c = (
        "W1TTEST0000000001", "W1TTEST0000000002", "W1TTEST0000000003",
    )
    rows = []
    for fin, dtc, day in (
        (a, "BEFORE", "2026-02-01"),
        (a, "SAME-DAY", "2026-05-10"),
        (a, "AFTER", "2026-05-11"),
        (a, "UNDATED", None),
        (b, "AFTER", "2026-06-01"),
        (c, "BEFORE", "2026-02-01"),
    ):
        rows.append({
            "category": "autoexport_dtc", "fin": fin,
            "data": {
                "EcuNm": "CPC3", "EcuFaultNm": dtc,
                "DiagStartDt": day, "EcuFaultTxt": f"Text-{dtc}",
            },
        })
    rows.append({
        "category": "autoexport_repair", "fin": c,
        "data": {
            "RepairDt": "2026-04-01", "RepairTypeNmGerman": "Workshop repair",
        },
    })
    store.save_records("a" * 64, "autoexport_rows", rows)
    all_fins, all_keys, _ = store.autoexport_fin_dtc_signatures()
    assert all_fins == (a, b, c)
    assert len(all_keys[a]) == 4

    anchored_fins, codes, labels = store.autoexport_fin_dtc_signatures(
        pump_swap_dates={a: "2026-05-10", b: "2026-05-10"},
    )
    assert anchored_fins == (a, b)
    assert codes == {a: (("CPC3", "BEFORE"),)}
    assert labels == {("CPC3", "BEFORE"): "Text-BEFORE"}
    assert c not in codes
    # A pump date without any pre-swap DTC remains in the scoped FIN count.
    result = cluster_autoexport_fins(anchored_fins, codes)
    assert result.total_fins == 2
    assert result.dtc_fins == 1
    assert result.no_dtc_fins == (b,)
    assert result.unassigned_fins == (a,)
    assert result.groups == ()


def test_combined_mode_uses_pre_swap_autoexport_only_for_qec_anchored_fin(tmp_path):
    """A VIN with a pump swap must not leak post-swap AutoExport diagnoses."""
    source = SourceKnowledgeStore(DuckDBStore(tmp_path / "all-fins-with-qec.db"))
    a, b, c = [
        f"W1TTEST000000{i:04d}" for i in (1, 2, 3)
    ]
    rows = []
    for fin, fault, day in (
        (a, "EARLY", "2026-04-10"),
        (a, "AFTER", "2026-05-11"),
        (a, "SAME-DAY", "2026-05-10"),
        (a, "UNRECORDED", None),
        (b, "AFTER", "2026-05-11"),
        (c, "UNRECORDED", None),
    ):
        rows.append({
            "category": "autoexport_dtc", "fin": fin,
            "data": {
                "EcuNm": "CPC3", "EcuFaultNm": fault,
                "DiagStartDt": day,
            },
        })
    source.save_records("a" * 64, "autoexport_rows", rows)
    fins, codes, _ = source.autoexport_fin_dtc_signatures(
        pump_swap_dates={a: "2026-05-10"},
        include_all_fins=True,
    )
    assert fins == (a, b, c)
    assert codes[a] == (("CPC3", "EARLY"),)
    assert codes[b] == (("CPC3", "AFTER"),)
    assert codes[c] == (("CPC3", "UNRECORDED"),)
    # In the unrestricted case even the known swap FIN has its full DTCs.
    _, unrestricted, _ = source.autoexport_fin_dtc_signatures()
    assert len(unrestricted[a]) == 4
