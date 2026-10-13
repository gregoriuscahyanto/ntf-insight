"""Lesender QEC-Export mit Playwright und interaktiver Mercedes-Benz-SSO-Anmeldung.

Die bereitgestellten QEC-HTML-Beispiele decken Suche und Anhang-Popup ab.
Die Detailreiter werden anhand der Anleitung angesprochen; ihre Selektoren
muessen mit einem berechtigten QEC-Zugang im Unternehmensnetz geprueft werden.
"""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import Event
from typing import Callable
from urllib.parse import parse_qs, quote, unquote, urljoin, urlsplit

from lxml import html as lxml_html

from ntf_insight.acquisition.qec_archive import case_folder

QEC_START = "https://qect.mo360cp.i.mercedes-benz.com/qec-access/supp/login.qec"
QEC_HOST = urlsplit(QEC_START).hostname
SSO_LOGIN_HOST = "login.mercedes-benz.com"
_QEC_NAV_SELECTOR = 'a[href*="navigationDispatch.qec"][href*="nav_schadteile=1"]'
QEC_SECTIONS = (
    "WE-Daten", "Voranalysen", "Stellungnahme Lieferant",
    "Ergebnis + Nachanalyse", "Historie",
)
_FIN = re.compile(r"[A-HJ-NPR-Z0-9]{17}\Z")
_PUMP = re.compile(r"k(?:u|ue|ü)hlmittelpumpe|umw(?:a|ae|ä)lzpumpe|coolant[ -]?pump", re.I)
_SAFE = re.compile(r"[^a-zA-Z0-9._-]+")
_ID = re.compile(r"(?:\?|&)schadteilID=(\d+)(?:&|\Z)")
_ALLOWED_SUFFIXES = frozenset({
    ".pdf", ".xlsx", ".xls", ".pptx", ".ppt", ".docx", ".doc",
    ".png", ".jpg", ".jpeg", ".zip", ".csv", ".txt", ".xml",
    ".rtf", ".msg", ".eml", ".bin",
})
MAX_ATTACHMENT_BYTES = 100 * 1024 * 1024
Progress = Callable[[str], None]


class QecCancelled(RuntimeError):
    """Der Benutzer hat den Download unterbrochen."""


@dataclass(frozen=True, slots=True)
class QecTarget:
    fin: str
    part_number: str = ""
    reference: str = ""  # Optionaler exakter Schadteilfall: keine FIN-weite Fremdzuordnung.


@dataclass(frozen=True, slots=True)
class QecHit:
    reference: str
    part_number: str
    description: str
    fin: str
    detail_path: str
    schadteil_id: str


@dataclass(slots=True)
class QecResult:
    fin: str
    status: str = "Ausstehend"
    references: list[str] = field(default_factory=list)
    files: list[Path] = field(default_factory=list)
    snapshots: list[Path] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    attempted_at: str = ""
    search_diagnostics: dict[str, int | bool | None] = field(default_factory=dict)


def parse_qec_targets(raw: str) -> list[QecTarget]:
    """FIN pro Zeile, optional '; Sachnummer'. Keine echten FINs in Git einchecken."""
    found: list[QecTarget] = []
    seen: set[tuple[str, str]] = set()
    seen_fin: dict[str, str] = {}
    for line_no, line in enumerate(raw.splitlines(), 1):
        if not line.strip():
            continue
        columns = [cell.strip() for cell in re.split(r"[;\t,]", line)]
        if len(columns) not in (1, 2):
            raise ValueError(f"Zeile {line_no}: FIN und optional eine Sachnummer eingeben.")
        fin = columns[0].upper()
        if not _FIN.fullmatch(fin):
            raise ValueError(f"Zeile {line_no}: FIN muss 17 gueltige Zeichen enthalten.")
        part = columns[1].upper() if len(columns) == 2 else ""
        if part and not re.fullmatch(r"[A-Z0-9 \-]{6,24}", part):
            raise ValueError(f"Zeile {line_no}: ungueltige Sachnummer.")
        key = (fin, _normalize_part(part))
        if fin in seen_fin and seen_fin[fin] != key[1]:
            raise ValueError(f"Zeile {line_no}: FIN mehrfach mit abweichender Sachnummer. "
                             "Fuer alle Pumpen die Sachnummer weglassen.")
        seen_fin[fin] = key[1]
        if key not in seen:
            seen.add(key)
            found.append(QecTarget(fin=fin, part_number=part))
    if not found:
        raise ValueError("Bitte mindestens eine 17-stellige FIN eingeben.")
    return found


