"""Synthetic Smrd2Xml adapter tests; no vendor EXE or license in repository."""
from __future__ import annotations

import json
import struct
import subprocess
from pathlib import Path

import pytest

import ntf_insight.smrd.smrd2xml_runner as runner
from ntf_insight.smrd.offline_convert import offline_convert


def _fake_smrd(root: Path) -> Path:
    meta = b"REVISION INFO: 24.01.00\r\nTRAFO VERSION: 9.04.019\r\n"
    words = [0] * 17
    words[0] = 68
    words[2] = 88 + len(meta)
    words[8:14] = [16, 0x1FF, 24, 0x1FF, 32, 0x1FF]
    path = root / "CPC3_24.01.00.smr-d"
    path.write_bytes(
        bytes.fromhex("5290d43067147e4781f23c4b73f0f737")
        + struct.pack("<17I", *words)
        + struct.pack("<I", len(meta))
        + meta + b"H" * 32 + b"A" * 16 + b"B" * 24 + b"C" * 32
    )
    return path


def _fake_runtime(root: Path) -> Path:
    runtime = root / "smrd" / "runtime" / "SMRxView"
    runtime.mkdir(parents=True)
    (runtime / "Smrd2Xml.exe").write_bytes(b"MZsynthetic non-executable test")
    return runtime


def test_ecu_name_derived_from_filename_not_from_binary():
    assert runner.guess_ecu_name(Path("CPC3_24.01.00.smr-d")) == "CPC3"
    assert runner.guess_ecu_name(Path("CPC_NG_02.21.03_SMR-D_8.17.smr-d")) == "CPC_NG"
    assert runner.guess_ecu_name(Path("ABC.smr-d")) == "ABC"


def test_dry_run_without_dts_or_network(tmp_path, monkeypatch):
    smrd = _fake_smrd(tmp_path)
    runtime = _fake_runtime(tmp_path)
    monkeypatch.setattr(runner.subprocess, "run", lambda *a, **k: pytest.fail("executed"))
    result = runner.run_smrd2xml(
        smrd, data_dir=tmp_path, runtime_dir=runtime, dry_run=True,
    )
    assert result["executed"] is False
    assert result["selected_modes"] == ["ECU", "DTCSXML"]
    assert result["ecu_name_guess"] == "CPC3"
    assert result["license_free_guaranteed"] is False
    assert result["network_used_by_adapter"] is False
    assert not (tmp_path / "ntf-insight.duckdb").exists()


def test_missing_vendor_executable_is_reported_without_fallback(tmp_path):
    smrd = _fake_smrd(tmp_path)
    with pytest.raises(FileNotFoundError, match="Smrd2Xml.exe"):
        runner.run_smrd2xml(smrd, data_dir=tmp_path)


