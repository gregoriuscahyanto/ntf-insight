"""VeDoc-Hardwarehistorie fuer frei waehlbares Objekt/Attribut (JSON/XLSX).

Die Anmeldung nutzt den bestehenden NTF-Insight-Schluesselbund oder fragt in PowerShell.
Weder Zugangsdaten noch HTML-Snapshots oder Browser-Profile werden gespeichert.
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import unicodedata
import os
import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from ntf_insight.acquisition.output_paths import standard_ausgabe
from ntf_insight.acquisition.sso_login_gate import serielle_sso_anmeldung

from lxml import html
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from ntf_insight.acquisition.fin_format import fin_passt_zu_anfrage, ist_gueltige_fin

from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo

_STEUERGERAET = "DCDC223"  # Bisheriger Standard fuer Legacy-Aufruf
_STANDARD_ATTRIBUT = "Seriennummer"
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
    attribut: str = _STANDARD_ATTRIBUT

    @property
    def objekt(self) -> str:
        """Neutrales Alias zum historischen Feld `steuergeraet`."""
        return self.steuergeraet

    @property
    def letzter_neuer_wert(self) -> str | None:
        """Der letzte dokumentierte, zeitlich eindeutige neue Attributwert."""
        return self.seriennummer


def pruefe_historienziel(wert: str, *, feld: str) -> str:
    """Freien VeDoc-Text vor Browser/Export validieren; keine Steuerzeichen."""
    text = " ".join(str(wert).split())
    if (not text or len(text) > 120 or any(
        unicodedata.category(zeichen).startswith("C") for zeichen in str(wert)
    )):
        raise ValueError(f"{feld} muss 1-120 lesbare Zeichen ohne Steuerzeichen enthalten.")
    return text


def _dateiteil(wert: str) -> str:
    """Kollisionsarme, Windows-sichere Exporte fuer frei waehlbare Namen."""
    ascii_text = unicodedata.normalize("NFKD", wert).encode("ascii", "ignore").decode("ascii")
    roh = re.sub(r"[^a-z0-9_-]+", "_", ascii_text.casefold()).strip("_")
    teil = (roh or "objekt")[:48].rstrip("_")
    if teil != wert.casefold():
        teil = teil[:39] + "_" + hashlib.sha256(wert.encode("utf-8")).hexdigest()[:8]
    return teil


def _dateistamm(objekt: str, attribut: str) -> str:
    if objekt == _STEUERGERAET and attribut == _STANDARD_ATTRIBUT:
        return "dcdc223_seriennummern"
    suffix = ("seriennummern" if attribut.casefold() == _STANDARD_ATTRIBUT.casefold()
              else _dateiteil(attribut))
    return f"{_dateiteil(objekt)}_{suffix}"


def lade_fins(pfad: Path) -> list[str]:
    """14-stellige Mercedes-Kurz-FIN oder 17-stellige FIN je Zeile."""
    if pfad.suffix.lower() != ".txt":
        raise ValueError("Die Eingabedatei muss eine .txt-Datei sein.")
    fin_liste: list[str] = []
    gesehen: set[str] = set()
    for nummer, zeile in enumerate(pfad.read_text(encoding="utf-8-sig").splitlines(), 1):
        fin = zeile.strip().upper()
        if not fin or fin.startswith("#"):
            continue
        if not ist_gueltige_fin(fin, kurz_erlaubt=True):
            raise ValueError(f"Zeile {nummer}: FIN muss 14 oder 17 Zeichen A-Z/0-9 ohne I, O, Q haben.")
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


def lese_historie_aus_html(
    quelltext: str, fin: str, objekt: str = _STEUERGERAET,
    attribut: str = _STANDARD_ATTRIBUT,
) -> tuple[SeriennummerAenderung, ...]:
    """Nur exakte Objekt-/Attributtreffer mit bestaetigter FIN auswerten.

    Keine unscharfen Teiltreffer: DCDC223 darf z.B. nicht DCDC223A oder
    einen fremden Hardwarestand einschliessen.
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
        if ist_gueltige_fin(anfang, kurz_erlaubt=True) and not fin_passt_zu_anfrage(fin, anfang):
            raise ValueError("Historie gehoert noch zu einer anderen FIN.")
        if " ".join(_history_feld(zeile, "parentObjectIdentifier").split()).casefold() != objekt.casefold():
            continue
        if " ".join(_history_feld(zeile, "attributeName").split()).casefold() != attribut.casefold():
            continue
        if not fin_passt_zu_anfrage(fin, anfang):
            raise ValueError("Historienzeile zum ausgewaehlten Objekt hat keine bestaetigte Voll-FIN.")
        zeit = _history_feld(zeile, "date")
        alt = _history_feld(zeile, "oldValue")
        neu = _history_feld(zeile, "newValue")
        eintraege.append(SeriennummerAenderung(zeit, alt or None, neu or None))
    return tuple(eintraege)


