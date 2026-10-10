"""Only synthetic cases and temporary DuckDB files: no customer sources."""
from __future__ import annotations

import csv
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import duckdb
import pytest

from ntf_insight.analysis.local_runner_report import (
    APPROVED_TOTAL_KEYS, approved_public_totals,
    build_runner_local_analysis, build_runner_local_report,
)
from ntf_insight.storage.duckdb_store import DuckDBStore
from ntf_insight.storage.readonly_case_store import ReadOnlyCaseStore
from ntf_insight.storage.quicktest_store import QuickTestStore
from ntf_insight.storage.source_knowledge_store import SourceKnowledgeStore
from test_hdbscan_clustering import sample


@pytest.fixture
def external_tmp_path():
    # Pytest's configured .pytest-tmp is INSIDE the repository. The real
    # runner correctly rejects this. Use OS-level temporary storage instead
    # of weakening the no-repository-output security invariant.
    with tempfile.TemporaryDirectory(prefix="ntf-runner-synthetic-") as root:
        yield Path(root)


def _database(external_tmp_path: Path) -> tuple[Path, list]:
    source = external_tmp_path / "fictional_synthetic.duckdb"
    cases = sample()
    cases[0].qec_ssl_end_finding = "SECRET_SYNTHETIC_SSL_TEXT_NEVER_LEAVE_LOCAL"
    DuckDBStore(source).save_cases(cases)
    return source, cases


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_read_only_store_cannot_write_or_initialize_database(external_tmp_path):
    source, cases = _database(external_tmp_path)
    before = _digest(source)
    store = ReadOnlyCaseStore(source)
    assert len(store.load_cases()) == len(cases)
    assert "case_snapshots" in store.tables()
    with store.connect() as con:
        with pytest.raises(duckdb.Error):
            con.execute("CREATE TABLE sensitive_temp (id INTEGER)")
        with pytest.raises(duckdb.Error):
            con.execute("DELETE FROM case_snapshots")
    assert _digest(source) == before


def test_opt_out_of_quicktest_and_autoexport_schema_init_in_readonly_mode(external_tmp_path):
    source, _ = _database(external_tmp_path)
    before = _digest(source)
    store = ReadOnlyCaseStore(source)
    assert "quicktest_reports" not in store.tables()
    assert "source_knowledge_rows" not in store.tables()
    qt = QuickTestStore(store, initialize=False)
    auto = SourceKnowledgeStore(store, initialize=False)
    assert qt.store is store and auto.store is store
    assert _digest(source) == before
    assert "quicktest_reports" not in store.tables()
    assert "source_knowledge_rows" not in store.tables()


def test_runner_json_contains_diagnostics_only_as_numbers_not_identifiers(external_tmp_path):
    _, cases = _database(external_tmp_path)
    report = build_runner_local_report(cases)
    numbers = report["summen"]
    assert numbers["qec_faelle"] == len(cases)
    assert numbers["ml_cluster"] == 2
    assert numbers["ml_clusterfaelle"] == 12
    assert numbers["repraesentanten_zur_pruefung"] == 2
    assert numbers["fachlich_bestaetigte_repraesentanten"] == 0
    assert report["szenario"]["hdbscan"] == "leaf"
    allowed = approved_public_totals(report)
    assert set(allowed) == set(APPROVED_TOTAL_KEYS)
    assert all(type(value) is int for value in allowed.values())
    assert len(report["cluster_nur_lokal"]) == 2
    encoded = json.dumps(report, ensure_ascii=False)
    assert "SECRET_SYNTHETIC_SSL_TEXT_NEVER_LEAVE_LOCAL" not in encoded
    assert "W1TTEST" not in encoded
    assert "CODE-A-ROOT" not in encoded
    assert "LAB-SYNTHETIC" not in encoded
    assert "raw:synthetic" not in encoded
    assert "case_id" not in encoded
    assert "representative_case_id" not in encoded
    assert "dtc_code" not in encoded


