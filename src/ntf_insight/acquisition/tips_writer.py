"""Schreibgeschuetzter Playwright-Abruf von XENTRY TIPS Writer: Faelle nach FIN.

Die UI-Marker stammen aus der mitgelieferten TIPS-Writer-Anleitung und
gespeicherten HTML-Ansichten. Keine privaten HTMLs oder echten FINs im Repo.
SSO und PING-ID werden ausschliesslich ueber den berechtigten Edge-Zugang benutzt.
"""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from threading import Event
from typing import Callable
from urllib.parse import urlsplit
from zipfile import ZipFile, is_zipfile

from lxml import html as lxml_html

from ntf_insight.acquisition.diagnosis_viewer import parse_fins


TIPS_START = "https://xentry.mercedes-benz.com/tips-writer/home/topics/search"
TIPS_HOST = "xentry.mercedes-benz.com"
SSO_HOST = "login.mercedes-benz.com"
TIPS_SECTIONS = (
    "Erstanfrage",
    "Betriebsdaten",
    "Fahrzeugdaten",
    "Symptom",
    "Kommunikation",
    "Anhänge",
    "Funktionsgruppe",
    "Steuergerät/FC",
    "Zustandsdaten",
    "Inspektor / Notizen",
)
MAX_ATTACHMENT_BYTES = 200 * 1024 * 1024
MAX_ZIP_TOTAL = 800 * 1024 * 1024
MAX_ZIP_ENTRIES = 500
ALLOWED_EXTENSIONS = frozenset({
    ".pdf", ".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp", ".tif", ".tiff",
    ".csv", ".txt", ".json", ".doc", ".docx", ".xls", ".xlsx", ".eml", ".msg",
})
_FIN = re.compile(r"[A-HJ-NPR-Z0-9]{17}\Z")
_CASE_ID = re.compile(r"\d{4,16}\Z")
Progress = Callable[[str], None]


class TipsCancelled(RuntimeError):
    """Benutzer hat den Abruf abgebrochen."""


@dataclass(frozen=True, slots=True)
class TipsHit:
    fin: str
    case_id: str
    title: str = ""
    cells: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class TipsResult:
    fin: str
    status: str = "Nicht gestartet"
    cases: list[str] = field(default_factory=list)
    reports: list[Path] = field(default_factory=list)
    files: list[Path] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _clean_text(value: str) -> str:
    return " ".join(value.split())


def _section(name: str) -> str | None:
    title = _clean_text(name).lower()
    if title.startswith("inspektor"):
        return "Inspektor / Notizen"
    if title.startswith("fahrzeugdaten"):
        return "Fahrzeugdaten"
    for known in TIPS_SECTIONS:
        if title == known.lower():
            return known
    return None


def _tips_url_valid(value: str) -> bool:
    parsed = urlsplit(value)
    return (parsed.scheme == "https" and parsed.hostname == TIPS_HOST
            and parsed.port in (None, 443)
            and parsed.path.startswith("/tips-writer/"))


def parse_tips_search_hits(document: str, fin: str) -> list[TipsHit]:
    """Nur sichtbare Ergebnistabellen mit *vollstaendig identischer* FIN.

    PrimeNG 'p-datatable' hat dynamische IDs, die Zellen sind dagegen durch
    die Beschriftungen Fall Nummer und FIN verifizierbar.
    """
    if not _FIN.fullmatch(fin):
        raise ValueError("Ungueltige FIN.")
    root = lxml_html.fromstring(document)
    results: list[TipsHit] = []
    seen: set[str] = set()
    for table in root.xpath('//p-tabpanel[contains(@class,"p-tabpanel-active")]//table'):
        headings = [_clean_text("".join(th.itertext()))
                    for th in table.xpath(".//thead/tr[1]/th")]
        try:
            case_index = headings.index("Fall Nummer")
            fin_index = headings.index("FIN")
        except ValueError:
            continue
        for tr in table.xpath(".//tbody/tr"):
            cells = tr.xpath("./td")
            if len(cells) <= max(fin_index, case_index):
                continue
            case_id = _clean_text(cells[case_index].text_content())
            found_fin = _clean_text(cells[fin_index].text_content()).upper()
            if found_fin != fin or not _CASE_ID.fullmatch(case_id) or case_id in seen:
                continue
            seen.add(case_id)
            values = {
                name: _clean_text(cell.text_content())
                for name, cell in zip(headings, cells)
                if name
            }
            results.append(TipsHit(
                fin=fin, case_id=case_id, title=values.get("Titel", ""), cells=values,
            ))
    return results


