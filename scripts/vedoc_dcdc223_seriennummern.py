"""Eigenstaendiger, lesender VeDoc-Export: FIN-TXT -> DCDC223-Seriennummernhistorie (JSON/XLSX).

Die Anmeldung nutzt den bestehenden NTF-Insight-Schluesselbund oder fragt in PowerShell.
Weder Zugangsdaten noch HTML-Snapshots oder Browser-Profile werden gespeichert.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from ntf_insight.acquisition.output_paths import standard_ausgabe

from lxml import html
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo

_FIN = re.compile(r"[A-HJ-NPR-Z0-9]{17}\Z")
_STEUERGERAET = "DCDC223"
VEDOC_START = "https://prod.core.public.vedoc.i.mercedes-benz.com/ui/homepage.html"
_SSO_HOST = "login.mercedes-benz.com"
_FIN_EINGABE = 'input[data-ng-model="viewDataObject.vehicleSearchValue"]'
_FIN_ANZEIGE = 'span[data-ng-bind="viewControl.globalFin"]'
_TAB = 'li[heading="Historie"] a'
_FILTER = 'input[input-binding="viewControl.historyTable_filterExpression"]'
_FILTER_SCHALTER = 'button[data-ng-click="toggleFilter(\'historyTable\', \'filter\')"]'
_ERWEITERN = 'a[data-ng-click="removeScrollLimit(\'historyTable\',viewDataObject.logEntry.length)"]'


@dataclass(frozen=True)
class SeriennummerAenderung:
    aenderungszeitpunkt: str
    alter_wert: str | None
    neuer_wert: str | None


@dataclass(frozen=True)
class Ergebnis:
    fin: str
    steuergeraet: str
    seriennummer: str | None
    status: str
    hinweis: str
    abgefragt_am_utc: str
    aenderungen: tuple[SeriennummerAenderung, ...] = ()


def lade_fins(pfad: Path) -> list[str]:
    """Eine 17-stellige FIN pro Zeile; leere Zeilen und # Kommentare ignorieren."""
    if pfad.suffix.lower() != ".txt":
        raise ValueError("Die Eingabedatei muss eine .txt-Datei sein.")
    fin_liste: list[str] = []
    gesehen: set[str] = set()
    for nummer, zeile in enumerate(pfad.read_text(encoding="utf-8-sig").splitlines(), 1):
        fin = zeile.strip().upper()
        if not fin or fin.startswith("#"):
            continue
        if not _FIN.fullmatch(fin):
            raise ValueError(f"Zeile {nummer}: FIN muss 17 Zeichen A-Z/0-9 ohne I, O, Q haben.")
        if fin not in gesehen:
            gesehen.add(fin)
            fin_liste.append(fin)
    if not fin_liste:
        raise ValueError("Die TXT-Datei enthaelt keine gueltigen FINs.")
    return fin_liste


def pruefe_vedoc_url(url: str) -> str:
    """Nur Unternehmensdomain ueber HTTPS akzeptieren: keine FINs an Fremdhosts."""
    url = url.strip()
    teile = urlsplit(url)
    host = (teile.hostname or "").lower()
    if teile.scheme != "https" or not host.endswith(".mercedes-benz.com"):
        raise ValueError("VeDoc-URL muss eine HTTPS-Adresse auf *.mercedes-benz.com sein.")
    if teile.username or teile.password or not teile.path:
        raise ValueError("VeDoc-URL ist ungueltig.")
    return url


def _history_feld(zeile, feld: str) -> str:
    """Liest explizit das Angular-Binding, nicht beliebige Spaltentexte."""
    elemente = zeile.xpath(
        './/*[@data-ng-bind and starts-with(@data-ng-bind, "historyTable_rec.' + feld + '")]'
    )
    return elemente[0].text_content().strip() if elemente else ""


