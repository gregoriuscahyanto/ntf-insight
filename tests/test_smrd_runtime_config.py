"""Purely synthetic runtime configuration tests; no vendor binaries involved."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from ntf_insight.smrd.runtime_config import (
    diagnose_native_runtime,
    prepare_native_runtime,
)


def _runtime(tmp_path: Path) -> Path:
    runtime = tmp_path / "smrd" / "runtime" / "SMRxView"
    for directory in ("globals", "mvciprojects", "mvci/bin", "mvci/config"):
        (runtime / directory).mkdir(parents=True, exist_ok=True)
    for filename in (
        "Softing.Dts.dll", "csWrap.dll", "cppApi.dll", "DtsKrnl.dll"
    ):
        (runtime / "mvci" / "bin" / filename).write_bytes(b"test only")
    (runtime / "mvci/config/license.bin").write_bytes(b"unchanged fixture")
    (runtime / "mvci/SystemConfig.xml").write_text(
        "<SystemConfig><ConfigurationPath>C:\\Nisp\\SMRxView\\mvci\\config"
        "</ConfigurationPath><ProductVersion>9.02.019</ProductVersion></SystemConfig>",
        encoding="utf-8",
    )
    (runtime / "mvci/config/DtsConfig64.xml").write_text(
        "<DtsConfig><Traces><TracePath>C:\\Nisp\\SMRxView\\temp</TracePath>"
        "</Traces><SystemProperties>"
        '<SystemProperty ShortName="com.softing.GlobalSmrFilePath" '
        'Value="C:\\Nisp\\SMRxView\\globals" />'
        '<SystemProperty ShortName="com.softing.StoragePath" '
        'Value="C:\\Nisp\\SMRxView\\temp" />'
        "</SystemProperties><Directories>"
        "<ProjectPath>C:\\Nisp\\SMRxView\\mvciprojects</ProjectPath>"
        "<DatabaseCachesPath>C:\\Nisp\\SMRxView\\temp</DatabaseCachesPath>"
        "</Directories></DtsConfig>",
        encoding="utf-8",
    )
    return runtime


def test_doctor_detects_six_original_absolute_path_mismatches(tmp_path):
    runtime = _runtime(tmp_path)
    report = diagnose_native_runtime(runtime)
    assert not report["ready_for_native_attempt"]
    assert not report["missing"]
    assert not report["errors"]
    assert len(report["mismatches"]) == 6


def test_dry_run_never_changes_vendor_config(tmp_path):
    runtime = _runtime(tmp_path)
    file = runtime / "mvci/SystemConfig.xml"
    before = file.read_bytes()
    report = prepare_native_runtime(runtime, data_dir=tmp_path, apply=False)
    assert not report["applied"]
    assert len(report["mismatches"]) == 6
    assert before == file.read_bytes()
    assert not list(runtime.rglob("*.bak"))


def test_apply_backups_and_is_idempotent(tmp_path):
    runtime = _runtime(tmp_path)
    license = runtime / "mvci/config/license.bin"
    license_sha = hashlib.sha256(license.read_bytes()).hexdigest()
    applied = prepare_native_runtime(runtime, data_dir=tmp_path, apply=True)
    assert applied["ready_for_native_attempt"]
    assert applied["applied"]
    assert len(applied["backups"]) == 2
    assert all(Path(file).is_file() for file in applied["backups"])
    assert hashlib.sha256(license.read_bytes()).hexdigest() == license_sha
    second = prepare_native_runtime(runtime, data_dir=tmp_path, apply=True)
    assert second["ready_for_native_attempt"]
    assert not second["applied"]
    assert second["backups"] == []


def test_outside_local_user_directory_cannot_be_modified(tmp_path):
    outside = tmp_path / "elsewhere" / "SMRxView"
    outside.mkdir(parents=True)
    with pytest.raises(ValueError, match="Nur lokale Kopie"):
        prepare_native_runtime(outside, data_dir=tmp_path, apply=True)


def test_missing_library_dll_prevents_patching(tmp_path):
    runtime = _runtime(tmp_path)
    (runtime / "mvci/bin/DtsKrnl.dll").unlink()
    with pytest.raises(ValueError, match="Runtime unvollstaendig"):
        prepare_native_runtime(runtime, data_dir=tmp_path, apply=True)
    assert "C:\\Nisp" in (runtime / "mvci/SystemConfig.xml").read_text()
