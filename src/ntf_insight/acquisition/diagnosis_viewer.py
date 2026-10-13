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
from datetime import datetime, timezone
from pathlib import Path
from threading import Event
from typing import Callable
from urllib.parse import quote

DIAGNOSIS_VIEWER = "https://app.diagviewer.prod.gspp-eu.cloud.corpintra.net/search"
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
    folder.mkdir(parents=True, exist_ok=True)
    payload = {
        "fin": result.fin,
        "stand_utc": datetime.now(timezone.utc).isoformat(),
        "status": result.status,
        "verfuegbare_sitzungen": result.available,
        "pdf_dateien": [file.name for file in result.files],
        "fehler": result.errors,
    }
    (folder / "abrufstatus.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )


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
    ) -> None:
        self.output_dir = Path(output_dir)
        self.profile_dir = Path(profile_dir)
        self.login_timeout_seconds = login_timeout_seconds
        self.result_timeout_seconds = result_timeout_seconds
        self.pdf_timeout_seconds = pdf_timeout_seconds

    @staticmethod
    def _check_cancel(cancel: Event) -> None:
        if cancel.is_set():
            raise DownloadCancelled("Abruf durch Benutzer beendet.")

    def _login(self, context, page, progress: Progress, cancel: Event):
        deadline = time.monotonic() + self.login_timeout_seconds
        clicked_sso = False
        progress("Edge: Bei Bedarf SSO öffnen und PING ID auf dem Handy bestätigen.")
        while time.monotonic() < deadline:
            self._check_cancel(cancel)
            for candidate in context.pages:
                if candidate.is_closed():
                    continue
                try:
                    if candidate.locator('input[name="finVin"]').count():
                        return candidate
                    if not clicked_sso:
                        for role in ("button", "link"):
                            sso = candidate.get_by_role(
                                role, name=re.compile(r"SSO|Single Sign.On", re.IGNORECASE)
                            )
                            if sso.count() and sso.first.is_visible():
                                sso.first.click(timeout=3000)
                                clicked_sso = True
                                progress("SSO gestartet: PING ID am Handy freigeben.")
                                break
                except Exception:  # Corporate redirects may invalidate a page mid-poll.
                    continue
            page.wait_for_timeout(1000)
        raise TimeoutError("SSO/PING ID nicht innerhalb des Anmeldezeitfensters abgeschlossen.")

    def _wait_results(self, page, cancel: Event):
        deadline = time.monotonic() + self.result_timeout_seconds
        while time.monotonic() < deadline:
            self._check_cancel(cancel)
            candidates, empty = _visible_rows(page)
            if candidates or empty:
                return candidates
            # There may be diagnosis sessions with Quicktest Count = 0 only.
            rows = page.locator("tbody tr")
            if any(rows.nth(i).locator("td").count() >= 11 for i in range(rows.count())):
                return []
            page.wait_for_timeout(500)
        raise TimeoutError("Zeitüberschreitung beim Laden der Suchergebnisse.")

    def _one_fin(self, context, page, fin: str, progress: Progress, cancel: Event) -> tuple[FinDownloadResult, object]:
        result = FinDownloadResult(fin=fin)
        folder = self.output_dir / fin
        folder.mkdir(parents=True, exist_ok=True)
        try:
            self._check_cancel(cancel)
            progress(f"{fin}: Diagnosis Viewer öffnen …")
            try:
                page.goto(search_url(fin), wait_until="domcontentloaded", timeout=45000)
            except Exception:
                # An interactive SSO redirect may exceed the navigation timeout.
                pass
            page = self._login(context, page, progress, cancel)
            field = page.locator('input[name="finVin"]')
            field.fill(fin)
            # Required even when the FIN was already passed in the address.
            search = page.get_by_role("button", name=re.compile(r"^(Search|Suchen)$", re.I))
            search.click(timeout=15000)
            progress(f"{fin}: Ergebnisse werden geladen …")
            rows = self._wait_results(page, cancel)
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
        """Run one Edge instance for all FINs and retain a separate FIN folder."""
        validated = parse_fins("\n".join(fins))
        progress = progress or (lambda message: None)
        cancel = cancel or Event()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError("Playwright fehlt. Bitte die App mit Browser-Unterstützung installieren.") from exc
        results: list[FinDownloadResult] = []
        with sync_playwright() as playwright:
            try:
                context = playwright.chromium.launch_persistent_context(
                    user_data_dir=str(self.profile_dir),
                    channel="msedge",  # Uses installed Edge, downloads no other browser.
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
                for fin in validated:
                    if cancel.is_set():
                        break
                    result, page = self._one_fin(context, page, fin, progress, cancel)
                    results.append(result)
                    if result.status == "Abgebrochen":
                        break
            finally:
                context.close()
        return results
