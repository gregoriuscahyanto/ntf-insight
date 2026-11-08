#!/usr/bin/env python3
"""Eigenstaendiger Diagnosis-Viewer-Scraper fuer Warning and Error Messages.

Eingabe: TXT mit FINs. Ausgabe: eine JSON-Datei mit atomaren Checkpoints.
Nutzt ausschliesslich das vorhandene Edge und die interaktive Unternehmens-SSO.
Es werden keine QuickTest-PDFs heruntergeladen.
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import re
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlsplit

SEARCH_URL = "https://app.diagviewer.prod.gspp-eu.cloud.corpintra.net/search"
VIEWER_HOST = urlsplit(SEARCH_URL).hostname
API_HOST = "api.diagviewer.prod.gspp-eu.cloud.corpintra.net"
LOGIN_HOST = "login.mercedes-benz.com"
SOURCES = "XD,XD(AQT),TD,DAS"
FIN_PATTERN = re.compile(r"[A-HJ-NPR-Z0-9]{17}\Z")
ENDED = {"erfolgreich", "keine_meldungen"}
SCHEMA_VERSION = 1


class Abbruch(RuntimeError):
    """Geordneter Abbruch, damit der letzte Checkpoint erhalten bleibt."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_fins(path: Path) -> list[str]:
    if path.suffix.lower() != ".txt":
        raise ValueError("Die Eingabe muss eine .txt-Datei sein.")
    content = path.read_text(encoding="utf-8-sig")
    tokens: list[str] = []
    for line in content.splitlines():
        without_comment = line.split("#", 1)[0]
        tokens.extend(item.upper() for item in re.split(r"[\s,;]+", without_comment) if item)
    if not tokens:
        raise ValueError("Die TXT-Datei enthaelt keine FIN.")
    invalid = [item for item in tokens if not FIN_PATTERN.fullmatch(item)]
    if invalid:
        raise ValueError("Ungueltige 17-stellige FIN(s): " + ", ".join(invalid[:5]))
    return list(dict.fromkeys(tokens))


def search_url(fin: str) -> str:
    if not FIN_PATTERN.fullmatch(fin):
        raise ValueError("FIN muss 17 Zeichen ohne I, O und Q besitzen.")
    return f"{SEARCH_URL}?fin={fin}&sources={quote(SOURCES, safe='')}"


def fresh_state() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "quelle": "Mercedes-Benz Diagnosis Viewer / Warning and Error Messages",
        "erstellt_utc": utc_now(),
        "aktualisiert_utc": utc_now(),
        "fahrzeuge": {},
    }


def load_state(output: Path) -> dict[str, Any]:
    if not output.exists():
        return fresh_state()
    with output.open("r", encoding="utf-8") as stream:
        data = json.load(stream)
    if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Bestehende Ausgabedatei hat eine unbekannte JSON-Struktur.")
    if not isinstance(data.get("fahrzeuge"), dict):
        raise ValueError("Ausgabedatei enthaelt kein gueltiges 'fahrzeuge'-Objekt.")
    return data


def save_state(output: Path, state: dict[str, Any]) -> None:
    """Ganze JSON-Datei auf demselben Datentraeger atomar austauschen.

    Bei SIGKILL/Absturz bleibt die vorangehende gueltige JSON-Version bestehen.
    """
    output.parent.mkdir(parents=True, exist_ok=True)
    state["aktualisiert_utc"] = utc_now()
    fd, name = tempfile.mkstemp(prefix=f".{output.stem}.", suffix=".tmp", dir=output.parent)
    temp_path = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(state, stream, indent=2, ensure_ascii=False, sort_keys=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, output)
    finally:
        temp_path.unlink(missing_ok=True)


def session_key(href: str) -> str:
    """Stabile ID aus dem Original-Sitzungslink (kein Index der Suchliste)."""
    p = urlsplit(href)
    q = parse_qs(p.query)
    identity = "|".join((p.path, q.get("s3PathName", [""])[0], q.get("diagStartTsLocal", [""])[0]))
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]


def safe_view_link(href: str, fin: str) -> bool:
    p = urlsplit(href)
    return (
        p.scheme == "https"
        and p.hostname == VIEWER_HOST
        and p.path.startswith("/view/")
        and parse_qs(p.query).get("fin", [""])[0].upper() == fin
    )


