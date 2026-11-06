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


def html_zeile(
    fin=FIN_1, objekt="DCDC223", attribut="Seriennummer",
    zeit="03.11.2026 13:27:22", alt="000123", neu="000456",
):
    werte = {"date": zeit, "attributeName": attribut,
             "parentObjectIdentifier": objekt, "pathToAttribute": f"{fin} / {objekt}",
             "oldValue": alt, "newValue": neu}
    return "<tr>" + "".join(
        f'<td><span data-ng-bind="historyTable_rec.{feld}">{wert}</span></td>'
        for feld, wert in werte.items()
    ) + "</tr>"


def html_tabelle(*zeilen: str) -> str:
    return '<table id="historyTable"><tbody>' + ''.join(zeilen) + '</tbody></table>


def test_lade_fins_bom_kommentare_doppelte(tmp_path):
    quelle = tmp_path / "fins.txt"
    quelle.write_text("\ufeff# intern\n" + FIN_1.lower() + "\n\n" + FIN_1 + "\n" + FIN_2)
    assert modul.lade_fins(quelle) == [FIN_1, FIN_2]


def test_ungueltige_fin_vor_browser_verhindern(tmp_path):
    quelle = tmp_path / "fins.txt"
    quelle.write_text(FIN_1 + "\nWDD12345I78901234\n")
    with pytest.raises(ValueError, match="Zeile 2"):
        modul.lade_fins(quelle)


def test_lokalisiert_nur_dcdc223_seriennummer_und_beide_werte():
    dokument = html_tabelle(
        html_zeile(objekt="CPC3", neu="falsch"),
        html_zeile(attribut="Datum des ersten Zugriffs", neu="datum"),
        html_zeile(alt="000001234", neu="000004567"),
    )
    ergebnis = modul.lese_historie_aus_html(dokument, FIN_1)
    assert ergebnis == (modul.SeriennummerAenderung("03.11.2026 13:27:22", "000001234", "000004567"),)


def test_ohne_seriennummer_aenderung_wird_nichts_erfunden():
    auszug = html_tabelle(html_zeile(attribut="Datum des ersten Zugriffs", neu="datum"))
    assert modul.lese_historie_aus_html(auszug, FIN_1) == ()
    assert modul._bewerte_historie(FIN_1, ()).status == "keine_seriennummer_aenderung"


def test_fremde_fin_und_fehlender_pfad_abweisen():
    with pytest.raises(ValueError, match="anderen FIN"):
        modul.lese_historie_aus_html(html_tabelle(html_zeile(fin=FIN_2)), FIN_1)
    with pytest.raises(ValueError, match="bestaetigte Voll-FIN"):
        modul.lese_historie_aus_html(html_tabelle(html_zeile(fin="UNBEKANNT")), FIN_1)
    with pytest.raises(ValueError, match="Historientabelle"):
        modul.lese_historie_aus_html("<html></html>", FIN_1)


def test_mehrere_historieneintraege_chronologisch_und_letzter_wert():
    zeilen = html_tabelle(
        html_zeile(zeit="10.11.2026 09:00:00", alt="002", neu="003"),
        html_zeile(zeit="03.11.2026 09:00:00", alt="001", neu="002"),
    )
    ergebnis = modul._bewerte_historie(FIN_1, modul.lese_historie_aus_html(zeilen, FIN_1))
    assert ergebnis.status == "gefunden"
    assert ergebnis.seriennummer == "003"
    assert [eintrag.neuer_wert for eintrag in ergebnis.aenderungen] == ["002", "003"]


def test_mehrdeutige_oder_ungueltige_zeitstempel_keine_letzte_seriennummer():
    eintraege = modul.lese_historie_aus_html(html_tabelle(
        html_zeile(neu="002"), html_zeile(neu="003")
    ), FIN_1)
    ergebnis = modul._bewerte_historie(FIN_1, eintraege)
    assert ergebnis.status == "mehrdeutig"
    assert ergebnis.seriennummer is None
    falsch = modul._bewerte_historie(FIN_1, (modul.SeriennummerAenderung("unbekannt", "001", "002"),))
    assert falsch.status == "zeitstempel_ungueltig"
    assert falsch.seriennummer is None


def test_nur_unternehmensdomain_fuer_fin_suche():
    assert modul.pruefe_vedoc_url("https://test.mercedes-benz.com/ui/homepage.html")
    for url in ("", "http://test.mercedes-benz.com/ui", "https://mercedes-benz.com.evil.com/ui"):
        with pytest.raises(ValueError):
            modul.pruefe_vedoc_url(url)


