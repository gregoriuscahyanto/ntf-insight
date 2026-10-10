"""Synthetic-only strict group links and confidential medoid review files."""
from __future__ import annotations

import csv
from dataclasses import replace
from io import StringIO

import pytest

from ntf_insight.analysis.cluster_core_review import (
    link_core_review_groups, write_core_review_template,
)
from ntf_insight.analysis.cluster_workspace_engine import (
    ClusterParameters, calculate_clusters,
)
from ntf_insight.analysis.mechanism_review import read_confirmed_mechanisms
from test_hdbscan_clustering import sample


def runs():
    cases = sample()
    leaf = calculate_clusters(cases, ClusterParameters(method="leaf"))
    strict = calculate_clusters(cases, ClusterParameters(
        method="complete_cosine", minimum_similarity=0.45,
    ))
    return cases, leaf, strict


def test_core_groups_link_by_real_case_overlaps_not_arbitrary_cluster_numbers():
    _, leaf, strict = runs()
    linked = link_core_review_groups(leaf, strict)
    assert len(linked) == len(strict.groups)
    active_by_case = {
        cid: g.cluster_id for g in leaf.groups for cid in g.case_ids
    }
    for row in linked:
        assert row.label == f"K{row.core.cluster_id}"
        overlaps = [
            active_by_case[cid] for cid in row.core.case_ids
            if cid in active_by_case
        ]
        assert set(overlaps) == set(row.active_group_ids)
        assert row.dominant_overlap == max(
            (overlaps.count(gid) for gid in row.active_group_ids),
            default=0,
        )
        assert row.fully_contained == (
            len(set(overlaps)) == 1
            and len(overlaps) == row.core.case_count
        )
        assert row.cross_vehicle == (row.core.vehicle_count >= 2)
    reversed_result = calculate_clusters(
        list(reversed(sample())),
        ClusterParameters(method="complete_cosine", minimum_similarity=0.45),
    )
    assert strict.groups == reversed_result.groups
    assert link_core_review_groups(leaf, reversed_result) == linked


def test_linking_detects_partial_overlap_not_false_matching_group_ids():
    _, leaf, strict = runs()
    if not strict.groups:
        pytest.skip("Synthetic test data yielded no strict groups.")
    empty_assignment = replace(leaf, groups=())
    links = link_core_review_groups(empty_assignment, strict)
    assert links
    assert all(link.active_group_ids == () for link in links)
    assert all(not link.fully_contained for link in links)
    assert all("Kein Fall" in link.note for link in links)


def test_refuse_different_dtc_cohort_distance_or_method():
    _, leaf, strict = runs()
    with pytest.raises(ValueError, match="Diagnosebasis"):
        link_core_review_groups(
            leaf, replace(strict, eligible_case_ids=()),
        )
    with pytest.raises(ValueError, match="Diagnosebasis"):
        link_core_review_groups(
            leaf, replace(strict, original_distances=()),
        )
    with pytest.raises(ValueError, match="Complete-Link"):
        link_core_review_groups(leaf, leaf)


def test_core_review_csv_contains_real_medoid_and_up_to_two_different_fins():
    cases, _, strict = runs()
    out = StringIO()
    write_core_review_template(out, cases, strict)
    out.seek(0)
    rows = list(csv.DictReader(out, delimiter=";"))
    assert rows
    by_case = {case.case_id: case for case in cases}
    for group in strict.groups:
        group_rows = [
            row for row in rows if row["pilot_group"] == f"K{group.cluster_id}"
        ]
        assert 1 <= len(group_rows) <= 3
        assert group_rows[0]["qec_case_id"] == group.representative_case_id
        assert "Repräsentant" in group_rows[0]["pilot_role"]
        assert all(
            row["representative_qec_id"] == group.representative_case_id
            for row in group_rows
        )
        assert len({row["fin"] for row in group_rows}) == len(group_rows)
        assert all(row["qec_case_id"] in group.case_ids for row in group_rows)
    assert all(row["fin"] == by_case[row["qec_case_id"]].vin for row in rows)
    assert all(row["review_status"] == "pending" for row in rows)
    assert all(not row["mechanism_code"] for row in rows)
    assert all(not row["reviewer"] for row in rows)
    assert all(not row["evidence_ref"] for row in rows)
    assert all(not row["confirmed_on"] for row in rows)
    out.seek(0)
    assert read_confirmed_mechanisms(out, cases) == ()


def test_review_escapes_untrusted_ssl_excel_formula_locally():
    cases = sample()
    cases[0].qec_ssl_end_finding = "=HYPERLINK(\"https://invalid.test\",\"Click\")"
    strict = calculate_clusters(
        cases, ClusterParameters(method="complete_cosine"),
    )
    out = StringIO()
    write_core_review_template(out, cases, strict)
    out.seek(0)
    rows = list(csv.DictReader(out, delimiter=";"))
    for row in rows:
        if row["qec_case_id"] == cases[0].case_id:
            assert row["qec_ssl_end_finding"].startswith("'=")


def test_strict_review_excludes_multiple_qecs_of_same_fin_from_independence():
    cases = sample()
    cases[1].vehicle = cases[1].vehicle.model_copy(
        update={"vin": cases[0].vin},
    )
    strict = calculate_clusters(
        cases, ClusterParameters(method="complete_cosine"),
    )
    out = StringIO()
    write_core_review_template(out, cases, strict)
    out.seek(0)
    rows = list(csv.DictReader(out, delimiter=";"))
    for group in strict.groups:
        group_rows = [
            row for row in rows if row["pilot_group"] == f"K{group.cluster_id}"
        ]
        assert len(group_rows) <= group.vehicle_count
        assert len({row["fin"] for row in group_rows}) == len(group_rows)
