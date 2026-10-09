"""Synthetic end-to-end local CLI ZIP export; no production VINs in CI."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from zipfile import ZipFile

from ntf_insight.storage.duckdb_store import DuckDBStore
from test_hdbscan_clustering import sample


def test_one_command_export_reads_local_database_without_manual_csv(tmp_path):
    repo = Path(__file__).resolve().parents[1]
    database = tmp_path / "testcases.duckdb"
    destination = tmp_path / "share-package.zip"
    cases = sample()
    DuckDBStore(database).save_cases(cases)
    result = subprocess.run(
        [
            sys.executable, str(repo / "scripts" / "export_cluster_review_zip.py"),
            "--datenbank", str(database),
            "--ausgabe", str(destination),
            "--vergleich",
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=repo,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        timeout=120,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert "NICHT HOCHLADEN" in result.stdout
    with ZipFile(destination) as package:
        info = json.loads(package.read("manifest.json"))
        assert info["faelle"] == len(cases)
        assert info["cluster"] > 0
        assert b"W1TTEST" not in package.read("repraesentanten.csv")
        assert package.read("methodenvergleich.csv")
    assert list(tmp_path.glob("*_NICHT_HOCHLADEN_FALLZUORDNUNG.csv"))
    assert list(tmp_path.glob("*_NICHT_HOCHLADEN_DTC_ZUORDNUNG.csv"))
