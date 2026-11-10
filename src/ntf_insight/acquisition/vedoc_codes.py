#!/usr/bin/env python3
"""VeDoc-Fahrzeugcodes (SA-/Ausstattungscodes) fuer eine FIN-Liste auslesen.

Basis: gesicherte VeDoc-HTML-Ansichten und VeDoc-Anleitung aus 'Vedoc Codes.zip'.
Automatisiert die sichtbare VeDoc-Oberflaeche mit Playwright und Microsoft Edge.
Benutzerkennung/Passwort koennen aus dem OS-Tresor eingetragen werden; PING ID bleibt manuell.

Hinweis: VeDoc-Fahrzeugcodes sind KEINE DTCs des CPC3-Steuergeraets.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from ntf_insight.acquisition.output_paths import standard_ausgabe
from ntf_insight.acquisition.sso_login_gate import serielle_sso_anmeldung
from ntf_insight.acquisition.credentials import load_saved_credentials

VEDOC_URL = "https://prod.core.public.vedoc.i.mercedes-benz.com/ui/VehicleArrangement.html"
FIN_REGEX = re.compile(r"[A-HJ-NPR-Z0-9]{17}\Z")
SCHEMA_VERSION = "1.0"
SSO_HOST = 'login.mercedes-benz.com'
VEDOC_HOST = urlsplit(VEDOC_URL).hostname

# Exakt aus dem bereitgestellten VeDoc-HTML (keine wechselnden Angular-IDs).
SUCHFELD = 'input[name="localSearch"]'
SUCHKATEGORIE = 'select[name="vehicleSearchCategory"]'
SUCHBUTTON = '#VehicleSearch_000_search'
AKTUELLE_FIN = '[data-ng-bind="viewControl.globalFin"]'
CODES_TAB = 'li[select*="VehicleCodesArrangement"] a'

# Zugriff auf das im Browser bereits vorhandene AngularJS-Datenmodell.
# Die VeDoc-Datei VehicleCodes_040.js referenziert:
# viewDataObject.consolidatedProductData.equipmentCode.
ANGULAR_CODES_JS = r"""(fin) => {
    const normal = v => String(v ?? '').replace(/\s/g, '').toUpperCase();
    const angular = window.angular;
    if (!angular) return { found: false, codes: [], reason: 'kein-angular' };

    const roots = [
        document.querySelector('#VehicleCodes_040'),
        document.querySelector('[data-ng-controller="VehicleCodes_040GenCtrl"]'),
        document.querySelector('#VehicleArrangement'),
        document.querySelector('#mainwrapper'),
        document.body, document.documentElement, document
    ].filter(Boolean);
    let views = [];
    for (const root of roots) {
        try {
            let scope = angular.element(root).scope?.();
            if (scope) {
                views.push(scope.viewDataObject, scope.$parent?.viewDataObject);
            }
        } catch (_) { /* Angular debug scope kann deaktiviert sein. */ }
        try {
            let injector = angular.element(root).injector?.();
            if (!injector) continue;
            let sharedBO = injector.get('sharedBO');
            if (!sharedBO) continue;
            let scopes = sharedBO.getViewScopes?.();
            views.push(scopes?.VehicleCodes_040?.viewDataObject);
            views.push(scopes?.VehicleArrangement?.viewDataObject);
            let data = sharedBO.getData?.();
            views.push(data?.vehicle, data?.VehicleArrangement, data);
        } catch (_) { /* Kein Einblick in den Angular-Service: DOM-Fallback. */ }
    }

    for (const data of views) {
        if (!data || typeof data !== 'object') continue;
        if (data.vehicle?.fin && normal(data.vehicle.fin) !== fin) continue;
        const rows = data.consolidatedProductData?.equipmentCode;
        if (!Array.isArray(rows)) continue;
        const codes = rows.map(x => ({
            code: x?.code ?? x?.codeNumber ?? '',
            benennung: x?.designation?.requestedText ?? x?.designation?.text ?? '',
            produktgruppe: x?.productGroupIndication ?? '',
            codetyp: x?.codeType ?? '',
            quelle: x?.source ?? ''
        }));
        return { found: true, codes, reason: 'datenmodell' };
    }
    return { found: false, codes: [], reason: 'datenmodell-nicht-verfuegbar' };
}"""

# Falls AngularJS in der Produktivversion die Scope-/Service-Abfrage nicht
# bereitstellt, wird die angezeigte Tabelle ausgelesen. Bei virtuellen Tabellen
# werden auch zunaechst nicht gerenderte Zeilen durch Scrollen erfasst.
DOM_CODES_JS = r"""async () => {
    const norm = s => String(s ?? '').replace(/\s+/g, ' ').trim();
    const root = document.querySelector('#VehicleCodes_040')
        || document.querySelector('[data-ng-controller="VehicleCodes_040GenCtrl"]')
        || document;
    const tables = Array.from(root.querySelectorAll('table, [role="table"]'));
    const headersOf = tab => Array.from(tab.querySelectorAll('thead th, [role="columnheader"]'))
        .map(el => norm(el.textContent).toLowerCase());
    const table = tables.find(t => {
        const headers = headersOf(t).join(' | ');
        return /\bcode\b/.test(headers) && /benennung|bezeichnung/.test(headers);
    });
    if (!table) return { found: false, codes: [], reason: 'codetabelle-nicht-im-dom' };

    const headers = headersOf(table);
    const indexOf = (patterns, defaultIndex) => {
        const i = headers.findIndex(h => patterns.some(p => p.test(h)));
        return i >= 0 ? i : defaultIndex;
    };
    const idxCode = indexOf([/^code$/], 1);
    const idxName = indexOf([/benennung/, /bezeichnung/], 2);
    const idxGroup = indexOf([/^pr/, /produktgruppe/], 0);
    const idxType = headers.findIndex((h, i) => i !== idxCode && /code.?typ/.test(h));
    const idxUse = indexOf([/verwendung/, /herkunft/], 4);

    const seen = new Map();
    const capture = () => {
        for (const tr of table.querySelectorAll('tbody tr, [role="rowgroup"] [role="row"]')) {
            const cells = Array.from(tr.querySelectorAll(':scope > td, :scope > [role="cell"]'));
            const get = i => i >= 0 && i < cells.length ? norm(cells[i].textContent) : '';
            const code = get(idxCode).toUpperCase();
            // VeDoc-Codes sind i. d. R. 3-stellige SA-/Ausstattungscodes;
            // die Laenge wird nicht auf 3 beschraenkt.
            if (!/^[A-Z0-9][A-Z0-9._-]{0,19}$/.test(code)) continue;
            const row = {
                code, benennung: get(idxName), produktgruppe: get(idxGroup),
                codetyp: get(idxType), verwendung: get(idxUse)
            };
            const key = JSON.stringify([code, row.produktgruppe, row.codetyp, row.verwendung]);
            const previous = seen.get(key);
            if (!previous || (!previous.benennung && row.benennung)) seen.set(key, row);
        }
    };

    capture();
    let scroll = table.parentElement;
    while (scroll && scroll !== document.documentElement) {
        const css = getComputedStyle(scroll);
        if (scroll.scrollHeight > scroll.clientHeight + 12
                && /auto|scroll/.test(css.overflowY)) break;
        scroll = scroll.parentElement;
    }
    if (scroll && scroll !== document.documentElement) {
        const oldTop = scroll.scrollTop;
        scroll.scrollTop = 0;
        await new Promise(resolve => setTimeout(resolve, 160));
        let stalled = 0;
        let oldCount = seen.size;
        for (let i = 0; i < 220; i++) {
            capture();
            const end = Math.max(0, scroll.scrollHeight - scroll.clientHeight);
            if (scroll.scrollTop >= end - 2) {
                if (++stalled >= 3) break;
            } else {
                const next = Math.min(end, scroll.scrollTop + Math.max(80, scroll.clientHeight * 0.75));
                scroll.scrollTop = next;
            }
            await new Promise(resolve => setTimeout(resolve, 140));
            capture();
            if (seen.size > oldCount) { stalled = 0; oldCount = seen.size; }
            else if (scroll.scrollTop >= end - 2 && ++stalled >= 3) break;
        }
        scroll.scrollTop = oldTop;
    }
    return { found: true, codes: Array.from(seen.values()), reason: 'sichtbare-tabelle' };
}"""


def zeitpunkt() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def lese_fins(pfad: Path) -> list[str]:
    """FINs zeilenweise oder mit Leerzeichen/Komma/Semikolon getrennt lesen."""
    text = pfad.read_text(encoding='utf-8-sig')
    fins: list[str] = []
    ungueltig: list[str] = []
    for zeilennummer, raw in enumerate(text.splitlines(), start=1):
        line = raw.split('#', 1)[0].strip()
        for token in re.split(r'[\s,;]+', line):
            fin = token.strip().upper()
            if not fin or fin in {'FIN', 'VIN'}:
                continue
            if not FIN_REGEX.fullmatch(fin):
                ungueltig.append(f'Zeile {zeilennummer}: {len(fin)} Zeichen / ungueltiges Zeichen')
                continue
            fins.append(fin)
    if ungueltig:
        raise ValueError('Ungueltige FIN-Eintraege:\n  ' + '\n  '.join(ungueltig[:20]))
    if not fins:
        raise ValueError('Keine gueltige 17-stellige FIN in der TXT-Datei gefunden.')
    return list(dict.fromkeys(fins))


def wert_als_text(value: Any) -> str:
    if isinstance(value, dict):
        for key in ('requestedText', 'text', 'value'):
            if key in value:
                return wert_als_text(value[key])
        return ''
    if value is None:
        return ''
    return ' '.join(str(value).split())


def normalisiere_codes(items: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Felder normalisieren, ohne Codes/Nullen abzuschneiden oder umzusortieren."""
    codes = []
    gesehen: set[tuple[str, ...]] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        code = wert_als_text(item.get('code')).upper()
        if not re.fullmatch(r'[A-Z0-9][A-Z0-9._-]{0,19}', code):
            continue
        row = {
            'code': code,
            'benennung': wert_als_text(item.get('benennung') or item.get('designation')),
            'produktgruppe': wert_als_text(item.get('produktgruppe')),
            'codetyp': wert_als_text(item.get('codetyp')),
            'verwendung': wert_als_text(item.get('verwendung')),
            'quelle': wert_als_text(item.get('quelle')),
        }
        key = (row['code'], row['produktgruppe'], row['codetyp'],
               row['verwendung'], row['quelle'])
        if key not in gesehen:
            gesehen.add(key)
            codes.append(row)
    return codes