def _historienmoment(
    quelltext: str, fin: str, objekt: str = _STEUERGERAET,
    attribut: str = _STANDARD_ATTRIBUT,
) -> tuple[tuple[SeriennummerAenderung, ...], int, bool]:
    """Aus einem DOM-Snapshot Historienentries und FIN-Zuordnung ableiten.

    Eine leere oder alte Tabelle ist kein Nachweis, dass es keine Aenderung gibt.
    """
    dokument = html.fromstring(quelltext)
    tabellen = dokument.xpath('//table[@id="historyTable"]')
    if len(tabellen) != 1:
        raise ValueError("Historientabelle noch nicht eindeutig verfuegbar.")
    zeilen = tabellen[0].xpath('./tbody/tr')
    bestaetigte_fin = False
    vollfin_funde: set[str] = set()
    for zeile in zeilen:
        pfad = _history_feld(zeile, "pathToAttribute")
        moegliche_fin = pfad.split("/", 1)[0].strip().upper()
        if ist_gueltige_fin(moegliche_fin, kurz_erlaubt=True):
            if not fin_passt_zu_anfrage(fin, moegliche_fin):
                raise ValueError("Historie zeigt noch Eintraege einer anderen FIN.")
            bestaetigte_fin = True
            if len(fin) == 14 and len(moegliche_fin) == 17:
                vollfin_funde.add(moegliche_fin)
    if len(vollfin_funde) > 1:
        raise ValueError(
            "Kurz-FIN mehrdeutig: VeDoc-Historie enthaelt verschiedene Voll-FINs. "
            "Bitte vollstaendige FIN verwenden."
        )
    return lese_historie_aus_html(quelltext, fin, objekt, attribut), len(zeilen), bestaetigte_fin


