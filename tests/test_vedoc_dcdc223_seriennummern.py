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
    return '<table id="historyTable"><tbody>' + ''.join(zeilen) + '</tbody></table>'


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


def test_browser_disconnect_stoppt_aktiv_wartenden_sso_loop_sofort():
    browser = type('Browser', (), {'is_connected': lambda self: False})()
    kontext = type('Kontext', (), {'pages': [FakePage(modul.VEDOC_START)]})()
    with pytest.raises(modul.VeDocBrowserFehler, match='Verbindung'):
        modul._anmelden(kontext, vedoc_host='prod.core.public.vedoc.i.mercedes-benz.com',
                        login_timeout_s=240, browser=browser)


def test_abgestuerzter_browser_tab_wird_erkannt(monkeypatch):
    seite = FakePage('https://login.mercedes-benz.com/', sichtbar=('#userid',))
    events = {}
    seite.on = lambda name, callback: events.__setitem__(name, callback)
    seite.wait_for_timeout = lambda ms: events['crash'](seite)
    kontext = type('Kontext', (), {'pages': [seite]})()
    browser = type('Browser', (), {'is_connected': lambda self: True})()
    monkeypatch.setattr(modul, '_zugangsdaten_fuer_lauf',
                        lambda: pytest.fail('Im manuellen Login ist kein Keyring erlaubt.'))
    with pytest.raises(modul.VeDocBrowserFehler, match='abgestuerzt'):
        modul._anmelden(kontext, vedoc_host='prod.core.public.vedoc.i.mercedes-benz.com',
                        login_timeout_s=30, browser=browser, auto_login=False)


def test_manueller_login_laesst_kennwort_unberuehrt(monkeypatch):
    sso = FakePage('https://login.mercedes-benz.com/', sichtbar=('#userid', '#password'))
    bereit = FakePage(modul.VEDOC_START, sichtbar=(modul._FIN_EINGABE,))
    sso.wait_for_timeout = lambda ms: None
    class Kontext:
        def __init__(self):
            self.counter = 0
        @property
        def pages(self):
            self.counter += 1
            return [sso] if self.counter == 1 else [bereit]
    monkeypatch.setattr(modul, '_zugangsdaten_fuer_lauf',
                        lambda: pytest.fail('Keine Anmeldedaten im manuellen Modus auslesen.'))
    assert modul._anmelden(Kontext(), vedoc_host='prod.core.public.vedoc.i.mercedes-benz.com',
                          login_timeout_s=30, auto_login=False) is bereit
    assert all(not locator.actions for locator in sso.eintraege.values())


def test_normales_schliessen_von_ssopopup_ist_nicht_automatisch_browserabsturz():
    assert not modul._browserfehler(RuntimeError('Target page, context or browser has been closed'))
    assert modul._browserfehler(RuntimeError('Page crashed'))


def test_login_absturz_ueberschreibt_keine_bestehenden_exporte(tmp_path, monkeypatch):
    import sys
    from types import ModuleType, SimpleNamespace

    eingabe = tmp_path / 'fins.txt'
    eingabe.write_text(FIN_1)
    ausgabe = tmp_path / 'ausgabe'
    ausgabe.mkdir()
    json_datei = ausgabe / 'dcdc223_seriennummern.json'
    xlsx_datei = ausgabe / 'dcdc223_seriennummern.xlsx'
    json_datei.write_bytes(b'altes-json')
    xlsx_datei.write_bytes(b'altes-excel')

    class Kontext:
        @property
        def pages(self):
            page = SimpleNamespace(goto=lambda *a, **kw: None)
            return [page]

        def on(self, name, callback):
            if name == "close":
                callback()

        def close(self):
            pass

    class PlaywrightManager:
        def __enter__(self):
            return SimpleNamespace(chromium=SimpleNamespace(
                launch_persistent_context=lambda **kwargs: Kontext()
            ))
        def __exit__(self, *_args):
            return False

    package = ModuleType('playwright')
    sync_api = ModuleType('playwright.sync_api')
    sync_api.TimeoutError = TimeoutError
    sync_api.sync_playwright = lambda: PlaywrightManager()
    package.sync_api = sync_api
    monkeypatch.setitem(sys.modules, 'playwright', package)
    monkeypatch.setitem(sys.modules, 'playwright.sync_api', sync_api)

    assert modul.main(['--eingabe', str(eingabe), '--ausgabe', str(ausgabe)]) == 3
    assert json_datei.read_bytes() == b'altes-json'
    assert xlsx_datei.read_bytes() == b'altes-excel'