def lese_historie_aus_html(quelltext: str, fin: str) -> tuple[SeriennummerAenderung, ...]:
    """Nur Seriennummer-Aenderungen von DCDC223 fuer die volle FIN.

    Die VeDoc-Historie enthaelt auch andere Attribute, z.B. das Datum des
    ersten Zugriffs. Alte DOM-Zeilen der vorherigen FIN werden abgewiesen.
    """
    dokument = html.fromstring(quelltext)
    tabellen = dokument.xpath('//table[@id="historyTable"]')
    if len(tabellen) != 1:
        raise ValueError("Historientabelle fehlt oder ist nicht eindeutig.")
    eintraege: list[SeriennummerAenderung] = []
    for zeile in tabellen[0].xpath('./tbody/tr'):
        pfad = _history_feld(zeile, "pathToAttribute")
        # FIN-Praefix in VeDoc, z.B. '<FIN> / DCDC223'.
        anfang = pfad.split("/", 1)[0].strip().upper()
        if _FIN.fullmatch(anfang) and anfang != fin:
            raise ValueError("Historie gehoert noch zu einer anderen FIN.")
        if _history_feld(zeile, "parentObjectIdentifier").upper() != _STEUERGERAET:
            continue
        if _history_feld(zeile, "attributeName").casefold() != "seriennummer":
            continue
        if anfang != fin:
            raise ValueError("DCDC223-Historienzeile hat keine bestaetigte Voll-FIN.")
        zeit = _history_feld(zeile, "date")
        alt = _history_feld(zeile, "oldValue")
        neu = _history_feld(zeile, "newValue")
        eintraege.append(SeriennummerAenderung(zeit, alt or None, neu or None))
    return tuple(eintraege)


def _historienmoment(quelltext: str, fin: str) -> tuple[tuple[SeriennummerAenderung, ...], int, bool]:
    """Aus einem DOM-Snapshot Historienentries und FIN-Zuordnung ableiten.

    Eine leere oder alte Tabelle ist kein Nachweis, dass es keine Aenderung gibt.
    """
    dokument = html.fromstring(quelltext)
    tabellen = dokument.xpath('//table[@id="historyTable"]')
    if len(tabellen) != 1:
        raise ValueError("Historientabelle noch nicht eindeutig verfuegbar.")
    zeilen = tabellen[0].xpath('./tbody/tr')
    bestaetigte_fin = False
    for zeile in zeilen:
        pfad = _history_feld(zeile, "pathToAttribute")
        moegliche_fin = pfad.split("/", 1)[0].strip().upper()
        if _FIN.fullmatch(moegliche_fin):
            if moegliche_fin != fin:
                raise ValueError("Historie zeigt noch Eintraege einer anderen FIN.")
            bestaetigte_fin = True
    return lese_historie_aus_html(quelltext, fin), len(zeilen), bestaetigte_fin


