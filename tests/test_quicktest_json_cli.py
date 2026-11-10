"""Offline-Tests: vorhandene QuickTest-PDFs ohne Edge/SSO als JSON exportieren."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from ntf_insight.acquisition.quicktest_json import (
    JSON_ORDNER,
    PDF_ORDNER,
    PARSER_VERSION,
    konvertiere_quicktests,
    main,
)

FIN = "WDD12345678901234"
KURZ = FIN[3:]
ANDERE_FIN = "WDD12345678901235"


def _quicktest_pdf(pfad: Path, *, fin: str = FIN, dtcs: int = 1) -> Path:
    """Echter, rein synthetischer XENTRY-PDF-Text in lesbarer PDF-Textebene."""
    from reportlab.pdfgen import canvas

    lines = [
        "TestReport.xml.json",
        f"FIN {fin}",
        "VIN -",
        "DISTANCE 29161 km",
        "DIAG START 2024-01-03 06:58:06.203",
        "VERSION 09/2023",
        "LANGUAGE de",
        "SOURCE XD",
        "QuickTest 1",
        "ECU Count 1",
        "ECUS (1)",
        "CPC3-N127 - Antriebsstrangsteuergeraet",
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
        lines += [
            "EV-DEV P26F100 - Pumpe sporadisch gestoppt. _ S",
            "Name Value (first occurence or unknown) Value (last occurence)",
            "Frequency_Counter - 3",
            "Vehicle_Odometer_in_Low_Resolution 2000.0 km 29161.0 km",
            "Operation_Cycle_Counter - 4",
        ]
    else:
        lines.append("No fault codes")
    pfad.parent.mkdir(parents=True, exist_ok=True)
    pdf = canvas.Canvas(str(pfad), pagesize=(595, 842))
    block = pdf.beginText(40, 800)
    block.setFont("Helvetica", 9)
    for line in lines:
        block.textLine(line)
    pdf.drawText(block)
    pdf.showPage()
    pdf.save()
    return pfad


def _basis(tmp_path: Path, name: str = "FIN Liste DCDC223 NTF PDF") -> Path:
    basis = tmp_path / name
    (basis / PDF_ORDNER).mkdir(parents=True)
    return basis


def _daten(pfad: Path) -> dict:
    return json.loads(pfad.read_text(encoding="utf-8"))


def test_posthoc_basisordner_mit_leerzeichen_exportiert_verlustarmen_quicktest(tmp_path):
    root = _basis(tmp_path)
    original = _quicktest_pdf(root / PDF_ORDNER / FIN / "S1 QuickTest.pdf")
    assert main(["--ordner", str(root)]) == 0
    result_path = root / JSON_ORDNER / FIN / "S1 QuickTest.pdf.json"
    assert result_path.is_file()
    data = _daten(result_path)
    assert data["fin"] == FIN
    assert data["fin_ordner"] == FIN
    assert data["report_id"]
    assert data["diag_start"] == "2024-01-03T06:58:06.203000"
    assert data["distance_km"] == 29161
    assert data["source_sha256"] == hashlib.sha256(original.read_bytes()).hexdigest()
    assert data["quell_pdf"]["relativer_pfad"] == f"{PDF_ORDNER}/{FIN}/S1 QuickTest.pdf"
    assert data["parser_version"] == PARSER_VERSION
    assert data["reported_ecu_count"] == 1
    assert data["observed_dtc_count"] == 1
    assert len(data["page_texts"]) == 1
    assert "P26F100" in data["page_texts"][0]
    assert len(data["ecus"]) == 1
    ecu = data["ecus"][0]
    assert ecu["ecu_code"] == "CPC3"
    assert ecu["metadata"]["ecu_variant"] == "CPC3_R20B"
    assert ecu["faults"][0]["code"] == "P26F100"
    assert ecu["faults"][0]["frequency_counter"] == 3
    assert original.is_file()  # Original nicht veraendert


def test_keine_dtc_erfunden_und_durchlauf_erhalten(tmp_path):
    root = _basis(tmp_path)
    _quicktest_pdf(root / PDF_ORDNER / FIN / "clean.PDF", dtcs=0)
    result = konvertiere_quicktests(root)
    assert result.fehler == 0 and result.konvertiert == 1
    data = _daten(root / JSON_ORDNER / FIN / "clean.PDF.json")
    assert data["observed_dtc_count"] == 0
    assert data["ecus"][0]["faults"] == []
    assert data["header"]["quicktest_runs"][0]["quicktest_number"] == "1"


def test_resume_verwendet_sha256_und_erkennt_ein_pdf_update(tmp_path):
    root = _basis(tmp_path)
    pdf = _quicktest_pdf(root / PDF_ORDNER / FIN / "S1.pdf")
    assert konvertiere_quicktests(root).konvertiert == 1
    original = _daten(root / JSON_ORDNER / FIN / "S1.pdf.json")
    again = konvertiere_quicktests(root)
    assert (again.konvertiert, again.uebersprungen, again.fehler) == (0, 1, 0)
    _quicktest_pdf(pdf, dtcs=0)
    changed = konvertiere_quicktests(root)
    assert (changed.konvertiert, changed.uebersprungen) == (1, 0)
    new = _daten(root / JSON_ORDNER / FIN / "S1.pdf.json")
    assert new["source_sha256"] != original["source_sha256"]
    assert new["observed_dtc_count"] == 0
    forced = konvertiere_quicktests(root, erneut=True)
    assert forced.konvertiert == 1 and forced.uebersprungen == 0


def test_alte_oder_defekte_json_werden_aus_pdf_neu_erstellt(tmp_path):
    root = _basis(tmp_path)
    _quicktest_pdf(root / PDF_ORDNER / FIN / "test.pdf")
    ziel = root / JSON_ORDNER / FIN / "test.pdf.json"
    ziel.parent.mkdir(parents=True)
    ziel.write_text('{"parser_version":"veraltet","source_sha256":"falsch"}', encoding="utf-8")
    assert konvertiere_quicktests(root).konvertiert == 1
    ziel.write_text("{KEINE JSON", encoding="utf-8")
    assert konvertiere_quicktests(root).konvertiert == 1
    assert _daten(ziel)["fin"] == FIN


def test_14stellige_kurz_fin_darf_voll_fin_im_pdf_nur_exakt_zuordnen(tmp_path):
    root = _basis(tmp_path)
    _quicktest_pdf(root / PDF_ORDNER / KURZ / "S1.pdf", fin=FIN)
    result = konvertiere_quicktests(root)
    assert result.konvertiert == 1 and result.fehler == 0
    data = _daten(root / JSON_ORDNER / KURZ / "S1.pdf.json")
    assert data["fin"] == FIN and data["fin_ordner"] == KURZ


def test_pdf_fin_mismatch_wird_abgelehnt_ohne_anderen_fall_zu_erfinden(tmp_path):
    root = _basis(tmp_path)
    _quicktest_pdf(root / PDF_ORDNER / FIN / "fremd.pdf", fin=ANDERE_FIN)
    result = konvertiere_quicktests(root)
    assert result.fehler == 1 and result.konvertiert == 0
    assert not (root / JSON_ORDNER / FIN / "fremd.pdf.json").exists()
    status = _daten(root / JSON_ORDNER / "konvertierungsstatus.json")
    assert status["dateien"][0]["status"] == "Fehler"
    assert "passt nicht" in status["dateien"][0]["fehler"]


def test_beschaedigte_pdf_blockiert_keinen_anderen_bericht(tmp_path):
    root = _basis(tmp_path)
    folder = root / PDF_ORDNER / FIN
    folder.mkdir()
    (folder / "kaputt.pdf").write_bytes(b"%PDF-defekt")
    _quicktest_pdf(folder / "okay.pdf")
    result = konvertiere_quicktests(root)
    assert (result.gefunden, result.konvertiert, result.fehler) == (2, 1, 1)
    assert (root / JSON_ORDNER / FIN / "okay.pdf.json").exists()
    assert main(["--ordner", str(root)]) == 1


def test_fehlender_ordner_gibt_exitcode_zwei_ohne_erstellte_daten(tmp_path):
    assert main(["--ordner", str(tmp_path / "nichts")]) == 2
    assert not (tmp_path / "nichts").exists()


def test_pdf_dir_direkt_als_ordner_und_custom_ausgabe(tmp_path):
    root = _basis(tmp_path)
    _quicktest_pdf(root / PDF_ORDNER / FIN / "S1.pdf")
    custom = tmp_path / "eigene-json"
    assert main([
        "--ordner", str(root / PDF_ORDNER),
        "--ausgabe", str(custom),
    ]) == 0
    assert (custom / FIN / "S1.pdf.json").exists()
    assert not (root / JSON_ORDNER).exists()


def test_leeres_quicktest_verzeichnis_ist_erfolgreicher_leerer_lauf(tmp_path):
    root = _basis(tmp_path)
    result = konvertiere_quicktests(root)
    assert result.gefunden == 0 and result.fehler == 0
    assert _daten(root / JSON_ORDNER / "konvertierungsstatus.json")["pdfs"] == 0


def test_fremde_dateien_werden_nicht_als_pdf_konvertiert(tmp_path):
    root = _basis(tmp_path)
    folder = root / PDF_ORDNER / FIN
    folder.mkdir()
    (folder / "abrufstatus.json").write_text("{}", encoding="utf-8")
    (folder / "irgendwas.txt").write_text("%PDF-1.7", encoding="utf-8")
    (root / PDF_ORDNER / "unbekannt").mkdir()
    _quicktest_pdf(root / PDF_ORDNER / "unbekannt" / "ignored.pdf")
    result = konvertiere_quicktests(root)
    assert result.gefunden == 0
    assert not list((root / JSON_ORDNER).rglob("*.pdf.json"))


def test_keine_symlink_pdfs_oder_fin_ordner_verfolgen(tmp_path):
    root = _basis(tmp_path)
    external = tmp_path / "extern.pdf"
    _quicktest_pdf(external)
    folder = root / PDF_ORDNER / FIN
    folder.mkdir()
    link = folder / "alias.pdf"
    try:
        link.symlink_to(external)
    except (NotImplementedError, OSError):
        pytest.skip("Symlink-Berechtigung unter Windows fehlt.")
    result = konvertiere_quicktests(root)
    assert result.gefunden == 0
    other_root = _basis(tmp_path, "zweite")
    (other_root / PDF_ORDNER / FIN).symlink_to(folder, target_is_directory=True)
    assert konvertiere_quicktests(other_root).gefunden == 0


def test_konvertiere_nur_ausgewaehlte_fins(tmp_path):
    root = _basis(tmp_path)
    _quicktest_pdf(root / PDF_ORDNER / FIN / "S1.pdf")
    _quicktest_pdf(root / PDF_ORDNER / ANDERE_FIN / "S2.pdf", fin=ANDERE_FIN)
    result = konvertiere_quicktests(root, erlaubte_fins={ANDERE_FIN})
    assert result.gefunden == 1 and result.konvertiert == 1
    assert (root / JSON_ORDNER / ANDERE_FIN / "S2.pdf.json").is_file()
    assert not (root / JSON_ORDNER / FIN / "S1.pdf.json").exists()


def test_json_ausgabe_darf_nicht_im_pdf_ordner_liegen(tmp_path):
    root = _basis(tmp_path)
    with pytest.raises(ValueError, match="ausserhalb"):
        konvertiere_quicktests(root, ausgabe=root / PDF_ORDNER / "output")


def test_parser_fehler_keine_falschen_dtc_und_status_mit_fehler(tmp_path):
    root = _basis(tmp_path)
    pfad = root / PDF_ORDNER / FIN / "leer.pdf"
    pfad.parent.mkdir()
    # PDF-Erkennung allein ist kein Beweis fuer lesbare Diagnoseinhalte.
    pfad.write_bytes(b"%PDF-1.7\n%%EOF")
    result = konvertiere_quicktests(root)
    assert result.fehler == 1
    assert not (root / JSON_ORDNER / FIN / "leer.pdf.json").exists()
    assert _daten(root / JSON_ORDNER / "konvertierungsstatus.json")["fehler"] == 1