def test_json_und_excel_enthalten_historie_und_schuetzen_vor_formeln(tmp_path):
    daten = [
        modul.Ergebnis(FIN_1, "DCDC223", "000340001234", "gefunden", "", "2026-11-06T10:00:00+00:00",
                      (modul.SeriennummerAenderung("01.11.2026 13:30:00", "000111", "000340001234"),)),
        modul.Ergebnis(FIN_2, "DCDC223", "=1+1", "gefunden", "", "2026-11-06T10:00:00+00:00",
                      (modul.SeriennummerAenderung("05.11.2026 13:30:00", "+SUM(A1:A2)", "=1+1"),)),
    ]
    json_pfad, excel_pfad = tmp_path / "ergebnis.json", tmp_path / "ergebnis.xlsx"
    modul._schreibe_json(json_pfad, daten)
    modul._schreibe_excel(excel_pfad, daten)
    gespeichert = json.loads(json_pfad.read_text(encoding="utf-8"))
    assert gespeichert["quelle"] == "VeDoc/Historie"
    assert gespeichert["fahrzeuge"][0]["aenderungen"][0]["alter_wert"] == "000111"
    workbook = load_workbook(excel_pfad, data_only=False)
    assert workbook.sheetnames == ["DCDC223", "Historie"]
    uebersicht, historie = workbook["DCDC223"], workbook["Historie"]
    assert uebersicht["C2"].value == "000340001234"
    assert uebersicht["C3"].value == "=1+1"
    assert uebersicht["C3"].data_type == "s"
    assert historie["E2"].value == "000111"
    assert historie["F2"].value == "000340001234"
    assert historie["E3"].value == "+SUM(A1:A2)"
    assert historie["E3"].data_type == "s"
    assert historie["F3"].data_type == "s"
    assert uebersicht.freeze_panes == historie.freeze_panes == "A2"


def test_steuergeraete_reiter_wird_nicht_verwendet():
    assert modul._TAB == 'li[heading="Historie"] a'
    assert 'historyTable_filterExpression' in modul._FILTER
    assert 'historyTable' in modul._FILTER_SCHALTER


def test_vedoc_url_ist_als_standard_hinterlegt():
    assert modul.VEDOC_START == (
        "https://prod.core.public.vedoc.i.mercedes-benz.com/ui/homepage.html"
    )
    assert modul.pruefe_vedoc_url(modul.VEDOC_START) == modul.VEDOC_START


def test_gespeicherte_credentials_ohne_rueckfrage(monkeypatch):
    monkeypatch.setattr(modul, "_lade_zugangsdaten", lambda: ("gespeicherter-nutzer", "geheim"))
    monkeypatch.setattr("builtins.input", lambda prompt: pytest.fail("Unnoetige Eingabe"))
    monkeypatch.setattr(modul.getpass, "getpass", lambda prompt: pytest.fail("Unnoetige Eingabe"))
    assert modul._zugangsdaten_fuer_lauf() == ("gespeicherter-nutzer", "geheim")


def test_keine_gespeicherten_credentials_fuehrt_zu_powershell_eingabe(monkeypatch):
    prompts = []
    monkeypatch.setattr(modul, "_lade_zugangsdaten", lambda: None)
    monkeypatch.setattr("builtins.input", lambda prompt: prompts.append(prompt) or " mb-nutzer ")
    monkeypatch.setattr(modul.getpass, "getpass", lambda prompt: prompts.append(prompt) or "test-passwort")
    assert modul._zugangsdaten_fuer_lauf() == ("mb-nutzer", "test-passwort")
    assert prompts == ["Mercedes-Benz-Benutzerkennung: ", "Mercedes-Benz-Passwort (verdeckt): "]


def test_ssologin_host_strikt_validiert():
    assert modul._ist_sso_seite("https://login.mercedes-benz.com/abc")
    assert not modul._ist_sso_seite("https://login.mercedes-benz.com.evil.example/abc")
    assert not modul._ist_sso_seite("http://login.mercedes-benz.com/abc")
    assert not modul._ist_sso_seite("https://other.mercedes-benz.com/abc")


class FakeLocator:
    def __init__(self, shown=False):
        self.shown = shown
        self.actions = []
        self.first = self

    def count(self):
        return 1 if self.shown else 0

    def is_visible(self):
        return self.shown

    def fill(self, value):
        self.actions.append(("fill", value))

    def click(self, **kwargs):
        self.actions.append(("click", kwargs))


class FakePage:
    def __init__(self, url: str, *, sichtbar=()):
        self.url = url
        self.eintraege = {selector: FakeLocator(True) for selector in sichtbar}

    def locator(self, selector):
        return self.eintraege.setdefault(selector, FakeLocator())

    def is_closed(self):
        return False


def test_credentials_nur_an_echten_sso_host_uebergeben():
    fake = FakePage("https://login.mercedes-benz.com.evil.example/",
                    sichtbar=("#userid", "#next-btn", "#password", "#loginSubmitButton"))
    status = {"benutzer": False, "passwort": False}
    modul._sso_felder_ausfuellen(fake, ("user", "secret"), status)
    assert all(not eintrag.actions for eintrag in fake.eintraege.values())
    assert status == {"benutzer": False, "passwort": False}
    fake.url = "https://login.mercedes-benz.com/"
    modul._sso_felder_ausfuellen(fake, ("user", "secret"), status)
    assert fake.locator("#userid").actions == [("fill", "user")]
    assert status == {"benutzer": True, "passwort": False}
    modul._sso_felder_ausfuellen(fake, ("user", "secret"), status)
    assert fake.locator("#password").actions == [("fill", "secret")]
    assert status == {"benutzer": True, "passwort": True}


def test_anmelden_bei_bereits_offenem_vedoc_ohne_credentials(monkeypatch):
    fake = FakePage(modul.VEDOC_START, sichtbar=(modul._FIN_EINGABE,))
    ctx = type("FakeContext", (), {"pages": [fake]})()
    monkeypatch.setattr(modul, "_zugangsdaten_fuer_lauf", lambda: pytest.fail("Unnoetige Eingabe"))
    assert modul._anmelden(ctx, vedoc_host="prod.core.public.vedoc.i.mercedes-benz.com",
                          login_timeout_s=1) is fake
