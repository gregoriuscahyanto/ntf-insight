"""Synthetic recovery tests: never use or publish real vendor binaries."""
from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

import pytest

from ntf_insight.smrd.runtime_config import (
    diagnose_native_runtime,
    prepare_native_runtime,
    recover_native_runtime_configs,
)

_DLLS = ("Softing.Dts.dll", "csWrap.dll", "cppApi.dll", "DtsKrnl.dll")


def _sample(tmp_path: Path):
    runtime = tmp_path / "smrd" / "runtime" / "SMRxView"
    for name in ("mvci/bin", "mvci/config", "globals", "mvciprojects"):
        (runtime / name).mkdir(parents=True, exist_ok=True)
    original = {
        "mvci/SystemConfig.xml": (
            b"<SystemConfig><ConfigurationPath>C:\\Nisp\\SMRxView\\mvci\\config"
            b"</ConfigurationPath></SystemConfig>"
        ),
        "mvci/config/DtsConfig64.xml": (
            b'<DtsConfig><Traces><TracePath>C:\\Nisp\\SMRxView\\temp</TracePath>'
            b'</Traces><SystemProperties>'
            b'<SystemProperty ShortName="com.softing.GlobalSmrFilePath" '
            b'Value="C:\\Nisp\\SMRxView\\globals" />'
            b'<SystemProperty ShortName="com.softing.StoragePath" '
            b'Value="C:\\Nisp\\SMRxView\\temp" />'
            b'</SystemProperties><Directories>'
            b'<ProjectPath>C:\\Nisp\\SMRxView\\mvciprojects</ProjectPath>'
            b'<DatabaseCachesPath>C:\\Nisp\\SMRxView\\temp</DatabaseCachesPath>'
            b'</Directories></DtsConfig>'
        ),
    }
    bad = {
        "mvci/SystemConfig.xml": (
            b"<SystemConfig><ConfigurationPath>bad & invalid"
            b"</ConfigurationPath></SystemConfig>"
        ),
        "mvci/config/DtsConfig64.xml": (
            b"<DtsConfig><TracePath>bad & invalid</TracePath></DtsConfig>"
        ),
    }
    archive_path = tmp_path / "original-SMRxView.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        for name, data in original.items():
            archive.writestr("SMRxView/" + name, data)
            (runtime / name).write_bytes(bad[name])
        for binary in _DLLS:
            sample = ("fake:" + binary).encode("ascii")
            (runtime / "mvci" / "bin" / binary).write_bytes(sample)
            archive.writestr("SMRxView/mvci/bin/" + binary, sample)
    license_file = runtime / "mvci/config/license.bin"
    license_file.write_bytes(b"license fixture must not be changed")
    return runtime, archive_path, original, bad, license_file


def test_restoration_preview_only_and_matching_binary_checks(tmp_path):
    runtime, archive, original, bad, license_file = _sample(tmp_path)
    old_license_hash = hashlib.sha256(license_file.read_bytes()).digest()
    report = recover_native_runtime_configs(runtime, archive, data_dir=tmp_path)
    assert report["dll_hashes_match"]
    assert report["restorable_count"] == 2
    assert not report["applied"]
    assert not report["backups"]
    for name in original:
        assert (runtime / name).read_bytes() == bad[name]
    assert hashlib.sha256(license_file.read_bytes()).digest() == old_license_hash


def test_restoration_creates_backups_then_path_relocation(tmp_path):
    runtime, archive, original, bad, license_file = _sample(tmp_path)
    report = recover_native_runtime_configs(
        runtime, archive, data_dir=tmp_path, apply=True
    )
    assert report["applied"]
    assert report["restorable_count"] == 2
    assert len(report["backups"]) == 2
    assert not report["doctor_after_restore"]["ready_for_native_attempt"]
    for filename in original:
        assert (runtime / filename).read_bytes() == original[filename]
        assert bad[filename] in [Path(b).read_bytes() for b in report["backups"]]
    assert license_file.read_bytes() == b"license fixture must not be changed"
    assert len(diagnose_native_runtime(runtime)["mismatches"]) == 6
    moved = prepare_native_runtime(runtime, data_dir=tmp_path, apply=True)
    assert moved["ready_for_native_attempt"]
    again = recover_native_runtime_configs(runtime, archive, data_dir=tmp_path)
    assert again["restorable_count"] == 0
    assert not again["applied"]


def test_mismatched_vendor_dll_prevents_recovery(tmp_path):
    runtime, archive, _, bad, _ = _sample(tmp_path)
    (runtime / "mvci/bin/cppApi.dll").write_bytes(b"changed vendor binary fixture")
    with pytest.raises(ValueError, match="cppApi.dll abweichend"):
        recover_native_runtime_configs(runtime, archive, data_dir=tmp_path, apply=True)
    assert (runtime / "mvci/SystemConfig.xml").read_bytes() == bad["mvci/SystemConfig.xml"]
    assert not list(runtime.rglob("*.bak"))


def test_recovery_preserves_valid_custom_configuration(tmp_path):
    runtime, archive, original, bad, _ = _sample(tmp_path)
    valid = (runtime / "mvci/SystemConfig.xml")
    valid.write_bytes(original["mvci/SystemConfig.xml"])
    report = recover_native_runtime_configs(
        runtime, archive, data_dir=tmp_path, apply=True
    )
    assert report["restorable_count"] == 1
    assert report["preserved_valid_configurations"] == ["mvci/SystemConfig.xml"]
    assert valid.read_bytes() == original["mvci/SystemConfig.xml"]
    assert (runtime / "mvci/config/DtsConfig64.xml").read_bytes() == original[
        "mvci/config/DtsConfig64.xml"
    ]
    assert len(report["backups"]) == 1
    assert bad["mvci/config/DtsConfig64.xml"] == Path(report["backups"][0]).read_bytes()


def test_restore_outside_local_runtime_forbidden(tmp_path):
    runtime, archive, _, _, _ = _sample(tmp_path)
    other_dir = tmp_path / "unrelated"
    other_dir.mkdir()
    with pytest.raises(ValueError, match="Wiederherstellung nur"):
        recover_native_runtime_configs(other_dir, archive, data_dir=tmp_path, apply=True)
    assert runtime.is_dir()


def test_invalid_vendor_config_in_archive_aborts_without_changes(tmp_path):
    runtime, archive, _, bad, _ = _sample(tmp_path)
    with zipfile.ZipFile(archive, "a") as zip_writer:
        # Duplicate critical member is rejected, before any file is changed.
        zip_writer.writestr(
            "SMRxView/mvci/SystemConfig.xml",
            b"<SystemConfig><ConfigurationPath>broken &</ConfigurationPath></SystemConfig>",
        )
    with pytest.raises(ValueError, match="nicht exakt eine Datei"):
        recover_native_runtime_configs(runtime, archive, data_dir=tmp_path, apply=True)
    assert (runtime / "mvci/SystemConfig.xml").read_bytes() == bad["mvci/SystemConfig.xml"]