def _warte_auf_historieneintraege(
    seite, fin: str, filter_feld, wartezeit_ms: int, *,
    objekt: str = _STEUERGERAET, attribut: str = _STANDARD_ATTRIBUT,
    ruhezeit_ms: int = 1500, intervall_ms: int = 350,
) -> Ergebnis:
    """Wartet auf gerenderte Objektdaten; prueft danach ungefiltert nach.

    Kein fruehzeitiges `keine_seriennummer_aenderung` beim Angular-Zwischenzustand
    0 Zeilen. Bei nicht belegbarer Vollstaendigkeit wird explizit ein unsicherer
    Status ausgegeben statt ein negativer Befund behauptet.
    """
    deadline = time.monotonic() + wartezeit_ms / 1000
    letzte_signatur: tuple[SeriennummerAenderung, ...] | None = None
    stabil_seit: float | None = None
    erweitert = False
    print(f"{_gekuerzte_fin(fin)}: VeDoc-Filter fuer {objekt} / {attribut} wird kontrolliert ...", flush=True)

    while time.monotonic() < deadline:
        # Erweiterung erst nach dem ersten sichtbaren Datenstand ist moeglich.
        erweitern = seite.locator(_ERWEITERN)
        if not erweitert and erweitern.count() and erweitern.first.is_visible():
            erweitern.first.click(timeout=max(1000, min(5000, wartezeit_ms)))
            erweitert = True
            seite.wait_for_timeout(intervall_ms)
        try:
            eintraege, _anzahl, _fin_erkennbar = _historienmoment(seite.content(), fin, objekt, attribut)
        except ValueError:
            # Seitenwechsel / Angular ist noch nicht fertig. Nicht als 0 Treffer zaehlen.
            eintraege = ()
        if eintraege:
            jetzt = time.monotonic()
            if eintraege != letzte_signatur:
                letzte_signatur, stabil_seit = eintraege, jetzt
            elif stabil_seit is not None and (jetzt - stabil_seit) * 1000 >= ruhezeit_ms:
                return _bewerte_historie(fin, eintraege, objekt=objekt, attribut=attribut)
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
            eintraege, anzahl, gilt_fin = _historienmoment(seite.content(), fin, objekt, attribut)
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
                ergebnis = _bewerte_historie(fin, eintraege, objekt=objekt, attribut=attribut)
                return _ergebnis(
                    fin, ergebnis.status, seriennummer=ergebnis.seriennummer,
                    hinweis=("Treffer nach ungefilterter Nachpruefung. " + ergebnis.hinweis),
                    aenderungen=ergebnis.aenderungen, objekt=objekt, attribut=attribut,
                )
        else:
            letzte_signatur, stabil_seit = None, None
        seite.wait_for_timeout(intervall_ms)
    # Negativbefund nur, wenn ein eindeutig zugeordnetes, nichtleeres
    # Historienbild am Ende der Nachpruefung mindestens 1 Sekunde stabil war.
    if (letzte_anzahl > 0 and unveraendert_seit is not None
            and (time.monotonic() - unveraendert_seit) >= 1.0
            and not fehlerhafte_fins):
        status = ("keine_seriennummer_aenderung" if attribut.casefold() ==
                  _STANDARD_ATTRIBUT.casefold() else "keine_attributaenderung")
        return _ergebnis(
            fin, status,
            hinweis="Nach Wartezeit auch ungefiltert keine passende Objekt-/Attributaenderung gefunden.",
            objekt=objekt, attribut=attribut,
        )
    return _ergebnis(
        fin, "historie_nicht_bestaetigt",
        hinweis="Historie nach Wartezeit nicht vollstaendig / FIN nicht zweifelsfrei belegt.",
        objekt=objekt, attribut=attribut,
    )


def _bewerte_historie(
    fin: str, eintraege: tuple[SeriennummerAenderung, ...], *,
    objekt: str = _STEUERGERAET, attribut: str = _STANDARD_ATTRIBUT,
) -> Ergebnis:
    """Letzten dokumentierten neuen Wert ableiten, nicht den aktuellen Einbau behaupten."""
    ziel = {"objekt": objekt, "attribut": attribut}
    if not eintraege:
        status = ("keine_seriennummer_aenderung" if attribut.casefold() ==
                  _STANDARD_ATTRIBUT.casefold() else "keine_attributaenderung")
        return _ergebnis(fin, status,
                         hinweis="Keine passende Objekt-/Attributaenderung in der Historie.", **ziel)
    try:
        sortiert = sorted(eintraege, key=lambda x: datetime.strptime(
            x.aenderungszeitpunkt, "%d.%m.%Y %H:%M:%S"
        ))
    except ValueError:
        return _ergebnis(fin, "zeitstempel_ungueltig",
                         hinweis="Zeitangabe nicht eindeutig lesbar; kein letzter Attributwert ableitbar.",
                         aenderungen=eintraege, **ziel)
    zeit = sortiert[-1].aenderungszeitpunkt
    letzte_werte = {eintrag.neuer_wert for eintrag in sortiert
                    if eintrag.aenderungszeitpunkt == zeit}
    if len(letzte_werte) != 1:
        return _ergebnis(fin, "mehrdeutig",
                         hinweis="Verschiedene neue Attributwerte zum letzten Zeitpunkt.",
                         aenderungen=tuple(sortiert), **ziel)
    wert = next(iter(letzte_werte))
    if not wert:
        status = ("seriennummer_fehlt" if attribut.casefold() ==
                  _STANDARD_ATTRIBUT.casefold() else "neuer_wert_fehlt")
        return _ergebnis(fin, status,
                         hinweis="Der letzte Historieneintrag enthaelt keinen neuen Wert.",
                         aenderungen=tuple(sortiert), **ziel)
    return _ergebnis(fin, "gefunden", seriennummer=wert,
                     hinweis="Letzter dokumentierter neuer Attributwert aus VeDoc (kein Ist-Zustand).",
                     aenderungen=tuple(sortiert), **ziel)


