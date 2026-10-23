from pathlib import Path
from ntf_insight.smrd.library import SmrdLocalLibrary
from ntf_insight.smrd.xml_reference import parse_xml


def test_manual_original_path(tmp_path):
    root = tmp_path / "smrd" / "originale"
    root.mkdir(parents=True)
    source = root / "Example.smr-d"
    source.write_bytes(b"fixture")
    lib = SmrdLocalLibrary(data_dir=tmp_path)
    assert lib.root == tmp_path / "smrd"
    assert lib.list_smrd()[0]["path"] == source
    assert lib.add_smrd(source)["path"] == source


def test_generic_dtc_and_extra_fields(tmp_path):
    xml = tmp_path / "fixture.xml"
    xml.write_text('<ECUS><ECU NAME="ECU_X" VERSION="1"><VARIANT NAME="V1"><DTC NAME="P060FFB" ERROR_LEVEL="2: error">Monitor: Text<SDG SEMANTIC="REPAIR_ACTION">Inspect wiring</SDG><SDG SEMANTIC="POSSIBLE_CAUSES">Connector</SDG></DTC></VARIANT></ECU></ECUS>', encoding="utf-8")
    _, rows = parse_xml(xml)
    dtc = next(row for row in rows if row["category"] == "smrd_xml_dtc")
    assert dtc["reference"] == "P060FFB"
    assert dtc["data"]["repair_action"] == "Inspect wiring"
    assert dtc["data"]["possible_causes"] == "Connector"
    assert dtc["data"]["error_level"] == "2: error"