def parse_tips_attachment_rows(document: str) -> list[dict[str, str]]:
    """HTML-Tabelle der aktiven Registerkarte: Datei, Datum und Beschreibung."""
    root = lxml_html.fromstring(document)
    results: list[dict[str, str]] = []
    for panel in root.xpath('//p-tabpanel[contains(@class,"p-tabpanel-active")]'):
        for table in panel.xpath(".//table"):
            headers = [_clean_text("".join(th.itertext()))
                       for th in table.xpath(".//thead/tr[1]/th")]
            if "Datei" not in headers:
                continue
            for row in table.xpath(".//tbody/tr"):
                cells = row.xpath("./td")
                if len(cells) <= headers.index("Datei"):
                    continue
                values = {
                    title: _clean_text(cell.text_content())
                    for title, cell in zip(headers, cells)
                    if title
                }
                if values.get("Datei"):
                    results.append(values)
    return results


def _safe_basename(value: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", Path(value.replace("\\", "/")).name)
    name = name.strip(" .")
    return name[:175] if name else "TIPS-Datei"


def _unique_target(folder: Path, name: str) -> Path:
    filename = _safe_basename(name)
    first = folder / filename
    if not first.exists():
        return first
    index = 2
    while True:
        candidate = folder / f"{Path(filename).stem}_{index}{Path(filename).suffix}"
        if not candidate.exists():
            return candidate
        index += 1


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent,
        prefix=".tips_", suffix=".tmp", delete=False,
    ) as stream:
        temporary = Path(stream.name)
        json.dump(payload, stream, indent=2, ensure_ascii=False)
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _file_record(path: Path, folder: Path) -> dict:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return {
        "datei": path.relative_to(folder).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": digest.hexdigest(),
    }


def _unpack_attachment(downloaded: Path, folder: Path) -> list[Path]:
    """Entpackt Browser-ZIP mit Groessenlimit, Pfadpruefung und Dateitypfilter."""
    if not is_zipfile(downloaded):
        if downloaded.suffix.lower() not in ALLOWED_EXTENSIONS:
            raise ValueError("Unerwarteter TIPS-Anhangstyp.")
        folder.mkdir(parents=True, exist_ok=True)
        destination = _unique_target(folder, downloaded.name)
        downloaded.replace(destination)
        return [destination]
    created: list[Path] = []
    with ZipFile(downloaded) as archive:
        members = [part for part in archive.infolist() if not part.is_dir()]
        if len(members) > MAX_ZIP_ENTRIES:
            raise ValueError("TIPS-Anhangarchiv enthaelt zu viele Dateien.")
        total = 0
        for info in members:
            relative = PurePosixPath(info.filename.replace("\\", "/"))
            if (relative.is_absolute() or not relative.parts
                    or any(part in (".", "..") or ":" in part for part in relative.parts)
                    or (info.external_attr >> 16) & 0o170000 == 0o120000):
                raise ValueError("Unsicherer Eintrag im TIPS-Anhangarchiv.")
            total += info.file_size
            if info.file_size > MAX_ATTACHMENT_BYTES or total > MAX_ZIP_TOTAL:
                raise ValueError("TIPS-Anhangarchiv ueberschreitet das Groessenlimit.")
        for info in members:
            relative = PurePosixPath(info.filename.replace("\\", "/"))
            if relative.suffix.lower() not in ALLOWED_EXTENSIONS:
                continue
            folder.mkdir(parents=True, exist_ok=True)
            target = _unique_target(folder, relative.name)
            try:
                with archive.open(info) as source, target.open("xb") as destination:
                    copied = 0
                    while block := source.read(1024 * 1024):
                        copied += len(block)
                        if copied > MAX_ATTACHMENT_BYTES:
                            raise ValueError("TIPS-Einzeldatei zu gross.")
                        destination.write(block)
                created.append(target)
            except Exception:
                target.unlink(missing_ok=True)
                raise
    return created


