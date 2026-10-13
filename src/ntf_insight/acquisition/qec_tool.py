"""Lesender QEC-Export mit Playwright und interaktiver Mercedes-Benz-SSO-Anmeldung.

Die bereitgestellten QEC-HTML-Beispiele decken Suche und Anhang-Popup ab.
Die Detailreiter werden anhand der Anleitung angesprochen; ihre Selektoren
muessen mit einem berechtigten QEC-Zugang im Unternehmensnetz geprueft werden.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import Event
from typing import Callable
from urllib.parse import parse_qs, unquote, urljoin, urlsplit

from lxml import html as lxml_html

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
    })


def _visible_fields(page) -> list[dict[str, str | bool]]:
    """Formularwerte, einschliesslich deaktivierter Felder, aber ohne SSO-Tokens."""
    return page.evaluate("""() => Array.from(document.querySelectorAll('input, textarea, select'))
      .filter(e => !['hidden', 'password', 'submit', 'button'].includes((e.type || '').toLowerCase()))
      .map(e => ({
        name: e.name || e.id || '',
        typ: (e.type || e.tagName || '').toLowerCase(),
        wert: e.type === 'checkbox' || e.type === 'radio'
          ? (e.checked ? 'ja' : 'nein') : String(e.value || ''),
        deaktiviert: Boolean(e.disabled),
      }))""")


def _snapshot(page, folder: Path, section: str, hit: QecHit) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    text = page.locator("body").inner_text(timeout=15000)
    fields = _visible_fields(page)
    payload = {
        "referenznummer": hit.reference,
        "sachnummer": hit.part_number,
        "bezeichnung": hit.description,
        "fin": hit.fin,
        "bereich": section,
        "zeitpunkt_utc": datetime.now(timezone.utc).isoformat(),
        "sichtbarer_text": text,
        "felder": fields,
    }
    _write_json(folder / "daten.json", payload)
    # Lesbare Offline-Kopie ohne Cookies, Token, Skripte oder aktive Links.
    rows = "\n".join(
        f"<tr><td>{html.escape(str(f['name']))}</td>"
        f"<td>{html.escape(str(f['wert']))}</td></tr>" for f in fields
    )
    content = (
        '<!doctype html><html lang="de"><head><meta charset="utf-8">'
        '<title>QEC-Offline-Befund</title></head><body>'
        f"<h1>{html.escape(section)}</h1><p>Referenz: {html.escape(hit.reference)}</p>"
        f"<pre>{html.escape(text)}</pre><h2>Formularfelder</h2>"
        f"<table><tr><th>Feld</th><th>Wert</th></tr>{rows}</table></body></html>"
    )
    (folder / "ansicht.html").write_text(content, encoding="utf-8")
    return folder / "daten.json"


class QecDownloader:
    """Funktioniert nur mit vorhandener QEC-Berechtigung und sichtbarem Edge."""

    def __init__(self, output_dir: Path, profile_dir: Path, *,
                 login_timeout_seconds: int = 240, navigation_timeout_ms: int = 45000,
                 attachment_timeout_ms: int = 90000, pump_only: bool = True,
                 user_id: str = "", password: str = "") -> None:
        self.output_dir = Path(output_dir)
        self.profile_dir = Path(profile_dir)
        self.login_timeout_seconds = login_timeout_seconds
        self.navigation_timeout_ms = navigation_timeout_ms
        self.attachment_timeout_ms = attachment_timeout_ms
        self.pump_only = pump_only
        self.user_id = user_id
        self.password = password

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
        else:
            progress("QEC: Schadteilsuche anklicken ...")
            nav.click(timeout=self.navigation_timeout_ms)

        page, form = self._search_form(context, cancel)
        progress("QEC: FIN-Suchfelder erkannt; BR und Endnummer eintragen ...")
        form.locator('input[name="_finBR"]').fill(target.fin[3:6])
        form.locator('input[name="_finEndnummerFrom"]').fill(target.fin[-6:])
        progress("QEC: Filtern klicken ...")
        button = form.locator('input[type="submit"][value="Filtern"]')
        if button.count():
            button.first.click(timeout=self.navigation_timeout_ms)
        else:
            form.get_by_role("button", name="Filtern", exact=True).click(
                timeout=self.navigation_timeout_ms
            )
        progress("QEC: Suchergebnisse werden ausgewertet ...")
        return page

    @classmethod
    def _search_html(cls, page) -> str:
        for scope in cls._scopes(page):
            if (scope.locator('input[name="_finBR"]').count()
                    and scope.locator('input[name="_finEndnummerFrom"]').count()):
                return scope.content()
        return page.content()

    @staticmethod
    def _click_section(page, title: str) -> bool:
        for role in ("tab", "link", "button"):
            matches = page.get_by_role(role, name=title, exact=True)
            for index in range(min(matches.count(), 4)):
                candidate = matches.nth(index)
                if candidate.is_visible():
                    candidate.click(timeout=12000)
                    page.wait_for_timeout(250)
                    return True
        # QEC besitzt in einigen Ansichten klickbare Div-/Tabellenreiter.
        matches = page.get_by_text(title, exact=True)
        for index in range(min(matches.count(), 5)):
            item = matches.nth(index)
            if item.is_visible():
                item.click(timeout=12000)
                page.wait_for_timeout(250)
                return True
        return False

    def _save_popups(self, context, page, folder: Path, result: QecResult,
                     progress: Progress, cancel: Event) -> None:
        buttons = page.locator('input[type="button"][value="Dateianhänge"], button:has-text("Dateianhänge")')
        for index in range(buttons.count()):
            self._check_cancel(cancel)
            if not buttons.nth(index).is_visible():
                continue
            try:
                with page.expect_popup(timeout=12000) as popup_event:
                    buttons.nth(index).click(timeout=12000)
                popup = popup_event.value
                try:
                    popup.wait_for_load_state("domcontentloaded", timeout=15000)
                    attachments = parse_attachment_urls(popup.content())
                    if not attachments:
                        result.warnings.append("Anhang-Fenster ohne erkennbare Dateien.")
                    for number, (attachment_id, url) in enumerate(attachments, 1):
                        self._check_cancel(cancel)
                        progress(f"{result.fin}: Anhang {number}/{len(attachments)} wird geladen …")
                        try:
                            response = context.request.get(url, timeout=self.attachment_timeout_ms)
                            _qec_url(response.url, expected_path="displayPruefberichtFile.qec")
                            if not response.ok:
                                raise RuntimeError(f"HTTP {response.status}")
                            headers = {str(k).lower(): str(v) for k, v in response.headers.items()}
                            if int(headers.get("content-length", "0") or 0) > MAX_ATTACHMENT_BYTES:
                                raise ValueError("Anhang groesser als 100 MB.")
                            path = _store_attachment(folder, attachment_id, headers, response.body())
                            if path not in result.files:
                                result.files.append(path)
                        except Exception as exc:
                            result.errors.append(f"Anhang {attachment_id}: {exc}")
                finally:
                    popup.close()
            except QecCancelled:
                raise
            except Exception as exc:
                result.errors.append(f"Dateianhaenge-Popup {index + 1}: {exc}")

    def _one_hit(self, context, page, target: QecTarget, hit: QecHit,
                 result: QecResult, progress: Progress, cancel: Event, run_id: str):
        page = self._search(context, page, target, progress, cancel)
        # Kein direkter HTTP-Link: erst den aktuell sichtbaren Treffer selektieren.
        hits = parse_search_hits(self._search_html(page), target.fin,
                                 part_number=target.part_number, pump_only=self.pump_only)
        if hit.schadteil_id not in {entry.schadteil_id for entry in hits}:
            raise RuntimeError("Schadteil nach erneutem Oeffnen nicht mehr eindeutig gefunden.")
        page.locator(f'a[href*="schadteilID={hit.schadteil_id}"]').first.click(
            timeout=self.navigation_timeout_ms
        )
        page.get_by_text("Schadteilmonitor", exact=False).first.wait_for(
            timeout=self.navigation_timeout_ms
        )
        reference_folder = self.output_dir / target.fin / f"ref_{_safe_name(hit.reference)}"
        run_folder = reference_folder / "laeufe" / run_id
        previous_signature = None
        for index, section in enumerate(QEC_SECTIONS):
            self._check_cancel(cancel)
            progress(f"{target.fin}: {hit.reference} – {section} …")
            if not self._click_section(page, section):
                result.warnings.append(f"{hit.reference}: Reiter {section} nicht gefunden.")
                continue
            folder = run_folder / f"{index + 1:02d}_{_safe_name(section)}"
            path = _snapshot(page, folder, section, hit)
            current = json.loads(path.read_text(encoding="utf-8"))
            signature = (current["sichtbarer_text"], str(current["felder"]))
            if signature == previous_signature:
                result.warnings.append(f"{hit.reference}: {section} zeigt dieselben Daten wie der vorherige Reiter; bitte pruefen.")
            previous_signature = signature
            result.snapshots.append(path)
            self._save_popups(context, page, reference_folder / "anhaenge", result, progress, cancel)
        result.references.append(hit.reference)
        return page

    def _one_target(self, context, page, target: QecTarget, progress: Progress,
                    cancel: Event, run_id: str) -> tuple[QecResult, object]:
        result = QecResult(fin=target.fin, status="Abruf gestartet",
                           attempted_at=datetime.now(timezone.utc).isoformat())
        root = self.output_dir / target.fin
        _write_result(root, result)
        try:
            page = self._search(context, page, target, progress, cancel)
            hits = parse_search_hits(self._search_html(page), target.fin, part_number=target.part_number,
                                     pump_only=self.pump_only)
            if not hits:
                result.status = "Keine passenden Schadteile"
                result.warnings.append("Kein eindeutiger FIN-/Sachnummer-/Bauteiltreffer.")
                return result, page
            for index, hit in enumerate(hits, 1):
                self._check_cancel(cancel)
                progress(f"{target.fin}: Schadteil {index}/{len(hits)} – {hit.reference} …")
                try:
                    page = self._one_hit(context, page, target, hit, result, progress, cancel, run_id)
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
        # Nie aus unvalidierten QecTarget-Objekten Verzeichnisse anlegen.
        validated = parse_qec_targets("\n".join(
            f"{target.fin};{target.part_number}" if target.part_number else target.fin
            for target in targets
        ))
        progress = progress or (lambda _: None)
        cancel = cancel or Event()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
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
                    result, page = self._one_target(context, page, target, progress, cancel, run_id)
                    results.append(result)
                    if result.status == "Abgebrochen":
                        break
            finally:
                context.close()
                self.password = ""
        return results
