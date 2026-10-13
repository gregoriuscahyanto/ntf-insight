"""QuickTest PDF acquisition via the company's existing interactive Edge SSO.

The browser is operated with Playwright; no credentials, SSO cookies or PING ID
secrets are accessed by the application. An independent browser profile is kept
locally so a valid SSO session may be reused between runs.
"""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event
from typing import Callable
from urllib.parse import quote, urlsplit

DIAGNOSIS_VIEWER = "https://app.diagviewer.prod.gspp-eu.cloud.corpintra.net/search"
LOGIN_HOST = "login.mercedes-benz.com"
VIEWER_HOST = urlsplit(DIAGNOSIS_VIEWER).hostname
SOURCES = "XD,XD(AQT),TD,DAS"
_FIN = re.compile(r"[A-HJ-NPR-Z0-9]{17}\Z")
_ILLEGAL_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")
Progress = Callable[[str], None]


class DownloadCancelled(RuntimeError):
    """Raised when the user requests cancellation."""


@dataclass(frozen=True, slots=True)
class DownloadRow:
    position: int
    source: str
    timestamp: str


@dataclass(slots=True)
class FinDownloadResult:
    fin: str
    files: list[Path] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    available: int = 0
    status: str = "Ausstehend"
    last_attempt_at: str = ""


def parse_fins(text: str) -> list[str]:
    """Read a copy/pasted FIN list, rejecting invalid input before network access."""
    tokens = [s.strip().upper() for s in re.split(r"[\s,;]+", text) if s.strip()]
    if not tokens:
        raise ValueError("Bitte mindestens eine 17-stellige FIN eingeben.")
    invalid = [s for s in tokens if not _FIN.fullmatch(s)]
    if invalid:
        raise ValueError("Ungültige FIN (17 Zeichen A–Z/0–9 ohne I, O, Q): " + ", ".join(invalid[:3]))
    return list(dict.fromkeys(tokens))


def search_url(fin: str) -> str:
    if not _FIN.fullmatch(fin):
        raise ValueError("FIN muss 17 gültige Zeichen enthalten.")
    return f"{DIAGNOSIS_VIEWER}?fin={fin}&sources={quote(SOURCES, safe='')}"


def _safe_name(name: str) -> str:
    return _ILLEGAL_FILENAME.sub("_", Path(name.replace("\\", "/")).name).strip("._")[:150] or "QuickTest"


def _save_pdf(download, folder: Path, row: DownloadRow) -> Path:
    """Never accept an HTML/login response or overwrite an existing PDF."""
    suggested = str(download.suggested_filename)
    if not suggested.lower().endswith(".pdf"):
        raise ValueError("Diagnosis Viewer liefert kein PDF. In Einstellungen QuickTest-Downloadtyp PDF wählen.")
    folder.mkdir(parents=True, exist_ok=True)
    prefix = _safe_name(f"{row.timestamp}_{row.source}")
    name = _safe_name(suggested)
    filename = f"{prefix}_{name}"
    with tempfile.NamedTemporaryFile(dir=folder, suffix=".partial", delete=False) as temp:
        temporary = Path(temp.name)
    try:
        download.save_as(str(temporary))
        with temporary.open("rb") as stream:
            if stream.read(5) != b"%PDF-":
                raise ValueError("Download ist kein gültiges PDF (möglicherweise SSO abgelaufen).")
        digest = hashlib.sha256(temporary.read_bytes()).hexdigest()
        target = folder / filename
        ordinal = 2
        while target.exists():
            if hashlib.sha256(target.read_bytes()).hexdigest() == digest:
                return target
            target = folder / f"{Path(filename).stem}_{ordinal}.pdf"
            ordinal += 1
        temporary.replace(target)
        return target
    finally:
        temporary.unlink(missing_ok=True)