def test_temporaeres_profil_und_nur_login_ohne_fin_export(tmp_path, monkeypatch):
    import sys
    from types import ModuleType, SimpleNamespace

    start_parameter = []
    geschlossen = []
    class Kontext:
        def __init__(self):
            self.seite = FakePage(modul.VEDOC_START, sichtbar=(modul._FIN_EINGABE,))
            self.seite.goto = lambda *args, **kwargs: None
        @property
        def pages(self):
            return [self.seite]
        def on(self, name, callback):
            pass
        def close(self):
            geschlossen.append(True)

    def starte(**kwargs):
        start_parameter.append(kwargs)
        return Kontext()

    class Manager:
        def __enter__(self):
            return SimpleNamespace(chromium=SimpleNamespace(launch_persistent_context=starte))
        def __exit__(self, *_args):
            return False

    package, api = ModuleType('playwright'), ModuleType('playwright.sync_api')
    api.TimeoutError = TimeoutError
    api.sync_playwright = lambda: Manager()
    package.sync_api = api
    monkeypatch.setitem(sys.modules, 'playwright', package)
    monkeypatch.setitem(sys.modules, 'playwright.sync_api', api)
    ziel = tmp_path / 'soll_nicht_existieren'
    assert modul.main(['--nur-login', '--ausgabe', str(ziel)]) == 0
    assert not ziel.exists()
    assert len(start_parameter) == 1
    assert start_parameter[0]['user_data_dir'] == ''
    assert start_parameter[0]['channel'] == 'msedge'
    assert start_parameter[0]['headless'] is False
    assert start_parameter[0]['accept_downloads'] is False
    assert geschlossen == [True]


def test_browserkontext_schliessung_in_login_wird_sofort_erkannt():
    class Kontext:
        pages = [FakePage('https://login.mercedes-benz.com/')]
        def on(self, name, callback):
            if name == 'close':
                callback()
    with pytest.raises(modul.VeDocBrowserFehler, match='Browserkontext'):
        modul._anmelden(Kontext(), vedoc_host='prod.core.public.vedoc.i.mercedes-benz.com',
                        login_timeout_s=30, auto_login=False)


def test_fin_export_verlangt_weiterhin_eingabedatei():
    with pytest.raises(SystemExit, match='2'):
        modul.main([])


class FakeHistorienSeite:
    """Simuliert Angular-Filterupdates ohne echtes Unternehmensnetz."""

    def __init__(self, gefiltert, ungefiltert):
        self.sekunden = 0.0
        self.filter_wert = "DCDC223"
        self.gefiltert = gefiltert
        self.ungefiltert = ungefiltert
        self.filter_feld = self.Filter(self)

    class Filter:
        def __init__(self, seite):
            self.seite = seite
        def fill(self, wert):
            self.seite.filter_wert = wert

    class Expand:
        @property
        def first(self):
            return self
        def count(self):
            return 0
        def is_visible(self):
            return False

    def locator(self, selector):
        assert selector == modul._ERWEITERN
        return self.Expand()

    def content(self):
        generator = self.gefiltert if self.filter_wert else self.ungefiltert
        return generator(self.sekunden)

    def wait_for_timeout(self, ms):
        self.sekunden += ms / 1000


