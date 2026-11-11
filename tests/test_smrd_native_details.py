"""Synthetic regression tests: no proprietary binaries, VINs or vehicle records."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from ntf_insight.smrd.native_details import (
    NativeDetailError,
    import_native_details,
    knowledge_source_key,
    normalize_sdg_groups,
    parse_native_details,
)
from ntf_insight.smrd.native_export import NativeRuntimeError, resolve_runtime_dir
from ntf_insight.smrd.library import SmrdLocalLibrary
from ntf_insight.storage.duckdb_store import DuckDBStore
from ntf_insight.storage.source_knowledge_store import SourceKnowledgeStore

SHA = "a" * 64


def _write_data(path: Path, *, complete: bool = True) -> None:
    data = {
        "format": "ntf-smrd-native-dtc-v1",
        "complete": complete,
        "smrd_sha256": SHA,
        "dts_version": "9.02.019",
        "dtcs": [{
            "ecu": "ECU_OTHER",
            "variant": "OTHER_V1",
            "location": "OTHER_CAN",
            "code": "P060FFB",
            "trouble_code": 397307,
            "level": 2,
            "dtc_text": "Coolant Temperature Performance",
            "short_name": "ErrEntry_ErrObch005",
            "sdgs": [{
                "semantic": "REPAIR_ACTION",
                "caption": "Service action",
                "elements": [
                    {"semantic": "", "content": "Inspect connector", "text_id": "SDG01"},
                    {"semantic": "POSSIBLE_CAUSES", "content": "Corrosion", "text_id": "SDG02"},
                    {"semantic": "OTHER_OEM_KEY", "content": "Value", "text_id": "SDG03"},
                ],
            }],
        }],
    }
    path.write_text(json.dumps(data), encoding="utf-8")


def test_native_dtc_level_and_original_sdg_values(tmp_path):
    path = tmp_path / "details.json"
    _write_data(path)
    metadata, rows = parse_native_details(path)
    assert metadata["complete"] is True
    assert len(rows) == 1
    data = rows[0]["data"]
    assert data["ecu"] == "ECU_OTHER"
    assert data["error_level"] == 2
    assert data["repair_action"] == "Inspect connector"
    assert data["possible_causes"] == "Corrosion"
    assert data["sdg_index"]["OTHER_OEM_KEY"] == ["Value"]
    assert data["sdgs"][0]["elements"][2]["text_id"] == "SDG03"
    assert data["trigger_conditions_validated"] is False
    assert data["is_vehicle_observation"] is False


def test_separate_element_semantics_do_not_mix_values():
    groups, index = normalize_sdg_groups([{
        "semantic": "",
        "elements": [
            {"semantic": "REPAIR_ACTION", "content": "Replace pump"},
            {"semantic": "POSSIBLE_CAUSES", "content": "Vibration"},
        ],
    }])
    assert index["REPAIR_ACTION"] == ["Replace pump"]
    assert index["POSSIBLE_CAUSES"] == ["Vibration"]
    assert len(groups) == 1


def test_reject_incomplete_native_export(tmp_path):
    path = tmp_path / "partial.json"
    _write_data(path, complete=False)
    with pytest.raises(NativeDetailError, match="Unvollstaendig"):
        parse_native_details(path)


def test_reject_invalid_smrd_digest(tmp_path):
    path = tmp_path / "bad.json"
    _write_data(path)
    data = json.loads(path.read_text())
    data["smrd_sha256"] = "invalid"
    path.write_text(json.dumps(data))
    with pytest.raises(NativeDetailError, match="SHA256"):
        parse_native_details(path)


def test_derived_import_key_is_not_the_raw_artifact_key():
    derived = knowledge_source_key(SHA)
    assert derived != SHA
    assert derived == hashlib.sha256(f"ntf-smrd-native-dtc-v1:{SHA}".encode()).hexdigest()


def test_missing_runtime_reports_clear_error(tmp_path):
    library = SmrdLocalLibrary(data_dir=tmp_path)
    with pytest.raises(NativeRuntimeError, match="Laufzeit fehlt"):
        resolve_runtime_dir(tmp_path / "missing", library)


def test_import_is_local_and_idempotent(tmp_path):
    source = tmp_path / "details.json"
    _write_data(source)
    assert import_native_details(source, data_dir=tmp_path) == 1
    assert import_native_details(source, data_dir=tmp_path) == 1
    store = SourceKnowledgeStore(DuckDBStore(tmp_path / "ntf-insight.duckdb"))
    rows = store.list_rows(category="smrd_native_dtc_detail", search="P060FFB")
    assert len(rows) == 1
    assert rows[0]["data"]["possible_causes"] == "Corrosion"


@pytest.mark.skipif(os.name != "nt", reason="Only Windows ships PowerShell 5.1")
def test_powershell_exporter_is_syntactically_valid():
    from importlib.resources import files

    exe = shutil.which("powershell.exe")
    assert exe is not None
    script = str(files("ntf_insight.smrd").joinpath("softing_native_export.ps1"))
    escaped = script.replace("'", "''")
    command = (
        "$tokens=$null; $errors=$null; "
        f"[System.Management.Automation.Language.Parser]::ParseFile('{escaped}',"
        "[ref]$tokens,[ref]$errors) | Out-Null; "
        "if ($errors.Count -gt 0) { "
        "$errors | ForEach-Object { Write-Output $_.ToString() }; exit 1 }"
    )
    result = subprocess.run(
        [exe, "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=30, check=False,
    )
    assert result.returncode == 0, (result.stdout or "") + (result.stderr or "")
