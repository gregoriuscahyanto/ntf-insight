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


def test_v4_ignoriert_nullzellen_zwischen_ecu_kopf_und_allgemeinen_daten():
    lines = _header() + ["QuickTest 1", "ECU Count 1", "ECUS (1)"]
    lines += [
        "CPC3-N127 - Steuergeraet Antriebsstrang",
        "\x00",  # Extraktionsartefakt aus einem PDF-Tabellenfeld
        "General information",
        "ECU variant CPC3_SYNTH",
        "FAULT CODES (0)", "No fault codes",
    ]
    result = parse_quicktest_structure(["\n".join(lines)])
    assert result["reported_ecu_count"] == 1
    assert result["ecus"][0]["ecu_code"] == "CPC3"
    assert result["observed_dtc_count"] == 0


def test_v4_erkennt_umgebrochene_ecu_beschreibung_ohne_falsche_ecu_anzahl():
    lines = _header() + ["QuickTest 1", "ECU Count 1", "ECUS (1)"]
    lines += [
        "CPC3-N127 - Steuergeraet Antriebsstrang",
        "X",  # Einzelnes umgebrochenes Zeichen zwischen Kopf und Abschnitt
        "General information",
        "SW version 26/01",
        "FAULT CODES (1)",
        "FC", "P20EA9A - Testfehler. S",
        "Name Value (first occurence or unknown)Value (last occurence)",
        "Frequency_Count 2",
    ]
    result = parse_quicktest_structure(["\n".join(lines)])
    assert result["reported_ecu_count"] == 1
    assert result["ecus"][0]["faults"][0]["code"] == "P20EA9A"
    assert result["observed_dtc_count"] == 1


def test_v4_erfindet_auch_bei_pdf_artefakten_keine_fehlenden_ecus():
    lines = _header() + ["QuickTest 1", "ECU Count 2", "ECUS (2)"]
    lines += [
        "CPC3-N127 - Steuergeraet Antriebsstrang",
        "\x00", "General information",
        "FAULT CODES (0)",
    ]
    with pytest.raises(ValueError, match="ECU-Anzahl stimmt nicht"):
        parse_quicktest_structure(["\n".join(lines)])


def test_v4_unterstuetzt_umfangreiche_aber_begrenzte_pdf_berichte(
    tmp_path, monkeypatch,
):
    from ntf_insight.ingestion import quicktest_detailed
    from ntf_insight.ingestion.real_source_parsers import QuickTestPdfParser

    class FakePage:
        def __init__(self, text=""):
            self.text = text

        def extract_text(self):
            return self.text

    class FakeReader:
        is_encrypted = False

        def __init__(self, _path, strict=False):
            lines = _header() + [
                "QuickTest 1", "ECU Count 1", "ECUS (1)",
                "CPC3-N127 - Steuergeraet Antriebsstrang",
                "General information",
                "FAULT CODES (0)", "No fault codes",
            ]
            self.pages = [FakePage("\n".join(lines))]
            self.pages.extend(FakePage() for _ in range(631))

    monkeypatch.setattr(quicktest_detailed, "PdfReader", FakeReader)
    pdf = tmp_path / "synthetischer_quicktest.pdf"
    pdf.write_bytes(b"FAKE PDF reader monkeypatched")
    parsed = QuickTestPdfParser("f" * 64).parse(pdf)
    assert QuickTestPdfParser.version == "4.1.0"
    assert len(parsed.quicktest_report["page_texts"]) == 632
    assert parsed.quicktest_report is not None
    assert parsed.quicktest_report["reported_ecu_count"] == 1


def test_v4_erkennt_zwei_lange_umbruchzeilen_zwischen_ecu_kopf_und_metadaten():
    lines = _header() + ["QuickTest 1", "ECU Count 1", "ECUS (1)"]
    lines += [
        "CPC3-N127 - Steuergeraet fuer synthetische Funktionsgruppe",
        "mit einer weiteren harmlosen Beschreibung",
        "und einer zweiten umgebrochenen Namensergaenzung",
        "General information",
        "ECU variant CPC3_SYNTH",
        "FAULT CODES (0)", "No fault codes",
    ]
    result = parse_quicktest_structure(["\n".join(lines)])
    assert result["reported_ecu_count"] == 1
    assert result["ecus"][0]["ecu_code"] == "CPC3"
    assert result["observed_dtc_count"] == 0


def test_v41_ev_dev_fault_before_next_ecu_is_not_a_phantom_control_unit():
    """A DTC near 'General information' belongs to the preceding ECU."""
    text = _header() + [
        "QuickTest 1", "ECU Count 2", "ECUS (2)",
        "CPC3-N127 - Steuergeraet Antriebsstrang",
        "General information",
        "ECU variant CPC3_TEST",
        "FAULT CODES (1)",
        "EV-DEV P26F100 - Diagnoseereignis an der Pumpe. _ S",
        "No environment data",
        "AVAS301-N110 - Akustisches Warnsteuergeraet",
        "General information",
        "ECU variant AVAS_TEST",
        "FAULT CODES (0)",
        "No fault codes",
    ]
    parsed = parse_quicktest_structure(["\\n".join(text)])
    assert parsed["reported_ecu_count"] == 2
    assert parsed["observed_dtc_count"] == 1
    assert [ecu["ecu_code"] for ecu in parsed["ecus"]] == [
        "CPC3", "AVAS301",
    ]
    assert parsed["ecus"][0]["faults"][0]["kind"] == "EV-DEV"
    assert parsed["ecus"][0]["faults"][0]["code"] == "P26F100"
    assert parsed["ecus"][1]["faults"] == []


def test_v41_ecu_location_may_contain_spaces_and_comma():
    """Real ECU names may have long locations: do not tighten the grammar."""
    lines = _header() + [
        "QuickTest 1", "ECU Count 1", "ECUS (1)",
        "BC_R213_LINs-R112/x, M112/x - Synthetisches Steuergeraet",
        "General information",
        "ECU variant BC_R213_TEST",
        "FAULT CODES (0)", "No fault codes",
    ]
    result = parse_quicktest_structure(["\\n".join(lines)])
    assert result["reported_ecu_count"] == 1
    assert result["ecus"][0]["ecu_code"] == "BC_R213_LINs"
    assert result["observed_dtc_count"] == 0


def test_v41_large_quicktest_keeps_explicit_page_and_text_safety_limits(
    tmp_path, monkeypatch,
):
    from ntf_insight.ingestion import quicktest_detailed
    from ntf_insight.ingestion.real_source_parsers import QuickTestPdfParser

    class FakePage:
        def __init__(self, content=""):
            self.content = content

        def extract_text(self):
            return self.content

    class FakeReader:
        is_encrypted = False
        def __init__(self, _path, strict=False):
            self.pages = [FakePage() for _ in range(1001)]

    monkeypatch.setattr(quicktest_detailed, "PdfReader", FakeReader)
    path = tmp_path / "synthetic.pdf"
    path.write_bytes(b"FAKE PDF")
    with pytest.raises(ValueError, match="Seitenanzahl"):
        QuickTestPdfParser("f" * 64).parse(path)

    class TooMuchTextReader:
        is_encrypted = False
        def __init__(self, _path, strict=False):
            self.pages = [FakePage("x" * 8_000_001)]

    monkeypatch.setattr(quicktest_detailed, "PdfReader", TooMuchTextReader)
    with pytest.raises(ValueError, match="Textmenge"):
        QuickTestPdfParser("f" * 64).parse(path)