def test_verzoegerte_historie_wird_nicht_als_leer_bewertet(monkeypatch):
    seite = FakeHistorienSeite(
        lambda t: html_tabelle() if t < 3 else html_tabelle(html_zeile(neu="000789")),
        lambda t: html_tabelle(html_zeile(neu="000789")),
    )
    monkeypatch.setattr(modul.time, "monotonic", lambda: seite.sekunden)
    ergebnis = modul._warte_auf_historieneintraege(
        seite, FIN_1, seite.filter_feld, 8000, ruhezeit_ms=600, intervall_ms=200,
    )
    assert ergebnis.status == "gefunden"
    assert ergebnis.seriennummer == "000789"
    assert seite.sekunden >= 3.6


def test_erst_nach_stabiler_historie_alle_aenderungen_erfasst(monkeypatch):
    erste = html_zeile(zeit="01.11.2026 10:00:00", neu="000111")
    zweite = html_zeile(zeit="02.11.2026 10:00:00", alt="000111", neu="000222")
    seite = FakeHistorienSeite(
        lambda t: html_tabelle() if t < 1 else (
            html_tabelle(erste) if t < 1.5 else html_tabelle(erste, zweite)
        ),
        lambda t: html_tabelle(erste, zweite),
    )
    monkeypatch.setattr(modul.time, "monotonic", lambda: seite.sekunden)
    ergebnis = modul._warte_auf_historieneintraege(
        seite, FIN_1, seite.filter_feld, 5000, ruhezeit_ms=700, intervall_ms=200,
    )
    assert ergebnis.status == "gefunden"
    assert ergebnis.seriennummer == "000222"
    assert len(ergebnis.aenderungen) == 2


def test_filter_zeigt_nichts_ungefilterte_historie_findet_seriennummer(monkeypatch):
    seite = FakeHistorienSeite(
        lambda t: html_tabelle(),
        lambda t: html_tabelle(html_zeile(neu="000999")),
    )
    monkeypatch.setattr(modul.time, "monotonic", lambda: seite.sekunden)
    ergebnis = modul._warte_auf_historieneintraege(
        seite, FIN_1, seite.filter_feld, 1400, ruhezeit_ms=600, intervall_ms=200,
    )
    assert ergebnis.status == "gefunden"
    assert ergebnis.seriennummer == "000999"
    assert "ungefiltert" in ergebnis.hinweis


def test_auch_nach_nachpruefung_kein_passender_eintrag(monkeypatch):
    ohne_seriennummer = html_tabelle(html_zeile(attribut="Datum des ersten Zugriffs"))
    seite = FakeHistorienSeite(lambda t: html_tabelle(), lambda t: ohne_seriennummer)
    monkeypatch.setattr(modul.time, "monotonic", lambda: seite.sekunden)
    ergebnis = modul._warte_auf_historieneintraege(
        seite, FIN_1, seite.filter_feld, 1400, ruhezeit_ms=600, intervall_ms=200,
    )
    assert ergebnis.status == "keine_seriennummer_aenderung"
    assert ergebnis.seriennummer is None


def test_leere_tabelle_bleibt_unbestaetigt(monkeypatch):
    seite = FakeHistorienSeite(lambda t: html_tabelle(), lambda t: html_tabelle())
    monkeypatch.setattr(modul.time, "monotonic", lambda: seite.sekunden)
    ergebnis = modul._warte_auf_historieneintraege(
        seite, FIN_1, seite.filter_feld, 1400, ruhezeit_ms=600, intervall_ms=200,
    )
    assert ergebnis.status == "historie_nicht_bestaetigt"
    assert ergebnis.seriennummer is None


def test_fremde_fin_auch_nach_warten_nicht_als_fehlend_bewerten(monkeypatch):
    fremd = html_tabelle(html_zeile(fin=FIN_2, neu="000888"))
    seite = FakeHistorienSeite(lambda t: fremd, lambda t: fremd)
    monkeypatch.setattr(modul.time, "monotonic", lambda: seite.sekunden)
    ergebnis = modul._warte_auf_historieneintraege(
        seite, FIN_1, seite.filter_feld, 1400, ruhezeit_ms=600, intervall_ms=200,
    )
    assert ergebnis.status == "historie_nicht_bestaetigt"
    assert ergebnis.seriennummer is None
