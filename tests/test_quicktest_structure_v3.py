"""Synthetische Regressionstests fuer echte XENTRY-Layoutvarianten.

Keine vertraulichen FINs, Originalbelege oder Diagnoseinhalte in GitHub.
"""
from datetime import datetime

import pytest

from ntf_insight.ingestion.quicktest_structure import parse_quicktest_structure


FIN = "W1TTEST0000000001"


def _header(timestamp="2024-01-03 06:58:06.203"):
    return [
        "TestReport.xml.json",
        f"FIN {FIN}",
        "VIN -",
        "DISTANCE 29161 km",
        f"DIAG START {timestamp}",
        "VERSION 09/2023",
        "LANGUAGE de",
        "SOURCE XD",
    ]


def _ecu(ecu="CPC3-N127 - Steuergeraet Antriebsstrang", *, dtcs=1):
    lines = [
        ecu,
        "General information",
        "Diag version 004B1D",
        "ECU variant CPC3_R20B",
        "Boot version 21/31 000",
        "SW version 22/44 000",
        "HW partnumber 000 901 62 22",
        "HW version 21/28 000",
        "HW Serial ID 2302090003015861",
        "Supplier Continental",
        f"FAULT CODES ({dtcs})",
    ]
    if dtcs:
        lines.extend([
            "EV-DEV P26F100 - Pumpe sporadisch gestoppt. _ S",
            "Name Value (first occurence or unknown)Value (last occurence)",
            "Frequency_Counter - 3",
            "Vehicle_Odometer_in_Low_Resolution 2000.0 km 29161.0 km",
            "Operation_Cycle_Counter - 4",
        ])
    else:
        lines.append("No fault codes")
    return lines


def test_reale_xentry_zeit_und_ecu_metadaten():
    text = _header() + ["QuickTest 1", "ECU Count 1", "ECUS (1)"] + _ecu()
    result = parse_quicktest_structure(["\n".join(text)])
    assert result["diag_start"] == datetime(2024, 1, 3, 6, 58, 6, 203000)
    assert result["reported_ecu_count"] == 1
    ecu = result["ecus"][0]
    assert ecu["metadata"]["software_version"] == "22/44 000"
    assert ecu["metadata"]["hardware_version"] == "21/28 000"
    assert ecu["metadata"]["ecu_variant"] == "CPC3_R20B"
    dtc = ecu["faults"][0]
    assert dtc["kind"] == "EV-DEV"
    assert dtc["status"] == "S"
    assert dtc["frequency_counter"] == 3
    assert dtc["most_recent_odometer_km"] == 29161


def test_zwei_quicktests_werden_nicht_zu_einem_durchlauf():
    text = _header() + [
        "QuickTest 1", "ECU Count 1", "ECUS (1)",
    ] + _ecu(dtcs=1) + [
        "QuickTest 3", "ECU Count 1", "ECUS (1)",
    ] + _ecu(dtcs=0)
    result = parse_quicktest_structure(["\n".join(text)])
    assert len(result["runs"]) == 2
    assert result["reported_ecu_count"] == 2
    assert result["observed_dtc_count"] == 1
    assert [ecu["quicktest_number"] for ecu in result["ecus"]] == ["1", "3"]


def test_dtc_code_umbruch_und_unbekannter_ecu_name():
    text = _header() + [
        "QuickTest 1", "ECU Count 1", "ECUS (1)",
        "NO DIOGENES NAME-N127 - Steuergeraet im Verbund",
        "General information", "Diag version ---", "ECU variant ---",
        "SW version ---", "HW version ---", "Supplier ---",
        "FAULT CODES (1)", "FC", "P20EA9A - Keine weitere Information. S",
        "Name Value (first occurence or unknown)Value (last occurence)",
        "Frequency_Count - 1",
    ]
    result = parse_quicktest_structure(["\n".join(text)])
    assert result["ecus"][0]["ecu_code"] == "NO DIOGENES NAME"
    assert result["ecus"][0]["faults"][0]["code"] == "P20EA9A"
    assert result["ecus"][0]["faults"][0]["frequency_counter"] == 1


def test_zahlabweichung_wird_nicht_stillschweigend_akzeptiert():
    text = _header() + ["QuickTest 1", "ECU Count 1", "ECUS (1)"] + _ecu(dtcs=1)
    text = [s for s in text if not s.startswith("EV-DEV")]
    with pytest.raises(ValueError, match="meldet 1 DTCs"):
        parse_quicktest_structure(["\n".join(text)])


def test_fehlende_fin_muss_im_integrationsparser_abgewiesen_werden():
    # The structure reader does not invent a FIN; the adapter uses canonical_fin.
    text = _header() + ["QuickTest 1", "ECU Count 1", "ECUS (1)"] + _ecu(dtcs=0)
    text = ["FIN -" if row.startswith("FIN ") else row for row in text]
    assert parse_quicktest_structure(["\n".join(text)])["fin"] is None


def test_legacy_supplier_and_hardware_fields_are_not_mixed_with_labels():
    text = _header() + [
        "QuickTest 1", "ECU Count 1", "ECUS (1)",
        "CPC3-N127 - Controller",
        "Diagnostics ID 00AB13 ECU Variant CPC3_TEST",
        "Hardware", "Partnumber", "001 002 003 Hardware",
        "Version", "23/15 000",
        "Supplier Example Software",
        "Version", "25/04 002",
        "FAULT CODES (0)", "No fault codes",
    ]
    parsed = parse_quicktest_structure(["\n".join(text)])
    meta = parsed["ecus"][0]["metadata"]
    assert meta["hardware_partnumber"] == "001 002 003"
    assert meta["hardware_version"] == "23/15 000"
    assert meta["supplier"] == "Example"
    assert meta["software_version"] == "25/04 002"