def kombiniere_codes(
    modell: list[dict[str, Any]], tabelle: list[dict[str, Any]]
) -> list[dict[str, str]]:
    """Alle Modell-Codes behalten und die gerenderte Benennung ergaenzen."""
    model_codes = normalisiere_codes(modell)
    table_codes = normalisiere_codes(tabelle)
    if not model_codes:
        return table_codes
    by_code: dict[str, list[dict[str, str]]] = {}
    for row in table_codes:
        by_code.setdefault(row['code'], []).append(row)
    model_code_set = {r['code'] for r in model_codes}
    for row in model_codes:
        options = by_code.get(row['code'], [])
        match = next((t for t in options if t['benennung']), None)
        if not match and options:
            match = options[0]
        if match:
            for key in ('benennung', 'produktgruppe', 'codetyp', 'verwendung'):
                if not row[key]:
                    row[key] = match[key]
    # Falls die Tabelle zusaetzliche Codes zeigt, gehen diese nicht verloren.
    return model_codes + [r for r in table_codes if r['code'] not in model_code_set]


def speichere_json_zuverlaessig(pfad: Path, daten: dict[str, Any]) -> None:
    pfad.parent.mkdir(parents=True, exist_ok=True)
    tempname: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode='w', encoding='utf-8', dir=pfad.parent,
            prefix=f'.{pfad.stem}.', suffix='.tmp', delete=False,
        ) as stream:
            tempname = stream.name
            json.dump(daten, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tempname, pfad)
    finally:
        if tempname and os.path.exists(tempname):
            os.unlink(tempname)