def _warte_auf_historieneintraege(
    seite, fin: str, filter_feld, wartezeit_ms: int, *,
    ruhezeit_ms: int = 1500, intervall_ms: int = 350,
) -> Ergebnis:
    """Wartet auf gerenderte DCDC223-Daten; prueft danach ungefiltert nach.

    Kein fruehzeitiges `keine_seriennummer_aenderung` beim Angular-Zwischenzustand
    0 Zeilen. Bei nicht belegbarer Vollstaendigkeit wird explizit ein unsicherer
    Status ausgegeben statt ein negativer Befund behauptet.
    """
    deadline = time.monotonic() + wartezeit_ms / 1000
    letzte_signatur: tuple[SeriennummerAenderung, ...] | None = None
    stabil_seit: float | None = None
    erweitert = False
    print(f"{_gekuerzte_fin(fin)}: Filter DCDC223 wird geladen und kontrolliert ...", flush=True)

    while time.monotonic() < deadline:
        # Erweiterung erst nach dem ersten sichtbaren Datenstand ist moeglich.
        erweitern = seite.locator(_ERWEITERN)
        if not erweitert and erweitern.count() and erweitern.first.is_visible():
            erweitern.first.click(timeout=max(1000, min(5000, wartezeit_ms)))
            erweitert = True
            seite.wait_for_timeout(intervall_ms)
        try:
            eintraege, _anzahl, _fin_erkennbar = _historienmoment(seite.content(), fin)
        except ValueError:
            # Seitenwechsel / Angular ist noch nicht fertig. Nicht als 0 Treffer zaehlen.
            eintraege = ()
        if eintraege:
            jetzt = time.monotonic()
            if eintraege != letzte_signatur:
                letzte_signatur, stabil_seit = eintraege, jetzt
            elif stabil_seit is not None and (jetzt - stabil_seit) * 1000 >= ruhezeit_ms:
                return _bewerte_historie(fin, eintraege)
        else:
            letzte_signatur, stabil_seit = None, None
        seite.wait_for_timeout(intervall_ms)

    # Der Filter kann verzoegert rendern oder das Suchfeld kann beim FIN-Wechsel
    # alte Daten behalten. Daher zweiter unabhaengiger Pruefweg OHNE Filter.
    print(f"{_gekuerzte_fin(fin)}: Kein Filtertreffer. Pruefe ungefilterte Historie ...", flush=True)
    filter_feld.fill("")
    deadline_ungefiltert = time.monotonic() + max(3, ruhezeit_ms / 1000 + 1)
    letzte_signatur = None
    stabil_seit = None
    erweitert = False  # Nach Filterwechsel ggf. erneut alle Zeilen freigeben.
    letzte_anzahl = 0
    unveraendert_seit: float | None = None
    fehlerhafte_fins = False
    while time.monotonic() < deadline_ungefiltert:
        erweitern = seite.locator(_ERWEITERN)
        if not erweitert and erweitern.count() and erweitern.first.is_visible():
            erweitern.first.click(timeout=5000)
            erweitert = True
        try:
            eintraege, anzahl, gilt_fin = _historienmoment(seite.content(), fin)
        except ValueError:
            fehlerhafte_fins = True
            letzte_signatur, stabil_seit = None, None
            seite.wait_for_timeout(intervall_ms)
            continue
        if anzahl > 0 and gilt_fin and not eintraege:
            if anzahl != letzte_anzahl:
                letzte_anzahl, unveraendert_seit = anzahl, time.monotonic()
        else:
            letzte_anzahl, unveraendert_seit = 0, None
        if eintraege:
            jetzt = time.monotonic()
            if eintraege != letzte_signatur:
                letzte_signatur, stabil_seit = eintraege, jetzt
            elif stabil_seit is not None and (jetzt - stabil_seit) * 1000 >= ruhezeit_ms:
                ergebnis = _bewerte_historie(fin, eintraege)
                return _ergebnis(
                    fin, ergebnis.status, seriennummer=ergebnis.seriennummer,
                    hinweis=("Treffer nach ungefilterter Nachpruefung. " + ergebnis.hinweis),
                    aenderungen=ergebnis.aenderungen,
                )
        else:
            letzte_signatur, stabil_seit = None, None
        seite.wait_for_timeout(intervall_ms)
    # Negativbefund nur, wenn ein eindeutig zugeordnetes, nichtleeres
    # Historienbild am Ende der Nachpruefung mindestens 1 Sekunde stabil war.
    if (letzte_anzahl > 0 and unveraendert_seit is not None
            and (time.monotonic() - unveraendert_seit) >= 1.0
            and not fehlerhafte_fins):
        return _ergebnis(
            fin, "keine_seriennummer_aenderung",
            hinweis="Nach Wartezeit auch ungefiltert keine DCDC223-Seriennummernaenderung gefunden.",
        )
    return _ergebnis(
        fin, "historie_nicht_bestaetigt",
        hinweis="Historie nach Wartezeit nicht vollstaendig / FIN nicht zweifelsfrei belegt.",
    )


def _bewerte_historie(fin: str, eintraege: tuple[SeriennummerAenderung, ...]) -> Ergebnis:
    """Letzten dokumentierten neuen Wert ableiten, nicht den aktuellen Einbau behaupten."""
    if not eintraege:
        return _ergebnis(fin, "keine_seriennummer_aenderung",
                         hinweis="Keine passende Seriennummer-Aenderung in der Historie.")
    try:
        sortiert = sorted(eintraege, key=lambda x: datetime.strptime(
            x.aenderungszeitpunkt, "%d.%m.%Y %H:%M:%S"
        ))
    except ValueError:
        return _ergebnis(fin, "zeitstempel_ungueltig",
                         hinweis="Zeitangabe nicht eindeutig lesbar; keine letzte Seriennummer ableiten.",
                         aenderungen=eintraege)
    zeit = sortiert[-1].aenderungszeitpunkt
    letzte_werte = {eintrag.neuer_wert for eintrag in sortiert
                    if eintrag.aenderungszeitpunkt == zeit}
    if len(letzte_werte) != 1:
        return _ergebnis(fin, "mehrdeutig",
                         hinweis="Verschiedene neue Seriennummern zum letzten Zeitpunkt.",
                         aenderungen=tuple(sortiert))
    wert = next(iter(letzte_werte))
    if not wert:
        return _ergebnis(fin, "seriennummer_fehlt",
                         hinweis="Der letzte Historieneintrag enthaelt keinen neuen Wert.",
                         aenderungen=tuple(sortiert))
    return _ergebnis(fin, "gefunden", seriennummer=wert,
                     hinweis="Seriennummer ist der letzte dokumentierte neue Wert aus VeDoc-Historie.",
                     aenderungen=tuple(sortiert))