def test_local_run_only_writes_outside_repo_and_preserves_original_duckdb(external_tmp_path):
    from scripts.runner_local_analysis import run_local_analysis

    source, _ = _database(external_tmp_path)
    before = _digest(source)
    output = external_tmp_path / "local_private_reports"
    report = run_local_analysis(database=source, output_dir=output)
    assert _digest(source) == before
    folders = list(output.iterdir())
    assert len(folders) == 1
    files = {file.name: file for file in folders[0].iterdir()}
    assert set(files) == {
        "lokale_aggregatanalyse_NICHT_AUTOMATISCH_HOCHLADEN.json",
        "pilot_fachpruefung_FIN_SSL_NICHT_HOCHLADEN.csv",
    }
    assert json.loads(
        files["lokale_aggregatanalyse_NICHT_AUTOMATISCH_HOCHLADEN.json"]
        .read_text(encoding="utf-8")
    ) == report
    review_csv = files["pilot_fachpruefung_FIN_SSL_NICHT_HOCHLADEN.csv"]
    with review_csv.open(encoding="utf-8-sig", newline="") as stream:
        inspections = list(csv.DictReader(stream, delimiter=";"))
    assert len(inspections) == (
        report["summen"]["repraesentanten_zur_pruefung"]
        + report["summen"]["unabhaengige_pilotvergleiche_vorgeschlagen"]
    )
    expected_cases = {case.case_id: case for case in sample()}
    assert all(row["qec_case_id"] in expected_cases for row in inspections)
    assert all(
        row["fin"] == expected_cases[row["qec_case_id"]].vin
        for row in inspections
    )
    for group in {row["pilot_group"] for row in inspections}:
        rows = [row for row in inspections if row["pilot_group"] == group]
        reps = [row for row in rows if "Repräsentant" in row["pilot_role"]]
        assert len(reps) == 1
        assert 1 <= len(rows) <= 3
        assert len({row["fin"] for row in rows}) == len(rows)
        assert all(
            row["representative_qec_id"] == reps[0]["qec_case_id"]
            for row in rows
        )
        assert all(row["review_status"] == "pending" for row in rows)
    assert not list(output.rglob("*.zip"))


def test_script_stdout_defaults_to_static_marker_only(external_tmp_path):
    source, _ = _database(external_tmp_path)
    output = external_tmp_path / "analysis"
    original_hash = _digest(source)
    script = Path(__file__).resolve().parents[1] / "scripts" / "runner_local_analysis.py"
    process = subprocess.run(
        [sys.executable, str(script)],
        cwd=script.parents[1],
        env={
            **os.environ,
            "NTF_INSIGHT_RUNNER_DB": str(source),
            "NTF_INSIGHT_RUNNER_REPORT_DIR": str(output),
        },
        capture_output=True, text=True, timeout=100,
    )
    assert process.returncode == 0
    assert process.stdout.strip() == "NTF_LOKALE_ANALYSE_OK"
    assert not process.stderr
    assert _digest(source) == original_hash
    assert list(output.glob("NTF_Lauf_*/*.json"))


def test_explicitly_approved_stdout_is_only_whitelisted_ints(external_tmp_path):
    source, _ = _database(external_tmp_path)
    script = Path(__file__).resolve().parents[1] / "scripts" / "runner_local_analysis.py"
    process = subprocess.run(
        [sys.executable, str(script), "--freigabe-summen"],
        cwd=script.parents[1],
        env={
            **os.environ,
            "NTF_INSIGHT_RUNNER_DB": str(source),
            "NTF_INSIGHT_RUNNER_REPORT_DIR": str(external_tmp_path / "aggregate_output"),
        },
        capture_output=True, text=True, timeout=100,
    )
    assert process.returncode == 0
    lines = process.stdout.strip().splitlines()
    assert len(lines) == 2 and lines[0] == "NTF_LOKALE_ANALYSE_OK"
    assert lines[1].startswith("NTF_FREIGEGEBENE_SUMMEN_JSON=")
    approved = json.loads(lines[1].split("=", 1)[1])
    assert set(approved) == set(APPROVED_TOTAL_KEYS)
    assert all(type(value) is int for value in approved.values())
    assert "W1TTEST" not in process.stdout
    assert "CODE-" not in process.stdout
    assert "SECRET_" not in process.stdout
    assert str(source) not in process.stdout


def test_error_log_does_not_reveal_local_path_or_originals(external_tmp_path):
    script = Path(__file__).resolve().parents[1] / "scripts" / "runner_local_analysis.py"
    hidden = external_tmp_path / "SECRET_LOCAL_FIN_SOURCE_NAME.duckdb"
    process = subprocess.run(
        [sys.executable, str(script)],
        cwd=script.parents[1],
        env={
            **os.environ,
            "NTF_INSIGHT_RUNNER_DB": str(hidden),
            "NTF_INSIGHT_RUNNER_REPORT_DIR": str(external_tmp_path / "private"),
        },
        capture_output=True, text=True, timeout=100,
    )
    assert process.returncode == 2
    assert process.stdout == ""
    assert "NTF_LOKALE_ANALYSE_FEHLER" in process.stderr
    assert "SECRET_LOCAL_FIN_SOURCE_NAME" not in process.stderr
    assert str(external_tmp_path) not in process.stderr
    assert not (external_tmp_path / "private").exists()


def test_runner_refuses_to_write_reports_inside_git_checkout(external_tmp_path):
    from scripts.runner_local_analysis import run_local_analysis

    source, _ = _database(external_tmp_path)
    checkout = Path(__file__).resolve().parents[1]
    with pytest.raises(ValueError, match="außerhalb"):
        run_local_analysis(
            database=source, output_dir=checkout / "reports" / "runner",
        )


