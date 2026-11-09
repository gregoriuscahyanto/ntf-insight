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


def test_cli_eingabe_und_ausgabe():
    options = m.kommandozeile(["--eingabe", "fins.txt", "--ausgabe", "daten.json"])
    assert options.fin_datei == Path("fins.txt")
    assert options.ausgabe == Path("daten.json")


def test_cli_standardpfad_und_positionsargument():
    expected = Path("data/processed/vedoc_codes.json")
    assert m.kommandozeile(["--eingabe", "fins.txt"]).ausgabe == expected
    assert m.kommandozeile(["fins.txt"]).ausgabe == expected


def test_cli_fehlende_oder_doppelte_eingabe():
    with pytest.raises(SystemExit) as missing:
        m.kommandozeile([])
    assert missing.value.code == 2
    with pytest.raises(SystemExit) as duplicate:
        m.kommandozeile(["fins.txt", "--eingabe", "zweite.txt"])
    assert duplicate.value.code == 2


def test_standardpfad_legt_data_processed_an(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    eingabe = tmp_path / "fins.txt"
    eingabe.write_text(FIN1 + "\n", encoding="utf-8")
    ausgabe = tmp_path / "data" / "processed" / "vedoc_codes.json"
    m.speichere_json_zuverlaessig(ausgabe, {
        "schema_version": "1.0",
        "fahrzeuge": [{"fin": FIN1, "status": "erfolgreich", "codes": [{"code": "01U"}]}],
    })
    options = m.kommandozeile(["--eingabe", str(eingabe)])
    assert m.abrufen(options) == 0
    assert ausgabe.exists()
    assert len(json.loads(ausgabe.read_text(encoding="utf-8"))["fahrzeuge"]) == 1



class FakeSSOLocator:
    def __init__(self, page, selector: str):
        self.page = page
        self.selector = selector

    @property
    def first(self):
        return self

    def count(self):
        return int(self.is_visible())

    def is_visible(self):
        return (
            self.selector == m.SUCHFELD and self.page.stage == "fertig"
            or self.selector == "#userid" and self.page.stage == "benutzer"
            or self.selector == "#password" and self.page.stage == "passwort"
            or self.selector in ("#next-btn", "#loginSubmitButton")
        )

    def fill(self, value, **kwargs):
        self.page.aktionen.append(("fill", self.selector, value))

    def click(self, **kwargs):
        self.page.aktionen.append(("click", self.selector))
        if self.selector == "#next-btn":
            self.page.stage = "passwort"
        elif self.selector == "#loginSubmitButton":
            self.page.stage = "fertig"
            self.page.url = m.VEDOC_URL


class FakeSSOPage:
    def __init__(self, url=None, stage="benutzer"):
        self.url = url or f"https://{m.SSO_HOST}/login"
        self.stage = stage
        self.aktionen = []
        self.closed = False

    def is_closed(self):
        return self.closed

    def locator(self, selector):
        self.aktionen.append(("locator", selector))
        return FakeSSOLocator(self, selector)


def test_automatische_sso_eingabe_nutzt_ntf_tresor(monkeypatch):
    from ntf_insight.acquisition.credentials import LoginCredentials

    aufrufe = []
    def lade():
        aufrufe.append("tresor")
        return LoginCredentials(user_id="sso-benutzer", password="synthetisch-testpasswort")

    monkeypatch.setattr(m, "load_saved_credentials", lade)
    monkeypatch.setattr(m.time, "sleep", lambda _: None)
    page = FakeSSOPage()
    context = SimpleNamespace(pages=[page])
    ready = m.browser_bereit(context, 3, auto_login=True)
    assert ready is page
    assert aufrufe == ["tresor"]
    assert ("fill", "#userid", "sso-benutzer") in page.aktionen
    assert ("fill", "#password", "synthetisch-testpasswort") in page.aktionen
    assert ("click", "#next-btn") in page.aktionen
    assert ("click", "#loginSubmitButton") in page.aktionen


def test_auto_login_bei_bestehender_sso_session_keine_tresor_abfrage(monkeypatch):
    monkeypatch.setattr(
        m, "load_saved_credentials",
        lambda: pytest.fail("Bei bestehender Anmeldung darf kein Passwort geladen werden"),
    )
    page = FakeSSOPage(url=m.VEDOC_URL, stage="fertig")
    assert m.browser_bereit(SimpleNamespace(pages=[page]), 3, auto_login=True) is page


def test_login_manuell_fasst_tresor_und_login_felder_nicht_an(monkeypatch):
    monkeypatch.setattr(
        m, "load_saved_credentials",
        lambda: pytest.fail("Mit --login-manuell darf der Tresor nicht gelesen werden"),
    )
    clock = [0.0]
    monkeypatch.setattr(m.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(m.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    page = FakeSSOPage()
    with pytest.raises(TimeoutError, match="VeDoc-Suche"):
        m.browser_bereit(SimpleNamespace(pages=[page]), 1.0, auto_login=False)
    assert all(aktion[0] != "fill" for aktion in page.aktionen)


@pytest.mark.parametrize("url", [
    "http://login.mercedes-benz.com/login",
    "https://login.mercedes-benz.com.evil.invalid/login",
    "https://login.mercedes-benz.com@evil.invalid/login",
    "https://evil.invalid/login",
])
def test_sso_ausfuellen_verweigert_fremde_hosts(url):
    page = FakeSSOPage(url=url)
    m._sso_ausfuellen(page, ("benutzer", "testpasswort"), {"benutzer": False, "passwort": False})
    assert page.aktionen == []


def test_zugangsdaten_aus_tresor_oder_terminal_fallback(monkeypatch):
    from ntf_insight.acquisition.credentials import LoginCredentials

    monkeypatch.setattr(
        m, "load_saved_credentials",
        lambda: LoginCredentials(user_id="konto", password="sicheres-testpasswort"),
    )
    assert m._zugangsdaten_fuer_lauf() == ("konto", "sicheres-testpasswort")

    monkeypatch.setattr(m, "load_saved_credentials", lambda: None)
    monkeypatch.setattr(m.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt: "manuell")
    monkeypatch.setattr(m.getpass, "getpass", lambda prompt: "verdecktes-testpasswort")
    assert m._zugangsdaten_fuer_lauf() == ("manuell", "verdecktes-testpasswort")


def test_keine_tresordaten_und_keine_konsole_erlaubt_manuale_browseranmeldung(monkeypatch):
    monkeypatch.setattr(m, "load_saved_credentials", lambda: None)
    monkeypatch.setattr(m.sys.stdin, "isatty", lambda: False)
    assert m._zugangsdaten_fuer_lauf() is None


def test_cli_nur_login_ohne_fin_liste():
    args = m.kommandozeile(["--nur-login", "--login-manuell"])
    assert args.nur_login is True
    assert args.login_manuell is True
    assert args.fin_datei is None


def test_nur_login_schreibt_keine_fahrzeugdaten(monkeypatch, tmp_path):
    class ReadyPage(FakeSSOPage):
        def __init__(self):
            super().__init__(url=m.VEDOC_URL, stage="fertig")
        def goto(self, url, **kwargs):
            assert url == m.VEDOC_URL
    page = ReadyPage()
    class FakeContext:
        pages = [page]
        def close(self):
            pass
    context = FakeContext()

    class PW:
        chromium = SimpleNamespace(launch_persistent_context=lambda **kw: context)

    class Runner:
        def __enter__(self):
            return PW()
        def __exit__(self, *args):
            pass

    import sys
    monkeypatch.setitem(sys.modules, "playwright.sync_api",
                        SimpleNamespace(sync_playwright=lambda: Runner()))
    monkeypatch.setattr(
        m, "load_saved_credentials",
        lambda: pytest.fail("Keine Tresor-Abfrage ohne Login noetig"),
    )
    output = tmp_path / "data" / "processed" / "vedoc_codes.json"
    args = m.kommandozeile(["--nur-login", "--ausgabe", str(output),
                            "--profil", str(tmp_path / "profil")])
    assert m.abrufen(args) == 0
    assert not output.exists()



def test_ping_id_seite_braucht_keinen_tresor_zugriff(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(m.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(m.time, "sleep", lambda sekunden: clock.__setitem__(0, clock[0] + sekunden))
    monkeypatch.setattr(
        m, "load_saved_credentials",
        lambda: pytest.fail("PING-ID-Seite darf keinen Tresorzugriff ausloesen"),
    )
    page = FakeSSOPage(stage="ping-id")
    with pytest.raises(TimeoutError, match="VeDoc-Suche"):
        m.browser_bereit(SimpleNamespace(pages=[page]), 1, auto_login=True)
    assert all(action[0] != "fill" for action in page.aktionen)