def _zeitpunkt() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _ergebnis(
    fin: str, status: str, seriennummer: str | None = None, hinweis: str = "",
    aenderungen: tuple[SeriennummerAenderung, ...] = (),
) -> Ergebnis:
    return Ergebnis(fin, _STEUERGERAET, seriennummer, status, hinweis, _zeitpunkt(), aenderungen)


def _gekuerzte_fin(fin: str) -> str:
    return f"***{fin[-5:]}"


class VeDocBrowserFehler(RuntimeError):
    """Browserprozess oder Browserfenster ist waehrend des Abrufs verschwunden."""


def _browserfehler(erreur: Exception) -> bool:
    """Playwright-Fehler ohne ungesicherte URL-/DOM-Texte auszugeben einordnen."""
    meldung = str(erreur).lower()
    # Ein SSO-Popup darf beim erfolgreichen Redirect normal schliessen.
    if "target page, context or browser has been closed" in meldung:
        return False
    return any(text in meldung for text in (
        "page crashed", "browser has been closed", "browser closed",
        "connection closed", "browser disconnected",
    ))


def _kontext_hat_seiten(kontext) -> bool:
    """Bei Verbindungsabbruch keine weiteren Playwright-Fehler ausloesen."""
    try:
        return bool(kontext.pages)
    except Exception:
        return False


def _ist_sso_seite(url: str) -> bool:
    adresse = urlsplit(url)
    return adresse.scheme == "https" and adresse.hostname == _SSO_HOST


def _ist_vedoc_bereit(seite, host: str) -> bool:
    adresse = urlsplit(seite.url)
    if adresse.scheme != "https" or adresse.hostname != host:
        return False
    feld = seite.locator(_FIN_EINGABE)
    if feld.count() and feld.is_visible():
        return True
    menue = seite.locator('a[href*="VehicleArrangement.html"]')
    return bool(menue.count() and menue.first.is_visible())


def _lade_zugangsdaten() -> tuple[str, str] | None:
    """Nur die bereits genutzten NTF-Insight-SSO-Zugangsdaten aus dem OS-Tresor."""
    try:
        from ntf_insight.acquisition.credentials import load_saved_credentials

        eintrag = load_saved_credentials()
    except (ImportError, RuntimeError):
        # Kein Keyring / kein passender Eintrag: nur fuer diesen Lauf abfragen.
        return None
    if eintrag and eintrag.user_id and eintrag.password:
        return eintrag.user_id, eintrag.password
    return None


def _zugangsdaten_fuer_lauf() -> tuple[str, str]:
    gespeichert = _lade_zugangsdaten()
    if gespeichert is not None:
        print("Mercedes-SSO-Zugangsdaten aus dem vorhandenen NTF-Insight-Tresor geladen.")
        return gespeichert
    print("Keine gespeicherten NTF-Insight-SSO-Zugangsdaten gefunden.")
    benutzer = input("Mercedes-Benz-Benutzerkennung: ").strip()
    if not benutzer:
        raise ValueError("Eine Benutzerkennung ist erforderlich.")
    passwort = getpass.getpass("Mercedes-Benz-Passwort (verdeckt): ")
    if not passwort:
        raise ValueError("Ein Passwort ist erforderlich.")
    return benutzer, passwort


def _sso_felder_ausfuellen(seite, zugang: tuple[str, str], gesendet: dict[str, bool]) -> None:
    """Zugangsdaten ausschliesslich an den verifizierten Mercedes-SSO-Host senden."""
    if not _ist_sso_seite(seite.url):
        return
    cookies = seite.locator("#c-s-bn")
    if cookies.count() and cookies.is_visible():
        cookies.click(timeout=3000)
    benutzerfeld = seite.locator("#userid")
    if not gesendet["benutzer"] and benutzerfeld.count() and benutzerfeld.is_visible():
        benutzerfeld.fill(zugang[0])
        seite.locator("#next-btn").click(timeout=10000)
        gesendet["benutzer"] = True
        print("Mercedes-SSO: Benutzerkennung gesendet.")
        return
    passwortfeld = seite.locator("#password")
    if not gesendet["passwort"] and passwortfeld.count() and passwortfeld.is_visible():
        passwortfeld.fill(zugang[1])
        seite.locator("#loginSubmitButton").click(timeout=10000)
        gesendet["passwort"] = True
        print("Mercedes-SSO: Passwort gesendet. Gegebenenfalls PING ID bestaetigen.")