class Taktgeber:
    """Maximale Abrufrate begrenzen; keine Umgehung von Bot-Schutzmechanismen."""

    def __init__(self, abstand_sekunden: float = 1.5) -> None:
        self.abstand = max(0.5, abstand_sekunden)
        self.letzte_aktion: float | None = None

    def warten(self) -> None:
        if self.letzte_aktion is not None:
            verbleibend = self.letzte_aktion + self.abstand - time.monotonic()
            if verbleibend > 0:
                time.sleep(verbleibend)
        self.letzte_aktion = time.monotonic()


def _sso_ist_vertrauenswuerdig(url: str) -> bool:
    """Zugangsdaten ausschliesslich an den echten Mercedes-Login-Host senden."""
    adresse = urlsplit(url)
    return adresse.scheme == 'https' and adresse.hostname == SSO_HOST


def _vedoc_ist_vertrauenswuerdig(url: str) -> bool:
    adresse = urlsplit(url)
    return adresse.scheme == 'https' and adresse.hostname == VEDOC_HOST


def _zugangsdaten_fuer_lauf() -> tuple[str, str] | None:
    """Bereits gespeicherte NTF-Insight-Daten verwenden oder einmalig abfragen.

    Kein Klartext in Dateien, Umgebungsvariablen, URLs, Logs oder JSON.
    """
    try:
        gespeicherte = load_saved_credentials()
    except RuntimeError:
        gespeicherte = None  # Tresor fehlt/gesperrt: niemals unsichere Ablage verwenden.
    if gespeicherte is not None and gespeicherte.user_id and gespeicherte.password:
        print('Mercedes-SSO: Zugangsdaten aus dem NTF-Insight-Windows-Tresor geladen.')
        return gespeicherte.user_id, gespeicherte.password

    if not sys.stdin.isatty():
        print('Kein OS-Tresoreintrag und kein interaktives Terminal. '
              'SSO bitte manuell im Edge-Fenster ausfuellen.')
        return None

    print('Keine gespeicherten NTF-Insight-SSO-Daten gefunden. '
          'Benutzerkennung und Passwort werden nur fuer diesen Abruf erfragt.')
    benutzer = input('Mercedes-Benz-Benutzerkennung: ').strip()
    if not benutzer:
        raise ValueError('Eine Benutzerkennung ist erforderlich (oder --login-manuell).')
    passwort = getpass.getpass('Mercedes-SSO-Passwort (verdeckt): ')
    if not passwort:
        raise ValueError('Ein Passwort ist erforderlich (oder --login-manuell).')
    return benutzer, passwort