def _normalize_part(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", value.upper())


def _safe_name(value: str) -> str:
    # Keine Verzeichnisanteile aus Webseiten-/HTTP-Header-Werten uebernehmen.
    return _SAFE.sub("_", value.replace("\\", "/").split("/")[-1]).strip("._")[:120] or "unbekannt"


def _qec_url(value: str, *, expected_path: str | None = None) -> str:
    resolved = urljoin(QEC_START.replace("supp/login.qec", ""), value)
    parsed = urlsplit(resolved)
    if parsed.scheme != "https" or parsed.hostname != QEC_HOST or parsed.username:
        raise ValueError("QEC-Link verweist auf eine nicht freigegebene Domain.")
    if not parsed.path.startswith("/qec-access/"):
        raise ValueError("Link liegt ausserhalb des QEC-Anwendungsbereichs.")
    if expected_path and parsed.path.rsplit("/", 1)[-1] != expected_path:
        raise ValueError("Unerwartetes QEC-Downloadziel.")
    return resolved


def parse_search_hits(document: str, fin: str, *, part_number: str = "",
                      pump_only: bool = True) -> list[QecHit]:
    """Nur vollstaendige FIN-Treffer aus der 39-spaltigen Schadteiltabelle.

    Ein nur passendes BR-/Endnummer-Paar darf nicht zu einer falschen
    Schadteilzuordnung fuehren. Exakt dieses Tabellenlayout liegt als HTML vor.
    """
    if not _FIN.fullmatch(fin):
        raise ValueError("Ungueltige FIN.")
    root = lxml_html.fromstring(document)
    hits: list[QecHit] = []
    seen: set[str] = set()
    for link in root.xpath("//a[contains(@href, 'schadteilSelektieren.qec')]"):
        href = link.get("href", "")
        match = _ID.search(href)
        if not match:
            continue
        rows = link.xpath("ancestor::tr[1]")
        if not rows:
            continue
        cells = [" ".join(cell.text_content().split()) for cell in rows[0].xpath("./td")]
        if len(cells) < 10:
            continue
        row_fin = "".join(cells[5:10]).replace(" ", "").upper()
        if row_fin != fin:
            continue
        reference = " ".join(link.text_content().split())
        sachnummer = cells[2]
        description = cells[3]
        if pump_only and not _PUMP.search(description):
            continue
        if part_number and _normalize_part(sachnummer) != _normalize_part(part_number):
            continue
        identifier = match.group(1)
        if identifier in seen:
            continue
        _qec_url(href, expected_path="schadteilSelektieren.qec")
        seen.add(identifier)
        hits.append(QecHit(reference, sachnummer, description, row_fin, href, identifier))
    return hits


def inspect_search_results(document: str, target: QecTarget, *, pump_only: bool = True) -> dict[str, int | bool | None]:
    """Check server-rendered filter values before trusting any QEC result rows.

    Form .fill() changes the DOM property, not the original HTML value
    attribute. QEC echoes the submitted values in the *result response*.
    Thus an untouched search form cannot be mistaken for a valid empty result.
    """
    root = lxml_html.fromstring(document)
    br_fields = root.xpath('//input[@name="_finBR"]')
    end_fields = root.xpath('//input[@name="_finEndnummerFrom"]')
    confirmed_filters = bool(
        br_fields and end_fields
        and br_fields[0].get("value", "").strip() == target.fin[3:6]
        and end_fields[0].get("value", "").strip() == target.fin[-6:]
    )
    reported: int | None = None
    for node in root.xpath('//*[contains(concat(" ", normalize-space(@class), " "), " messageGreen ")]'):
        match = re.search(r"(?<!\d)(\d+)\s+Treffer\b", node.text_content(), re.I)
        if match:
            reported = int(match.group(1))
            break
    rows = len(root.xpath("//a[contains(@href, 'schadteilSelektieren.qec')]"))
    ready = confirmed_filters and (rows > 0 or reported == 0)
    # Never interpret *unconfirmed* UI as a zero-result search.
    if not ready:
        return {
            "bestaetigt": False,
            "qec_trefferzahl": reported,
            "sichtbare_zeilen": rows,
            "fin_identisch": 0,
            "pumpen": 0,
            "sachnummer": 0,
        }
    fin_matches = len(parse_search_hits(document, target.fin, pump_only=False))
    pump_matches = len(parse_search_hits(document, target.fin, pump_only=True))
    final_matches = len(parse_search_hits(
        document, target.fin, pump_only=pump_only, part_number=target.part_number,
    ))
    return {
        "bestaetigt": True,
        "qec_trefferzahl": reported,
        "sichtbare_zeilen": rows,
        "fin_identisch": fin_matches,
        "pumpen": pump_matches,
        "sachnummer": final_matches,
    }


def parse_attachment_urls(document: str) -> list[tuple[str, str]]:
    """Anhang-Popup: doppelte Linktexte/Anchors anhand attachmentId entfernen."""
    root = lxml_html.fromstring(document)
    urls: list[tuple[str, str]] = []
    ids: set[str] = set()
    for anchor in root.xpath("//a[contains(@href, 'displayPruefberichtFile.qec')]"):
        url = _qec_url(anchor.get("href", ""), expected_path="displayPruefberichtFile.qec")
        ids_in_url = parse_qs(urlsplit(url).query).get("attachmentId", [])
        if len(ids_in_url) != 1 or not re.fullmatch(r"\d+", ids_in_url[0]):
            continue
        identifier = ids_in_url[0]
        if identifier not in ids:
            ids.add(identifier)
            urls.append((identifier, url))
    return urls


def _validate_attachment_response_url(url: str) -> str:
    """A QEC attachment may redirect internally to a different download action.

    Accept only HTTPS within the original QEC application. Never accept the
    login page, off-domain redirects, or unexpected application roots as files.
    """
    try:
        final = _qec_url(url)
    except ValueError as exc:
        raise ValueError(
            "Anhang wurde ausserhalb der freigegebenen QEC-Anwendung umgeleitet."
        ) from exc
    parsed = urlsplit(final)
    if parsed.port not in (None, 443):
        raise ValueError("Anhang wurde auf einen unzulaessigen QEC-Port umgeleitet.")
    if parsed.path.endswith(("/login.qec", "/qecentry.qec")):
        raise ValueError("QEC leitete den Anhang zur Anmeldung weiter (SSO pruefen).")
    return final


def parse_attachment_listing(document: str) -> list[dict[str, str]]:
    """Store attachment IDs and visible popup-row metadata without active links."""
    root = lxml_html.fromstring(document)
    items: list[dict[str, str]] = []
    seen: set[str] = set()
    for anchor in root.xpath("//a[contains(@href, 'displayPruefberichtFile.qec')]"):
        url = _qec_url(anchor.get("href", ""), expected_path="displayPruefberichtFile.qec")
        ids = parse_qs(urlsplit(url).query).get("attachmentId", [])
        if len(ids) != 1 or not ids[0].isdigit() or ids[0] in seen:
            continue
        seen.add(ids[0])
        rows = anchor.xpath("ancestor::tr[1]")
        columns = [" ".join(c.text_content().split()) for c in rows[0].xpath("./td|./th")] if rows else []
        items.append({
            "anhang_id": ids[0],
            "linktext": " ".join(anchor.text_content().split()),
            "spalten": columns,
        })
    return items


def _filename_from_headers(headers: dict, attachment_id: str, data: bytes) -> str:
    disposition = headers.get("content-disposition", "")
    match = re.search(r"filename\*?=(?:UTF-8''|\")?([^\";]+)", disposition, re.I)
    suggested = unquote(match.group(1).strip()) if match else ""
    suffix = Path(suggested).suffix.lower() if suggested else ""
    if suffix not in _ALLOWED_SUFFIXES:
        if data.startswith(b"%PDF-"):
            suffix = ".pdf"
        elif data.startswith(b"PK\x03\x04"):
            suffix = ".zip"
        elif data.startswith(b"\x89PNG\r\n\x1a\n"):
            suffix = ".png"
        elif data.startswith(b"\xff\xd8\xff"):
            suffix = ".jpg"
        else:
            suffix = ".bin"
    stem = _safe_name(Path(suggested).stem) if suggested else "befundungsbericht"
    return f"{attachment_id}_{stem}{suffix}"


def _store_attachment(folder: Path, attachment_id: str, headers: dict, data: bytes) -> Path:
    if not data or len(data) > MAX_ATTACHMENT_BYTES:
        raise ValueError("QEC-Anhang ist leer oder ueberschreitet 100 MB.")
    content_type = headers.get("content-type", "").lower()
    stripped = data[:512].lstrip().lower()
    if ("text/html" in content_type or stripped.startswith((b"<!doctype html", b"<html"))):
        raise ValueError("Statt eines Anhangs wurde HTML geliefert (Anmeldung pruefen).")
    filename = _filename_from_headers(headers, attachment_id, data)
    if filename.lower().endswith(".pdf") and b"%PDF-" not in data[:1024]:
        raise ValueError("Als PDF bezeichneter QEC-Anhang enthaelt keinen PDF-Header.")
    folder.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(data).hexdigest()
    target = folder / filename
    if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() != digest:
        target = folder / f"{Path(filename).stem}_{digest[:12]}{Path(filename).suffix}"
    if target.is_file():
        return target
    with tempfile.NamedTemporaryFile(dir=folder, suffix=".partial", delete=False) as out:
        temporary = Path(out.name)
        out.write(data)
    try:
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def _write_json(target: Path, payload: dict) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=target.parent, mode="w", encoding="utf-8",
                                     suffix=".partial", delete=False) as stream:
        tmp = Path(stream.name)
        json.dump(payload, stream, indent=2, ensure_ascii=False)
    try:
        tmp.replace(target)
    finally:
        tmp.unlink(missing_ok=True)