def test_local_analysis_pilot_plan_keeps_ids_out_of_aggregate_json():
    report, plan = build_runner_local_analysis(sample())
    assert plan.representative_count == report["summen"]["ml_cluster"]
    assert len(plan.inspections) == plan.representative_count + plan.independent_targets
    assert plan.independent_targets == report["summen"][
        "unabhaengige_pilotvergleiche_vorgeschlagen"
    ]
    encoded = json.dumps(report, ensure_ascii=False)
    for inspection in plan.inspections:
        assert inspection.case_id not in encoded
        assert inspection.representative_case_id not in encoded
    assert "W1TTEST" not in encoded


def test_private_local_review_is_not_exposed_with_approved_numeric_logs(external_tmp_path):
    source, _ = _database(external_tmp_path)
    output = external_tmp_path / "approved_logs"
    script = Path(__file__).resolve().parents[1] / "scripts" / "runner_local_analysis.py"
    process = subprocess.run(
        [sys.executable, str(script), "--freigabe-summen"],
        cwd=script.parents[1],
        env={
            **os.environ,
            "NTF_INSIGHT_RUNNER_DB": str(source),
            "NTF_INSIGHT_RUNNER_REPORT_DIR": str(output),
        },
        capture_output=True, text=True, timeout=100,
    )
    assert process.returncode == 0
    confidential = list(output.glob("NTF_Lauf_*/*FIN_SSL_NICHT_HOCHLADEN.csv"))
    assert len(confidential) == 1
    assert "qec_case_id" in confidential[0].read_text(encoding="utf-8-sig")
    assert "qec_case_id" not in process.stdout
    assert "fin" not in process.stdout.lower()
    assert "W1TTEST" not in process.stdout
    assert "CODE-" not in process.stdout
    assert not process.stderr


def test_separately_approved_method_comparison_is_aggregate_only(external_tmp_path):
    source, _ = _database(external_tmp_path)
    output = external_tmp_path / "methods_local"
    script = Path(__file__).resolve().parents[1] / "scripts" / "runner_local_analysis.py"
    process = subprocess.run(
        [sys.executable, str(script), "--methodenvergleich-freigeben"],
        cwd=script.parents[1],
        env={
            **os.environ,
            "NTF_INSIGHT_RUNNER_DB": str(source),
            "NTF_INSIGHT_RUNNER_REPORT_DIR": str(output),
        },
        capture_output=True, text=True, timeout=120,
    )
    assert process.returncode == 0, "CLI did not complete successfully"
    lines = process.stdout.splitlines()
    assert len(lines) == 2 and lines[0] == "NTF_LOKALE_ANALYSE_OK"
    assert lines[1].startswith("NTF_FREIGEGEBENER_METHODENVERGLEICH_JSON=")
    assert "NTF_FREIGEGEBENE_SUMMEN_JSON" not in process.stdout
    approved = json.loads(lines[1].split("=", 1)[1])
    assert approved["methode_leaf"]["cluster"] == 2
    assert set(approved) == {
        "methode_leaf", "methode_eom", "methode_complete_link_45",
        "methode_complete_link_65", "geeignete_faelle",
    }
    assert "W1TTEST" not in process.stdout
    assert "SECRET_SYNTHETIC_SSL" not in process.stdout
    assert "CODE-" not in process.stdout
    assert str(source) not in process.stdout
    assert not process.stderr
    stored = list(output.glob("NTF_Lauf_*/*.json"))
    assert len(stored) == 1
    report = json.loads(stored[0].read_text(encoding="utf-8"))
    assert report["methodenbewertung"]["methode_leaf"]["cluster"] == 2
    assert report["methodenbewertung"]["methode_complete_link_45"][
        "clusterfaelle"
    ] >= report["methodenbewertung"]["methode_complete_link_65"]["clusterfaelle"]


def test_runner_workflow_requires_main_and_per_run_authorisation():
    yaml_text = (
        Path(__file__).resolve().parents[1] / ".github" / "workflows"
        / "local-analysis.yml"
    ).read_text(encoding="utf-8")
    assert "workflow_dispatch:" in yaml_text
    assert "inputs.analyse_freigegeben == true" in yaml_text
    assert "methodenvergleich_freigeben:" in yaml_text
    assert "RELEASE_METHOD_TOTALS:" in yaml_text
    assert "inputs.methodenvergleich_freigeben" in yaml_text
    assert "--methodenvergleich-freigeben" in yaml_text
    assert "refs/heads/main" in yaml_text
    assert "ntf-insight-1" in yaml_text
    assert "ntf-insight-2" not in yaml_text
    assert "persist-credentials: false" in yaml_text
    assert "permissions:\n  contents: read" in yaml_text
    assert "uses: actions/upload-artifact" not in yaml_text
    assert "pull_request:" not in yaml_text
    assert "\n  push:" not in yaml_text