def _anmelden(
    kontext, *, vedoc_host: str, login_timeout_s: int, browser=None,
    auto_login: bool = True,
) -> object:
    """SSO abwarten; Browserabsturz statt stiller Endlosschleife erkennen.

    Auto-Login nutzt nur Mercedes-SSO. Im manuellen Modus werden keine
    gespeicherten Zugangsdaten ausgelesen und keine Eingaben automatisiert.
    """
    deadline = time.monotonic() + login_timeout_s
    zugang: tuple[str, str] | None = None
    gesendet = {"benutzer": False, "passwort": False}
    sso_geoeffnet = False
    manuell_erklaert = False
    naechster_status = time.monotonic() + 12
    ohne_fenster_seit: float | None = None
    beobachtet: set[int] = set()
    renderer_abgestuerzt = {"ja": False}
    kontext_geschlossen = {"ja": False}
    registrieren_kontext = getattr(kontext, "on", None)
    if callable(registrieren_kontext):
        registrieren_kontext(
            "close", lambda *_argumente: kontext_geschlossen.__setitem__("ja", True)
        )

    def crash_erkannt(*_argumente) -> None:
        renderer_abgestuerzt["ja"] = True

    print("Warte auf die VeDoc-Anmeldung. PING ID bei Bedarf am Smartphone bestaetigen.", flush=True)
    while time.monotonic() < deadline:
        if renderer_abgestuerzt["ja"]:
            raise VeDocBrowserFehler("Die VeDoc-/SSO-Browserseite ist abgestuerzt.")
        if kontext_geschlossen["ja"]:
            raise VeDocBrowserFehler("Der Edge-Browserkontext wurde unerwartet geschlossen.")
        if browser is not None and not browser.is_connected():
            raise VeDocBrowserFehler("Die Verbindung zu Edge/Chromium ist abgebrochen.")
        try:
            seiten = [seite for seite in kontext.pages if not seite.is_closed()]
        except Exception:
            raise VeDocBrowserFehler("Der Browser-Kontext ist nicht mehr erreichbar.") from None

        if not seiten:
            if ohne_fenster_seit is None:
                ohne_fenster_seit = time.monotonic()
            elif time.monotonic() - ohne_fenster_seit >= 5:
                raise VeDocBrowserFehler("Alle Browserfenster wurden geschlossen.")
        else:
            ohne_fenster_seit = None

        for seite in reversed(seiten):
            if id(seite) not in beobachtet:
                beobachtet.add(id(seite))
                registrieren = getattr(seite, "on", None)
                if callable(registrieren):
                    registrieren("crash", crash_erkannt)
            try:
                if _ist_vedoc_bereit(seite, vedoc_host):
                    print("VeDoc-Anmeldung abgeschlossen.", flush=True)
                    return seite
                if _ist_sso_seite(seite.url):
                    if auto_login:
                        if zugang is None:
                            zugang = _zugangsdaten_fuer_lauf()
                        _sso_felder_ausfuellen(seite, zugang, gesendet)
                    elif not manuell_erklaert:
                        print("Manueller SSO-Modus: Benutzerkennung und Passwort im Browser eingeben; "
                              "PING ID selbst bestaetigen.", flush=True)
                        manuell_erklaert = True
                    continue
                if not sso_geoeffnet:
                    adresse = urlsplit(seite.url)
                    if adresse.scheme == "https" and adresse.hostname == vedoc_host:
                        sso = seite.get_by_role("button", name=re.compile("SSO|Single Sign.On", re.I))
                        if not sso.count():
                            sso = seite.get_by_role("link", name=re.compile("SSO|Single Sign.On", re.I))
                        if sso.count() and sso.first.is_visible():
                            sso.first.click(timeout=3000)
                            sso_geoeffnet = True
            except (KeyboardInterrupt, EOFError, ValueError, VeDocBrowserFehler):
                raise
            except Exception as fehler:
                if (renderer_abgestuerzt["ja"] or kontext_geschlossen["ja"]
                        or (browser is not None and not browser.is_connected())):
                    raise VeDocBrowserFehler("Der Browser ist waehrend der Anmeldung abgestuerzt.") from None
                if _browserfehler(fehler):
                    raise VeDocBrowserFehler("Die Browserseite wurde geschlossen oder ist abgestuerzt.") from None
                # Ein normaler SSO-Redirect kann die aktuelle Seite kurzfristig ungueltig machen.
                continue

        if time.monotonic() >= naechster_status:
            verbleibend = max(0, int(deadline - time.monotonic()))
            print(f"SSO/PING ID weiterhin ausstehend ({verbleibend} s verbleibend). "
                  "Browserfenster pruefen; Abbruch mit Strg+C.", flush=True)
            naechster_status = time.monotonic() + 12
        if seiten:
            try:
                seiten[0].wait_for_timeout(400)
            except Exception as fehler:
                if (renderer_abgestuerzt["ja"] or kontext_geschlossen["ja"]
                        or (browser is not None and not browser.is_connected())):
                    raise VeDocBrowserFehler("Der Browser ist waehrend der Anmeldung abgestuerzt.") from None
                if _browserfehler(fehler):
                    raise VeDocBrowserFehler("Die Browserseite wurde geschlossen oder ist abgestuerzt.") from None
                # Redirect kann genau beim Warten stattgefunden haben.
        else:
            time.sleep(0.4)
    raise TimeoutError("SSO-/PING-ID-Anmeldung nach Ablauf des Login-Timeouts nicht abgeschlossen.")


