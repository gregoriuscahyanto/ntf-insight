"""Offline-Tests fuer den eigenstaendigen VeDoc-Exporter (ohne echte FINs)."""

import importlib.util
import json
from pathlib import Path

import pytest
from openpyxl import load_workbook

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "vedoc_dcdc223_seriennummern.py"
spezifikation = importlib.util.spec_from_file_location("vedoc_export", SCRIPT)
modul = importlib.util.module_from_spec(spezifikation)
import sys
sys.modules[spezifikation.name] = modul
spezifikation.loader.exec_module(modul)
FIN_1 = "WDD12345678901234"
FIN_2 = "WDD98765432101234"


def html_zeile(bezeichnung: str, seriennummer: str) -> str:
    return (
        '<tr><td><span data-ng-bind="controlUnitTable_rec.cuDesignation">'
        + bezeichnung + '</span></td><td><span data-ng-bind="controlUnitTable_rec.activeState.serialNumber">'
        + seriennummer + '</span></td></tr>'
    )


def html_tabelle(*zeilen: str) -> str:
    return '<table id="controlUnitTable"><tbody>' + ''.join(zeilen) + '</tbody></table>'


def test_lade_fins_bom_kommentare_doppelte(tmp_path):
    quelle = tmp_path / "fins.txt"
    quelle.write_text("\ufeff# intern\n" + FIN_1.lower() + "\n\n" + FIN_1 + "\n" + FIN_2)
    assert modul.lade_fins(quelle) == [FIN_1, FIN_2]


def test_ungueltige_fin_vor_browser_verhindern(tmp_path):
    quelle = tmp_path / "fins.txt"
    quelle.write_text(FIN_1 + "\nWDD12345I78901234\n")
    with pytest.raises(ValueError, match="Zeile 2"):
        modul.lade_fins(quelle)


def test_lokalisiert_seriennummer_in_der_richtigen_zeile():
    auszug = html_tabelle(
        html_zeile("CPC3", "99999999"),
        html_zeile("DCDC223", "0003456000123"),
    )
    assert modul.lese_seriennummer_aus_html(auszug) == (True, "0003456000123")


def test_fehlende_und_mehrdeutige_seriennummer():
    assert modul.lese_seriennummer_aus_html(html_tabelle(html_zeile("CPC3", "12"))) == (False, None)
    assert modul.lese_seriennummer_aus_html(html_tabelle(html_zeile("DCDC223", ""))) == (True, None)
    with pytest.raises(ValueError, match="mehrfach"):
        modul.lese_seriennummer_aus_html(
            html_tabelle(html_zeile("DCDC223", "1"), html_zeile("DCDC223", "2"))
        )


def test_nur_unternehmensdomain_fuer_fin_suche():
    assert modul.pruefe_vedoc_url("https://test.mercedes-benz.com/ui/homepage.html")
    for url in ("", "http://test.mercedes-benz.com/ui", "https://mercedes-benz.com.evil.com/ui"):
        with pytest.raises(ValueError):
            modul.pruefe_vedoc_url(url)


def test_json_und_excel_enthalten_text_statt_formeln(tmp_path):
    daten = [
        modul.Ergebnis(FIN_1, "DCDC223", "000340001234", "gefunden", "", "2026-11-06T10:00:00+00:00"),
        modul.Ergebnis(FIN_2, "DCDC223", "=1+1", "gefunden", "", "2026-11-06T10:00:00+00:00"),
    ]
    json_pfad, excel_pfad = tmp_path / "ergebnis.json", tmp_path / "ergebnis.xlsx"
    modul._schreibe_json(json_pfad, daten)
    modul._schreibe_excel(excel_pfad, daten)
    gespeichert = json.loads(json_pfad.read_text(encoding="utf-8"))
    assert gespeichert["fahrzeuge"][0]["seriennummer"] == "000340001234"
    workbook = load_workbook(excel_pfad, data_only=False)
    sheet = workbook["DCDC223"]
    assert sheet["C2"].value == "000340001234"
    assert sheet["C2"].data_type == "s"
    assert sheet["C3"].value == "=1+1"
    assert sheet["C3"].data_type == "s"
    assert sheet.freeze_panes == "A2"
