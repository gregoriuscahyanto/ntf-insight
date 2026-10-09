"""Synthetic-only tests: confidential identifiers must never enter share ZIP."""
from __future__ import annotations

import csv
import io
import json
from dataclasses import replace
from datetime import date
from zipfile import ZipFile

import pytest

from ntf_insight.analysis.cluster_review_zip import (
    PACKAGE_FILES, write_cluster_review_zip,
)
from ntf_insight.analysis.diagnostic_evidence_audit import audit_diagnostic_evidence
from ntf_insight.analysis.diagnostic_gap_investigation import investigate_diagnostic_gaps
from ntf_insight.analysis.hdbscan_clustering import (
    cluster_hdbscan_cases, compare_hdbscan_methods,
)
from ntf_insight.analysis.mechanism_review import ConfirmedMechanism
from test_hdbscan_clustering import sample


def _csv(archive, name):
    text = archive.read(name).decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(text), delimiter=";"))


def test_zip_one_real_medoid_per_cluster_with_no_sensitive_source_fields(tmp_path):
    cases = sample()
    cases[0].qec_ssl_end_finding = "SECRET-CONFIDENTIAL-SSL-TEXT"
    audited = audit_diagnostic_evidence(cases)
    result = cluster_hdbscan_cases(cases, selection_method="leaf")
    rep = result.clusters[0].representative_case_id
    labels = (ConfirmedMechanism(
        case_id=rep, mechanism_code="PUMP_BEARING_BLOCKAGE",
        reviewer="SECRET-INTERNAL-REVIEWER",
        evidence_ref="SECRET-LAB-REPORT-987",
        confirmed_on=date(2026, 10, 9),
    ),)
    gaps = investigate_diagnostic_gaps(cases, audited)
    comparison = compare_hdbscan_methods(cases)
    export = write_cluster_review_zip(
        tmp_path / "paket.zip", cases, result, audited,
        confirmations=labels, gaps=gaps, comparison=comparison,
    )

    assert export.zip_path.exists()
    assert export.private_case_map.exists()
    assert export.private_dtc_map.exists()
    assert export.representative_count == len(result.clusters)
    assert export.case_count == len(cases)
    assert "W1TTEST" in export.private_case_map.read_text(encoding="utf-8-sig")
    assert "CODE-A-ROOT-A" in export.private_dtc_map.read_text(encoding="utf-8-sig")
    with ZipFile(export.zip_path) as archive:
        assert set(archive.namelist()) == set(PACKAGE_FILES)
        assert all(member.date_time[:3] == (1980, 1, 1) for member in archive.infolist())
        merged = "\n".join(
            archive.read(name).decode("utf-8-sig") for name in archive.namelist()
        )
        assert "W1TTEST" not in merged
        assert "CODE-A-ROOT-A" not in merged
        assert "SECRET-CONFIDENTIAL" not in merged
        assert "SECRET-INTERNAL-REVIEWER" not in merged
        assert "SECRET-LAB-REPORT-987" not in merged
        assert "raw:synthetic" not in merged
        assert "_NICHT_HOCHLADEN_" not in "\n".join(archive.namelist())
        assert "PUMP_BEARING_BLOCKAGE" in merged  # reviewed mechanism, not SSL
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["pseudonymisiert"]
        assert manifest["fin_oder_qec_ids"] is False
        assert manifest["faelle"] == len(cases)
        assert manifest["repraesentanten"] == len(result.clusters)
        reps = _csv(archive, "repraesentanten.csv")
        assert len(reps) == len(result.clusters)
        assert len({r["Repräsentanten-Fall"] for r in reps}) == len(reps)
        assert sum(int(r["Fachlich bestätigt"]) for r in reps) == 1
        members = _csv(archive, "cluster_mitglieder.csv")
        assert len(members) == result.clustered_count
        assert sum(int(r["Ist Repräsentant"]) for r in members) == len(reps)
        assert all(r["Fall"].startswith("F") for r in members)
        internal_pairs = _csv(archive, "interne_fallpaare.csv")
        assert len(internal_pairs) == sum(g.internal_pair_count for g in result.clusters)
        gap_rows = _csv(archive, "ausgeschlossene_faelle.csv")
        assert len(gap_rows) == audited.excluded_count
        assert len(_csv(archive, "methodenvergleich.csv")) == 2


def test_zip_from_filtered_scenario_keeps_raw_dtc_signatures_as_screened(tmp_path):
    cases = sample()
    audited = audit_diagnostic_evidence(cases)
    result = cluster_hdbscan_cases(cases, common_dtc_cutoff=0.35)
    export = write_cluster_review_zip(
        tmp_path / "filter.zip", cases, result, audited,
    )
    with ZipFile(export.zip_path) as archive:
        codes = _csv(archive, "diagnosemerkmale.csv")
        assert len(codes) >= len(result.eligible_case_ids)
        # DTCs used for engineering sensitivity testing are not treated
        # as permanently irrelevant. Both in-model and screened are visible.
        assert any(r["Merkmal im gewählten ML-Szenario"] == "0" for r in codes)
        assert any(r["Merkmal im gewählten ML-Szenario"] == "1" for r in codes)


def test_zip_rejects_mismatched_analysis_before_writing(tmp_path):
    cases = sample()
    result = cluster_hdbscan_cases(cases)
    audit = audit_diagnostic_evidence(cases)
    out = tmp_path / "bad.zip"
    with pytest.raises(ValueError, match="Fallbestand"):
        write_cluster_review_zip(
            out, cases, replace(result, case_count=result.case_count + 1), audit,
        )
    assert not out.exists()


def test_zip_never_overwrites_existing_private_mappings(tmp_path):
    cases = sample()
    result = cluster_hdbscan_cases(cases)
    audit = audit_diagnostic_evidence(cases)
    dest = tmp_path / "private.zip"
    export = write_cluster_review_zip(dest, cases, result, audit)
    before = export.zip_path.read_bytes()
    with pytest.raises(FileExistsError, match="existiert"):
        write_cluster_review_zip(dest, cases, result, audit)
    assert export.zip_path.read_bytes() == before


def test_zip_pseudonyms_are_not_original_order_identifiers(tmp_path, monkeypatch):
    cases = sample()
    result = cluster_hdbscan_cases(cases)
    audit = audit_diagnostic_evidence(cases)
    import ntf_insight.analysis.cluster_review_zip as module

    monkeypatch.setattr(module.secrets, "token_bytes", lambda n: b"x" * n)
    first = write_cluster_review_zip(tmp_path / "first.zip", cases, result, audit)
    second = write_cluster_review_zip(tmp_path / "second.zip", cases, result, audit)
    assert first.zip_path.read_bytes() == second.zip_path.read_bytes()
    assert first.private_case_map.read_bytes() == second.private_case_map.read_bytes()
