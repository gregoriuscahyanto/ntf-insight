"""Only synthetic locally stored DuckDB cases; no original FIN/QEC data."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from ntf_insight.analysis.local_runner_report import APPROVED_TOTAL_KEYS
from ntf_insight.storage.duckdb_store import DuckDBStore
from scripts.cluster_ergebnisse_fuer_chatgpt import calculate_shareable_results
from test_hdbscan_clustering import sample


_SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts" / "cluster_ergebnisse_fuer_chatgpt.py"
)


@pytest.fixture
def external_synthetic_db():
    # The repository test directory is inside the checkout, which the
    # command rightly rejects for a potentially sensitive database.
    with TemporaryDirectory(prefix="ntf-private-chat-status-synthetic-") as directory:
        db = Path(directory) / "SECRET_LOCAL_ORIGINAL_FILENAME.duckdb"
        cases = sample()
        cases[0].qec_ssl_end_finding = (
            "=SECRET_SSL_FORMULA_FIN_W1TTEST_NEVER_SHARE"
        )
        DuckDBStore(db).save_cases(cases)
        yield db


def _run(db: Path, *additional: str):
    return subprocess.run(
        [sys.executable, str(_SCRIPT), "--datenbank", str(db), *additional],
        cwd=_SCRIPT.parents[1],
        env={**os.environ, "NTF_INSIGHT_RUNNER_DB": str(db)},
        text=True, capture_output=True, timeout=120,
    )


def _read(stdout: str):
    lines = stdout.splitlines()
    assert lines[-1] == "NTF_CLUSTER_STATUS_OK_NUR_LOKAL_READ_ONLY"
    result = {}
    for line in lines[:-1]:
        key, separator, value = line.partition("=")
        assert separator and key.startswith("NTF_")
        assert key not in result
        result[key] = json.loads(value)
    return result


def test_default_report_is_approved_counts_only_and_read_only(external_synthetic_db):
    db = external_synthetic_db
    before = hashlib.sha256(db.read_bytes()).hexdigest()
    completed = _run(db)
    assert completed.returncode == 0
    assert completed.stderr == ""
    result = _read(completed.stdout)
    assert set(result) == {
        "NTF_FREIGEGEBENE_SUMMEN_JSON",
        "NTF_FREIGEGEBENER_METHODENVERGLEICH_JSON",
    }
    sums = result["NTF_FREIGEGEBENE_SUMMEN_JSON"]
    methods = result["NTF_FREIGEGEBENER_METHODENVERGLEICH_JSON"]
    assert set(sums) == set(APPROVED_TOTAL_KEYS)
    assert sums["qec_faelle"] == 15
    assert sums["qec_mit_vor_tausch_diagnose"] == 13
    assert sums["qec_ohne_vor_tausch_diagnose"] == 2
    assert sums["ml_cluster"] == 2
    assert sums["ml_clusterfaelle"] == 12
    assert methods["methode_leaf"]["cluster"] == 2
    assert methods["geeignete_faelle"] == 13
    assert not any("k1" in key.casefold() for key in result)
    for value in sums.values():
        assert type(value) is int and value >= 0
    assert hashlib.sha256(db.read_bytes()).hexdigest() == before
    assert not list(db.parent.glob("*chat*"))
    for secret in (
        "A0", "B0", "OUTLIER", "W1TTEST", "CODE-", "CPC3",
        "SECRET", "FIN_", "qec_case_id", "SSL", "source_ref",
        str(db), str(db.parent), "case_snapshots",
    ):
        assert secret not in completed.stdout


def test_opt_in_k1_is_numbers_and_booleans_only_with_no_identity(external_synthetic_db):
    db = external_synthetic_db
    completed = _run(db, "--k1-zahlen-nach-freigabe")
    assert completed.returncode == 0 and not completed.stderr
    result = _read(completed.stdout)
    assert set(result) == {
        "NTF_FREIGEGEBENE_SUMMEN_JSON",
        "NTF_FREIGEGEBENER_METHODENVERGLEICH_JSON",
        "NTF_K1_NUMERISCHE_DETAILS_NACH_FREIGABE_JSON",
    }
    k1 = result["NTF_K1_NUMERISCHE_DETAILS_NACH_FREIGABE_JSON"]
    assert k1["k1_vorhanden"]
    assert k1["qec_faelle"] >= 3
    assert k1["unterschiedliche_fin"] >= 1
    assert 0 <= k1["davon_gemeinsame_cpc3_dtc"] <= k1[
        "gemeinsame_ecu_dtc_anzahl"
    ]
    assert k1["ueberlappende_leaf_cluster_anzahl"] >= 0
    assert k1["min_paar_cosinus_promille"] >= 450
    assert all(type(x) in (bool, int) for x in k1.values())
    for secret in (
        "A0", "B0", "W1TTEST", "CODE-", "CPC3", "SECRET",
        "qec_case_id", "SSL", str(db), str(db.parent),
    ):
        assert secret not in completed.stdout


def test_direct_api_never_returns_raw_identifiers(external_synthetic_db):
    sums, methods, k1 = calculate_shareable_results(external_synthetic_db)
    assert type(sums["ml_cluster"]) is int
    assert methods["methode_complete_link_45"]["clusterfaelle"] >= 0
    assert k1 is None
    _, _, k1 = calculate_shareable_results(
        external_synthetic_db, approve_k1=True,
    )
    assert k1 is not None
    encoded = json.dumps(k1)
    assert "W1TTEST" not in encoded
    assert "CODE-" not in encoded


def test_failure_hides_original_database_path_and_does_not_create_database(
    external_synthetic_db,
):
    missing = external_synthetic_db.parent / "SECRET_MISSING_FIN_123.duckdb"
    completed = _run(missing)
    assert completed.returncode == 2
    assert completed.stdout == ""
    assert "NTF_CLUSTER_STATUS_FEHLER" in completed.stderr
    assert "SECRET_MISSING_FIN_123" not in completed.stderr
    assert str(missing.parent) not in completed.stderr
    assert not missing.exists()


def test_refuse_database_inside_git_checkout(tmp_path):
    repo = _SCRIPT.parents[1]
    # A fake file suffices: rejection must occur before any DB connection.
    db = repo / "SECRET_TEMPORARY_INTERNAL_CHAT_TEST.duckdb"
    assert not db.exists()
    # Even when it does not exist, the error message stays private.
    result = _run(db)
    assert result.returncode == 2
    assert "NTF_CLUSTER_STATUS_FEHLER" in result.stderr
    assert str(repo) not in result.stderr
    assert not db.exists()