def _sso_ausfuellen(page: Any, zugang: tuple[str, str], gesendet: dict[str, bool]) -> None:
    """SSO-Formular wie bei DCDC223 ausfuellen, nur auf verifiziertem HTTPS-Host."""
    if not _sso_ist_vertrauenswuerdig(page.url):
        return
    cookie = page.locator('#c-s-bn')
    if cookie.count() and cookie.is_visible():
        cookie.click(timeout=3000)

    benutzerfeld = page.locator('#userid')
    if not gesendet['benutzer'] and benutzerfeld.count() and benutzerfeld.is_visible():
        benutzerfeld.fill(zugang[0], timeout=10000)
        page.locator('#next-btn').click(timeout=10000)
        gesendet['benutzer'] = True
        print('Mercedes-SSO: Benutzerkennung gesendet.')
        return

    passwortfeld = page.locator('#password')
    if not gesendet['passwort'] and passwortfeld.count() and passwortfeld.is_visible():
        passwortfeld.fill(zugang[1], timeout=10000)
        page.locator('#loginSubmitButton').click(timeout=10000)
        gesendet['passwort'] = True
        print('Mercedes-SSO: Passwort gesendet. PING ID bei Bedarf selbst bestaetigen.')


def browser_bereit(context: Any, wartezeit: float, *, auto_login: bool = True) -> Any:
    """VeDoc-Suchseite nach regulaerem SSO/PING ID abwarten.

    Die Anmeldung wird nur in der echten Mercedes-SSO-Domaene automatisiert.
    Ein bereits authentifiziertes Edge-Profil braucht keine Passworteingabe.
    """
    print('VeDoc wird in Microsoft Edge geoeffnet.')
    print('PING ID bei Bedarf regulär auf dem Smartphone bestaetigen.')
    if not auto_login:
        print('Manueller Login: Benutzerkennung und Passwort direkt im Browser eingeben.')
    deadline = time.monotonic() + wartezeit
    zugang: tuple[str, str] | None = None
    zugang_geprueft = False
    gesendet = {'benutzer': False, 'passwort': False}
    sso_geklickt = False
    fahrzeugdaten_geklickt = False
    while time.monotonic() < deadline:
        for page in reversed(list(context.pages)):
            if page.is_closed():
                continue
            try:
                if _vedoc_ist_vertrauenswuerdig(page.url):
                    feld = page.locator(SUCHFELD)
                    if feld.count() and feld.first.is_visible():
                        return page

                    if not sso_geklickt:
                        for role in ('button', 'link'):
                            sso = page.get_by_role(role, name=re.compile(r'SSO|Single Sign.On', re.I))
                            if sso.count() and sso.first.is_visible():
                                sso.first.click(timeout=3000)
                                sso_geklickt = True
                                break
                    if not fahrzeugdaten_geklickt:
                        eintrag = page.locator('a[href*="VehicleArrangement.html"]')
                        if eintrag.count() and eintrag.first.is_visible():
                            eintrag.first.click(timeout=3000)
                            fahrzeugdaten_geklickt = True
                elif _sso_ist_vertrauenswuerdig(page.url):
                    # Nach dem SSO-Redirect ggf. erneut "Fahrzeugdaten" oeffnen.
                    fahrzeugdaten_geklickt = False
                    if auto_login:
                        benutzerfeld = page.locator('#userid')
                        passwortfeld = page.locator('#password')
                        anmeldefeld_sichtbar = (
                            bool(benutzerfeld.count() and benutzerfeld.is_visible())
                            or bool(passwortfeld.count() and passwortfeld.is_visible())
                        )
                        # Nur nach Zugangsdaten fragen, wenn tatsaechlich ein
                        # Benutzer-/Passwortfeld sichtbar ist, nie bei PING ID.
                        if anmeldefeld_sichtbar and not zugang_geprueft:
                            zugang = _zugangsdaten_fuer_lauf()
                            zugang_geprueft = True
                        if anmeldefeld_sichtbar and zugang is not None:
                            _sso_ausfuellen(page, zugang, gesendet)
            except (KeyboardInterrupt, EOFError, ValueError):
                raise
            except Exception:
                # Kurzlebige Redirects koennen Playwright-Locators invalidieren.
                continue
        time.sleep(0.4)
    raise TimeoutError('VeDoc-Suche nach SSO/PING ID nicht erreichbar. '
                       'Anmeldung oder Berechtigungen pruefen; ggf. --login-manuell verwenden.')

