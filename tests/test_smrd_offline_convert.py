"""Offline SMR-D converter regression tests; no vendor runtime or secrets."""
from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest

from ntf_insight.smrd.offline_convert import (
    OFFLINE_FORMAT,
    import_offline_bundle,
    offline_convert,
)


def _synthetic_smrd(root: Path, *, revision: str = "24.01.00") -> Path:
    # Valid public SMR-D container header with entirely synthetic opaque bytes.
    metadata = (
        "DATE/TIME: 2024-01-01T00:00:00\r\n"
        "TRAFO VERSION: 0.0.0\r\n"
        "ODX VERSION: 2.2.0\r\n"
        f"REVISION INFO: {revision}\r\n"
        "D-SERVER VERSION: 0.0.0\r\n"
    ).encode("ascii")
    words = [0] * 17
    words[0] = 68
    words[2] = 88 + len(metadata)
    words[3] = 4
    words[8:14] = [16, 0x1FF, 24, 0x1FF, 32, 0x1FF]
    original = root / "CPC3_24.01.00.smr-d"
    original.write_bytes(
        bytes.fromhex("5290d43067147e4781f23c4b73f0f737")
        + struct.pack("<17I", *words)
        + struct.pack("<I", len(metadata))
        + metadata
        + b"H" * 32
        + b"A" * 16 + b"B" * 24 + b"C" * 32
    )
    return original


def _dtcs_xml(path: Path, *, ecu: str = "CPC3") -> Path:
    path.write_text(
        f'<ECUS><ECU NAME="{ecu}" VERSION="24.1.0">'
        '<VARIANT NAME="CPC3_R24A">'
        '<DTC NAME="P000000">Sample DTC</DTC>'
        '</VARIANT></ECU></ECUS>',
        encoding="utf-8",
    )
    return path


def _ecu_xml(path: Path) -> Path:
    path.write_text(
        '<Smrd2Xml EcuName="CPC3" Version="" XmlFormatVersion="0.9">'
        '<Variants name="CPC3_R24A">'
        '<Services name="ReadStatus">'
        '<OutParams name="Status" Unit="percent"/>'
        '</Services>'
        '<DTCs name="P000000">Sample DTC</DTCs>'
        '</Variants></Smrd2Xml>',
        encoding="utf-8",
    )
    return path


def test_metadata_only_never_claims_binary_dtc_decoding(tmp_path):
    smrd = _synthetic_smrd(tmp_path)
    result = offline_convert(smrd, data_dir=tmp_path)
    assert result["status"] == "metadata_only"
    assert result["total_references"] == 0
    assert result["native_binary_dtc_decoded"] is False
    bundle = json.loads(Path(result["bundle"]).read_text(encoding="utf-8"))
    assert bundle["format"] == OFFLINE_FORMAT
    assert bundle["coverage"]["native_binary_dtc_decoded"] is False
    assert bundle["source_smrd"]["container"]["metadata"]["REVISION INFO"] == "24.01.00"
    sections = bundle["source_smrd"]["opaque_sections"]
    assert sum(s["size_bytes"] for s in sections) + bundle[
        "source_smrd"
    ]["container"]["payload_offset_bytes"] == smrd.stat().st_size
    assert all(s["decode_status"] == "opaque_not_decoded" for s in sections[1:])
    assert bundle["xml_sources"] == []
    assert bundle["reference_records"] == []
    assert not (tmp_path / "ntf-insight.duckdb").exists()


def test_explicit_local_xml_files_merge_without_duplicate_dtcs(tmp_path):
    smrd = _synthetic_smrd(tmp_path)
    xml1 = _dtcs_xml(tmp_path / "CPC3_dtc.xml")
    xml2 = _ecu_xml(tmp_path / "CPC3_ecu.xml")
    result = offline_convert(
        smrd, xml_files=[xml1, xml2], data_dir=tmp_path, remember=True,
    )
    assert result["status"] == "metadata_and_local_xml_references"
    assert result["xml_sources"] == 2
    assert result["counts"] == {
        "smrd_xml_dtc": 1,
        "smrd_xml_ecu": 1,
        "smrd_xml_parameter": 1,
        "smrd_xml_service": 1,
        "smrd_xml_variant": 1,
    }
    document = json.loads(Path(result["bundle"]).read_text(encoding="utf-8"))
    assert document["vendor_runtime_used"] is False
    assert document["network_used"] is False
    assert len(document["reference_records"]) == 5
    dtc = next(x for x in document["reference_records"] if x["category"] == "smrd_xml_dtc")
    assert len(dtc["source_provenance"]) == 2
    assert dtc["data"]["from_native_smrd_payload"] is False
    assert dtc["data"]["trigger_conditions_validated"] is False
    assert not (tmp_path / "ntf-insight.duckdb").exists()