def view_filename(href: str) -> str:
    """S3-Dateiname aus der bereits im Viewer sichtbaren /view/-Adresse."""
    path = urlsplit(href).path
    match = re.fullmatch(r"/view/[^/]+/(.+)", path)
    if not match:
        raise ValueError("Unerwartete Sitzungsadresse im Diagnosis Viewer.")
    return unquote(match.group(1))


def _raw_warnings(obj: Any, depth: int = 0) -> list[dict[str, Any]] | None:
    """Nur den expliziten Warnungsabschnitt aus einer API-Antwort herauslesen."""
    if depth > 6:
        return None
    if isinstance(obj, dict):
        if "warningEventMessages" in obj:
            value = obj["warningEventMessages"]
            if isinstance(value, list) and all(isinstance(x, dict) for x in value):
                return value
            if isinstance(value, dict):
                return _raw_warnings(value, depth + 1)
        if "warn_hil_id" in obj:
            return [obj]
        for key in ("data", "result", "payload", "section", "warningEventMessages"):
            if key in obj:
                result = _raw_warnings(obj[key], depth + 1)
                if result is not None:
                    return result
    if isinstance(obj, list) and all(isinstance(x, dict) for x in obj):
        if not obj or any("warn_" in key for item in obj[:3] for key in item):
            return obj
    return None


def _field(value: dict[str, Any], key: str) -> Any:
    result = value.get(key)
    return result if result is not None else None


def normalize_raw(message: dict[str, Any]) -> dict[str, Any]:
    """UI-relevante Felder plus unveraenderte Meldungs-Rohdaten bewahren."""
    event_types = {1: "Lampe", 2: "Displaymeldung", 3: "Ton"}
    event_num = message.get("warn_event_type_id")
    try:
        event_label = event_types.get(int(event_num), "Unbekannt")
    except (ValueError, TypeError):
        event_label = "Unbekannt"
    return {
        "kennung": _field(message, "warn_hil_id"),
        "status": _field(message, "warn_message_status_txt"),
        "erstes_auftreten": {
            "wert": _field(message, "warn_original_odometer_nu"),
            "einheit": _field(message, "warn_original_odometer_unit_txt"),
        },
        "letztes_auftreten": {
            "wert": _field(message, "warn_most_recent_odometer_nu"),
            "einheit": _field(message, "warn_most_recent_odometer_unit_txt"),
        },
        "haeufigkeit": _field(message, "warn_frequency_nu"),
        "zuendzyklen": _field(message, "warn_ignition_cycle_nu"),
        "ereignistyp": {"id": event_num, "bezeichnung": event_label},
        "anzeigetext": {
            "de": _field(message, "warn_text_de_txt"),
            "en": _field(message, "warn_text_en_txt"),
        },
        "lampen_ton_symbol_text": {
            "de": _field(message, "warn_icon_de_txt"),
            "en": _field(message, "warn_icon_en_txt"),
        },
        "rohdaten": message,
    }


def _int_or_none(text: str) -> int | None:
    text = text.strip()
    if not re.fullmatch(r"-?\d+", text):
        return None
    return int(text)


def normalize_dom(row: list[str]) -> dict[str, Any]:
    """Fallback aus den 9 in der Anleitung gezeigten UI-Spalten."""
    if len(row) != 9:
        raise ValueError("Die Meldungstabelle hat nicht die erwarteten neun Spalten.")
    return {
        "kennung": row[0], "status": row[1],
        "erstes_auftreten": {"anzeige": row[2]},
        "letztes_auftreten": {"anzeige": row[3]},
        "haeufigkeit": _int_or_none(row[4]),
        "zuendzyklen": _int_or_none(row[5]),
        "ereignistyp": {"bezeichnung": row[6]},
        "anzeigetext": {"angezeigt": row[7]},
        "lampen_ton_symbol_text": {"angezeigt": row[8]},
        "rohdaten": None,
    }


def no_sensitive_error(exc: BaseException) -> str:
    """URL-Parameter/SSO-Tokens in Fehlermeldungen nicht protokollieren."""
    message = re.sub(r"https?://\S+", "<URL>", str(exc))
    return f"{type(exc).__name__}: {message[:400]}"


class Taktung:
    def __init__(self, interval: float):
        self.interval = max(0.0, interval)
        self.last: float | None = None

    def pause(self) -> None:
        now = time.monotonic()
        if self.last is not None:
            delay = self.last + self.interval - now
            if delay > 0:
                time.sleep(delay)
        self.last = time.monotonic()