def _visible_rows(page) -> tuple[list[DownloadRow], bool]:
    """Identify usable icons from the actual Diagnosis Viewer DOM.

    The file-down icon is a clickable SPAN (not a BUTTON). Non-clickable SVGs
    represent sessions without an available QuickTest and must be ignored.
    """
    rows = page.locator("tbody tr")
    candidates: list[DownloadRow] = []
    no_results = False
    for index in range(rows.count()):
        row = rows.nth(index)
        cells = row.locator("td")
        if "No Results Found" in row.inner_text() or "Keine Ergebnisse" in row.inner_text():
            no_results = True
            continue
        if cells.count() < 11:
            continue
        icon = row.locator("span.cursor-pointer:has(svg.lucide-file-down)")
        if not icon.count():
            continue
        candidates.append(DownloadRow(
            position=index,
            source=cells.nth(0).inner_text().strip(),
            timestamp=cells.nth(1).inner_text().strip(),
        ))
    return candidates, no_results


def _write_manifest(folder: Path, result: FinDownloadResult) -> None:
    """An attempt timestamp is recorded once and survives the final write."""
    folder.mkdir(parents=True, exist_ok=True)
    if not result.last_attempt_at:
        result.last_attempt_at = datetime.now(timezone.utc).isoformat()
    payload = {
        "fin": result.fin,
        "stand_utc": result.last_attempt_at,
        "status": result.status,
        "verfuegbare_sitzungen": result.available,
        "pdf_dateien": [file.name for file in result.files],
        "fehler": result.errors,
    }
    (folder / "abrufstatus.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def read_last_attempt(folder: Path, fin: str) -> FinDownloadResult | None:
    """Read previous status without allowing paths from JSON to escape the FIN directory."""
    manifest = Path(folder) / fin / "abrufstatus.json"
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        if payload.get("fin") != fin:
            return None
        timestamp = str(payload.get("stand_utc", ""))
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return None
        names = payload.get("pdf_dateien", [])
        files = [
            manifest.parent / name for name in names
            if isinstance(name, str) and name == Path(name).name
            and (manifest.parent / name).is_file()
        ]
        return FinDownloadResult(
            fin=fin,
            files=files,
            available=int(payload.get("verfuegbare_sitzungen", 0)),
            status=str(payload.get("status", "")),
            last_attempt_at=parsed.astimezone(timezone.utc).isoformat(),
        )
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return None


def scan_local_quicktests(folder: Path) -> list[FinDownloadResult]:
    """List *all* existing FIN directories, even without an abrufstatus.json.

    The GUI inventory is intentionally independent of the last batch selection.
    A manifest is an attempt record, not an inventory of all PDFs on disk.
    """
    root = Path(folder)
    if not root.is_dir():
        return []
    entries: list[FinDownloadResult] = []
    for fin_folder in root.iterdir():
        if (
            not fin_folder.is_dir()
            or fin_folder.is_symlink()
            or not _FIN.fullmatch(fin_folder.name)
        ):
            continue
        pdfs = sorted(
            path for path in fin_folder.iterdir()
            if path.is_file() and not path.is_symlink() and path.suffix.lower() == ".pdf"
        )
        previous = read_last_attempt(root, fin_folder.name)
        if previous is None:
            previous = FinDownloadResult(
                fin=fin_folder.name,
                status="PDFs lokal (ohne Abrufprotokoll)" if pdfs else "Ordner ohne PDFs",
            )
        # The current or legacy manifest may refer only to the most recent run.
        previous.files = pdfs
        entries.append(previous)
    return sorted(entries, key=lambda result: result.fin)


def recently_attempted(
    folder: Path, fin: str, *, now: datetime | None = None
) -> FinDownloadResult | None:
    """Every request attempted in the last 24h is skipped, including unsuccessful ones."""
    previous = read_last_attempt(folder, fin)
    if previous is None:
        return None
    at = now or datetime.now(timezone.utc)
    last = datetime.fromisoformat(previous.last_attempt_at)
    delta = at.astimezone(timezone.utc) - last
    if timedelta(minutes=-5) <= delta < timedelta(hours=24):
        previous.status = "Übersprungen (< 24 h)"
        return previous
    return None


def format_last_attempt(value: str) -> str:
    """Display timestamps in the local time zone (GUI)."""
    if not value:
        return "Noch kein Abruf"
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone().strftime(
            "%d.%m.%Y %H:%M"
        )
    except ValueError:
        return "Unbekannt"


class DiagnosisViewerDownloader:
    """Operate installed Microsoft Edge; PING ID confirmation stays with the user."""

    def __init__(
        self,
        output_dir: Path,
        profile_dir: Path,
        *,
        login_timeout_seconds: int = 240,
        result_timeout_seconds: int = 60,
        pdf_timeout_seconds: int = 90,
        user_id: str = "",
        password: str = "",
        retry_recent: bool = False,
        action_interval_seconds: float = 1.5,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.profile_dir = Path(profile_dir)
        self.login_timeout_seconds = login_timeout_seconds
        self.result_timeout_seconds = result_timeout_seconds
        self.pdf_timeout_seconds = pdf_timeout_seconds
        self.user_id = user_id
        self.password = password
        self.retry_recent = retry_recent
        # Fixed, conservative pacing to limit request rate and avoid overloading the service.
        self.action_interval_seconds = max(0.0, float(action_interval_seconds))
        self._last_action_at: float | None = None

    @staticmethod
    def _check_cancel(cancel: Event) -> None:
        if cancel.is_set():
            raise DownloadCancelled("Abruf durch Benutzer beendet.")


    def _pace(self, cancel: Event | None = None) -> None:
        """Keep a minimum interval between our own browser actions.

        This is request pacing, not an attempt to bypass bot defenses. Dynamic
        page transitions are still awaited through Playwright's state checks.
        """
        if self._last_action_at is not None:
            deadline = self._last_action_at + self.action_interval_seconds
            while True:
                if cancel is not None:
                    self._check_cancel(cancel)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                pause = min(remaining, 0.2)
                if cancel is not None:
                    cancel.wait(pause)
                else:
                    time.sleep(pause)
        if cancel is not None:
            self._check_cancel(cancel)
        self._last_action_at = time.monotonic()

    @staticmethod
    def _is_login_host(url: str) -> bool:
        """Never fill corporate credentials on an unverified redirect host."""
        parsed = urlsplit(url)
        return parsed.scheme == "https" and parsed.hostname == LOGIN_HOST

    def _enter_credentials(
        self, candidate, submitted: dict[str, bool], progress: Progress,
        cancel: Event | None = None,
    ) -> None:
        """Fill the two Mercedes SSO form steps, but leave PING ID to the user."""
        if not self._is_login_host(candidate.url):
            return
        cookie = candidate.locator("#c-s-bn")
        if cookie.count() and cookie.is_visible():
            # Necessary cookies only. This is sufficient for signing in.
            self._pace(cancel)
            cookie.click(timeout=2500)
        user_field = candidate.locator("#userid")
        if (
            self.user_id and not submitted["user"]
            and user_field.count() and user_field.is_visible()
        ):
            self._pace(cancel)
            user_field.fill(self.user_id)
            self._pace(cancel)
            candidate.locator("#next-btn").click(timeout=8000)
            submitted["user"] = True
            progress("Benutzer-ID eingetragen. Passwortseite wird geöffnet …")
            return
        password_field = candidate.locator("#password")
        if (
            self.password and not submitted["password"]
            and password_field.count() and password_field.is_visible()
        ):
            self._pace(cancel)
            password_field.fill(self.password)
            self._pace(cancel)
            candidate.locator("#loginSubmitButton").click(timeout=8000)
            submitted["password"] = True
            progress("Anmeldung gesendet. Bitte PING ID auf dem Smartphone bestätigen …")

    def _login(self, context, page, progress: Progress, cancel: Event):
        deadline = time.monotonic() + self.login_timeout_seconds
        clicked_sso = False
        submitted = {"user": False, "password": False}
        progress("Edge: SSO öffnen. Benutzer-ID und Passwort werden bei Verfügbarkeit eingetragen.")
        while time.monotonic() < deadline:
            self._check_cancel(cancel)
            for candidate in context.pages:
                if candidate.is_closed():
                    continue
                try:
                    fin_field = candidate.locator('input[name="finVin"]')
                    if (
                        urlsplit(candidate.url).scheme == "https"
                        and urlsplit(candidate.url).hostname == VIEWER_HOST
                        and fin_field.count() and fin_field.is_visible()
                    ):
                        progress("PING ID abgeschlossen. Diagnosis Viewer ist bereit.")
                        return candidate
                    if self._is_login_host(candidate.url):
                        self._enter_credentials(candidate, submitted, progress, cancel)
                        continue
                    if not clicked_sso:
                        for role in ("button", "link"):
                            sso = candidate.get_by_role(
                                role, name=re.compile(r"SSO|Single Sign.On", re.IGNORECASE)
                            )
                            if sso.count() and sso.first.is_visible():
                                self._pace(cancel)
                                sso.first.click(timeout=3000)
                                clicked_sso = True
                                progress("SSO gestartet. PING ID nach der Passwort-Anmeldung bestätigen.")
                                break
                except DownloadCancelled:
                    raise
                except Exception:
                    # Login redirects can invalidate the page during a polling cycle.
                    continue
            time.sleep(0.7)
        raise TimeoutError(
            "SSO-/PING-ID-Anmeldung nicht rechtzeitig abgeschlossen. "
            "Bitte Benutzer-ID, Passwort und die PING-ID-Freigabe in Edge prüfen."
        )

    def _wait_results(self, page, cancel: Event, fin: str):
        """Wait until the displayed rows belong to the *requested* FIN.

        Search is asynchronous; otherwise old rows from the preceding FIN could
        accidentally be downloaded while the new search is still loading.
        """
        deadline = time.monotonic() + self.result_timeout_seconds
        while time.monotonic() < deadline:
            self._check_cancel(cancel)
            candidates, empty = _visible_rows(page)
            if empty:
                return []
            rows = page.locator("tbody tr")
            matching = set()
            for index in range(rows.count()):
                cells = rows.nth(index).locator("td")
                if cells.count() < 11:
                    continue
                if fin in (
                    cells.nth(3).inner_text().strip().upper(),
                    cells.nth(4).inner_text().strip().upper(),
                ):
                    matching.add(index)
            if matching:
                # Rows with Quicktest Count=0 have no clickable PDF icon.
                return [row for row in candidates if row.position in matching]
            page.wait_for_timeout(850)
        raise TimeoutError(
            "Zeitüberschreitung: keine Ergebnisse für die angeforderte FIN geladen."
        )

    def _one_fin(self, context, page, fin: str, progress: Progress, cancel: Event) -> tuple[FinDownloadResult, object]:
        result = FinDownloadResult(
            fin=fin, status="Abruf gestartet",
            last_attempt_at=datetime.now(timezone.utc).isoformat(),
        )
        folder = self.output_dir / fin
        _write_manifest(folder, result)  # last download ATTEMPT, not only success
        try:
            self._check_cancel(cancel)
            progress(f"{fin}: Diagnosis Viewer öffnen …")
            try:
                self._pace(cancel)
                page.goto(search_url(fin), wait_until="domcontentloaded", timeout=45000)
            except Exception:
                # An interactive SSO redirect may exceed the navigation timeout.
                pass
            page = self._login(context, page, progress, cancel)
            field = page.locator('input[name="finVin"]')
            self._pace(cancel)
            field.fill(fin)
            # Required even when the FIN was already passed in the address.
            search = page.get_by_role("button", name=re.compile(r"^(Search|Suchen)$", re.I))
            self._pace(cancel)
            search.click(timeout=15000)
            progress(f"{fin}: Ergebnisse werden geladen …")
            self._pace(cancel)  # Give the asynchronous search time to refresh its table.
            rows = self._wait_results(page, cancel, fin)
            result.available = len(rows)
            if not rows:
                result.status = "Keine Quicktests"
                progress(f"{fin}: keine herunterladbaren Quicktests.")
                return result, page
            for number, descriptor in enumerate(rows, 1):
                self._check_cancel(cancel)
                progress(f"{fin}: PDF {number}/{len(rows)} wird geladen …")
                try:
                    icon = page.locator("tbody tr").nth(descriptor.position).locator(
                        "span.cursor-pointer:has(svg.lucide-file-down)"
                    )
                    self._pace(cancel)
                    with page.expect_download(timeout=self.pdf_timeout_seconds * 1000) as event:
                        icon.first.click(timeout=15000)
                    downloaded = event.value
                    if downloaded.failure():
                        raise RuntimeError(downloaded.failure())
                    saved = _save_pdf(downloaded, folder, descriptor)
                    if saved not in result.files:
                        result.files.append(saved)
                except Exception as exc:
                    result.errors.append(f"Sitzung {number} ({descriptor.timestamp}): {exc}")
            result.status = "Erfolgreich" if not result.errors else (
                "Teilweise erfolgreich" if result.files else "Fehler"
            )
            progress(f"{fin}: {len(result.files)} PDF(s) gespeichert, {len(result.errors)} Fehler.")
            return result, page
        except DownloadCancelled:
            result.status = "Abgebrochen"
            return result, page
        except Exception as exc:
            result.status = "Fehler"
            result.errors.append(str(exc))
            return result, page
        finally:
            _write_manifest(folder, result)

    def run(
        self,
        fins: list[str],
        *,
        progress: Progress | None = None,
        cancel: Event | None = None,
    ) -> list[FinDownloadResult]:
        """Use the installed Edge for new requests; skip FINs attempted within 24h."""
        validated = parse_fins("\n".join(fins))
        progress = progress or (lambda message: None)
        cancel = cancel or Event()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        results_by_fin: dict[str, FinDownloadResult] = {}
        pending: list[str] = []
        for fin in validated:
            previous = None if self.retry_recent else recently_attempted(self.output_dir, fin)
            if previous is None:
                pending.append(fin)
            else:
                results_by_fin[fin] = previous
                progress(f"{fin}: letzter Abruf < 24 Stunden – übersprungen.")
        if not pending:
            progress("Alle FINs wurden innerhalb der letzten 24 Stunden bereits abgerufen.")
            return [results_by_fin[fin] for fin in validated]
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError("Playwright fehlt. Bitte die App mit Browser-Unterstützung installieren.") from exc
        with sync_playwright() as playwright:
            try:
                context = playwright.chromium.launch_persistent_context(
                    user_data_dir=str(self.profile_dir),
                    channel="msedge",
                    headless=False,
                    accept_downloads=True,
                    no_viewport=True,
                )
            except Exception as exc:
                raise RuntimeError(
                    "Microsoft Edge konnte nicht gestartet werden. "
                    "Edge muss installiert sein und das NTF-Browserprofil darf nicht von "
                    "einem zweiten Programm verwendet werden. " + str(exc)
                ) from exc
            try:
                page = context.pages[0] if context.pages else context.new_page()
                for fin in pending:
                    if cancel.is_set():
                        break
                    result, page = self._one_fin(context, page, fin, progress, cancel)
                    results_by_fin[fin] = result
                    if result.status == "Abgebrochen":
                        break
            finally:
                context.close()
                self.password = ""  # Best effort: no credential retained between runs.
        return [results_by_fin[fin] for fin in validated if fin in results_by_fin]
