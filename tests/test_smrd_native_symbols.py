"""Synthetic PE export-table fixtures. No proprietary Softing binaries in Git."""
from __future__ import annotations

import struct
from pathlib import Path

import pytest

from ntf_insight.smrd.native_symbols import (
    NativeSymbolError,
    diagnose_native_symbols,
    dll_exports,
)


def _build_pe_stub(path: Path, names: tuple[str, ...]) -> None:
    data = bytearray(0x1200)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, 0x80)
    data[0x80:0x84] = b"PE\x00\x00"
    struct.pack_into("<H", data, 0x84, 0x8664)
    struct.pack_into("<H", data, 0x86, 1)
    struct.pack_into("<H", data, 0x94, 0xF0)
    optional = 0x98
    struct.pack_into("<H", data, optional, 0x20B)
    struct.pack_into("<II", data, optional + 112, 0x1000, 0x500)
    section = optional + 0xF0
    data[section:section + 8] = b".rdata\x00\x00"
    struct.pack_into("<IIII", data, section + 8, 0xA00, 0x1000, 0xA00, 0x200)
    struct.pack_into("<I", data, 0x200 + 24, len(names))
    struct.pack_into("<I", data, 0x200 + 32, 0x1050)
    for i, name in enumerate(names):
        offset = 0x300 + i * 0x70
        encoded = name.encode("ascii") + b"\x00"
        data[offset:offset + len(encoded)] = encoded
        struct.pack_into("<I", data, 0x250 + 4 * i, 0x1000 + offset - 0x200)
    path.write_bytes(data)


def test_pe_named_exports_can_be_read_without_loading_binary(tmp_path):
    path = tmp_path / "synthetic.dll"
    names = ("FirstSymbol", "CSNIDTS_DtsSystem_selectDynamicProject")
    _build_pe_stub(path, names)
    assert dll_exports(path) == frozenset(names)


def test_non_pe_file_is_safely_rejected(tmp_path):
    path = tmp_path / "invalid.dll"
    path.write_bytes(b"not a DLL")
    with pytest.raises(NativeSymbolError, match="PE"):
        dll_exports(path)


def test_missing_entrypoints_are_reported_not_assumed(tmp_path):
    path = tmp_path / "synthetic.dll"
    _build_pe_stub(path, (
        "CSNIDTS_DtsSystem_selectDynamicProject",
        "CSNIDTS_DtsProject_getDbProject",
    ))
    result = diagnose_native_symbols(path)
    assert result["managed_only_viewer_api"] is True
    assert result["has_dynamic_project_api"] is True
    assert result["has_project_database_api"] is True
    assert result["native_api_ready"] is False
    assert "CSNIDTS_DtsSystem_initialize" in result["missing_required_exports"]


@pytest.mark.skipif(__import__("os").name != "nt", reason="PowerShell 5.1 is Windows-only")
def test_powershell_backend_uses_supported_dynamic_project_api():
    from importlib.resources import files

    source = files("ntf_insight.smrd").joinpath("softing_native_export.ps1").read_text(
        encoding="utf-8"
    )
    assert ".SelectDynamicProject(" in source
    assert "Read-Prop $project 'DbProject'" in source
    assert ".DeselectProject()" in source
    assert ".LoadViewerProject(" not in source
    assert ".UnloadViewerProject(" not in source