class WarningCapture:
    """Passiv nur Warnungsfelder aus den legitimen Viewer-Antworten aufnehmen."""

    def __init__(self):
        self.messages: list[dict[str, Any]] | None = None
        self.empty_verified = False

    def observe(self, response: Any) -> None:
        try:
            url = urlsplit(response.url)
            if url.scheme != "https" or url.hostname != API_HOST:
                return
            if url.path == "/view/section":
                query = parse_qs(url.query)
                if query.get("section") != ["warningEventMessages"]:
                    return
            elif url.path != "/view":
                return
            if response.status != 200 or "json" not in response.headers.get("content-type", "").lower():
                return
            payload = response.json()
            records = _raw_warnings(payload)
            if records is not None:
                self.messages = records
                self.empty_verified = not records
            elif url.path == "/view" and isinstance(payload, dict):
                if payload.get("type") == "sectioned" and isinstance(payload.get("sections"), list):
                    self.empty_verified = "warningEventMessages" not in payload["sections"]
                # Ein unbekannter API-Payload-Typ ist KEIN Beleg fuer 0 Meldungen.
                # Sonst koennte z.B. ein S3-Verweis faelschlich als leer gelten.
        except Exception:
            # Keine HTML-/Login-Antwort als erfolgreichen Datensatz interpretieren.
            return