def _zeitpunkt() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _ergebnis(
    fin: str, status: str, seriennummer: str | None = None, hinweis: str = "",
    aenderungen: tuple[SeriennummerAenderung, ...] = (), *,
    objekt: str = _STEUERGERAET, attribut: str = _STANDARD_ATTRIBUT,
) -> Ergebnis:
    return Ergebnis(fin, objekt, seriennummer, status, hinweis, _zeitpunkt(), aenderungen, attribut)


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


def _abfrage(
    seite, fin: str, timeout_ms: int, historie_wartezeit_ms: int = 20000, *,
    objekt: str = _STEUERGERAET, attribut: str = _STANDARD_ATTRIBUT,
) -> Ergebnis:
    """Historie nach bestaetigtem FIN-Wechsel laden und auf Ergebnisse warten."""
    from playwright.sync_api import TimeoutError as PlaywrightTimeout

    try:
        _fahrzeugdaten_oeffnen(seite, timeout_ms)
        seite.locator(_FIN_EINGABE).fill(fin)
        seite.locator("#VehicleSearch_000_search").click(timeout=timeout_ms)
        seite.wait_for_function(
            """fin => {
                const anzeige = document.querySelector('span[data-ng-bind="viewControl.globalFin"]');
                if (!anzeige) return false;
                const wert = anzeige.textContent.replace(/[\\s-]/g, '').toUpperCase();
                return wert === fin || (fin.length === 14
                    && wert.length === 17 && wert.slice(3) === fin);
            }""",
            arg=fin,
            timeout=timeout_ms,
        )
    except PlaywrightTimeout:
        hinweis = (
            "VeDoc hat nach der Suche keine passende Fahrzeugkennung angezeigt. "
            + (
                "Bei 14-stelliger Kurz-FIN kann eine vollstaendige 17-stellige FIN "
                "fuer die serverseitige Suche erforderlich sein; ggf. --timeout 60 testen."
                if len(fin) == 14
                else "SSO-/Fahrzeugauswahl pruefen; ggf. --timeout 60 testen."
            )
        )
        return _ergebnis(
            fin, "fin_nicht_bestaetigt", hinweis=hinweis,
            objekt=objekt, attribut=attribut,
        )

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
        filter_feld.fill(objekt)
        return _warte_auf_historieneintraege(
            seite, fin, filter_feld, historie_wartezeit_ms,
            objekt=objekt, attribut=attribut,
        )
    except PlaywrightTimeout:
        return _ergebnis(fin, "zeitueberschreitung",
                         hinweis="Historienreiter oder Filter nicht bereit.",
                         objekt=objekt, attribut=attribut)
    except ValueError:
        return _ergebnis(fin, "historie_nicht_bestaetigt",
                         hinweis="Historie ist nicht eindeutig dieser FIN zuzuordnen.",
                         objekt=objekt, attribut=attribut)