def test_saved_links_allow_repeat_without_xml_argument(tmp_path):
    smrd = _synthetic_smrd(tmp_path)
    xml = _dtcs_xml(tmp_path / "export.xml")
    original = offline_convert(
        smrd, xml_files=[xml], data_dir=tmp_path, remember=True,
    )
    repeated = offline_convert(smrd, data_dir=tmp_path)
    assert repeated["counts"] == original["counts"]
    assert repeated["xml_sources"] == 1
    assert repeated["bundle"] == original["bundle"]


def test_saved_xml_change_is_rejected_not_silently_reused(tmp_path):
    smrd = _synthetic_smrd(tmp_path)
    xml = _dtcs_xml(tmp_path / "source.xml")
    offline_convert(smrd, xml_files=[xml], data_dir=tmp_path, remember=True)
    xml.write_text('<ECUS><ECU NAME="CPC3"/></ECUS>', encoding="utf-8")
    with pytest.raises(ValueError, match="veraendert"):
        offline_convert(smrd, data_dir=tmp_path)


def test_ecu_mismatch_is_warning_not_fake_binary_verification(tmp_path):
    smrd = _synthetic_smrd(tmp_path)
    xml = _dtcs_xml(tmp_path / "other_ecu.xml", ecu="OTHER")
    result = offline_convert(smrd, xml_files=[xml], data_dir=tmp_path)
    assert result["total_references"] == 3
    assert any("nicht eindeutig" in warning for warning in result["warnings"])


def test_unexpected_revision_does_not_silently_match(tmp_path):
    smrd = _synthetic_smrd(tmp_path, revision="30.01.00")
    xml = _dtcs_xml(tmp_path / "reference.xml")
    result = offline_convert(smrd, xml_files=[xml], data_dir=tmp_path)
    assert any("weicht" in warning for warning in result["warnings"])


def test_invalid_or_truncated_opaque_sections_rejected(tmp_path):
    smrd = _synthetic_smrd(tmp_path)
    source = smrd.read_bytes()
    smrd.write_bytes(source[:-20])
    with pytest.raises(ValueError, match="groesser"):
        offline_convert(smrd, data_dir=tmp_path)


def test_db_import_uses_reference_knowledge_and_is_idempotent(tmp_path):
    smrd = _synthetic_smrd(tmp_path)
    xml = _dtcs_xml(tmp_path / "src.xml")
    result = offline_convert(smrd, xml_files=[xml], data_dir=tmp_path)
    assert import_offline_bundle(Path(result["bundle"]), data_dir=tmp_path) == 3
    assert import_offline_bundle(Path(result["bundle"]), data_dir=tmp_path) == 3
    from ntf_insight.storage.duckdb_store import DuckDBStore
    from ntf_insight.storage.source_knowledge_store import SourceKnowledgeStore

    store = SourceKnowledgeStore(DuckDBStore(tmp_path / "ntf-insight.duckdb"))
    rows = store.list_rows(category="smrd_xml_dtc", search="P000000")
    assert len(rows) == 1
    assert rows[0]["data"]["is_vehicle_observation"] is False


def test_metadata_only_bundle_cannot_be_imported_as_dtc_catalogue(tmp_path):
    smrd = _synthetic_smrd(tmp_path)
    report = offline_convert(smrd, data_dir=tmp_path)
    with pytest.raises(ValueError, match="keine importierbaren"):
        import_offline_bundle(Path(report["bundle"]), data_dir=tmp_path)