def test_external_tool_xml_is_indexed_and_original_is_untouched(tmp_path, monkeypatch):
    smrd = _fake_smrd(tmp_path)
    original = smrd.read_bytes()
    runtime = _fake_runtime(tmp_path)
    monkeypatch.setattr(runner.sys, "platform", "win32")
    received = []

    def fake_subprocess(args, **kwargs):
        received.append(args)
        assert Path(args[2]) != smrd
        assert Path(args[2]).read_bytes() == original
        assert kwargs["cwd"] == runtime
        if args[1] == "CPC3":
            destination = Path(args[3]) / "CPC3_ECU.xml"
            destination.write_text(
                '<Smrd2Xml EcuName="CPC3" Version="24.01.00">'
                '<Variants name="V1"><Services name="ReadEcu">'
                '<OutParams name="Status" Unit="percent"/></Services>'
                '<DTCs name="P123456">A synthetic DTC</DTCs>'
                '</Variants></Smrd2Xml>',
                encoding="utf-8",
            )
        elif args[1] == "DTCSXML":
            destination = Path(args[2]).parent / "CPC3_DTCSXML.xml"
            destination.write_text(
                '<ECUS><ECU NAME="CPC3" VERSION="24.01.00">'
                '<VARIANT NAME="V1"><DTC NAME="P123456">A synthetic DTC</DTC>'
                '</VARIANT></ECU></ECUS>',
                encoding="utf-8",
            )
        else:
            pytest.fail("unexpected mode")
        return subprocess.CompletedProcess(
            args=args, returncode=0, stdout="Conversion completed", stderr=""
        )

    monkeypatch.setattr(runner.subprocess, "run", fake_subprocess)
    result = runner.run_smrd2xml(
        smrd, data_dir=tmp_path, runtime_dir=runtime, remember=True,
    )
    assert [args[1] for args in received] == ["CPC3", "DTCSXML"]
    assert result["xml_catalogue_generated"] is True
    assert result["total_references"] == 5
    assert result["counts"] == {
        "smrd_xml_ecu": 1,
        "smrd_xml_variant": 1,
        "smrd_xml_service": 1,
        "smrd_xml_parameter": 1,
        "smrd_xml_dtc": 1,
    }
    assert len(result["generated_xml"]) == 2
    assert smrd.read_bytes() == original
    assert not (tmp_path / "ntf-insight.duckdb").exists()
    bundle = json.loads(Path(result["bundle"]).read_text(encoding="utf-8"))
    dtc = next(r for r in bundle["reference_records"] if r["category"] == "smrd_xml_dtc")
    assert len(dtc["source_provenance"]) == 2
    # Vendor-generated XML is retained; subsequent pure-Python runs need no EXE.
    pure = offline_convert(smrd, data_dir=tmp_path)
    assert pure["total_references"] == 5


def test_vendor_license_error_is_not_hidden(tmp_path, monkeypatch):
    smrd = _fake_smrd(tmp_path)
    runtime = _fake_runtime(tmp_path)
    monkeypatch.setattr(runner.sys, "platform", "win32")
    monkeypatch.setattr(
        runner.subprocess, "run",
        lambda *a, **k: subprocess.CompletedProcess(
            args=a[0], returncode=1, stdout="",
            stderr="eSYSTEM_LICENSE_ERROR: No BaseSystem license was found",
        ),
    )
    with pytest.raises(runner.Smrd2XmlLicenseError, match="BaseSystem"):
        runner.run_smrd2xml(
            smrd, data_dir=tmp_path, runtime_dir=runtime, modes=("ECU",),
        )
    assert not (tmp_path / "ntf-insight.duckdb").exists()


def test_unrecognized_xml_is_preserved_but_not_falsely_indexed(tmp_path, monkeypatch):
    smrd = _fake_smrd(tmp_path)
    runtime = _fake_runtime(tmp_path)
    monkeypatch.setattr(runner.sys, "platform", "win32")

    def fake_subprocess(args, **kwargs):
        (Path(args[2]).parent / "CanModel.xml").write_text(
            '<?xml version="1.0"?><CANMODEL><Opaque name="X"/></CANMODEL>',
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(runner.subprocess, "run", fake_subprocess)
    result = runner.run_smrd2xml(
        smrd, data_dir=tmp_path, runtime_dir=runtime, modes=("CANMODEL",),
    )
    assert result["total_references"] == 0
    assert result["xml_catalogue_generated"] is False
    assert len(result["additional_xml"]) == 1
    assert Path(result["additional_xml"][0]["file"]).is_file()
    assert "bundle" not in result


def test_vendor_arguments_do_not_allow_unknown_modes(tmp_path):
    smrd = _fake_smrd(tmp_path)
    runtime = _fake_runtime(tmp_path)
    with pytest.raises(ValueError, match="Zulaessige"):
        runner.run_smrd2xml(
            smrd, data_dir=tmp_path, runtime_dir=runtime,
            modes=("UNSAFE_MODE",), dry_run=True,
        )


def test_license_error_classification_distinguishes_other_failures():
    other = subprocess.CompletedProcess(
        args=[], returncode=14, stdout="", stderr="Unknown ECU short name",
    )
    error = runner._error_from_vendor(other, "ECU")
    assert isinstance(error, runner.Smrd2XmlError)
    assert not isinstance(error, runner.Smrd2XmlLicenseError)
    assert "Unknown ECU" in str(error)
