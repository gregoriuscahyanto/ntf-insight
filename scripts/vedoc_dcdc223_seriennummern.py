"""Eigenstaendiger, lesender VeDoc-Export: FIN-TXT -> DCDC223-Seriennummern (JSON/XLSX).

Die Anmeldung erfolgt manuell mit dem berechtigten Unternehmenszugang.
Weder Zugangsdaten noch HTML-Snapshots oder Browser-Profile werden gespeichert.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from lxml import html
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo

_FIN = re.compile(r"[A-HJ-NPR-Z0-9]{17}\Z")
_STEUERGERAET = "DCDC223"
_FIN_EINGABE = 'input[data-ng-model="viewDataObject.vehicleSearchValue"]'
_FIN_ANZEIGE = 'span[data-ng-bind="viewControl.globalFin"]'
_TAB = 'li[heading="Steuergeräte"] a'
_FILTER = 'input[input-binding="viewControl.controlUnitTable_filterExpression"]'
_ZEILE = (
    '#controlUnitTable tbody tr:has('
    'span[data-ng-bind="controlUnitTable_rec.cuDesignation"]:text-is("DCDC223"))'
)


@dataclass(frozen=True)
class Ergebnis:
    fin: str
    steuergeraet: str
    seriennummer: str | None
    status: str
    hinweis: str
    abgefragt_am_utc: str


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


def lese_seriennummer_aus_html(quelltext: str) -> tuple[bool, str | None]:
    """Verknuepft die DCDC223-Bezeichnung und Seriennummer in derselben Tabellenzeile."""
    dokument = html.fromstring(quelltext)
    treffer: list[str | None] = []
    for zeile in dokument.xpath('//table[@id="controlUnitTable"]//tbody/tr'):
        bezeichnungen = zeile.xpath('.//*[@data-ng-bind="controlUnitTable_rec.cuDesignation"]')
        if not any(text.text_content().strip().upper() == _STEUERGERAET for text in bezeichnungen):
            continue
        serielle = zeile.xpath(
            './/*[@data-ng-bind="controlUnitTable_rec.activeState.serialNumber"]'
        )
        seriennummer = serielle[0].text_content().strip() if serielle else ""
        treffer.append(seriennummer or None)
    if len(treffer) > 1:
        raise ValueError("DCDC223 wurde mehrfach gefunden; keine eindeutige Zuordnung.")
    return (True, treffer[0]) if treffer else (False, None)


def _zeitpunkt() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _ergebnis(fin: str, status: str, seriennummer: str | None = None, hinweis: str = "") -> Ergebnis:
    return Ergebnis(fin, _STEUERGERAET, seriennummer, status, hinweis, _zeitpunkt())


def _gekuerzte_fin(fin: str) -> str:
    return f"***{fin[-5:]}"


def _fahrzeugdaten_oeffnen(seite, timeout_ms: int) -> None:
    feld = seite.locator(_FIN_EINGABE)
    if feld.count() and feld.is_visible():
        return
    menue = seite.locator('a[href*="VehicleArrangement.html"]')
    if menue.count():
        menue.first.click(timeout=timeout_ms)
    feld.wait_for(state="visible", timeout=timeout_ms)


def _abfrage(seite, fin: str, timeout_ms: int) -> Ergebnis:
    """Bevor Seriennummern gelesen werden, muss VeDoc exakt diese FIN anzeigen."""
    from playwright.sync_api import TimeoutError as PlaywrightTimeout

    try:
        _fahrzeugdaten_oeffnen(seite, timeout_ms)
        seite.locator(_FIN_EINGABE).fill(fin)
        seite.locator("#VehicleSearch_000_search").click(timeout=timeout_ms)
        # Schutz gegen Daten des vorherigen Fahrzeugs bei langsamer Angular-Antwort.
        seite.wait_for_function(
            """fin => {
                const anzeige = document.querySelector('span[data-ng-bind="viewControl.globalFin"]');
                return !!anzeige && anzeige.textContent.replace(/[\\s-]/g, '').toUpperCase() === fin;
            }""",
            arg=fin,
            timeout=timeout_ms,
        )
    except PlaywrightTimeout:
        return _ergebnis(fin, "fin_nicht_bestaetigt", hinweis="FIN-Wechsel in VeDoc nicht bestaetigt.")

    try:
        seite.locator(_TAB).click(timeout=timeout_ms)
        seite.locator("#controlUnitTable").wait_for(state="visible", timeout=timeout_ms)
        filter_feld = seite.locator(_FILTER)
        if not filter_feld.is_visible():
            seite.locator('button[data-ng-click*="toggleFilter"][data-ng-click*="controlUnitTable"]').click(
                timeout=timeout_ms
            )
        filter_feld.fill(_STEUERGERAET)
        # Die Tabelle wird dynamisch gefiltert; Enter ist laut Anleitung nicht noetig.
        try:
            seite.locator(_ZEILE).first.wait_for(state="visible", timeout=min(timeout_ms, 8000))
        except PlaywrightTimeout:
            pass  # Bei bekannter FIN darf ein DCDC223 tatsaechlich fehlen.
        vorhanden, seriennummer = lese_seriennummer_aus_html(seite.content())
        if not vorhanden:
            return _ergebnis(fin, "steuergeraet_nicht_gefunden", hinweis="Kein DCDC223-Eintrag.")
        if not seriennummer:
            return _ergebnis(fin, "seriennummer_fehlt", hinweis="DCDC223 ohne Seriennummer.")
        return _ergebnis(fin, "gefunden", seriennummer=seriennummer)
    except ValueError:
        return _ergebnis(fin, "mehrdeutig", hinweis="Mehrere DCDC223-Eintraege vorhanden.")
    except PlaywrightTimeout:
        return _ergebnis(fin, "zeitueberschreitung", hinweis="Steuergeraete-Tabelle nicht erreichbar.")


def _schreibe_json(pfad: Path, ergebnisse: list[Ergebnis]) -> None:
    daten = {"quelle": "VeDoc", "steuergeraet": _STEUERGERAET,
             "anzahl": len(ergebnisse), "fahrzeuge": [asdict(x) for x in ergebnisse]}
    temporaer = pfad.with_suffix(pfad.suffix + ".tmp")
    temporaer.write_text(json.dumps(daten, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporaer.replace(pfad)


def _schreibe_excel(pfad: Path, ergebnisse: list[Ergebnis]) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "DCDC223"
    ws.sheet_view.showGridLines = False
    spalten = ["FIN", "Steuergerät", "Seriennummer", "Status", "Hinweis", "Abfragezeit (UTC)"]
    ws.append(spalten)
    for zelle in ws[1]:
        zelle.fill = PatternFill("solid", fgColor="1C2730")
        zelle.font = Font(name="Aptos", size=11, bold=True, color="FFFFFF")
        zelle.alignment = Alignment(vertical="center")
    ws.row_dimensions[1].height = 25
    for eintrag in ergebnisse:
        werte = [eintrag.fin, eintrag.steuergeraet, eintrag.seriennummer or "",
                 eintrag.status, eintrag.hinweis, eintrag.abgefragt_am_utc]
        ws.append(werte)
        for zelle in ws[ws.max_row]:
            # Externe Inhalte bleiben Text, auch wenn sie mit '=' beginnen.
            zelle.data_type = "s"
            zelle.number_format = "@"
            zelle.alignment = Alignment(vertical="center")
        ws.cell(ws.max_row, 3).font = Font(name="Aptos", color="16635A")
        ws.row_dimensions[ws.max_row].height = 22
    for nummer, breite in enumerate((24, 17, 35, 30, 55, 28), 1):
        ws.column_dimensions[get_column_letter(nummer)].width = breite
    ws.freeze_panes = "A2"
    if ergebnisse:
        tabelle = Table(displayName="VeDocDCDC223", ref=f"A1:F{len(ergebnisse) + 1}")
        tabelle.tableStyleInfo = TableStyleInfo(
            name="TableStyleMedium2", showFirstColumn=False,
            showLastColumn=False, showRowStripes=True, showColumnStripes=False
        )
        ws.add_table(tabelle)
    temporaer = pfad.with_suffix(".tmp.xlsx")
    wb.save(temporaer)
    temporaer.replace(pfad)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Liest die DCDC223-Seriennummer je FIN aus VeDoc und exportiert JSON + Excel."
    )
    parser.add_argument("--eingabe", required=True, type=Path, help="TXT mit einer FIN pro Zeile")
    parser.add_argument("--ausgabe", type=Path, default=Path("data/processed/vedoc_dcdc223"),
                        help="Lokales Zielverzeichnis (wird ueberschrieben)")
    parser.add_argument("--url", default=os.getenv("VEDOC_URL", ""),
                        help="VeDoc-Startadresse; alternativ Umgebungsvariable VEDOC_URL")
    parser.add_argument("--browser", choices=["edge", "chromium"], default="edge")
    parser.add_argument("--timeout", type=int, default=30, help="Timeout pro Schritt in Sekunden")
    argumente = parser.parse_args(argv)
    try:
        fins = lade_fins(argumente.eingabe)
        url = pruefe_vedoc_url(argumente.url)
        if not 5 <= argumente.timeout <= 120:
            raise ValueError("--timeout muss zwischen 5 und 120 Sekunden liegen.")
    except (OSError, ValueError) as fehler:
        parser.error(str(fehler))

    argumente.ausgabe.mkdir(parents=True, exist_ok=True)
    json_pfad = argumente.ausgabe / "dcdc223_seriennummern.json"
    excel_pfad = argumente.ausgabe / "dcdc223_seriennummern.xlsx"
    ergebnisse: list[Ergebnis] = []
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            start_parameter = {"headless": False}
            if argumente.browser == "edge":
                start_parameter["channel"] = "msedge"
            browser = playwright.chromium.launch(**start_parameter)
            try:
                kontext = browser.new_context(accept_downloads=False)
                seite = kontext.new_page()
                seite.goto(url, wait_until="domcontentloaded", timeout=60_000)
                input("VeDoc-Anmeldung (ggf. PING ID) im Browser abschliessen, dann Enter druecken: ")
                _fahrzeugdaten_oeffnen(seite, argumente.timeout * 1000)
                for nummer, fin in enumerate(fins, 1):
                    try:
                        ergebnis = _abfrage(seite, fin, argumente.timeout * 1000)
                    except Exception:
                        # Keine internen Browserfehlermeldungen mit FIN/URLs ausgeben.
                        ergebnis = _ergebnis(fin, "fehler", hinweis="VeDoc-Abfrage fehlgeschlagen.")
                    ergebnisse.append(ergebnis)
                    _schreibe_json(json_pfad, ergebnisse)  # Zwischenstand nach jeder FIN.
                    print(f"[{nummer}/{len(fins)}] {_gekuerzte_fin(fin)}: {ergebnis.status}")
            finally:
                browser.close()  # Temporaeres Profil; keine SSO-Sitzung speichern.
    except (KeyboardInterrupt, EOFError):
        print("Abgebrochen: bisherige Ergebnisse werden exportiert.")
        returncode = 130
    except Exception as fehler:
        print(f"VeDoc konnte nicht gestartet werden ({type(fehler).__name__}).")
        returncode = 2
    else:
        returncode = 0 if all(x.status == "gefunden" for x in ergebnisse) else 1
    finally:
        _schreibe_json(json_pfad, ergebnisse)
        _schreibe_excel(excel_pfad, ergebnisse)
        print(f"JSON: {json_pfad}\nExcel: {excel_pfad}")
    return returncode


if __name__ == "__main__":
    raise SystemExit(main())