def suche_fin(page: Any, fin: str, pacer: Taktgeber, timeout_ms: int) -> None:
    kategorie = page.locator(SUCHKATEGORIE)
    if kategorie.count():
        pacer.warten()
        try:
            kategorie.select_option(value='string:finOrVin', timeout=timeout_ms)
        except Exception:
            # AngularJS kann Werte mit dynamischem Prefix rendern.
            kategorie.select_option(label='Fahrzeug-Ident-Nummer (FIN oder VIN)', timeout=timeout_ms)
    pacer.warten()
    page.locator(SUCHFELD).fill(fin, timeout=timeout_ms)
    # AngularJS aktiviert den Suchen-Button ueber eine CSS-Klasse, nicht
    # zwingend ueber das native disabled-Attribut.
    page.wait_for_function(
        "() => { const b = document.querySelector('#VehicleSearch_000_search');"
        " return b && !b.classList.contains('disabled'); }",
        timeout=timeout_ms,
    )
    pacer.warten()
    page.locator(SUCHBUTTON).click(timeout=timeout_ms)
    # Nicht versehentlich Daten der vorherigen FIN uebernehmen.
    page.wait_for_function(
        "fin => { const el = document.querySelector('[data-ng-bind=\"viewControl.globalFin\"]');"
        " return el && el.textContent.replace(/\\s/g, '').toUpperCase() === fin; }",
        arg=fin, timeout=timeout_ms,
    )