def _fahrzeugdaten_oeffnen(seite, timeout_ms: int) -> None:
    feld = seite.locator(_FIN_EINGABE)
    if feld.count() and feld.is_visible():
        return
    menue = seite.locator('a[href*="VehicleArrangement.html"]')
    if menue.count():
        menue.first.click(timeout=timeout_ms)
    feld.wait_for(state="visible", timeout=timeout_ms)


def _abfrage(seite, fin: str, timeout_ms: int, historie_wartezeit_ms: int = 20000) -> Ergebnis:
    """Historie nach bestaetigtem FIN-Wechsel laden und auf Ergebnisse warten."""
    from playwright.sync_api import TimeoutError as PlaywrightTimeout

    try:
        _fahrzeugdaten_oeffnen(seite, timeout_ms)
        seite.locator(_FIN_EINGABE).fill(fin)
        seite.locator("#VehicleSearch_000_search").click(timeout=timeout_ms)
        seite.wait_for_function(
            """fin => {
                const anzeige = document.querySelector('span[data-ng-bind="viewControl.globalFin"]');
                return !!anzeige && anzeige.textContent.replace(/[\\s-]/g, '').toUpperCase() === fin;
            }""",
            arg=fin,
            timeout=timeout_ms,
        )
    except PlaywrightTimeout:
        return _ergebnis(fin, "fin_nicht_bestaetigt", hinweis="FIN-Wechsel nicht bestaetigt.")

    try:
        seite.locator(_TAB).click(timeout=timeout_ms)
        seite.locator("#historyTable").wait_for(state="visible", timeout=timeout_ms)
        filter_feld = seite.locator(_FILTER)
        if not filter_feld.is_visible():
            seite.locator(_FILTER_SCHALTER).click(timeout=timeout_ms)
        filter_feld.wait_for(state="visible", timeout=timeout_ms)
        # Alter Filter kann noch zur vorherigen FIN gehoeren.
        filter_feld.fill("")
        seite.wait_for_timeout(350)
        filter_feld.fill(_STEUERGERAET)
        return _warte_auf_historieneintraege(
            seite, fin, filter_feld, historie_wartezeit_ms,
        )
    except PlaywrightTimeout:
        return _ergebnis(fin, "zeitueberschreitung",
                         hinweis="Historienreiter oder Filter nicht bereit.")
    except ValueError:
        return _ergebnis(fin, "historie_nicht_bestaetigt",
                         hinweis="Historie ist nicht eindeutig dieser FIN zuzuordnen.")