def _write_result(folder: Path, result: QecResult) -> None:
    def relative(path: Path) -> str:
        return str(path.relative_to(folder))
    _write_json(folder / "abrufstatus.json", {
        "fin": result.fin,
        "stand_utc": result.attempted_at,
        "status": result.status,
        "referenzen": result.references,
        "anhaenge": [relative(path) for path in result.files],
        "seiten": [relative(path) for path in result.snapshots],
        "hinweise": result.warnings,
        "fehler": result.errors,
        "suchdiagnose": result.search_diagnostics,
    })


def _visible_fields(page) -> list[dict[str, str | bool]]:
    """Visible form values with selected labels and radio/checkbox option values.

    No passwords, hidden inputs, SSO tokens or executable page source are exported.
    """
    return page.evaluate("""() => Array.from(document.querySelectorAll('input, textarea, select'))
      .filter(e => !['hidden', 'password', 'submit', 'button', 'file'].includes((e.type || '').toLowerCase()))
      .filter(e => e.getClientRects().length > 0)
      .map(e => ({
        name: e.name || e.id || '',
        typ: (e.type || e.tagName || '').toLowerCase(),
        wert: e.type === 'checkbox' || e.type === 'radio'
          ? (e.checked ? 'ja' : 'nein') : String(e.value || ''),
        optionwert: ['checkbox', 'radio'].includes(e.type) ? String(e.value || '') : '',
        beschriftung: Array.from(e.labels || []).map(label => label.innerText.trim()).join(' | '),
        auswahltext: e.tagName.toLowerCase() === 'select'
          ? Array.from(e.selectedOptions).map(option => option.textContent.trim()).join(' | ') : '',
        deaktiviert: Boolean(e.disabled),
      }))""")


def _visible_tables(page) -> list[dict]:
    """Preserve visible QEC rows and columns, not just flattened body.innerText."""
    return page.evaluate("""() => Array.from(document.querySelectorAll('table'))
      .filter(table => table.getClientRects().length > 0)
      .map((table, index) => ({
        nummer: index + 1,
        zeilen: Array.from(table.rows)
          .filter(row => row.getClientRects().length > 0)
          .map(row => Array.from(row.cells).map(cell => ({
            typ: cell.tagName.toLowerCase(),
            text: cell.innerText.trim(),
            colspan: cell.colSpan,
          }))),
      })).filter(table => table.zeilen.length > 0)""")