def _schreibe_json(
    pfad: Path, ergebnisse: list[Ergebnis], *,
    objekt: str = _STEUERGERAET, attribut: str = _STANDARD_ATTRIBUT,
) -> None:
    fahrzeuge = []
    for eintrag in ergebnisse:
        datenreihe = asdict(eintrag)
        datenreihe["objekt"] = eintrag.objekt
        datenreihe["letzter_neuer_wert"] = eintrag.letzter_neuer_wert
        # Seriennummer ist ein Legacy-Feld: niemals fremde Attribute als solche ausgeben.
        if eintrag.attribut.casefold() != _STANDARD_ATTRIBUT.casefold():
            datenreihe["seriennummer"] = None
        fahrzeuge.append(datenreihe)
    daten = {"quelle": "VeDoc/Historie", "steuergeraet": objekt,
             "objekt": objekt, "attribut": attribut,
             "anzahl": len(ergebnisse), "fahrzeuge": fahrzeuge}
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
                                    if ws.title != "Historie" else
                                    [24, 17, 20, 25, 39, 39, 27]), 1):
        ws.column_dimensions[get_column_letter(nummer)].width = breite
    if zeilen:
        tabelle = Table(displayName="VeDocHistorie" if ws.title == "Historie" else "VeDocUebersicht", ref=f"A1:G{len(zeilen) + 1}")
        tabelle.tableStyleInfo = TableStyleInfo(
            name="TableStyleMedium2", showFirstColumn=False,
            showLastColumn=False, showRowStripes=True, showColumnStripes=False
        )
        ws.add_table(tabelle)


def _schreibe_excel(
    pfad: Path, ergebnisse: list[Ergebnis], *,
    objekt: str = _STEUERGERAET, attribut: str = _STANDARD_ATTRIBUT,
) -> None:
    wb = Workbook()
    uebersicht = wb.active
    uebersicht.title = ("DCDC223" if objekt == _STEUERGERAET
                        and attribut == _STANDARD_ATTRIBUT else "Uebersicht")
    _tabelle_formatieren(
        uebersicht,
        ["FIN", "VeDoc-Objekt", "Letzter neuer Wert (Historie)", "Änderungen", "Status",
         "Hinweis", "Abfragezeit (UTC)"],
        [
            [e.fin, e.objekt, e.letzter_neuer_wert or "", str(len(e.aenderungen)),
             e.status, e.hinweis, e.abgefragt_am_utc]
            for e in ergebnisse
        ],
    )
    historie = wb.create_sheet("Historie")
    zeilen = [
        [e.fin, e.objekt, e.attribut, a.aenderungszeitpunkt,
         a.alter_wert or "", a.neuer_wert or "", e.status]
        for e in ergebnisse for a in e.aenderungen
    ]
    _tabelle_formatieren(
        historie,
        ["FIN", "VeDoc-Objekt", "Attributname", "Änderungszeitpunkt (VeDoc)",
         "Alter Wert", "Neuer Wert", "FIN-Status"],
        zeilen,
    )
    temporaer = pfad.with_suffix(".tmp.xlsx")
    wb.save(temporaer)
    temporaer.replace(pfad)