def lies_codes(page: Any, fin: str, pacer: Taktgeber, timeout_ms: int) -> tuple[list[dict[str, str]], str]:
    tab = page.locator(CODES_TAB)
    tab.wait_for(state='visible', timeout=timeout_ms)
    pacer.warten()
    tab.click(timeout=timeout_ms)

    # Benennung moeglichst sichtbar schalten (laut Anleitung gibt es
    # "Benennung ausblenden" bzw. "Benennung einblenden").
    anzeigen = page.get_by_text('Benennung einblenden', exact=False)
    try:
        if anzeigen.count() and anzeigen.first.is_visible():
            pacer.warten()
            anzeigen.first.click(timeout=min(3000, timeout_ms))
    except Exception:
        pass

    deadline = time.monotonic() + timeout_ms / 1000
    letzter_modellfund: dict[str, Any] = {'found': False, 'codes': []}
    letzter_domfund: dict[str, Any] = {'found': False, 'codes': []}
    while time.monotonic() < deadline:
        letzter_modellfund = page.evaluate(ANGULAR_CODES_JS, fin)
        if letzter_modellfund.get('found') and letzter_modellfund.get('codes'):
            modell = letzter_modellfund['codes']
            # Wenn Beschreibung / Verwendung im Modell fehlen, die Tabelle
            # zumindest ergaenzend auslesen.
            if all(wert_als_text(x.get('benennung')) for x in modell):
                # Auch bei vollstaendigen Benennungen ist die DOM-Spalte
                # 'Verwendung' interessant (im Modell steht nur 'source').
                letzter_domfund = page.evaluate(DOM_CODES_JS)
                if letzter_domfund.get('codes'):
                    return kombiniere_codes(modell, letzter_domfund['codes']), 'angular-und-dom'
                return normalisiere_codes(modell), 'angular-datenmodell'
            letzter_domfund = page.evaluate(DOM_CODES_JS)
            return kombiniere_codes(modell, letzter_domfund.get('codes', [])), 'angular-und-dom'
        letzter_domfund = page.evaluate(DOM_CODES_JS)
        if letzter_domfund.get('found') and letzter_domfund.get('codes'):
            return normalisiere_codes(letzter_domfund['codes']), 'dom-tabelle'
        if letzter_modellfund.get('found') and letzter_domfund.get('found'):
            return [], 'veDoc-leere-codetabelle'
        page.wait_for_timeout(600)
    raise TimeoutError(
        'VeDoc-Codetabelle / Datenmodell nicht gefunden. '
        'Moeglicherweise hat sich die Oberflaeche geaendert.'
    )


