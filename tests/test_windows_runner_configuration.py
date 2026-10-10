"""Synthetic Windows integration test for local runner configuration.

The self-hosted production runner is NEVER used by this test.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from ntf_insight.storage.duckdb_store import DuckDBStore
from test_hdbscan_clustering import sample


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell only")
def test_runner1_setup_preserves_existing_environment_and_never_starts_analysis():
    repo = Path(__file__).resolve().parents[1]
    script = repo / "scripts" / "konfiguriere_ntf_runner.ps1"
    assert script.exists()
    with tempfile.TemporaryDirectory(prefix="ntf-test-runner-") as folder:
        root = Path(folder)
        fake_runner = root / "isolated-runner1"
        fake_runner.mkdir()
        (fake_runner / ".runner").write_text(
            json.dumps({"agentName": "vehicle-sim-windows-laptop"}),
            encoding="utf-8",
        )
        (fake_runner / "run.cmd").write_text("@echo off\n", encoding="ascii")
        (fake_runner / ".env").write_text(
            "UNRELATED_CONFIG=SAFE\nNTF_INSIGHT_RUNNER_DB=OLD\n",
            encoding="utf-8",
        )
        database = root / "synthetic.duckdb"
        DuckDBStore(database).save_cases(sample())
        output = root / "private-reports"
        command = [
            "powershell.exe", "-NoProfile", "-NonInteractive",
            "-ExecutionPolicy", "Bypass", "-File", str(script),
            "-RunnerRoot", str(fake_runner),
            "-PythonPath", sys.executable,
            "-DatabasePath", str(database),
            "-OutputDirectory", str(output),
        ]
        before = (fake_runner / ".env").read_bytes()
        check = subprocess.run(
            [*command, "-NurPruefen"], capture_output=True, text=True,
            timeout=45, env=os.environ.copy(),
        )
        assert check.returncode == 0, check.stderr
        assert "NTF_RUNNER_TEST_OK" in check.stdout
        assert (fake_runner / ".env").read_bytes() == before
        assert not output.exists()

        configured = subprocess.run(
            command, capture_output=True, text=True,
            timeout=45, env=os.environ.copy(),
        )
        assert configured.returncode == 0, configured.stderr
        assert "NTF_RUNNER_KONFIGURIERT_LOKAL" in configured.stdout
        assert "GH_ANALYSE" not in configured.stdout
        env_lines = (fake_runner / ".env").read_text(
            encoding="utf-8",
        ).splitlines()
        assert "UNRELATED_CONFIG=SAFE" in env_lines
        for key in (
            "NTF_INSIGHT_RUNNER_PYTHON",
            "NTF_INSIGHT_RUNNER_DB",
            "NTF_INSIGHT_RUNNER_REPORT_DIR",
        ):
            assert sum(line.startswith(key + "=") for line in env_lines) == 1
        assert len(list(fake_runner.glob(".env.ntf-backup-*"))) == 1
        assert output.is_dir()

        # A second setup is idempotent, never duplicates the three keys.
        again = subprocess.run(
            command, capture_output=True, text=True,
            timeout=45, env=os.environ.copy(),
        )
        assert again.returncode == 0, again.stderr
        final_lines = (fake_runner / ".env").read_text(
            encoding="utf-8",
        ).splitlines()
        assert final_lines == env_lines


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell only")
def test_runner_configuration_rejects_other_runner_identity():
    repo = Path(__file__).resolve().parents[1]
    script = repo / "scripts" / "konfiguriere_ntf_runner.ps1"
    with tempfile.TemporaryDirectory(prefix="ntf-test-runner2-") as folder:
        root = Path(folder)
        fake_runner = root / "runner2"
        fake_runner.mkdir()
        (fake_runner / ".runner").write_text(
            json.dumps({"agentName": "vehicle-sim-windows-laptop-2"}),
            encoding="utf-8",
        )
        (fake_runner / "run.cmd").write_text("@echo off\n", encoding="ascii")
        db = root / "fake.duckdb"
        DuckDBStore(db).save_cases(sample())
        proc = subprocess.run([
            "powershell.exe", "-NoProfile", "-NonInteractive",
            "-ExecutionPolicy", "Bypass", "-File", str(script),
            "-RunnerRoot", str(fake_runner),
            "-PythonPath", sys.executable,
            "-DatabasePath", str(db),
            "-OutputDirectory", str(root / "output"),
        ], capture_output=True, text=True, timeout=45)
        assert proc.returncode != 0
        assert not (fake_runner / ".env").exists()


def test_script_guards_real_data_and_never_auto_dispatches():
    script = (
        Path(__file__).resolve().parents[1]
        / "scripts" / "konfiguriere_ntf_runner.ps1"
    ).read_text(encoding="utf-8")
    assert "NTF_INSIGHT_RUNNER_DB" in script
    assert "NTF_INSIGHT_RUNNER_REPORT_DIR" in script
    assert "NTF_INSIGHT_RUNNER_PYTHON" in script
    assert "vehicle-sim-windows-laptop-2" not in script
    assert "if ($AnalyseStarten)" in script
    assert "workflow run local-analysis.yml" in script
    assert "analyse_freigegeben=true" in script
    assert "summen_in_actions_log_freigeben=$release" in script
    assert "NTF_RUNNER_KONFIGURIERT_LOKAL" in script