class DiagnosisViewerScraper:
    def __init__(
        self, output: Path, profile: Path, *, user_id: str = "", password: str = "",
        pacing: float = 1.5, login_timeout: float = 300, page_timeout: float = 70,
    ):
        self.output = output
        self.profile = profile
        self.user_id = user_id
        self.password = password
        self.taktung = Taktung(pacing)
        self.login_timeout = login_timeout
        self.page_timeout = page_timeout
        self.stopped = False

    @staticmethod
    def log(message: str) -> None:
        print(message, flush=True)

    def _login(self, context: Any) -> Any:
        """Bestehende Edge-SSO; PING ID wird nicht automatisiert oder umgangen."""
        deadline = time.monotonic() + self.login_timeout
        submitted = {"user": False, "password": False}
        clicked_sso = False
        self.log("SSO: Bei Aufforderung bitte PING ID auf dem Smartphone bestaetigen.")
        while time.monotonic() < deadline:
            for page in context.pages:
                if page.is_closed():
                    continue
                try:
                    host = urlsplit(page.url).hostname
                    if host == VIEWER_HOST and urlsplit(page.url).scheme == "https":
                        field = page.locator('input[name="finVin"]')
                        if field.count() and field.first.is_visible():
                            return page
                        if not clicked_sso:
                            for role in ("button", "link"):
                                button = page.get_by_role(role, name=re.compile("SSO|Single Sign.On", re.I))
                                if button.count() and button.first.is_visible():
                                    self.taktung.pause()
                                    button.first.click(timeout=4000)
                                    clicked_sso = True
                                    break
                    elif host == LOGIN_HOST and urlsplit(page.url).scheme == "https":
                        cookie = page.locator("#c-s-bn")  # nur notwendige Cookies
                        if cookie.count() and cookie.is_visible():
                            self.taktung.pause()
                            cookie.click(timeout=4000)
                        user_field = page.locator("#userid")
                        if self.user_id and not submitted["user"] and user_field.count() and user_field.is_visible():
                            self.taktung.pause()
                            user_field.fill(self.user_id)
                            self.taktung.pause()
                            page.locator("#next-btn").click(timeout=10000)
                            submitted["user"] = True
                            continue
                        password_field = page.locator("#password")
                        if self.password and not submitted["password"] and password_field.count() and password_field.is_visible():
                            self.taktung.pause()
                            password_field.fill(self.password)
                            self.taktung.pause()
                            page.locator("#loginSubmitButton").click(timeout=10000)
                            submitted["password"] = True
                except Exception:
                    # Kurzlebige Login-Redirects koennen Locator-Zugriffe unterbrechen.
                    continue
            alive = next((p for p in context.pages if not p.is_closed()), None)
            if alive:
                alive.wait_for_timeout(450)
            else:
                time.sleep(0.45)
        raise TimeoutError("SSO/PING ID wurde nicht innerhalb des Zeitlimits abgeschlossen.")

    def _search(self, context: Any, page: Any, fin: str) -> tuple[Any, list[dict[str, str]]]:
        self.taktung.pause()
        page.goto(search_url(fin), wait_until="domcontentloaded", timeout=45000)
        page = self._login(context)
        field = page.locator('input[name="finVin"]')
        self.taktung.pause()
        field.fill(fin)
        self.taktung.pause()
        page.get_by_role("button", name=re.compile(r"^(Search|Suchen)$", re.I)).click(timeout=15000)
        # Ein alter "No Results Found"-Zustand darf nicht als Ergebnis der neuen FIN gelten.
        page.wait_for_timeout(650)
        deadline = time.monotonic() + self.page_timeout
        empty_since: float | None = None
        found: dict[str, dict[str, str]] = {}
        saw_requested_fin = False
        empty = False
        while time.monotonic() < deadline:
            rows = page.evaluate("""(fin) => {
                const table = document.querySelector('table');
                if (!table) return [];
                return Array.from(table.querySelectorAll('tbody tr')).map(tr => {
                    const cells = Array.from(tr.querySelectorAll(':scope > td'));
                    if (cells.length < 10) return null;
                    const text = cell => (cell?.querySelector('[title]')?.getAttribute('title') || cell?.innerText || '').trim();
                    const finCell = text(cells[4]).toUpperCase();
                    const vinCell = text(cells[3]).toUpperCase();
                    if (finCell !== fin && vinCell !== fin) return null;
                    const anchor = Array.from(cells[9].querySelectorAll('a'))
                        .find(a => a.querySelector('svg.lucide-eye'));
                    return {
                        href: anchor?.href || '', quelle: text(cells[0]),
                        diagnosezeitpunkt: text(cells[1]), vin: text(cells[3]),
                        fin: text(cells[4]), baureihe: text(cells[5]),
                        quicktest_anzahl: text(cells[6]), laufleistung: text(cells[8])
                    };
                }).filter(Boolean);
            }""", fin)
            if rows:
                saw_requested_fin = True
                for item in rows:
                    # Auch fehlerhafte/fehlende Augen-Links werden als Problem gemeldet.
                    identifier = item["href"] or f"FEHLENDER_LINK:{item['quelle']}:{item['diagnosezeitpunkt']}"
                    found[identifier] = item
                table = page.locator("table").first
                scroll = page.evaluate("""table => {
                    const el = table.parentElement;
                    const before = el.scrollTop;
                    el.scrollTop = Math.min(el.scrollHeight, el.scrollTop + Math.max(150, el.clientHeight * .72));
                    return {before, after: el.scrollTop, bottom: el.scrollTop + el.clientHeight >= el.scrollHeight - 3};
                }""", table.element_handle())
                if scroll["bottom"]:
                    # Einmal noch reagieren lassen, damit virtualisierte Schlusszeilen erscheinen.
                    page.wait_for_timeout(350)
                    last_rows = page.evaluate("""fin => Array.from(document.querySelectorAll('table tbody tr'))
                      .map(tr => { const c = Array.from(tr.querySelectorAll(':scope > td'));
                        if (c.length < 10) return null;
                        const val = i => (c[i].querySelector('[title]')?.getAttribute('title') || c[i].innerText || '').trim();
                        if (val(3).toUpperCase() !== fin && val(4).toUpperCase() !== fin) return null;
                        const a = Array.from(c[9].querySelectorAll('a')).find(x => x.querySelector('svg.lucide-eye'));
                        return {href: a?.href || '', quelle:val(0), diagnosezeitpunkt:val(1),
                          vin:val(3), fin:val(4), baureihe:val(5), quicktest_anzahl:val(6), laufleistung:val(8)};
                      }).filter(Boolean)""", fin)
                    for item in last_rows:
                        found[item["href"] or f"FEHLENDER_LINK:{item['quelle']}:{item['diagnosezeitpunkt']}"] = item
                    break
            else:
                empty_label = page.get_by_text("No Results Found", exact=False)
                if empty_label.count() and empty_label.first.is_visible():
                    if empty_since is None:
                        empty_since = time.monotonic()
                    elif time.monotonic() - empty_since >= 1.5:
                        empty = True
                        break
                else:
                    empty_since = None
            page.wait_for_timeout(450)
        if not saw_requested_fin and not empty:
            raise TimeoutError(f"Keine eindeutigen Suchergebnisse fuer {fin} geladen.")
        if saw_requested_fin:
            # Der Viewer nennt die Gesamtzahl; keinen partiellen Abruf als vollstaendig melden.
            total = page.evaluate(r"""() => {
                const table = document.querySelector('table');
                const text = table?.parentElement?.parentElement?.innerText || '';
                const match = text.match(/Records\s*:\s*(\d+)/i);
                return match ? Number(match[1]) : null;
            }""")
            if total is not None and len(found) < total:
                raise RuntimeError(
                    f"Ergebnisliste unvollstaendig: {len(found)} von {total} Sitzungen gelesen."
                )
        return page, list(found.values())

    def _read_api_section(self, page: Any, href: str) -> list[dict[str, Any]] | None:
        """Vom Browser bereits genutzte Leseschnittstelle, ausschliesslich section=warningEventMessages.

        SSO-Cookies bleiben im Edge-Profil. Eine API-/Login-Fehlantwort wird
        ignoriert und nicht als '0 Meldungen' interpretiert.
        """
        filename = view_filename(href)
        response = page.evaluate("""async (filename) => {
            const endpoint = new URL('https://api.diagviewer.prod.gspp-eu.cloud.corpintra.net/view/section');
            endpoint.searchParams.set('filename', filename);
            endpoint.searchParams.set('section', 'warningEventMessages');
            try {
                const result = await fetch(endpoint.toString(), {credentials: 'include'});
                if (!result.ok || !(result.headers.get('content-type') || '').includes('json')) return null;
                let value = await result.json();
                if (value?.type === 'url' && value?.downloadUrl && value?.fileType === 'gzip') {
                    // Dieselbe freigegebene, signierte Lese-URL, die auch der Viewer verwendet.
                    const sub = await fetch(value.downloadUrl);
                    if (!sub.ok) return null;
                    value = await sub.json();
                }
                if (value?.type === 'url') return null; // ZIP -> DOM-Fallback
                return value;
            } catch { return null; }
        }""", filename)
        return _raw_warnings(response)

    def _read_dom_table(self, page: Any, button: Any) -> list[dict[str, Any]]:
        """Auch TanStack-virtualisierte Tabellen vollstaendig durchscrollen."""
        controls = button.get_attribute("aria-controls")
        scope = page.locator(f'[id="{controls}"]') if controls else page
        deadline = time.monotonic() + self.page_timeout
        while time.monotonic() < deadline:
            no_messages = scope.get_by_text("No warning or error messages", exact=False)
            if no_messages.count() and no_messages.first.is_visible():
                return []
            tables = scope.locator("table")
            if tables.count():
                break
            page.wait_for_timeout(350)
        else:
            raise TimeoutError("Die Warning-and-Error-Messages-Tabelle wurde nicht angezeigt.")
        table = scope.locator("table").first
        count_text = table.locator("xpath=../..").inner_text()
        match = re.search(r"Records\s*:\s*(\d+)", count_text, re.I)
        expected = int(match.group(1)) if match else None
        collected: dict[int, list[str]] = {}
        previous_scroll = -1
        while time.monotonic() < deadline:
            chunk = page.evaluate("""table => {
                const body = table.querySelector('tbody');
                const result = [];
                for (const tr of body.querySelectorAll('tr[data-index]')) {
                    const values = Array.from(tr.querySelectorAll(':scope > td')).map(td => {
                        const titled = Array.from(td.querySelectorAll('[title]'))
                          .map(x => x.getAttribute('title')).find(x => x?.trim());
                        return (titled || td.innerText || '').trim();
                    });
                    result.push({index:Number(tr.dataset.index), values});
                }
                const scroller = table.parentElement;
                const top = scroller.scrollTop;
                const step = Math.max(140, scroller.clientHeight * .7);
                scroller.scrollTop = Math.min(scroller.scrollHeight, top + step);
                return {rows:result, top, next:scroller.scrollTop,
                  bottom:scroller.scrollTop + scroller.clientHeight >= scroller.scrollHeight - 3};
            }""", table.element_handle())
            for item in chunk["rows"]:
                if len(item["values"]) == 9:
                    collected[item["index"]] = item["values"]
            if chunk["bottom"] and chunk["next"] == chunk["top"]:
                # Nach letztem Scrollschritt nochmals denselben Endbereich lesen.
                break
            if chunk["next"] == previous_scroll:
                break
            previous_scroll = chunk["next"]
            page.wait_for_timeout(100)
        if expected is not None and len(collected) != expected:
            raise RuntimeError(f"Tabelle unvollstaendig: {len(collected)} von {expected} Meldungen sichtbar.")
        if not collected and expected != 0:
            raise RuntimeError("Keine Meldungszeilen aus dem DOM gelesen; kein leerer Datensatz bestaetigt.")
        return [normalize_dom(collected[index]) for index in sorted(collected)]

    def _read_session(self, context: Any, href: str) -> tuple[list[dict[str, Any]], str]:
        if not safe_view_link(href, parse_qs(urlsplit(href).query).get("fin", [""])[0]):
            raise ValueError("Sitzungsadresse besitzt keinen erlaubten Diagnosis-Viewer-Host.")
        page = context.new_page()
        capture = WarningCapture()
        page.on("response", capture.observe)
        try:
            self.taktung.pause()
            page.goto(href, wait_until="domcontentloaded", timeout=45000)
            button = page.get_by_role("button", name=re.compile("Warning and Error Messages", re.I))
            deadline = time.monotonic() + self.page_timeout
            while time.monotonic() < deadline:
                if capture.messages is not None:
                    return [normalize_raw(row) for row in capture.messages], "datenstruktur"
                if capture.empty_verified:
                    return [], "datenstruktur"
                if button.count() and button.first.is_visible():
                    break
                page.wait_for_timeout(350)
            else:
                # Falls der Viewer eine leere Warnungssektion ganz ausblendet.
                records = self._read_api_section(page, href)
                if records is not None:
                    return [normalize_raw(row) for row in records], "datenstruktur"
                raise TimeoutError("Warnungssektion nicht vorhanden und keine leeren Quelldaten bestaetigt.")
            if button.get_attribute("aria-expanded") != "true":
                self.taktung.pause()
                button.click(timeout=15000)
            # Leseversuch bevorzugt die strukturierten Originalfelder statt einer UI-Teilansicht.
            if capture.messages is None:
                page.wait_for_timeout(700)
            records = capture.messages
            if records is None:
                records = self._read_api_section(page, href)
            if records is not None:
                return [normalize_raw(row) for row in records], "datenstruktur"
            return self._read_dom_table(page, button), "tabelle"
        finally:
            page.remove_listener("response", capture.observe)
            page.close()

    def run(
        self, fins: list[str], state: dict[str, Any], *,
        refresh: bool, redo: bool, login_only: bool = False,
        browser: str = "edge",
    ) -> int:
        """Pro Sitzung checkpointen; mit --nur-login keinerlei Ausgabedaten veraendern."""
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError("Playwright fehlt: python -m pip install playwright") from exc
        failures = 0
        todo = [] if login_only else [
            fin for fin in fins
            if redo or refresh or state["fahrzeuge"].get(fin, {}).get("status") != "abgeschlossen"
        ]
        if not todo and not login_only:
            self.log("Alle FINs bereits abgeschlossen. --aktualisieren prueft neue Sitzungen.")
            return 0
        self.profile.mkdir(parents=True, exist_ok=True)
        if not login_only:
            save_state(self.output, state)
        with sync_playwright() as playwright:
            try:
                browser_args = {
                    "user_data_dir": str(self.profile), "headless": False,
                    "no_viewport": True, "accept_downloads": False,
                }
                if browser == "edge":
                    browser_args["channel"] = "msedge"
                context = playwright.chromium.launch_persistent_context(**browser_args)
            except Exception as exc:
                raise RuntimeError("Microsoft Edge konnte nicht gestartet werden. Profil ggf. bereits geoeffnet.") from exc
            try:
                page = context.pages[0] if context.pages else context.new_page()
                if login_only:
                    self.taktung.pause()
                    page.goto(SEARCH_URL, wait_until="domcontentloaded", timeout=45000)
                    self._login(context)
                    self.log("SSO/PING ID erfolgreich: Diagnosis Viewer ist erreichbar. Keine FIN abgefragt.")
                    return 0
                for fin_index, fin in enumerate(todo, 1):
                    existing = state["fahrzeuge"].setdefault(fin, {"status": "ausstehend", "sitzungen": {}})
                    existing.setdefault("sitzungen", {})
                    existing["letzter_versuch_utc"] = utc_now()
                    existing["status"] = "in_bearbeitung"
                    save_state(self.output, state)
                    self.log(f"[{fin_index}/{len(todo)}] FIN {fin}: Diagnose-Sitzungen suchen ...")
                    try:
                        page, sessions = self._search(context, page, fin)
                        existing["anzahl_sitzungen_gefunden"] = len(sessions)
                        existing["suchfehler"] = None
                        save_state(self.output, state)
                        for current, session in enumerate(sessions, 1):
                            href = session["href"]
                            key = session_key(href) if href else session_key(f"https://invalid.local/view/{session['quelle']}/{session['diagnosezeitpunkt']}?fin={fin}")
                            entry = existing["sitzungen"].get(key, {})
                            if entry.get("status") in ENDED and not redo:
                                self.log(f"  [{current}/{len(sessions)}] Bereits gespeichert – uebersprungen.")
                                continue
                            if not safe_view_link(href, fin):
                                err = "Kein gueltiger Augen-Link fuer die Diagnose-Sitzung vorhanden."
                                existing["sitzungen"][key] = {
                                    **{k: v for k, v in session.items() if k != "href"},
                                    "status": "fehler", "fehler": err, "versucht_utc": utc_now(),
                                }
                                save_state(self.output, state)
                                self.log(f"  [{current}/{len(sessions)}] {err}")
                                continue
                            self.log(f"  [{current}/{len(sessions)}] {session['quelle']} {session['diagnosezeitpunkt']}: Meldungen ...")
                            try:
                                warnings, method = self._read_session(context, href)
                                existing["sitzungen"][key] = {
                                    **{k: v for k, v in session.items() if k != "href"},
                                    "status": "erfolgreich" if warnings else "keine_meldungen",
                                    "auslesemethode": method, "anzahl_meldungen": len(warnings),
                                    "meldungen": warnings, "abgerufen_utc": utc_now(), "fehler": None,
                                }
                                self.log(f"    {len(warnings)} Meldung(en) / {method}; gespeichert.")
                            except KeyboardInterrupt:
                                raise
                            except Exception as exc:
                                existing["sitzungen"][key] = {
                                    **{k: v for k, v in session.items() if k != "href"},
                                    "status": "fehler", "fehler": no_sensitive_error(exc),
                                    "versucht_utc": utc_now(),
                                }
                                self.log(f"    FEHLER: {no_sensitive_error(exc)}")
                            finally:
                                save_state(self.output, state)
                        current_ids = [
                            session_key(item["href"]) if item["href"] else session_key(
                                f"https://invalid.local/view/{item['quelle']}/{item['diagnosezeitpunkt']}?fin={fin}"
                            ) for item in sessions
                        ]
                        done = len(sessions) == 0 or all(
                            existing["sitzungen"].get(key, {}).get("status") in ENDED
                            for key in current_ids
                        )
                        existing["status"] = "abgeschlossen" if done else "teilweise"
                        if not done:
                            failures += 1
                    except KeyboardInterrupt:
                        existing["status"] = "unterbrochen"
                        save_state(self.output, state)
                        raise
                    except Exception as exc:
                        existing["suchfehler"] = no_sensitive_error(exc)
                        existing["status"] = "fehler"
                        failures += 1
                        self.log(f"  Suchfehler: {no_sensitive_error(exc)}")
                    finally:
                        save_state(self.output, state)
                    self.log(f"  FIN {fin}: {existing['status']}.")
            finally:
                context.close()
                self.password = ""
        return failures


