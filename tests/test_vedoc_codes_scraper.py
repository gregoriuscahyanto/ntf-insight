"""Offline-Tests fuer den VeDoc-Codes-Abruf (ohne Unternehmensnetz)."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ntf_insight.acquisition import vedoc_codes as m


FIN1 = "W1N12345678901234"
FIN2 = "WDD98765432109876"


def test_lese_fins_utf8_bom_duplikate_kommentare_und_trenner(tmp_path: Path) -> None:
    eingabe = tmp_path / "fins.txt"
    eingabe.write_text(
        "\ufeffFIN\n" + FIN1 + "\n" + FIN1 + " ; " + FIN2 + " # Kommentar\n",
        encoding="utf-8",
    )
    assert m.lese_fins(eingabe) == [FIN1, FIN2]


@pytest.mark.parametrize("ungueltig", ["W1N12345", "W1O12345678901234", "W1I12345678901234"])
def test_lese_fins_ungueltige_eingaben(tmp_path: Path, ungueltig: str) -> None:
    eingabe = tmp_path / "fins.txt"
    eingabe.write_text(FIN1 + "\n" + ungueltig + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Zeile 2"):
        m.lese_fins(eingabe)


def test_modell_und_tabelle_zusammenfuehren() -> None:
    modell = [
        {"code": "01U", "benennung": "", "produktgruppe": "PKW", "quelle": "vehicle"},
        {"code": "B53", "benennung": "BESCHREIBUNG", "codetyp": "sales"},
    ]
    tabelle = [
        {"code": "01U", "benennung": "MB CONNECT", "verwendung": "V"},
        {"code": "B53", "benennung": "BESCHREIBUNG", "verwendung": "V"},
        {"code": "F243", "benennung": "BAUREIHE", "verwendung": "V"},
    ]
    codes = m.kombiniere_codes(modell, tabelle)
    assert [row["code"] for row in codes] == ["01U", "B53", "F243"]
    assert codes[0]["benennung"] == "MB CONNECT"
    assert codes[0]["produktgruppe"] == "PKW"
    assert codes[0]["quelle"] == "vehicle"
    assert codes[1]["codetyp"] == "sales"
    assert all(row["verwendung"] == "V" for row in codes)


def test_text_und_codes_normalisieren() -> None:
    codes = m.normalisiere_codes([
        {"code": "01u", "designation": {"requestedText": " Navigation   und Dienste "}},
        {"code": "I", "benennung": "ein Code ist kein VIN"},
        {"code": "01u", "designation": {"requestedText": "Duplikat"}},
    ])
    assert codes[0]["code"] == "01U"
    assert codes[0]["benennung"] == "Navigation und Dienste"
    assert len(codes) == 2


def test_json_atomar_sichern_und_fortsetzen(tmp_path: Path) -> None:
    ziel = tmp_path / "daten.json"
    daten = {
        "schema_version": "1.0",
        "fahrzeuge": [{"fin": FIN1, "status": "erfolgreich", "codes": [{"code": "01U"}]}],
    }
    m.speichere_json_zuverlaessig(ziel, daten)
    assert json.loads(ziel.read_text(encoding="utf-8")) == daten
    assert m.einlesen_alte_ergebnisse(ziel)[FIN1]["status"] == "erfolgreich"
    assert not list(tmp_path.glob("*.tmp"))


def test_beschaedigtes_json_wird_nicht_ueberschrieben(tmp_path: Path) -> None:
    ziel = tmp_path / "daten.json"
    ziel.write_text("{nicht-json", encoding="utf-8")
    with pytest.raises(ValueError, match="kein gueltiges"):
        m.einlesen_alte_ergebnisse(ziel)


def test_konsolenargumente_und_sicherheit() -> None:
    options = m.kommandozeile(["fins.txt", "--ausgabe", "daten.json"])
    assert options.fin_datei == Path("fins.txt")
    assert options.ausgabe == Path("daten.json")
    assert "VehicleArrangement.html" in m.VEDOC_URL
    assert "password" not in options.__dict__


def test_vorhandene_fin_ohne_edge_wiederverwenden(tmp_path: Path) -> None:
    eingabe = tmp_path / "fins.txt"
    eingabe.write_text(FIN1 + "\n", encoding="utf-8")
    ziel = tmp_path / "daten.json"
    m.speichere_json_zuverlaessig(ziel, {
        "schema_version": "1.0",
        "fahrzeuge": [{
            "fin": FIN1, "status": "erfolgreich",
            "anzahl_codes": 1, "codes": [{"code": "01U"}],
        }],
    })
    optionen = SimpleNamespace(
        fin_datei=eingabe, ausgabe=ziel, erneut=False, profil=tmp_path / "edge",
        pause=1.5, anmeldezeit=1, ladezeit=1,
    )
    assert m.abrufen(optionen) == 0
    assert not optionen.profil.exists()


def test_input_und_output_must_not_match(tmp_path: Path) -> None:
    eingabe = tmp_path / "fins.txt"
    eingabe.write_text(FIN1 + "\n", encoding="utf-8")
    optionen = SimpleNamespace(fin_datei=eingabe, ausgabe=eingabe)
    with pytest.raises(ValueError, match="nicht die FIN"):
        m.abrufen(optionen)