def _schreibe_json(pfad: Path, ergebnisse: list[Ergebnis]) -> None:
    daten = {"quelle": "VeDoc/Historie", "steuergeraet": _STEUERGERAET,
             "anzahl": len(ergebnisse), "fahrzeuge": [asdict(x) for x in ergebnisse]}
    temporaer = pfad.with_suffix(pfad.suffix + ".tmp")
    temporaer.write_text(json.dumps(daten, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporaer.replace(pfad)


def _tabelle_formatieren(ws, spalten: list[str], zeilen: list[list[str]]) -> None:
    ws.sheet_view.showGridLines = False
    ws.append(spalten)
    for zelle in ws[1]:
        zelle.fill = PatternFill("solid", fgColor="1C2730")
        zelle.font = Font(name="Aptos", size=11, bold=True, color="FFFFFF")
        zelle.alignment = Alignment(vertical="center")
    ws.row_dimensions[1].height = 28
    for werte in zeilen:
        ws.append(werte)
        for zelle in ws[ws.max_row]:
            # Alle aus VeDoc gelesenen Inhalte sind Text; verhindert Excel-Formeln.
            zelle.data_type = "s"
            zelle.number_format = "@"
            zelle.alignment = Alignment(vertical="center")
        ws.row_dimensions[ws.max_row].height = 23
    ws.freeze_panes = "A2"
    for nummer, breite in enumerate(([24, 17, 39, 21, 30, 68, 29]
                                    if ws.title == "DCDC223" else
                                    [24, 17, 20, 25, 39, 39, 27]), 1):
        ws.column_dimensions[get_column_letter(nummer)].width = breite
    if zeilen:
        tabelle = Table(displayName="VeDoc" + ws.title, ref=f"A1:G{len(zeilen) + 1}")
        tabelle.tableStyleInfo = TableStyleInfo(
            name="TableStyleMedium2", showFirstColumn=False,
            showLastColumn=False, showRowStripes=True, showColumnStripes=False
        )
        ws.add_table(tabelle)


def _schreibe_excel(pfad: Path, ergebnisse: list[Ergebnis]) -> None:
    wb = Workbook()
    uebersicht = wb.active
    uebersicht.title = "DCDC223"
    _tabelle_formatieren(
        uebersicht,
        ["FIN", "Steuergerät", "Letzter neuer Wert (Historie)", "Änderungen", "Status",
         "Hinweis", "Abfragezeit (UTC)"],
        [
            [e.fin, e.steuergeraet, e.seriennummer or "", str(len(e.aenderungen)),
             e.status, e.hinweis, e.abgefragt_am_utc]
            for e in ergebnisse
        ],
    )
    historie = wb.create_sheet("Historie")
    zeilen = [
        [e.fin, e.steuergeraet, "Seriennummer", a.aenderungszeitpunkt,
         a.alter_wert or "", a.neuer_wert or "", e.status]
        for e in ergebnisse for a in e.aenderungen
    ]
    _tabelle_formatieren(
        historie,
        ["FIN", "Steuergerät", "Attributname", "Änderungszeitpunkt (VeDoc)",
         "Alter Wert", "Neuer Wert", "FIN-Status"],
        zeilen,
    )
    temporaer = pfad.with_suffix(".tmp.xlsx")
    wb.save(temporaer)
    temporaer.replace(pfad)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Exportiert die DCDC223-Seriennummernhistorie je FIN als JSON und Excel."
    )
    parser.add_argument("--eingabe", type=Path, help="TXT mit einer FIN pro Zeile")
    parser.add_argument("--ausgabe", type=Path, default=None,
                        help="Zielordner (Standard: data/processed/<TXT-Name>/vedoc_dcdc223)")
    parser.add_argument("--url", default=os.getenv("VEDOC_URL", VEDOC_START),
                        help="VeDoc-Startadresse (Standard bereits im Skript hinterlegt)")
    parser.add_argument("--browser", choices=["edge", "chromium"], default="edge")
    parser.add_argument("--timeout", type=int, default=30, help="Timeout pro Schritt in Sekunden")
    parser.add_argument("--login-timeout", type=int, default=240,
                        help="Maximale Wartezeit fuer SSO/PING ID in Sekunden")
    parser.add_argument("--historie-wartezeit", type=int, default=20,
                        help="Wartezeit auf DCDC223-Historie pro FIN in Sekunden (Standard: 20)")
    parser.add_argument("--login-manuell", action="store_true",
                        help="SSO ohne automatisches Ausfuellen von Benutzername/Passwort")
    parser.add_argument("--nur-login", action="store_true",
                        help="Nur den SSO/PING-ID-Login testen, ohne FIN-Abfrage oder Export")
    argumente = parser.parse_args(argv)
    if argumente.ausgabe is None:
        argumente.ausgabe = (standard_ausgabe(argumente.eingabe, "dcdc223")
                            if argumente.eingabe is not None
                            else Path("data/processed/vedoc_dcdc223"))
    try:
        if not argumente.nur_login and argumente.eingabe is None:
            raise ValueError("--eingabe ist fuer FIN-Exporte erforderlich.")
        fins = [] if argumente.nur_login else lade_fins(argumente.eingabe)
        url = pruefe_vedoc_url(argumente.url)
        if not 5 <= argumente.timeout <= 120:
            raise ValueError("--timeout muss zwischen 5 und 120 Sekunden liegen.")
        if not 30 <= argumente.login_timeout <= 900:
            raise ValueError("--login-timeout muss zwischen 30 und 900 Sekunden liegen.")
        if not 5 <= argumente.historie_wartezeit <= 120:
            raise ValueError("--historie-wartezeit muss zwischen 5 und 120 Sekunden liegen.")
    except (OSError, ValueError) as fehler:
        parser.error(str(fehler))

    if not argumente.nur_login:
        argumente.ausgabe.mkdir(parents=True, exist_ok=True)
    json_pfad = argumente.ausgabe / "dcdc223_seriennummern.json"
    excel_pfad = argumente.ausgabe / "dcdc223_seriennummern.xlsx"
    ergebnisse: list[Ergebnis] = []
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeout, sync_playwright

        with sync_playwright() as playwright:
            # Im Unterschied zu chromium.launch() + new_context() wird kein
            # InPrivate-/Inkognito-Kontext gestartet. Das temporare Profil
            # besteht nur fuer diesen Lauf und wird beim Schliessen entfernt.
            start_parameter = {
                "user_data_dir": "", "headless": False,
                "accept_downloads": False, "no_viewport": True,
            }
            if argumente.browser == "edge":
                start_parameter["channel"] = "msedge"
            print("Starte Edge/Chromium mit temporaerem, separatem Browserprofil.", flush=True)
            kontext = playwright.chromium.launch_persistent_context(**start_parameter)
            try:
                seite = kontext.pages[0] if kontext.pages else kontext.new_page()
                try:
                    seite.goto(url, wait_until="domcontentloaded", timeout=60_000)
                except PlaywrightTimeout:
                    # Ein SSO-Redirect kann einen Navigationstimeout ausloesen.
                    pass
                except Exception as fehler:
                    if _browserfehler(fehler) or not _kontext_hat_seiten(kontext):
                        raise VeDocBrowserFehler("Browser waehrend der VeDoc-Navigation verloren.") from None
                    raise
                seite = _anmelden(
                    kontext, vedoc_host=urlsplit(url).hostname or "",
                    login_timeout_s=argumente.login_timeout,
                    auto_login=not argumente.login_manuell,
                )
                if argumente.nur_login:
                    print("SSO/PING ID erfolgreich: VeDoc ist erreichbar. Keine FIN abgefragt.", flush=True)
                else:
                    _fahrzeugdaten_oeffnen(seite, argumente.timeout * 1000)
                    for nummer, fin in enumerate(fins, 1):
                        try:
                            ergebnis = _abfrage(
                                seite, fin, argumente.timeout * 1000,
                                argumente.historie_wartezeit * 1000,
                            )
                        except Exception as fehler:
                            if _browserfehler(fehler) or not _kontext_hat_seiten(kontext):
                                raise VeDocBrowserFehler(
                                    "Browser waehrend der FIN-Abfrage geschlossen oder abgestuerzt."
                                ) from None
                            # Keine internen Browserfehlermeldungen mit FIN/URLs ausgeben.
                            ergebnis = _ergebnis(fin, "fehler", hinweis="VeDoc-Abfrage fehlgeschlagen.")
                        ergebnisse.append(ergebnis)
                        _schreibe_json(json_pfad, ergebnisse)  # Zwischenstand nach jeder FIN.
                        print(f"[{nummer}/{len(fins)}] {_gekuerzte_fin(fin)}: {ergebnis.status}")
            finally:
                try:
                    kontext.close()  # Auch nach SSO-/Browserfehlern aufraeumen.
                except Exception:
                    pass  # Der urspruengliche Fehler hat Vorrang.
    except (KeyboardInterrupt, EOFError):
        print("Abgebrochen: bisherige Ergebnisse werden exportiert.")
        returncode = 130
    except VeDocBrowserFehler as fehler:
        print(f"Browser-Verbindung verloren: {fehler}", flush=True)
        print("SSO-Uebergang pruefen: --nur-login --login-manuell. "
              "Ggf. die Unternehmens-IT kontaktieren.", flush=True)
        returncode = 3
    except TimeoutError as fehler:
        print(f"Anmeldung nicht abgeschlossen: {fehler}", flush=True)
        returncode = 4
    except Exception as fehler:
        print(f"VeDoc konnte nicht gestartet werden ({type(fehler).__name__}).", flush=True)
        returncode = 2
    else:
        returncode = 0 if (argumente.nur_login or all(
            x.status == "gefunden" for x in ergebnisse)) else 1
    finally:
        if argumente.nur_login:
            pass  # Login-Probe erzeugt und ueberschreibt keine Exportdateien.
        elif ergebnisse:
            _schreibe_json(json_pfad, ergebnisse)
            _schreibe_excel(excel_pfad, ergebnisse)
            print(f"JSON: {json_pfad}\nExcel: {excel_pfad}")
        else:
            print("Keine FIN verarbeitet; vorhandene Exporte bleiben unveraendert.", flush=True)
    return returncode


if __name__ == "__main__":
    raise SystemExit(main())
