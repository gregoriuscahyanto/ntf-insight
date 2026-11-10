"""Synthetische Offline-Tests der frei waehlbaren VeDoc-Hardwarehistorie."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from openpyxl import load_workbook

from scripts import vedoc_dcdc223_seriennummern as m

FIN = "WDD12345678901234"
FIN_FREMD = "WDD12345678901235"


def _zeile(
    objekt="CPC3", attribut="Seriennummer", fin=FIN, zeit="03.11.2026 12:00:00",
    vorher="00123", nachher="00456",
):
    werte = {
        "parentObjectIdentifier": objekt, "attributeName": attribut,
        "date": zeit, "oldValue": vorher, "newValue": nachher,
        "pathToAttribute": f"{fin} / {objekt}",
    }
    return "<tr>" + "".join(
        f'<td><span data-ng-bind="historyTable_rec.{feld}">{wert}</span></td>'
        for feld, wert in werte.items()
    ) + "</tr>"


def _html(*zeilen):
    return '<table id="historyTable"><tbody>' + "".join(zeilen) + "</tbody></table>"


def test_freie_objektnamen_ohne_teiltreffer_und_fremde_attribute():
    quelle = _html(
        _zeile(objekt="DCDC223", nachher="niemals"),
        _zeile(objekt="CPC3A", nachher="niemals"),
        _zeile(attribut="Hardwarestand", nachher="niemals"),
        _zeile(objekt="cpc3", attribut="seriennummer", nachher="000999"),
        _zeile(nachher="000456"),
    )
    gefunden = m.lese_historie_aus_html(quelle, FIN, "CPC3", "Seriennummer")
    assert [x.neuer_wert for x in gefunden] == ["000999", "000456"]
    assert m.lese_historie_aus_html(quelle, FIN, "DCDC223", "Seriennummer")[0].neuer_wert == "niemals"
    assert [x.neuer_wert for x in m.lese_historie_aus_html(
        quelle, FIN, "CPC3", "Hardwarestand",
    )] == ["niemals"]


def test_fremde_fin_oder_fehlende_volles_fin_werden_zurueckgewiesen():
    with pytest.raises(ValueError, match="anderen FIN"):
        m.lese_historie_aus_html(_html(_zeile(fin=FIN_FREMD)), FIN, "CPC3")
    with pytest.raises(ValueError, match="bestaetigte Voll-FIN"):
        m.lese_historie_aus_html(_html(_zeile(fin="UNBEKANNT")), FIN, "CPC3")


def test_attribut_hardwarestand_historie_ohne_annahme_ueber_seriennummer():
    quelle = _html(
        _zeile(attribut="Hardwarestand", zeit="05.11.2026 11:30:00", vorher="HW02", nachher="HW03"),
        _zeile(attribut="Hardwarestand", zeit="03.11.2026 11:30:00", vorher="HW01", nachher="HW02"),
    )
    liste = m.lese_historie_aus_html(quelle, FIN, "CPC3", "Hardwarestand")
    ergebnis = m._bewerte_historie(FIN, liste, objekt="CPC3", attribut="Hardwarestand")
    assert ergebnis.status == "gefunden"
    assert ergebnis.objekt == "CPC3"
    assert ergebnis.attribut == "Hardwarestand"
    assert ergebnis.letzter_neuer_wert == "HW03"
    assert len(ergebnis.aenderungen) == 2


def test_json_enthaelt_frei_gewaehltes_objekt_und_neutrales_wertfeld(tmp_path):
    ergebnis = m._ergebnis(
        FIN, "gefunden", seriennummer="HW03", objekt="CPC3", attribut="Hardwarestand",
        aenderungen=(m.SeriennummerAenderung("05.11.2026 11:30:00", "HW02", "HW03"),),
    )
    ziel = tmp_path / "cpc3.json"
    m._schreibe_json(ziel, [ergebnis], objekt="CPC3", attribut="Hardwarestand")
    daten = json.loads(ziel.read_text("utf-8"))
    assert daten["objekt"] == "CPC3"
    assert daten["attribut"] == "Hardwarestand"
    assert daten["fahrzeuge"][0]["objekt"] == "CPC3"
    assert daten["fahrzeuge"][0]["letzter_neuer_wert"] == "HW03"
    assert daten["fahrzeuge"][0]["seriennummer"] is None
    assert daten["fahrzeuge"][0]["aenderungen"][0]["alter_wert"] == "HW02"


def test_excel_zeigt_gewaehltes_objekt_und_attribut(tmp_path):
    ergebnis = m._ergebnis(
        FIN, "gefunden", seriennummer="000333", objekt="CPC3", attribut="Hardwarestand",
        aenderungen=(m.SeriennummerAenderung("05.11.2026 11:30:00", "000111", "000333"),),
    )
    ausgabe = tmp_path / "cpc3.xlsx"
    m._schreibe_excel(ausgabe, [ergebnis], objekt="CPC3", attribut="Hardwarestand")
    wb = load_workbook(ausgabe)
    assert wb.sheetnames == ["Uebersicht", "Historie"]
    assert wb["Uebersicht"]["B2"].value == "CPC3"
    assert wb["Uebersicht"]["C2"].value == "000333"
    assert wb["Historie"]["B2"].value == "CPC3"
    assert wb["Historie"]["C2"].value == "Hardwarestand"
    assert wb["Historie"]["E2"].value == "000111"
    assert wb["Historie"]["E2"].data_type == "s"


def test_standardobjekt_und_alte_dateinamen_bleiben_kompatibel():
    assert m._STEUERGERAET == "DCDC223"
    assert m._dateistamm("DCDC223", "Seriennummer") == "dcdc223_seriennummern"
    assert m._dateistamm("CPC3", "Seriennummer") == "cpc3_seriennummern"
    assert m._dateistamm("CPC3", "Hardwarestand") == "cpc3_hardwarestand"
    assert m._dateistamm("CPC3", "Seriennummer") != m._dateistamm("CPC3", "Hardwarestand")


def test_usernamen_sind_lesbar_und_dateistamm_bleibt_sicher():
    for name in ("", " ", "A\nB", "A\tB", "A\u202eB", "X" * 121):
        with pytest.raises(ValueError, match="--objekt"):
            m.pruefe_historienziel(name, feld="--objekt")
    assert m.pruefe_historienziel("  CPC3  ", feld="--objekt") == "CPC3"
    name = m._dateistamm("CPC3/../../", "Seriennummer")
    assert "/" not in name and "\\" not in name and ".." not in name
    assert len(name) < 120
    assert m._dateistamm("CPC3/ A", "Seriennummer") != m._dateistamm("CPC3 A", "Seriennummer")


def test_fremdattr_status_nicht_falsch_als_seriennummer():
    result = m._bewerte_historie(FIN, (), objekt="CPC3", attribut="Hardwarestand")
    assert result.status == "keine_attributaenderung"
    leer = m._bewerte_historie(
        FIN, (m.SeriennummerAenderung("03.11.2026 12:00:00", "HW01", None),),
        objekt="CPC3", attribut="Hardwarestand",
    )
    assert leer.status == "neuer_wert_fehlt"


def test_frei_gewaehlter_filter_wird_an_playwright_uebergeben(monkeypatch):
    class Locator:
        def __init__(self):
            self.actions = []

        def count(self):
            return 1

        def is_visible(self):
            return True

        def click(self, **kwargs):
            self.actions.append(("click", kwargs))

        def wait_for(self, **kwargs):
            self.actions.append(("wait_for", kwargs))

        def fill(self, text):
            self.actions.append(("fill", text))

    class Seite:
        def __init__(self):
            self.selectors = {}

        def locator(self, selector):
            return self.selectors.setdefault(selector, Locator())

        def wait_for_function(self, js, *, arg, timeout):
            assert arg == FIN

        def wait_for_timeout(self, milliseconds):
            pass

    page = Seite()
    aufrufe = []

    def fake_warten(seite, fin, filter_feld, wartezeit_ms, *, objekt, attribut):
        aufrufe.append((fin, objekt, attribut, wartezeit_ms))
        return m._ergebnis(fin, "gefunden", "00123", objekt=objekt, attribut=attribut)

    monkeypatch.setattr(m, "_warte_auf_historieneintraege", fake_warten)
    res = m._abfrage(page, FIN, 1000, objekt="CPC3", attribut="Hardwarestand")
    assert res.objekt == "CPC3"
    assert res.attribut == "Hardwarestand"
    assert ("fill", "CPC3") in page.locator(m._FILTER).actions
    assert ("fill", "DCDC223") not in page.locator(m._FILTER).actions
    assert aufrufe == [(FIN, "CPC3", "Hardwarestand", 20000)]


def test_cli_optionen_vor_browser_validieren(tmp_path):
    eingabe = tmp_path / "fins.txt"
    eingabe.write_text(FIN, encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        m.historie_main(["--eingabe", str(eingabe), "--objekt", "A\nB"])
    assert exc.value.code == 2
    with pytest.raises(SystemExit) as exc:
        m.historie_main(["--eingabe", str(eingabe), "--attribut", " "])
    assert exc.value.code == 2



def test_cli_komplett_offline_schreibt_objektbezogene_dateien(monkeypatch, tmp_path):
    """Inklusive Argumente, Browsergrenze, JSON, Excel und sicherer Defaultablage."""
    import sys
    from types import ModuleType

    monkeypatch.chdir(tmp_path)
    datei = tmp_path / "FIN-Liste SensorIssue.txt"
    datei.write_text(FIN + "\n", encoding="utf-8")
    aufrufe = []

    seite = SimpleNamespace(goto=lambda *args, **kwargs: None)

    class Kontext:
        pages = [seite]

        def close(self):
            pass

    class Manager:
        def __enter__(self):
            return SimpleNamespace(chromium=SimpleNamespace(
                launch_persistent_context=lambda **kwargs: Kontext(),
            ))

        def __exit__(self, *_args):
            return False

    fake_api = ModuleType("playwright.sync_api")
    fake_api.TimeoutError = TimeoutError
    fake_api.sync_playwright = lambda: Manager()
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake_api)
    monkeypatch.setattr(m, "_anmelden", lambda *_args, **kwargs: seite)
    monkeypatch.setattr(m, "_fahrzeugdaten_oeffnen", lambda *_args, **kwargs: None)

    def abrufen(page, fin, timeout, historie_timeout, *, objekt, attribut):
        aufrufe.append((objekt, attribut, fin))
        return m._ergebnis(
            fin, "gefunden", "HW05", objekt=objekt, attribut=attribut,
            aenderungen=(m.SeriennummerAenderung("01.11.2026 12:00:00", "HW04", "HW05"),),
        )

    monkeypatch.setattr(m, "_abfrage", abrufen)
    assert m.historie_main([
        "--eingabe", str(datei), "--objekt", "CPC3", "--attribut", "Hardwarestand",
        "--login-manuell",
    ]) == 0
    pfad = tmp_path / "data/processed/FIN-Liste SensorIssue/vedoc_historie"
    assert (pfad / "cpc3_hardwarestand.json").exists()
    assert (pfad / "cpc3_hardwarestand.xlsx").exists()
    assert aufrufe == [("CPC3", "Hardwarestand", FIN)]
    daten = json.loads((pfad / "cpc3_hardwarestand.json").read_text("utf-8"))
    assert daten["fahrzeuge"][0]["letzter_neuer_wert"] == "HW05"
    assert daten["fahrzeuge"][0]["seriennummer"] is None

    # Derselbe Ordner kann auch eine andere Hardware enthalten:
    assert m.main(["--eingabe", str(datei), "--ausgabe", str(pfad), "--login-manuell"]) == 0
    assert (pfad / "dcdc223_seriennummern.json").exists()
    assert (pfad / "cpc3_hardwarestand.json").exists()
    assert aufrufe[1] == ("DCDC223", "Seriennummer", FIN)



KURZ_FIN = "1671061B000001"
VOLL_FIN = "W1N" + KURZ_FIN


def test_vedoc_kurz_fin_aus_txt_unveraendert_laden(tmp_path):
    txt = tmp_path / "kurzliste.txt"
    txt.write_text(KURZ_FIN + "\n" + VOLL_FIN + "\n" + KURZ_FIN, encoding="utf-8")
    assert m.lade_fins(txt) == [KURZ_FIN, VOLL_FIN]


def test_vedoc_historie_bestaetigt_kurz_fin_bei_17stelliger_anzeige():
    quelltext = _html(
        _zeile(fin=VOLL_FIN, nachher="HW02"),
        _zeile(fin=KURZ_FIN, nachher="HW03"),
    )
    aenderungen, anzahl, bestaetigt = m._historienmoment(
        quelltext, KURZ_FIN, "CPC3", "Seriennummer",
    )
    assert bestaetigt is True
    assert anzahl == 2
    assert [row.neuer_wert for row in aenderungen] == ["HW02", "HW03"]


def test_vedoc_kurz_fin_verwirft_fremde_und_mehrdeutige_voll_fins():
    fremd = _html(_zeile(fin="W1N1671061B000002"))
    with pytest.raises(ValueError, match="anderen FIN"):
        m.lese_historie_aus_html(fremd, KURZ_FIN, "CPC3")
    zweideutig = _html(
        _zeile(fin=VOLL_FIN), _zeile(fin="WDD" + KURZ_FIN),
    )
    with pytest.raises(ValueError, match="mehrdeutig"):
        m._historienmoment(zweideutig, KURZ_FIN, "CPC3", "Seriennummer")


def test_vedoc_kurz_fin_ui_pruefung_akzeptiert_17stellige_anzeige(monkeypatch):
    class Feld:
        def __init__(self):
            self.wert = None

        def fill(self, wert):
            self.wert = wert

        def click(self, **kwargs):
            pass

        def wait_for(self, **kwargs):
            pass

    class Seite:
        def __init__(self):
            self.felder = {}
            self.js = ""

        def locator(self, name):
            return self.felder.setdefault(name, Feld())

        def wait_for_function(self, js, *, arg, timeout):
            self.js = js
            assert arg == KURZ_FIN

    seite = Seite()
    monkeypatch.setattr(m, "_fahrzeugdaten_oeffnen", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        m, "_warte_auf_historieneintraege",
        lambda seite, fin, filter_feld, wartezeit_ms, *, objekt, attribut:
            m._ergebnis(fin, "gefunden", "000111", objekt=objekt, attribut=attribut),
    )
    result = m._abfrage(seite, KURZ_FIN, 1000, objekt="CPC3")
    assert result.fin == KURZ_FIN
    assert seite.locator(m._FIN_EINGABE).wert == KURZ_FIN
    assert "wert.slice(3) === fin" in seite.js
    assert seite.locator(m._FILTER).wert == "CPC3"