def einlesen_alte_ergebnisse(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    try:
        daten = json.loads(path.read_text(encoding='utf-8'))
        if daten.get('schema_version') != SCHEMA_VERSION:
            raise ValueError('abweichende Schema-Version')
        return {r['fin']: r for r in daten.get('fahrzeuge', []) if isinstance(r, dict) and 'fin' in r}
    except (OSError, ValueError, TypeError) as exc:
        raise ValueError('Bestehende Ausgabedatei ist kein gueltiges VeDoc-JSON.') from exc


def abrufen(args: argparse.Namespace) -> int:
    nur_login = getattr(args, 'nur_login', False)
    if not nur_login:
        if not args.fin_datei.is_file():
            raise FileNotFoundError(f'FIN-Datei fehlt: {args.fin_datei}')
        if args.ausgabe.resolve() == args.fin_datei.resolve():
            raise ValueError('Ausgabedatei darf nicht die FIN-Eingabedatei ueberschreiben.')
        if args.ausgabe.suffix.lower() != '.json':
            raise ValueError('Die Ausgabe muss eine .json-Datei sein.')

    fins = [] if nur_login else lese_fins(args.fin_datei)
    alte = {} if nur_login or args.erneut else einlesen_alte_ergebnisse(args.ausgabe)
    ergebnisse: dict[str, dict[str, Any]] = {}
    for fin in fins:
        prev = alte.get(fin)
        if prev and prev.get('status') in {'erfolgreich', 'keine_codes'}:
            ergebnisse[fin] = prev

    def persistieren() -> None:
        daten = {
            'schema_version': SCHEMA_VERSION,
            'quelle': 'VeDoc PROD / Fahrzeugdaten > Codes',
            'codeart': 'Fahrzeug-/Ausstattungscodes (SA), keine Diagnosefehlercodes (DTC)',
            'stand_utc': zeitpunkt(),
            'anzahl_fins': len(fins),
            'fahrzeuge': [ergebnisse[fin] for fin in fins if fin in ergebnisse],
        }
        speichere_json_zuverlaessig(args.ausgabe, daten)

    rest = [fin for fin in fins if fin not in ergebnisse]
    if not nur_login:
        print(f'{len(fins)} eindeutige FINs, davon {len(rest)} abzufragen.')
        if not rest:
            persistieren()
            print(f'Alle FINs bereits vorhanden: {args.ausgabe}')
            return 0

    # Diese Imports/Browserzugriffe erfolgen nur im echten Abruf.
    from playwright.sync_api import sync_playwright

    profil = args.profil.expanduser().resolve()
    profil.mkdir(parents=True, exist_ok=True)
    if os.name == 'posix':
        os.chmod(profil, 0o700)  # lokales Profil enthaelt sensible SSO-Session-Daten
    pacer = Taktgeber(args.pause)
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(profil), channel='msedge', headless=False,
            accept_downloads=False,
        )
        try:
            page = context.pages[0] if context.pages else context.new_page()
            # PING-ID-Sperre mit den anderen fuenf CLI-Quellen teilen.
            # Datenabrufe beginnen erst nach SSO-Freigabe und laufen parallel.
            with serielle_sso_anmeldung(status=lambda m: print(m, flush=True)):
                try:
                    page.goto(VEDOC_URL, wait_until='domcontentloaded', timeout=60_000)
                except Exception as exc:
                    # SSO-Redirect darf eine manuelle PING-ID-Freigabe nicht abbrechen.
                    if type(exc).__name__ != 'TimeoutError':
                        raise
                page = browser_bereit(
                    context, args.anmeldezeit,
                    auto_login=not getattr(args, 'login_manuell', False),
                )
            if nur_login:
                print('SSO/PING ID erfolgreich: VeDoc-Fahrzeugdaten erreichbar. '
                      'Keine FIN abgefragt oder Ausgabedatei veraendert.')
                return 0
            for idx, fin in enumerate(rest, start=1):
                print(f'[{idx}/{len(rest)}] FIN {fin[:3]}...{fin[-4:]}')
                try:
                    suche_fin(page, fin, pacer, args.ladezeit * 1000)
                    codes, methode = lies_codes(page, fin, pacer, args.ladezeit * 1000)
                    status = 'erfolgreich' if codes else 'keine_codes'
                    ergebnisse[fin] = {
                        'fin': fin, 'status': status,
                        'anzahl_codes': len(codes), 'codes': codes,
                        'extraktionsmethode': methode,
                        'abgerufen_am_utc': zeitpunkt(), 'fehler': None,
                    }
                    print(f'  {len(codes)} Codes erfasst ({methode})')
                except KeyboardInterrupt:
                    print('Abbruch durch Benutzer. Bereits erfasste Daten bleiben erhalten.')
                    persistieren()
                    return 130
                except Exception as exc:
                    meldung = str(exc).splitlines()[0][:250] or type(exc).__name__
                    print(f'  Fehler: {meldung}', file=sys.stderr)
                    ergebnisse[fin] = {
                        'fin': fin, 'status': 'fehler', 'anzahl_codes': 0,
                        'codes': [], 'extraktionsmethode': None,
                        'abgerufen_am_utc': zeitpunkt(), 'fehler': meldung,
                    }
                finally:
                    persistieren()  # Fortschritt nach *jeder* FIN sichern
        finally:
            context.close()

    anzahl_fehler = sum(r['status'] == 'fehler' for r in ergebnisse.values())
    print(f'Fertig. JSON: {args.ausgabe} | Fehler: {anzahl_fehler}')
    return 1 if anzahl_fehler else 0