def _capture_section(panel) -> dict:
    """Ausfuehrungsfreie Kopie sichtbarer UI-Daten, ohne HTML/Script/Token."""
    return panel.evaluate("""el => {
      const clean = v => String(v || '').trim();
      return {
        sichtbarer_text: clean(el.innerText),
        felder: Array.from(el.querySelectorAll('input, textarea, select, [contenteditable="true"]'))
          .filter(field => !['hidden', 'password', 'submit', 'button', 'file']
             .includes((field.type || '').toLowerCase()))
          .map(field => ({
            name: field.name || field.id || '',
            typ: (field.type || field.tagName).toLowerCase(),
            wert: ['checkbox','radio'].includes(field.type)
              ? (field.checked ? 'ja' : 'nein')
              : field.hasAttribute('contenteditable') ? clean(field.innerText) : clean(field.value),
            optionwert: ['checkbox','radio'].includes(field.type) ? clean(field.value) : '',
            auswahltext: field.tagName.toLowerCase() === 'select'
              ? Array.from(field.selectedOptions).map(option => clean(option.textContent)).join(' | ') : '',
            beschriftung: Array.from(field.labels || []).map(label => clean(label.innerText)).join(' | '),
            deaktiviert: Boolean(field.disabled),
          })),
        tabellen: Array.from(el.querySelectorAll('table')).map((table, index) => ({
          nummer: index + 1,
          zeilen: Array.from(table.rows).map(row =>
            Array.from(row.cells).map(cell => ({
              typ: cell.tagName.toLowerCase(),
              text: clean(cell.innerText),
              colspan: cell.colSpan
            })))
        })),
      };
    }""")