def _snapshot_data(page, section: str, hit: QecHit) -> dict:
    """Collect one complete tab into memory; only the per-case JSON is written.

    Never persist executable scripts, active form links, or credentials.
    """
    return {
        "referenznummer": hit.reference,
        "sachnummer": hit.part_number,
        "bezeichnung": hit.description,
        "fin": hit.fin,
        "bereich": section,
        "zeitpunkt_utc": datetime.now(timezone.utc).isoformat(),
        "sichtbarer_text": page.locator("body").inner_text(timeout=15000),
        "felder": _visible_fields(page),
        "tabellen": _visible_tables(page),
    }


class QecDownloader:
    """Funktioniert nur mit vorhandener QEC-Berechtigung und sichtbarem Edge."""

    def __init__(self, output_dir: Path, profile_dir: Path, *,
                 login_timeout_seconds: int = 240, navigation_timeout_ms: int = 45000,
                 attachment_timeout_ms: int = 90000, pump_only: bool = True,
                 user_id: str = "", password: str = "",
                 click_delay_seconds: float = 0.65) -> None:
        self.output_dir = Path(output_dir)
        self.profile_dir = Path(profile_dir)
        self.login_timeout_seconds = login_timeout_seconds
        self.navigation_timeout_ms = navigation_timeout_ms
        self.attachment_timeout_ms = attachment_timeout_ms
        self.pump_only = pump_only
        self.user_id = user_id
        self.password = password
        self.click_delay_seconds = min(4.0, max(0.0, float(click_delay_seconds)))

    def _pause(self, cancel: Event) -> None:
        """Cancellable pause after QEC navigation/clicks (legacy server UI)."""
        if cancel.wait(self.click_delay_seconds):
            raise QecCancelled("Abruf durch Benutzer beendet.")

    @staticmethod
    def _check_cancel(cancel: Event) -> None:
        if cancel.is_set():
            raise QecCancelled("Abruf durch Benutzer beendet.")

    @staticmethod
    def _is_sso_page(url: str) -> bool:
        parsed = urlsplit(url)
        return parsed.scheme == "https" and parsed.hostname == SSO_LOGIN_HOST

    @staticmethod
    def _is_qec_page(url: str) -> bool:
        parsed = urlsplit(url)
        return (parsed.scheme == "https" and parsed.hostname == QEC_HOST
                and parsed.path.startswith("/qec-access/"))

    @staticmethod
    def _scopes(page):
        # In some QEC deployments navigation lives in a child frame.
        yield page
        main = getattr(page, "main_frame", None)
        for frame in getattr(page, "frames", ()):
            if frame is not main:
                yield frame

    @classmethod
    def _is_qec_ready(cls, page) -> bool:
        if not cls._is_qec_page(page.url):
            return False
        # A completed SSO can land on qecentry.qec before the navigation
        # menu is available. Do not require one exact anchor as login proof.
        if urlsplit(page.url).path.endswith("/qecentry.qec"):
            return True
        for scope in cls._scopes(page):
            if (scope.locator(_QEC_NAV_SELECTOR).count()
                    or (scope.locator('input[name="_finBR"]').count()
                        and scope.locator('input[name="_finEndnummerFrom"]').count())):
                return True
        return False

    def _enter_credentials(self, page, submitted: dict[str, bool], progress: Progress) -> None:
        """Fill only the verified Mercedes SSO pages; PING ID remains manual."""
        if not self._is_sso_page(page.url):
            return
        cookie = page.locator("#c-s-bn")
        if cookie.count() and cookie.is_visible():
            cookie.click(timeout=3000)
        user = page.locator("#userid")
        if self.user_id and not submitted["user"] and user.count() and user.is_visible():
            user.fill(self.user_id)
            page.locator("#next-btn").click(timeout=10000)
            submitted["user"] = True
            progress("Mercedes SSO: Benutzer-ID uebermittelt; Passwortseite wird geoeffnet.")
            return
        password = page.locator("#password")
        if (self.password and not submitted["password"] and password.count()
                and password.is_visible()):
            password.fill(self.password)
            page.locator("#loginSubmitButton").click(timeout=10000)
            submitted["password"] = True
            progress("Mercedes SSO: Anmeldung gesendet; bitte gegebenenfalls PING ID bestaetigen.")

    def _wait_for_login(self, context, progress: Progress, cancel: Event):
        deadline = time.monotonic() + self.login_timeout_seconds
        submitted = {"user": False, "password": False}
        progress("QEC: SSO abwarten. Benutzer-ID/Passwort bei Bedarf in Edge eingeben; PING ID bestaetigen.")
        next_heartbeat = time.monotonic() + 12
        while time.monotonic() < deadline:
            self._check_cancel(cancel)
            for candidate in reversed(context.pages):
                if candidate.is_closed():
                    continue
                try:
                    if self._is_qec_ready(candidate):
                        progress("QEC: Anmeldung abgeschlossen; Schadteilsuche wird geoeffnet.")
                        return candidate
                    if self._is_sso_page(candidate.url):
                        self._enter_credentials(candidate, submitted, progress)
                except QecCancelled:
                    raise
                except Exception:
                    # A navigation can invalidate the locator during SSO redirect.
                    continue
            if time.monotonic() >= next_heartbeat:
                progress("QEC: Anmeldung / PING ID wird noch abgewartet (Abbrechen ist moeglich).")
                next_heartbeat = time.monotonic() + 12
            time.sleep(0.4)
        raise TimeoutError(
            "QEC-Anmeldung nicht erkannt. Bitte pruefen, ob die angemeldete "
            "QEC-Hauptansicht im von NTF Insight gestarteten Edge-Fenster "
            "geoeffnet ist (qecentry.qec)."
        )

    def _search_form(self, context, cancel: Event):
        deadline = time.monotonic() + self.navigation_timeout_ms / 1000
        while time.monotonic() < deadline:
            self._check_cancel(cancel)
            for candidate in reversed(context.pages):
                if candidate.is_closed() or not self._is_qec_page(candidate.url):
                    continue
                for scope in self._scopes(candidate):
                    try:
                        if (scope.locator('input[name="_finBR"]').count()
                                and scope.locator('input[name="_finEndnummerFrom"]').count()):
                            return candidate, scope
                    except Exception:
                        continue
            time.sleep(0.3)
        raise TimeoutError(
            "QEC-Schadteilsuche nicht bereit: die Suchfelder _finBR und "
            "_finEndnummerFrom fehlen. Bitte QEC-Rolle und Navigation pruefen."
        )

    def _wait_search_results(self, context, target: QecTarget,
                             progress: Progress, cancel: Event):
        """Wait for a confirmed server response, scanning QEC pages and frames.

        The search form is present *before* filtering. A URL/form wait alone
        can incorrectly treat an initial empty table as a real zero result.
        """
        deadline = time.monotonic() + self.navigation_timeout_ms / 1000
        last_reported: int | None = None
        last_rows = 0
        while time.monotonic() < deadline:
            self._check_cancel(cancel)
            for candidate in reversed(context.pages):
                if candidate.is_closed() or not self._is_qec_page(candidate.url):
                    continue
                for scope in self._scopes(candidate):
                    try:
                        document = scope.content()
                        evidence = inspect_search_results(
                            document, target, pump_only=self.pump_only,
                        )
                    except (QecCancelled, KeyboardInterrupt):
                        raise
                    except Exception:
                        # Frames may navigate during the polling cycle.
                        continue
                    last_reported = evidence["qec_trefferzahl"]
                    last_rows = max(last_rows, int(evidence["sichtbare_zeilen"]))
                    if evidence["bestaetigt"]:
                        progress(
                            f"QEC: Suchantwort bestaetigt ({evidence['sichtbare_zeilen']} "
                            f"sichtbare Zeilen, {evidence['fin_identisch']} volle FIN-Treffer, "
                            f"{evidence['sachnummer']} passende Bauteile)."
                        )
                        return candidate, scope, document, evidence
            time.sleep(0.35)
        details = (
            f"QEC-Trefferzahl: {last_reported if last_reported is not None else 'unbekannt'}, "
            f"erkannte Trefferlinks: {last_rows}."
        )
        raise TimeoutError(
            "QEC-Suchantwort nach 'Filtern' nicht bestaetigt. "
            "Die Serverantwort muss BR und Endnummer sowie Ergebniszeilen "
            "oder '0 Treffer' enthalten. " + details
        )

    def _search(self, context, page, target: QecTarget, progress: Progress, cancel: Event):
        # The QEC instructions require a fresh start for each FIN/reference.
        self._check_cancel(cancel)
        progress("QEC: Hauptansicht neu oeffnen ...")
        try:
            page.goto(QEC_START, wait_until="domcontentloaded", timeout=self.navigation_timeout_ms)
        except Exception:
            # Interactive SSO may interrupt the initial navigation.
            progress("QEC: Weiterleitung zur Anmeldung; warte auf QEC-Hauptansicht ...")
        page = self._wait_for_login(context, progress, cancel)
        self._pause(cancel)

        nav = None
        for scope in self._scopes(page):
            links = scope.locator(_QEC_NAV_SELECTOR)
            for index in range(min(links.count(), 3)):
                item = links.nth(index)
                if item.is_visible():
                    _qec_url(item.get_attribute("href"), expected_path="navigationDispatch.qec")
                    nav = item
                    break
            if nav is not None:
                break
        if nav is None:
            # This path comes from the provided QEC example, not a guessed URL.
            progress("QEC: Navigationslink fehlt; dokumentierte Schadteilsuche direkt oeffnen ...")
            destination = _qec_url(
                "navigationDispatch.qec?nav_schadteile=1",
                expected_path="navigationDispatch.qec",
            )
            page.goto(destination, wait_until="domcontentloaded", timeout=self.navigation_timeout_ms)
            self._pause(cancel)
        else:
            progress("QEC: Schadteilsuche anklicken ...")
            nav.click(timeout=self.navigation_timeout_ms)
            self._pause(cancel)

        page, form = self._search_form(context, cancel)
        progress("QEC: FIN-Suchfelder erkannt; BR und Endnummer eintragen ...")
        form.locator('input[name="_finBR"]').fill(target.fin[3:6])
        form.locator('input[name="_finEndnummerFrom"]').fill(target.fin[-6:])
        self._pause(cancel)
        progress("QEC: Filtern klicken ...")
        button = form.locator('input[type="submit"][value="Filtern"]')
        if button.count():
            button.first.click(timeout=self.navigation_timeout_ms)
        else:
            form.get_by_role("button", name="Filtern", exact=True).click(
                timeout=self.navigation_timeout_ms
            )
        self._pause(cancel)
        progress("QEC: Auf bestaetigte Suchergebnisse warten ...")
        return self._wait_search_results(context, target, progress, cancel)

    def _click_section(self, page, title: str, cancel: Event) -> bool:
        for role in ("tab", "link", "button"):
            matches = page.get_by_role(role, name=title, exact=True)
            for index in range(min(matches.count(), 4)):
                candidate = matches.nth(index)
                if candidate.is_visible():
                    candidate.click(timeout=12000)
                    self._pause(cancel)
                    return True
        # QEC besitzt in einigen Ansichten klickbare Div-/Tabellenreiter.
        matches = page.get_by_text(title, exact=True)
        for index in range(min(matches.count(), 5)):
            item = matches.nth(index)
            if item.is_visible():
                item.click(timeout=12000)
                self._pause(cancel)
                return True
        return False

    def _download_attachment_api(self, context, popup, attachment_id: str,
                                 url: str, folder: Path) -> Path:
        """Use the browser-context cookies; accept valid QEC-internal redirects.

        The old check required the final URL to be displayPruefberichtFile.qec,
        incorrectly rejecting the QEC download endpoint after a 302 redirect.
        """
        referer = _qec_url(popup.url)
        response = context.request.get(
            url, timeout=self.attachment_timeout_ms,
            headers={"Referer": referer},
        )
        _validate_attachment_response_url(response.url)
        if not response.ok:
            raise RuntimeError(f"QEC-Anhang: HTTP {response.status}.")
        headers = {str(k).lower(): str(v) for k, v in response.headers.items()}
        if int(headers.get("content-length", "0") or 0) > MAX_ATTACHMENT_BYTES:
            raise ValueError("Anhang groesser als 100 MB.")
        return _store_attachment(folder, attachment_id, headers, response.body())

    def _download_attachment_browser(self, popup, attachment_id: str,
                                     url: str, folder: Path) -> Path:
        """Fallback: click the actual authenticated QEC link in visible Edge."""
        links = popup.locator('a[href*="displayPruefberichtFile.qec"]')
        chosen = None
        for index in range(links.count()):
            link = links.nth(index)
            try:
                href = _qec_url(link.get_attribute("href"), expected_path="displayPruefberichtFile.qec")
            except ValueError:
                continue
            if href == url:
                chosen = link
                break
        if chosen is None:
            raise RuntimeError("Anhanglink im QEC-Popup nicht mehr vorhanden.")
        with popup.expect_download(timeout=min(self.attachment_timeout_ms, 20000)) as pending:
            chosen.click(timeout=12000)
        download = pending.value
        if download.failure():
            raise RuntimeError("Edge konnte den QEC-Anhang nicht herunterladen.")
        folder.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=folder, suffix=".partial", delete=False) as stream:
            temporary = Path(stream.name)
        try:
            download.save_as(str(temporary))
            if temporary.stat().st_size > MAX_ATTACHMENT_BYTES:
                raise ValueError("Anhang groesser als 100 MB.")
            headers = {
                "content-disposition": "attachment; filename*=UTF-8''"
                + quote(str(download.suggested_filename), safe=""),
            }
            return _store_attachment(folder, attachment_id, headers, temporary.read_bytes())
        finally:
            temporary.unlink(missing_ok=True)

    def _save_popups(self, context, page, folder: Path, result: QecResult,
                     progress: Progress, cancel: Event,
                     inventory: dict[str, dict[str, str]]) -> None:
        """Collect all popup metadata in memory for the single QEC case JSON."""
        buttons = page.locator('input[type="button"][value="Dateianhänge"], button:has-text("Dateianhänge")')
        for index in range(buttons.count()):
            self._check_cancel(cancel)
            if not buttons.nth(index).is_visible():
                continue
            self._pause(cancel)
            try:
                with page.expect_popup(timeout=12000) as popup_event:
                    buttons.nth(index).click(timeout=12000)
                popup = popup_event.value
                try:
                    popup.wait_for_load_state("domcontentloaded", timeout=15000)
                    self._pause(cancel)
                    original_url = _qec_url(popup.url)
                    document = popup.content()
                    attachments = parse_attachment_urls(document)
                    listing = parse_attachment_listing(document)
                    for item in listing:
                        inventory.setdefault(item["anhang_id"], {}).update({
                            key: value for key, value in item.items()
                            if key in {"anhang_id", "linktext", "spalten"}
                        })
                    if not attachments:
                        result.warnings.append("Anhang-Fenster ohne erkennbare Dateien.")
                    for number, (attachment_id, url) in enumerate(attachments, 1):
                        self._check_cancel(cancel)
                        progress(f"{result.fin}: Anhang {number}/{len(attachments)} wird geladen …")
                        entry = inventory.setdefault(attachment_id, {"anhang_id": attachment_id})
                        existing = next(
                            (item for item in folder.glob(f"{attachment_id}_*") if item.is_file()),
                            None,
                        ) if folder.is_dir() else None
                        if existing:
                            entry.update(status="Bereits vorhanden", datei=existing.name)
                            if existing not in result.files:
                                result.files.append(existing)
                            continue
                        try:
                            try:
                                path = self._download_attachment_api(
                                    context, popup, attachment_id, url, folder,
                                )
                            except Exception as api_error:
                                progress(f"{result.fin}: Anhang {attachment_id}, QEC-Antwort; "
                                         "Download direkt ueber Edge versuchen …")
                                self._pause(cancel)
                                try:
                                    path = self._download_attachment_browser(
                                        popup, attachment_id, url, folder,
                                    )
                                except Exception as edge_error:
                                    raise RuntimeError(
                                        "API-Antwort nicht als Datei verwendbar "
                                        f"({type(api_error).__name__}); Edge-Download fehlgeschlagen "
                                        f"({type(edge_error).__name__})."
                                    ) from edge_error
                                finally:
                                    if not popup.is_closed() and popup.url != original_url:
                                        try:
                                            popup.goto(
                                                original_url, wait_until="domcontentloaded",
                                                timeout=15000,
                                            )
                                            self._pause(cancel)
                                        except QecCancelled:
                                            raise
                                        except Exception:
                                            pass
                            entry.update(status="Gespeichert", datei=path.name)
                            entry.pop("fehler", None)
                            if path not in result.files:
                                result.files.append(path)
                        except QecCancelled:
                            raise
                        except Exception as exc:
                            entry.update(status="Fehler", fehler=str(exc))
                            result.errors.append(f"Anhang {attachment_id}: {exc}")
                finally:
                    popup.close()
            except QecCancelled:
                raise
            except Exception as exc:
                result.errors.append(f"Dateianhaenge-Popup {index + 1}: {exc}")

    def _one_hit(self, context, page, target: QecTarget, hit: QecHit,
                 result: QecResult, progress: Progress, cancel: Event):
        page, result_scope, result_html, _ = self._search(context, page, target, progress, cancel)
        # Selection is by exact QEC ID from a verified full-FIN and reference match.
        hits = parse_search_hits(
            result_html, target.fin,
            part_number=target.part_number, pump_only=self.pump_only,
        )
        if target.reference:
            hits = [entry for entry in hits if entry.reference == target.reference]
        if hit.schadteil_id not in {entry.schadteil_id for entry in hits}:
            raise RuntimeError("Schadteil nach erneutem Oeffnen nicht mehr eindeutig gefunden.")
        self._pause(cancel)
        result_scope.locator(f'a[href*="schadteilID={hit.schadteil_id}"]').first.click(
            timeout=self.navigation_timeout_ms
        )
        self._pause(cancel)
        page.get_by_text("Schadteilmonitor", exact=False).first.wait_for(
            timeout=self.navigation_timeout_ms
        )
        reference_folder = case_folder(self.output_dir, target.fin, hit.reference)
        report_path = reference_folder / "qec.json"
        inventory: dict[str, dict[str, str]] = {}
        previous_case: dict | None = None
        # A repeated download must not silently lose existing attachment evidence.
        if report_path.is_file():
            try:
                previous = json.loads(report_path.read_text(encoding="utf-8"))
                if (previous.get("fin") == target.fin
                        and previous.get("referenznummer") == hit.reference):
                    previous_case = previous
                    for item in previous.get("anhaenge", []):
                        if (isinstance(item, dict) and
                                str(item.get("anhang_id", "")).isdigit()):
                            inventory[str(item["anhang_id"])] = dict(item)
            except (OSError, ValueError, TypeError, AttributeError):
                result.warnings.append(
                    f"{hit.reference}: Vorherige Fall-JSON nicht lesbar; Original bleibt erhalten."
                )

        sections: list[dict] = []
        warning_offset, error_offset = len(result.warnings), len(result.errors)
        previous_signature = None
        try:
            for section in QEC_SECTIONS:
                self._check_cancel(cancel)
                progress(f"{target.fin}: {hit.reference} – {section} …")
                if not self._click_section(page, section, cancel):
                    result.warnings.append(f"{hit.reference}: Reiter {section} nicht gefunden.")
                    continue
                data = _snapshot_data(page, section, hit)
                signature = (data["sichtbarer_text"], str(data["felder"]))
                if signature == previous_signature:
                    result.warnings.append(
                        f"{hit.reference}: {section} zeigt dieselben Daten wie "
                        "der vorherige Reiter; bitte pruefen."
                    )
                previous_signature = signature
                sections.append(data)
                self._save_popups(
                    context, page, reference_folder / "anhaenge",
                    result, progress, cancel, inventory,
                )
        finally:
            # Keep missing previously captured tabs, marked as *older* evidence.
            # Never claim a stale tab was recaptured during the current run.
            freshly_captured = {item["bereich"] for item in sections}
            if previous_case is not None:
                for old_section in previous_case.get("abschnitte", []):
                    if (not isinstance(old_section, dict) or
                            old_section.get("bereich") not in QEC_SECTIONS or
                            old_section["bereich"] in freshly_captured):
                        continue
                    restored = dict(old_section)
                    restored["aus_vorherigem_abruf"] = True
                    sections.append(restored)
                sections.sort(key=lambda item: QEC_SECTIONS.index(item["bereich"]))
            if len(freshly_captured) != len(QEC_SECTIONS):
                result.warnings.append(
                    f"{hit.reference}: Nicht alle QEC-Reiter im aktuellen Lauf erfasst. "
                    "Uebernommene alte Reiter sind entsprechend gekennzeichnet."
                )
            # No laeufe/NN_Reiter folders and no active HTML: ONE JSON per case.
            report = {
                "schema_version": 2,
                "fin": hit.fin,
                "referenznummer": hit.reference,
                "sachnummer": hit.part_number,
                "bezeichnung": hit.description,
                "schadteil_id": hit.schadteil_id,
                "abgerufen_am_utc": datetime.now(timezone.utc).isoformat(),
                "abschnitte": sections,
                "vollstaendige_reiter": len(freshly_captured) == len(QEC_SECTIONS),
                "anhaenge": sorted(
                    inventory.values(), key=lambda item: int(item["anhang_id"])
                ),
                "hinweise": result.warnings[warning_offset:],
                "fehler": result.errors[error_offset:],
            }
            _write_json(report_path, report)
            if report_path not in result.snapshots:
                result.snapshots.append(report_path)
        result.references.append(hit.reference)
        return page

    def _one_target(self, context, page, target: QecTarget, progress: Progress,
                    cancel: Event) -> tuple[QecResult, object]:
        result = QecResult(fin=target.fin, status="Abruf gestartet",
                           attempted_at=datetime.now(timezone.utc).isoformat())
        root = self.output_dir / target.fin
        _write_result(root, result)
        try:
            page, _result_scope, result_html, evidence = self._search(
                context, page, target, progress, cancel,
            )
            result.search_diagnostics = evidence
            hits = parse_search_hits(
                result_html, target.fin, part_number=target.part_number,
                pump_only=self.pump_only,
            )
            if target.reference:
                hits = [hit for hit in hits if hit.reference == target.reference]
            if not hits:
                reported = evidence["qec_trefferzahl"]
                visible = evidence["sichtbare_zeilen"]
                if reported is not None and reported > visible:
                    result.status = "Ergebnispruefung erforderlich"
                    result.errors.append(
                        "QEC meldet weitere Treffer, die in der sichtbaren Tabelle "
                        "nicht enthalten sind (Moeglichkeit weiterer Ergebnisseiten)."
                    )
                else:
                    result.status = "Keine passenden Schadteile"
                    result.warnings.append(
                        "QEC-Suche bestaetigt, aber kein eindeutiger Voll-FIN- / "
                        "Pumpen- / Sachnummer-Treffer. Suchdiagnose im abrufstatus.json pruefen."
                    )
                progress(
                    f"{target.fin}: {result.status}. "
                    + (result.errors or result.warnings)[0]
                )
                return result, page
            if (evidence["qec_trefferzahl"] is not None
                    and evidence["qec_trefferzahl"] > evidence["sichtbare_zeilen"]):
                result.warnings.append(
                    "Es sind moeglicherweise weitere Ergebnisseiten vorhanden; "
                    "bisher nur die sichtbaren QEC-Zeilen geprueft."
                )
            for index, hit in enumerate(hits, 1):
                self._check_cancel(cancel)
                progress(f"{target.fin}: Schadteil {index}/{len(hits)} – {hit.reference} …")
                try:
                    page = self._one_hit(context, page, target, hit, result, progress, cancel)
                except QecCancelled:
                    raise
                except Exception as exc:
                    result.errors.append(f"Referenz {hit.reference}: {exc}")
            result.status = "Erfolgreich" if not (result.errors or result.warnings) else (
                "Teilweise erfolgreich" if result.snapshots or result.files else "Fehler"
            )
        except QecCancelled:
            result.status = "Abgebrochen"
        except Exception as exc:
            result.status = "Fehler"
            result.errors.append(str(exc))
        finally:
            _write_result(root, result)
        return result, page

    def run(self, targets: list[QecTarget], *, progress: Progress | None = None,
            cancel: Event | None = None) -> list[QecResult]:
        if not targets:
            raise ValueError("Mindestens eine FIN erforderlich.")
        # Mehrere Schadteilfaelle koennen dieselbe FIN haben: exakte
        # QEC-Referenzen bleiben beim Batch-Abruf erhalten.
        validated: list[QecTarget] = []
        seen: set[tuple[str, str, str]] = set()
        for target in targets:
            raw = target.fin + (f";{target.part_number}" if target.part_number else "")
            item = parse_qec_targets(raw)[0]
            reference = str(target.reference or "").strip()
            if reference and not re.fullmatch(r"[0-9]{1,14}", reference):
                raise ValueError("Ungueltige QEC-Referenznummer.")
            key = (item.fin, _normalize_part(item.part_number), reference)
            if key in seen:
                continue
            seen.add(key)
            validated.append(QecTarget(item.fin, item.part_number, reference))
        progress = progress or (lambda _: None)
        cancel = cancel or Event()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError("Playwright fehlt. Bitte Browser-Unterstuetzung installieren.") from exc
        results: list[QecResult] = []
        with sync_playwright() as playwright:
            try:
                context = playwright.chromium.launch_persistent_context(
                    user_data_dir=str(self.profile_dir), channel="msedge",
                    headless=False, accept_downloads=True, no_viewport=True,
                )
            except Exception as exc:
                raise RuntimeError("Microsoft Edge konnte nicht mit einem eigenen QEC-Profil starten. "
                                   "Bitte Edge/Profilbelegung pruefen.") from exc
            try:
                page = context.pages[0] if context.pages else context.new_page()
                for target in validated:
                    if cancel.is_set():
                        break
                    result, page = self._one_target(context, page, target, progress, cancel)
                    results.append(result)
                    if result.status == "Abgebrochen":
                        break
            finally:
                context.close()
                self.password = ""
        # FIN manifest aggregates individual reference-scoped downloads.
        # This avoids losing the first case when the same FIN has multiple refs.
        by_fin: dict[str, QecResult] = {}
        for item in results:
            combined = by_fin.get(item.fin)
            if combined is None:
                combined = QecResult(item.fin, status=item.status,
                                     attempted_at=item.attempted_at)
                by_fin[item.fin] = combined
            elif combined.status != item.status:
                combined.status = "Teilweise erfolgreich"
            for attr in ("references", "files", "snapshots", "warnings", "errors"):
                target_list = getattr(combined, attr)
                for value in getattr(item, attr):
                    if value not in target_list:
                        target_list.append(value)
            combined.search_diagnostics = item.search_diagnostics
            combined.attempted_at = item.attempted_at
        for fin, combined in by_fin.items():
            _write_result(self.output_dir / fin, combined)
        return results