def kommandozeile(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='VeDoc-Fahrzeugcodes fuer eine FIN-Liste mit Edge/SSO als JSON exportieren.'
    )
    parser.add_argument('fin_datei', nargs='?', type=Path,
                        help='TXT-Datei mit FINs (alternativ --eingabe)')
    parser.add_argument('-i', '--eingabe', type=Path,
                        help='TXT-Datei mit FINs (alternativ als Positionsargument)')
    parser.add_argument('-o', '--ausgabe', type=Path,
                        default=None,
                        help='Ausgabe-JSON (Standard: data/processed/<TXT-Name>/vedoc_codes/vedoc_codes.json)')
    parser.add_argument('--profil', type=Path,
                        default=Path.home() / '.ntf-insight' / 'vedoc-edge-profile',
                        help='Lokales separates Edge-Profil fuer VeDoc-SSO')
    parser.add_argument('--anmeldezeit', type=int, default=300,
                        help='Zeit fuer SSO/PING ID in Sekunden (Standard: 300)')
    parser.add_argument('--ladezeit', type=int, default=45,
                        help='Maximale Ladezeit pro Schritt/FIN in Sekunden (Standard: 45)')
    parser.add_argument('--pause', type=float, default=1.5,
                        help='Mindestpause zwischen Browseraktionen in Sekunden (mind. 0.5)')
    parser.add_argument('--erneut', action='store_true',
                        help='Erfolgreich gespeicherte FINs erneut abrufen (sonst Fortsetzen)')
    parser.add_argument('--login-manuell', action='store_true',
                        help='OS-Tresor nicht lesen; SSO-Anmeldung vollstaendig im Browser')
    parser.add_argument('--nur-login', action='store_true',
                        help='Nur SSO/PING ID testen, keine FIN abfragen oder JSON schreiben')
    args = parser.parse_args(argv)
    if args.fin_datei is not None and args.eingabe is not None:
        parser.error('FIN-Datei entweder positional oder mit --eingabe angeben, nicht beides.')
    if args.fin_datei is None and args.eingabe is None and not args.nur_login:
        parser.error('FIN-Datei fehlt: bitte --eingabe oder Positionsargument verwenden.')
    if args.eingabe is not None:
        args.fin_datei = args.eingabe
    del args.eingabe
    if args.ausgabe is None:
        args.ausgabe = (standard_ausgabe(args.fin_datei, "sa-codes") if args.fin_datei
                        else Path("data/processed/vedoc_codes.json"))
    return args


def main() -> int:
    try:
        return abrufen(kommandozeile())
    except (OSError, ValueError, TimeoutError, EOFError) as exc:
        print(f'Fehler: {exc}', file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print('Anmeldung bzw. Abruf abgebrochen.', file=sys.stderr)
        return 130


if __name__ == '__main__':
    raise SystemExit(main())