class TipsWriterDownloader:
    """Benutzt nur sichtbare, nicht schreibende XENTRY-TIPS-Oberflaechenelemente."""

    def __init__(
        self, output_dir: Path, profile_dir: Path, *,
        user_id: str = "", password: str = "",
        login_timeout_seconds: int = 240,
        navigation_timeout_ms: int = 45000,
        download_timeout_ms: int = 90000,
        click_delay_seconds: float = 0.8,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.profile_dir = Path(profile_dir)
        self.user_id = user_id
        self.password = password
        self.login_timeout_seconds = login_timeout_seconds
        self.navigation_timeout_ms = navigation_timeout_ms
        self.download_timeout_ms = download_timeout_ms
        self.click_delay_seconds = min(4.0, max(0.0, float(click_delay_seconds)))

    @staticmethod
    def _check(cancel: Event) -> None:
        if cancel.is_set():
            raise TipsCancelled("TIPS-Abruf abgebrochen.")

    def _pause(self, cancel: Event) -> None:
        if cancel.wait(self.click_delay_seconds):
            raise TipsCancelled("TIPS-Abruf abgebrochen.")

    @staticmethod
    def _login_host(value: str) -> bool:
        parsed = urlsplit(value)
        return (parsed.scheme == "https" and parsed.hostname == SSO_HOST
                and parsed.port in (None, 443))

    def _sso(self, page, submitted: dict[str, bool], progress: Progress) -> None:
        if not self._login_host(page.url):
            return
        cookie = page.locator("#c-s-bn")
        if cookie.count() and cookie.is_visible():
            cookie.click(timeout=3000)
        login = page.locator("#userid")
        if self.user_id and not submitted["user"] and login.count() and login.is_visible():
            login.fill(self.user_id)
            page.locator("#next-btn").click(timeout=10000)
            submitted["user"] = True
            progress("TIPS: Benutzer-ID uebermittelt; Passwortseite wird geoeffnet.")
            return
        password = page.locator("#password")
        if (self.password and not submitted["password"] and password.count()
                and password.is_visible()):
            password.fill(self.password)
            page.locator("#loginSubmitButton").click(timeout=10000)
            submitted["password"] = True
            progress("TIPS: SSO-Anmeldung gesendet; PING ID gegebenenfalls bestaetigen.")

    def _ready(self, page) -> bool:
        if not _tips_url_valid(page.url):
            return False
        search = page.locator("tn-c-search input.xy-c-search-input")
        return search.count() > 0 and search.first.is_visible()

    def _wait_login(self, context, progress: Progress, cancel: Event):
        deadline = time.monotonic() + self.login_timeout_seconds
        submitted = {"user": False, "password": False}
        progress("TIPS: Mercedes SSO / PING ID abwarten.")
        while time.monotonic() < deadline:
            self._check(cancel)
            for page in reversed(context.pages):
                if page.is_closed():
                    continue
                try:
                    if self._ready(page):
                        progress("TIPS: Suchmaske nach Anmeldung bereit.")
                        return page
                    if self._login_host(page.url):
                        self._sso(page, submitted, progress)
                except TipsCancelled:
                    raise
                except Exception:
                    continue  # SSO-Seiten koennen waehrend eines Redirects wechseln.
            time.sleep(0.5)
        raise TimeoutError(
            "TIPS-Suchmaske nach SSO/PING ID nicht erkannt. "
            "Bitte Anmeldung im gestarteten Edge und Berechtigung pruefen."
        )

    def _search(self, context, page, fin: str, progress: Progress, cancel: Event):
        self._check(cancel)
        page.goto(TIPS_START, wait_until="domcontentloaded", timeout=self.navigation_timeout_ms)
        page = self._wait_login(context, progress, cancel)
        self._pause(cancel)
        search = page.locator("tn-c-search input.xy-c-search-input")
        if search.count() == 0:
            raise RuntimeError("TIPS: dokumentiertes FIN-Suchfeld fehlt.")
        search.first.fill(fin)
        self._pause(cancel)
        # Search button is a sibling of the documented input, not the header search icon.
        search.first.locator("xpath=following-sibling::button").click(
            timeout=self.navigation_timeout_ms
        )
        self._pause(cancel)
        cases = page.get_by_role("tab", name=re.compile(r"^Fälle\s*:"))
        cases.first.wait_for(state="visible", timeout=self.navigation_timeout_ms)
        if "p-tab-active" not in (cases.first.get_attribute("class") or ""):
            cases.first.click(timeout=self.navigation_timeout_ms)
            self._pause(cancel)
        progress("TIPS: Falltabelle wird nach FIN ausgewertet.")
        deadline = time.monotonic() + self.navigation_timeout_ms / 1000
        empty_since: float | None = None
        while time.monotonic() < deadline:
            self._check(cancel)
            html = page.content()
            hits = parse_tips_search_hits(html, fin)
            if hits:
                progress(f"TIPS: {len(hits)} Falltreffer mit identischer FIN.")
                return page, hits
            current = page.get_by_role("tab", name=re.compile(r"^Fälle\s*:"))
            text = current.first.inner_text() if current.count() else ""
            if re.search(r"\(\s*0\s*\)", text):
                empty_since = empty_since or time.monotonic()
                if time.monotonic() - empty_since > 1:
                    return page, []
            else:
                empty_since = None
            time.sleep(0.4)
        raise TimeoutError(
            "TIPS-Suchergebnis nach 'Suchen' nicht eindeutig geladen. "
            "Kein gepruefter Voll-FIN-Treffer; keine Fremdfaelle ausgewaehlt."
        )

    def _open_case(self, context, page, hit: TipsHit,
                   progress: Progress, cancel: Event):
        page, verified = self._search(context, page, hit.fin, progress, cancel)
        if hit.case_id not in {item.case_id for item in verified}:
            raise RuntimeError("TIPS-Fall ist in der erneut geprueften FIN-Suche nicht vorhanden.")
        rows = page.locator('p-tabpanel.p-tabpanel-active tbody tr.p-datatable-selectable-row')
        chosen = None
        for index in range(rows.count()):
            candidate = rows.nth(index)
            values = candidate.locator("td")
            if values.count() < 4:
                continue
            if (_clean_text(values.nth(1).inner_text()) == hit.case_id
                    and _clean_text(values.nth(3).inner_text()).upper() == hit.fin):
                chosen = candidate
                break
        if chosen is None:
            raise RuntimeError("TIPS-Fallzeile nicht eindeutig klickbar.")
        progress(f"TIPS: Fall {hit.case_id} wird geoeffnet.")
        self._pause(cancel)
        chosen.click(timeout=self.navigation_timeout_ms)
        try:
            detail = page.get_by_role("tab", name=re.compile(r"^Erstanfrage$"))
            detail.first.wait_for(state="visible", timeout=12000)
        except Exception:
            # PrimeNG case rows can require a double click to open details.
            chosen.dblclick(timeout=12000)
            detail = page.get_by_role("tab", name=re.compile(r"^Erstanfrage$"))
            detail.first.wait_for(state="visible", timeout=self.navigation_timeout_ms)
        self._pause(cancel)
        if not _tips_url_valid(page.url):
            raise RuntimeError("TIPS-Falldetail wurde auf eine unerwartete Domain umgeleitet.")
        return page

    def _tab(self, page, label: str, cancel: Event):
        locator = page.locator('p-tab[role="tab"]')
        chosen = None
        for index in range(locator.count()):
            item = locator.nth(index)
            if _section(item.inner_text()) == label:
                chosen = item
                break
        if chosen is None:
            return None
        if "p-tab-active" not in (chosen.get_attribute("class") or ""):
            self._pause(cancel)
            chosen.click(timeout=self.navigation_timeout_ms)
            self._pause(cancel)
        panel_id = chosen.get_attribute("aria-controls")
        if panel_id:
            panel = page.locator(f'p-tabpanel[id="{panel_id}"]')
        else:
            panel = page.locator("p-tabpanel.p-tabpanel-active")
        panel.first.wait_for(state="visible", timeout=self.navigation_timeout_ms)
        return panel.first

    def _download_attachments(self, page, panel, folder: Path,
                              progress: Progress, cancel: Event):
        buttons = panel.locator("button.xy-i-download")
        listing = parse_tips_attachment_rows(page.content())
        if not listing:
            return [], listing, []  # no files shown, never click empty download.
        if buttons.count() == 0 or not buttons.first.is_visible():
            return [], listing, ["TIPS: Download-alle-Anhaenge-Schaltflaeche fehlt."]
        warnings: list[str] = []
        # In PrimeNG the download button acts on selected rows. Select all shown.
        box = panel.locator("p-tableheadercheckbox input[type='checkbox']")
        if box.count() and not box.first.is_checked():
            self._pause(cancel)
            box.first.check(timeout=9000, force=True)
            self._pause(cancel)
        progress("TIPS: Dokumentierte Schaltflaeche 'Alle Anhaenge herunterladen'.")
        with page.expect_download(timeout=self.download_timeout_ms) as event:
            self._pause(cancel)
            buttons.first.click(timeout=15000)
        download = event.value
        if download.failure():
            raise RuntimeError("TIPS-Anhangdownload im Edge fehlgeschlagen.")
        suggested = _safe_basename(str(download.suggested_filename))
        with tempfile.TemporaryDirectory(prefix="tips_download_") as directory:
            saved = Path(directory) / suggested
            download.save_as(str(saved))
            if saved.stat().st_size > MAX_ZIP_TOTAL:
                raise ValueError("TIPS-Download ist groesser als 800 MB.")
            files = _unpack_attachment(saved, folder)
            if not files:
                warnings.append(
                    "TIPS-Anhangarchiv enthaelt keine unterstuetzten Dokumenttypen."
                )
            return files, listing, warnings

    def _one_case(self, context, page, hit: TipsHit, progress: Progress,
                  cancel: Event):
        page = self._open_case(context, page, hit, progress, cancel)
        folder = self.output_dir / hit.fin / f"fall_{hit.case_id}"
        report_path = folder / "tips.json"
        previous: dict = {}
        if report_path.is_file() and not report_path.is_symlink():
            try:
                data = json.loads(report_path.read_text(encoding="utf-8"))
                if data.get("fin") == hit.fin and data.get("fallnummer") == hit.case_id:
                    previous = data
            except (OSError, ValueError, TypeError, AttributeError):
                pass

        sections: list[dict] = []
        files: list[Path] = []
        attachments: list[dict] = []
        warnings: list[str] = []
        errors: list[str] = []
        # Details: head information plus all ten documented tabs.
        headline = page.locator("h2").first.inner_text() if page.locator("h2").count() else ""
        try:
            for section_name in TIPS_SECTIONS:
                self._check(cancel)
                progress(f"TIPS {hit.case_id}: {section_name} erfassen.")
                panel = self._tab(page, section_name, cancel)
                if panel is None:
                    warnings.append(f"Reiter '{section_name}' nicht vorhanden.")
                    continue
                captured = _capture_section(panel)
                captured["bereich"] = section_name
                captured["erfasst_am_utc"] = datetime.now(timezone.utc).isoformat()
                sections.append(captured)
                if section_name != "Anhänge":
                    continue
                attachments = parse_tips_attachment_rows(page.content())
                try:
                    files, _found, extra = self._download_attachments(
                        page, panel, folder / "dateien", progress, cancel,
                    )
                    warnings.extend(extra)
                except TipsCancelled:
                    raise
                except Exception as exc:
                    errors.append(f"Anhangdownload: {type(exc).__name__}: {exc}")
        finally:
            current_sections = {section["bereich"] for section in sections}
            for prior in previous.get("abschnitte", []):
                if (isinstance(prior, dict)
                        and prior.get("bereich") in TIPS_SECTIONS
                        and prior["bereich"] not in current_sections):
                    older = dict(prior)
                    older["aus_vorherigem_abruf"] = True
                    sections.append(older)
            sections.sort(key=lambda item: TIPS_SECTIONS.index(item["bereich"]))
            report = {
                "schema_version": 1,
                "quelle": "XENTRY TIPS Writer",
                "fin": hit.fin,
                "fallnummer": hit.case_id,
                "titel": headline or hit.title,
                "suchtreffer": hit.cells,
                "abgerufen_am_utc": datetime.now(timezone.utc).isoformat(),
                "aktuell_erfasste_reiter": len(current_sections),
                "vollstaendige_reiter": len(current_sections) == len(TIPS_SECTIONS),
                "abschnitte": sections,
                "anhangliste": attachments or previous.get("anhangliste", []),
                "dateien": [
                    _file_record(file, folder) for file in sorted(
                        (folder / "dateien").rglob("*")
                    ) if file.is_file() and not file.is_symlink()
                ] if (folder / "dateien").is_dir() else [],
                "hinweise": warnings,
                "fehler": errors,
            }
            _write_json(report_path, report)
        return report_path, files, warnings, errors, page

    def _one_fin(self, context, page, fin: str, progress: Progress, cancel: Event):
        result = TipsResult(fin)
        try:
            page, hits = self._search(context, page, fin, progress, cancel)
            if not hits:
                result.status = "Keine TIPS-Faelle"
            else:
                for hit in hits:
                    self._check(cancel)
                    try:
                        report, files, warnings, errors, page = self._one_case(
                            context, page, hit, progress, cancel,
                        )
                        result.cases.append(hit.case_id)
                        result.reports.append(report)
                        result.files.extend(files)
                        result.warnings.extend(warnings)
                        result.errors.extend(f"Fall {hit.case_id}: {e}" for e in errors)
                    except TipsCancelled:
                        raise
                    except Exception as exc:
                        result.errors.append(
                            f"Fall {hit.case_id}: {type(exc).__name__}: {exc}"
                        )
                result.status = "Teilweise erfolgreich" if result.errors else "Erfolgreich"
        except TipsCancelled:
            result.status = "Abgebrochen"
        except Exception as exc:
            result.status = "Fehler"
            result.errors.append(f"{type(exc).__name__}: {exc}")
        finally:
            _write_json(self.output_dir / fin / "abrufstatus.json", {
                "fin": fin,
                "stand_utc": datetime.now(timezone.utc).isoformat(),
                "status": result.status,
                "fallnummern": result.cases,
                "fehler": result.errors,
                "hinweise": result.warnings,
                "dateien": [p.relative_to(self.output_dir / fin).as_posix()
                            for p in result.files],
            })
        return result, page

    def run(self, fins: list[str], *, progress: Progress | None = None,
            cancel: Event | None = None) -> list[TipsResult]:
        targets = parse_fins("\n".join(fins))
        if not targets:
            raise ValueError("Mindestens eine 17-stellige FIN erforderlich.")
        progress = progress or (lambda _message: None)
        cancel = cancel or Event()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError("Playwright fehlt. Bitte Browser-Unterstuetzung installieren.") from exc
        results: list[TipsResult] = []
        with sync_playwright() as playwright:
            try:
                context = playwright.chromium.launch_persistent_context(
                    user_data_dir=str(self.profile_dir),
                    channel="msedge", headless=False,
                    accept_downloads=True, no_viewport=True,
                )
            except Exception as exc:
                raise RuntimeError(
                    "Microsoft Edge fuer TIPS Writer konnte nicht gestartet werden. "
                    "Bitte Edge-Installation und exklusive Profilnutzung pruefen."
                ) from exc
            try:
                page = context.pages[0] if context.pages else context.new_page()
                for fin in targets:
                    if cancel.is_set():
                        break
                    result, page = self._one_fin(context, page, fin, progress, cancel)
                    results.append(result)
                    if result.status == "Abgebrochen":
                        break
            finally:
                context.close()
                self.password = ""
        return results