def main(argv: list[str] | None = None, *, allgemeine_historie: bool = False) -> int:
    parser = argparse.ArgumentParser(
        description="Exportiert die VeDoc-Seriennummern- oder Attributhistorie fuer ein frei waehlbares Hardware-Objekt."
    )
    parser.add_argument("--eingabe", type=Path, help="TXT mit 14-stelliger Kurz-FIN oder 17-stelliger FIN pro Zeile")
    parser.add_argument("--objekt", "--steuergeraet", dest="objekt", default=_STEUERGERAET,
                        help="Exakter VeDoc-Objektname (Standard: DCDC223)")
    parser.add_argument("--attribut", default=_STANDARD_ATTRIBUT,
                        help="Exakter Attributname im VeDoc-Historienreiter (Standard: Seriennummer)")
    parser.add_argument("--ausgabe", type=Path, default=None,
                        help="Zielordner unter data/processed/<TXT-Name>/vedoc_historie (Legacy: vedoc_dcdc223)")
    parser.add_argument("--url", default=os.getenv("VEDOC_URL", VEDOC_START),
                        help="VeDoc-Startadresse (Standard bereits im Skript hinterlegt)")
    parser.add_argument("--browser", choices=["edge", "chromium"], default="edge")
    parser.add_argument("--timeout", type=int, default=30, help="Timeout pro Schritt in Sekunden")
    parser.add_argument("--login-timeout", type=int, default=240,
                        help="Maximale Wartezeit fuer SSO/PING ID in Sekunden")
    parser.add_argument("--historie-wartezeit", type=int, default=20,
                        help="Wartezeit auf Objekt-/Attributhistorie pro FIN in Sekunden (Standard: 20)")
    parser.add_argument("--login-manuell", action="store_true",
                        help="SSO ohne automatisches Ausfuellen von Benutzername/Passwort")
    parser.add_argument("--nur-login", action="store_true",
                        help="Nur den SSO/PING-ID-Login testen, ohne FIN-Abfrage oder Export")
    argumente = parser.parse_args(argv)
    try:
        argumente.objekt = pruefe_historienziel(argumente.objekt, feld="--objekt")
        argumente.attribut = pruefe_historienziel(argumente.attribut, feld="--attribut")
        if argumente.ausgabe is None:
            quelle = ("vedoc-historie" if allgemeine_historie
                      or argumente.objekt != _STEUERGERAET
                      or argumente.attribut != _STANDARD_ATTRIBUT else "dcdc223")
            argumente.ausgabe = (standard_ausgabe(argumente.eingabe, quelle)
                                if argumente.eingabe is not None
                                else Path("data/processed/vedoc_historie" if allgemeine_historie
                                          else "data/processed/vedoc_dcdc223"))
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
    dateistamm = _dateistamm(argumente.objekt, argumente.attribut)
    json_pfad = argumente.ausgabe / f"{dateistamm}.json"
    excel_pfad = argumente.ausgabe / f"{dateistamm}.xlsx"
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
                # Gemeinsamer OS-Lock mit QuickTest-CLI: PING ID nie parallel.
                # Vor der Navigation sperren, da bereits goto einen SSO-Redirect
                # ausloesen kann; nach erfolgreichem Login sofort freigeben.
                with serielle_sso_anmeldung(
                    status=lambda meldung: print(meldung, flush=True),
                ):
                    try:
                        seite.goto(url, wait_until="domcontentloaded", timeout=60_000)
                    except PlaywrightTimeout:
                        # Ein SSO-Redirect kann einen Navigationstimeout ausloesen.
                        pass
                    except Exception as fehler:
                        if _browserfehler(fehler) or not _kontext_hat_seiten(kontext):
                            raise VeDocBrowserFehler(
                                "Browser waehrend der VeDoc-Navigation verloren."
                            ) from None
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
                                objekt=argumente.objekt, attribut=argumente.attribut,
                            )
                        except Exception as fehler:
                            if _browserfehler(fehler) or not _kontext_hat_seiten(kontext):
                                raise VeDocBrowserFehler(
                                    "Browser waehrend der FIN-Abfrage geschlossen oder abgestuerzt."
                                ) from None
                            # Keine internen Browserfehlermeldungen mit FIN/URLs ausgeben.
                            ergebnis = _ergebnis(fin, "fehler", hinweis="VeDoc-Abfrage fehlgeschlagen.",
                                                    objekt=argumente.objekt, attribut=argumente.attribut)
                        ergebnisse.append(ergebnis)
                        _schreibe_json(json_pfad, ergebnisse, objekt=argumente.objekt,
                                        attribut=argumente.attribut)  # Zwischenstand nach jeder FIN.
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
            _schreibe_json(json_pfad, ergebnisse, objekt=argumente.objekt,
                            attribut=argumente.attribut)
            _schreibe_excel(excel_pfad, ergebnisse, objekt=argumente.objekt,
                             attribut=argumente.attribut)
            print(f"JSON: {json_pfad}\nExcel: {excel_pfad}")
        else:
            print("Keine FIN verarbeitet; vorhandene Exporte bleiben unveraendert.", flush=True)
    return returncode


def historie_main(argv: list[str] | None = None) -> int:
    """Neuer neutral benannter CLI-Einstieg fuer beliebige VeDoc-Objekte."""
    return main(argv, allgemeine_historie=True)


if __name__ == "__main__":
    raise SystemExit(main())
