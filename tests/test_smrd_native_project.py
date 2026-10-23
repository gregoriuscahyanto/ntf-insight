"""Isolated native project selection tests; no vendor DLLs or ECU files."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import ntf_insight.smrd.native_export as native_export
import ntf_insight.smrd.runtime_config as runtime_config


def _setup_preflight(monkeypatch, runtime: Path) -> None:
    monkeypatch.setattr(
        native_export, "resolve_runtime_dir",
        lambda runtime_dir, library: (runtime, runtime / "mvci" / "bin"),
    )
    monkeypatch.setattr(
        native_export, "diagnose_native_symbols",
        lambda path: {"native_api_ready": True, "missing_required_exports": []},
    )
    monkeypatch.setattr(
        runtime_config, "diagnose_native_runtime",
        lambda path: {
            "ready_for_native_attempt": True, "errors": [],
            "missing": [], "mismatches": [],
        },
    )


def test_project_test_calls_only_project_mode_without_db_or_json(tmp_path, monkeypatch):
    smrd = tmp_path / "Other_ECU.smr-d"
    smrd.write_bytes(b"synthetic header not decoded")
    _setup_preflight(monkeypatch, tmp_path)
    calls = []

    def fake_script(*args, **kwargs):
        calls.append(kwargs)
        return subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout="SOFTING_DTS_PROJECT_OPEN_OK project_type=Mock db_type=Mock\n",
            stderr="",
        )

    monkeypatch.setattr(native_export, "_run_script", fake_script)
    result = native_export.native_project_test(smrd, data_dir=tmp_path)
    assert result.startswith("SOFTING_DTS_PROJECT_OPEN_OK")
    assert len(calls) == 1
    assert calls[0]["source"] == smrd
    assert calls[0]["output"] is None
    assert calls[0]["project_only"] is True
    assert calls[0]["probe_only"] is False
    assert not (tmp_path / "ntf-insight.duckdb").exists()
    assert not (tmp_path / "smrd" / "exporte").exists()


def test_project_test_rejects_nonzero_exit_and_never_persists(tmp_path, monkeypatch):
    smrd = tmp_path / "ECU.smr-d"
    smrd.write_bytes(b"synthetic test")
    _setup_preflight(monkeypatch, tmp_path)
    monkeypatch.setattr(
        native_export, "_run_script",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="Mock project failed",
        ),
    )
    with pytest.raises(native_export.NativeRuntimeError, match="Mock project failed"):
        native_export.native_project_test(smrd, data_dir=tmp_path)
    assert not (tmp_path / "ntf-insight.duckdb").exists()


def test_project_test_rejects_missing_success_marker(tmp_path, monkeypatch):
    smrd = tmp_path / "ECU.smr-d"
    smrd.write_bytes(b"synthetic test")
    _setup_preflight(monkeypatch, tmp_path)
    monkeypatch.setattr(
        native_export, "_run_script",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=[], returncode=0, stdout="Unexpected response", stderr="",
        ),
    )
    with pytest.raises(native_export.NativeRuntimeError, match="keine Datenbank"):
        native_export.native_project_test(smrd, data_dir=tmp_path)


def test_project_test_blocks_unready_runtime_before_any_native_call(
    tmp_path, monkeypatch,
):
    smrd = tmp_path / "ECU.smr-d"
    smrd.write_bytes(b"synthetic test")
    _setup_preflight(monkeypatch, tmp_path)
    monkeypatch.setattr(
        runtime_config, "diagnose_native_runtime",
        lambda path: {
            "ready_for_native_attempt": False,
            "errors": ["config bad"],
            "missing": [], "mismatches": [],
        },
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("Native process was executed without preflight")

    monkeypatch.setattr(native_export, "_run_script", forbidden)
    with pytest.raises(native_export.NativeRuntimeError, match="config bad"):
        native_export.native_project_test(smrd, data_dir=tmp_path)


def test_project_test_subprocess_flags_exclude_outputjson(tmp_path, monkeypatch):
    smrd = tmp_path / "ECU.smr-d"
    smrd.write_bytes(b"synthetic test")
    script = tmp_path / "test.ps1"
    script.write_text("# empty synthetic test")
    monkeypatch.setattr(native_export.sys, "platform", "win32")
    monkeypatch.setattr(native_export.shutil, "which", lambda cmd: "powershell.exe")
    captured = []

    def fake_run(args, **kwargs):
        captured.append(args)
        return subprocess.CompletedProcess(
            args=args, returncode=0, stdout="ok", stderr="",
        )

    monkeypatch.setattr(native_export.subprocess, "run", fake_run)
    result = native_export._run_script(
        script, source=smrd, runtime=tmp_path, output=None,
        timeout=10, probe_only=False, project_only=True,
    )
    assert result.returncode == 0
    assert captured[0][-3:] == ["-SmrdFile", str(smrd), "-ProjectOnly"]
    assert "-OutputJson" not in captured[0]


def test_script_does_not_enumerate_dtcs_in_project_only_branch():
    from importlib.resources import files

    script = files("ntf_insight.smrd").joinpath("softing_native_export.ps1").read_text(
        encoding="utf-8"
    )
    assert "[switch] $ProjectOnly" in script
    assert "if ($ProjectOnly) {" in script
    assert "SOFTING_DTS_PROJECT_OPEN_OK" in script
    assert 'if (-not $ProjectOnly) {' in script