def _load_keyring_credentials() -> tuple[str, str] | None:
    """NTF-Insight-Credentials optional aus dem OS-Tresor, niemals Klartextdatei.

    Kein Eintrag, kein keyring oder gesperrter Tresor bedeutet: manuelle
    Anmeldung im regulaeren Unternehmens-SSO-Fenster ist weiterhin moeglich.
    """
    try:
        import keyring
        if keyring.get_keyring().priority <= 0:
            return None
        uid = keyring.get_password("NTF Insight - Diagnosis Viewer", "benutzer-id")
        password = keyring.get_password("NTF Insight - Diagnosis Viewer", "passwort")
    except Exception:
        return None
    return (uid, password) if uid and password else None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Warning and Error Messages je FIN aus Diagnosis Viewer nach JSON exportieren."
    )
    parser.add_argument("fin_datei", nargs="?", type=Path,
                        help="Optional: FIN-TXT als Positionsargument")
    parser.add_argument("--eingabe", type=Path, help="TXT mit FINs (eine FIN pro Zeile)")
    parser.add_argument("--ausgabe", type=Path,
                        default=Path("data/processed/diagnosis_viewer_warn_error/warnings_errors.json"),
                        help="JSON-Ausgabedatei; erneute Laeufe setzen diesen Stand fort")
    parser.add_argument("--profil", type=Path,
                        default=Path.home() / ".ntf-insight" / "edge-diagnosis-warnungen")
    parser.add_argument("--browser", choices=("edge", "chromium"), default="edge")
    parser.add_argument("--aktualisieren", action="store_true",
                        help="Abgeschlossene FINs nach NEUEN Sitzungen durchsuchen")
    parser.add_argument("--erneut", action="store_true",
                        help="Auch bereits erfolgreiche Sitzungen neu einlesen")
    parser.add_argument("--nur-login", action="store_true",
                        help="Nur SSO/PING-ID testen, ohne FIN-Abfrage oder JSON-Aenderung")
    parser.add_argument("--login-manuell", action="store_true",
                        help="Windows-Tresor nicht lesen; Login komplett im Browser")
    parser.add_argument("--sso-tresor", action="store_true",
                        help="Gespeicherte NTF-Insight-Daten erzwingen; bei Fehlen abbrechen")
    parser.add_argument("--benutzer-id", default="", help="Optionaler SSO-Benutzername")
    parser.add_argument("--passwort-abfragen", action="store_true",
                        help="Passwort bei Bedarf maskiert im Terminal abfragen")
    parser.add_argument("--anmelde-timeout", type=float, default=300)
    parser.add_argument("--seiten-timeout", type=float, default=70)
    parser.add_argument("--abstand", type=float, default=1.5,
                        help="Mindestabstand zwischen Browseraktionen (Sekunden)")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.login_manuell and args.sso_tresor:
            raise ValueError("--login-manuell und --sso-tresor schliessen sich aus.")
        if args.login_manuell and args.passwort_abfragen:
            raise ValueError("--login-manuell und --passwort-abfragen schliessen sich aus.")
        if args.eingabe and args.fin_datei and args.eingabe != args.fin_datei:
            raise ValueError("Bitte nur eine Eingabedatei angeben.")
        input_path = args.eingabe or args.fin_datei
        if not args.nur_login and input_path is None:
            raise ValueError("Eine FIN-Liste mit --eingabe muss angegeben werden.")
        fins = [] if args.nur_login else read_fins(input_path)
        output = args.ausgabe.expanduser().resolve()
        if output.suffix.lower() != ".json":
            raise ValueError("Die Ausgabe muss die Endung .json besitzen.")
        if input_path is not None and output == input_path.expanduser().resolve():
            raise ValueError("Eingabe und Ausgabe muessen unterschiedliche Dateien sein.")
        if not 30 <= args.anmelde_timeout <= 900:
            raise ValueError("--anmelde-timeout muss 30 bis 900 Sekunden betragen.")
        if not 5 <= args.seiten_timeout <= 180:
            raise ValueError("--seiten-timeout muss 5 bis 180 Sekunden betragen.")
        if args.abstand < 1.0:
            raise ValueError("--abstand muss mindestens 1 Sekunde betragen.")
        state = fresh_state() if args.nur_login else load_state(output)

        user_id, password = args.benutzer_id, ""
        if not args.login_manuell and not args.passwort_abfragen:
            saved = _load_keyring_credentials()
            if saved:
                user_id, password = saved
                print("SSO-Daten aus dem Windows-Anmeldeinformationsmanager geladen.", flush=True)
            elif args.sso_tresor:
                raise RuntimeError("Keine gespeicherten SSO-Daten gefunden. --login-manuell nutzen.")
            else:
                print("Keine gespeicherten SSO-Daten: Anmeldung ggf. manuell in Edge.", flush=True)
        elif args.passwort_abfragen:
            user_id = user_id or input("Mercedes-Benz-Benutzerkennung: ").strip()
            password = getpass.getpass("Mercedes-SSO-Passwort (verdeckt): ")

        scraper = DiagnosisViewerScraper(
            output, args.profil.expanduser(), user_id=user_id, password=password,
            pacing=args.abstand, login_timeout=args.anmelde_timeout,
            page_timeout=args.seiten_timeout,
        )
        if not args.nur_login:
            scraper.log(f"FINs: {len(fins)} | Ausgabe: {output}")
        scraper.log("Nur mit berechtigtem Unternehmenszugang und im erlaubten Umfang nutzen.")
        scraper.log("FINs/Diagnosedaten nicht nach GitHub oder in CI-Artefakte hochladen.")
        failed = scraper.run(
            fins, state, refresh=args.aktualisieren, redo=args.erneut,
            login_only=args.nur_login, browser=args.browser,
        )
        if not args.nur_login:
            scraper.log(f"Fertig. Fehlgeschlagene/unvollstaendige FINs: {failed}. Datei: {output}")
        return 1 if failed else 0
    except KeyboardInterrupt:
        print("\nUnterbrochen. Bereits gespeicherte Sitzungen bleiben in der JSON erhalten.",
              file=sys.stderr)
        return 130
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Fehler: {no_sensitive_error(exc)}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())