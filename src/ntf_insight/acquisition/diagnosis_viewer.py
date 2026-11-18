"""QuickTest PDF acquisition via the company's existing interactive Edge SSO.

The browser is operated with Playwright; no credentials, SSO cookies or PING ID
secrets are accessed by the application. An independent browser profile is kept
locally so a valid SSO session may be reused between runs.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from contextlib import nullcontext
import re
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event
from typing import Callable
from urllib.parse import quote, urlsplit

from ntf_insight.acquisition.diagnosis_viewer_pdf import (
    _beobachtete_pdf_antwort,
    pdf_aus_browser_antworten,
    pdf_aus_popup_blob,
    pdf_aus_popup_url,
)
from ntf_insight.acquisition.fin_format import fin_passt_zu_anfrage, ist_gueltige_fin
from ntf_insight.acquisition.sso_login_gate import serielle_sso_anmeldung

DIAGNOSIS_VIEWER = "https://app.diagviewer.prod.gspp-eu.cloud.corpintra.net/search"
LOGIN_HOST = "login.mercedes-benz.com"
VIEWER_HOST = urlsplit(DIAGNOSIS_VIEWER).hostname
SOURCES = "XD,XD(AQT),TD,DAS"
NO_QUICKTEST_DATA_MESSAGE = "Diagnosis payload loaded from S3 does not contain quicktest data"
_ILLEGAL_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")
Progress = Callable[[str], None]


class DownloadCancelled(RuntimeError):
    """Raised when the user requests cancellation."""


class QuickTestDataUnavailable(RuntimeError):
    """A diagnosis exists, but its S3 payload has no QuickTest PDF."""


class BrowserSessionLost(RuntimeError):
    """Die Edge-/Playwright-Verbindung wurde unerwartet getrennt."""


class ViewerTabClosed(RuntimeError):
    """Nur das Viewer-Tab wurde geschlossen; Edge ist weiterhin verbunden."""


class QuickTestPopupOhneDownload(RuntimeError):
    """Ein PDF-Fenster wurde geoeffnet, ohne einen Download zu starten."""


def _browser_verbunden(context) -> bool:
    """Browser- statt Tab-Status pruefen, auch bei persistentem Edge-Profil."""
    try:
        if getattr(context, "_ntf_context_geschlossen", False):
            return False
        browser = getattr(context, "browser", None)
        # Persistent Edge contexts besitzen haeufig kein Browser-Objekt.
        # Ein registriertes close-Ereignis liefert hier den Zustand.
        return browser is None or bool(browser.is_connected())
    except Exception:
        return False


def _browser_verloren(exc: Exception) -> bool:
    """Playwright schliesst Tab, Kontext und Browser mit aehnlichen Meldungen."""
    name = type(exc).__name__.casefold()
    message = str(exc).casefold()
    return (
        "targetclosed" in name
        or any(meldung in message for meldung in (
            "target page, context or browser has been closed",
            "target closed",
            "browser has been closed",
            "browser closed",
            "page crashed",
            "target crashed",
            "connection closed",
        ))
    )


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
    no_quicktest_sessions: list[str] = field(default_factory=list)
    available: int = 0
    status: str = "Ausstehend"
    last_attempt_at: str = ""


def parse_fins(text: str, *, kurz_erlaubt: bool = False) -> list[str]:
    """FIN-Listen pruefen; Kurz-FINs nur bei expliziter CLI-Freigabe zulassen."""
    tokens = [s.strip().upper() for s in re.split(r"[\s,;]+", text) if s.strip()]
    if not tokens:
        raise ValueError(
            "Bitte mindestens eine 14- oder 17-stellige FIN eingeben."
            if kurz_erlaubt else "Bitte mindestens eine 17-stellige FIN eingeben."
        )
    invalid = [s for s in tokens if not ist_gueltige_fin(s, kurz_erlaubt=kurz_erlaubt)]
    if invalid:
        erlaubte_laengen = "14 oder 17" if kurz_erlaubt else "17"
        raise ValueError(
            f"Ungueltige FIN ({erlaubte_laengen} Zeichen A-Z/0-9 ohne I, O, Q): "
            + ", ".join(invalid[:3])
        )
    return list(dict.fromkeys(tokens))


def search_url(fin: str, *, kurz_erlaubt: bool = False) -> str:
    if not ist_gueltige_fin(fin, kurz_erlaubt=kurz_erlaubt):
        raise ValueError(
            "FIN muss 14 oder 17 gueltige Zeichen enthalten."
            if kurz_erlaubt else "FIN muss 17 gueltige Zeichen enthalten."
        )
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


def _vorhandene_sitzungs_pdf(folder: Path, row: DownloadRow) -> Path | None:
    """Nur eine gueltige PDF mit eindeutigem Sitzungs-Praefix wiederverwenden.

    Der alte Downloader speichert bereits <Zeitpunkt>_<Quelle>_<PDF-Name>.
    Eine Dateigroesse >0 oder ein Manifest allein ist kein Download-Beleg.
    """
    if not folder.is_dir() or folder.is_symlink():
        return None
    prefix = _safe_name(f"{row.timestamp}_{row.source}") + "_"
    for pdf in sorted(folder.iterdir()):
        if (
            not pdf.is_file() or pdf.is_symlink()
            or pdf.suffix.casefold() != ".pdf"
            or not pdf.name.startswith(prefix)
        ):
            continue
        try:
            with pdf.open("rb") as datei:
                if datei.read(5) == b"%PDF-":
                    return pdf
        except OSError:
            continue
    return None


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
        "ohne_quicktest": result.no_quicktest_sessions,
    }
    # Bei Stromausfall oder Edge-Absturz nie einen halb geschriebenen
    # Checkpoint als gueltigen Status zuruecklassen.
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=folder,
        suffix=".partial", delete=False,
    ) as stream:
        temp = Path(stream.name)
        json.dump(payload, stream, indent=2, ensure_ascii=False)
    try:
        temp.replace(folder / "abrufstatus.json")
    finally:
        temp.unlink(missing_ok=True)


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
            no_quicktest_sessions=[
                str(item) for item in payload.get("ohne_quicktest", [])
            ],
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
            or not ist_gueltige_fin(fin_folder.name, kurz_erlaubt=True)
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


def lokal_vorhandene_pdf(
    ordner: Path, fin: str,
) -> FinDownloadResult | None:
    """CLI: Nur eine echte PDF im eigenen FIN-Ordner erlaubt das Ueberspringen.

    Ein 24-h-Abrufstatus ohne PDF, auch 'Keine Quicktests' oder 'Fehler',
    ist *kein* Grund, eine weitere Abfrage zu unterdruecken. Ebenso zaehlen
    fremde FIN-Ordner, symlinks, defekte PDF-Dateien und JSON nicht.
    """
    fin_ordner = Path(ordner) / fin
    if not fin_ordner.is_dir() or fin_ordner.is_symlink():
        return None
    pdfs: list[Path] = []
    for pfad in fin_ordner.iterdir():
        if not pfad.is_file() or pfad.is_symlink() or pfad.suffix.lower() != ".pdf":
            continue
        try:
            with pfad.open("rb") as datei:
                if datei.read(5) == b"%PDF-":
                    pdfs.append(pfad)
        except OSError:
            continue
    if not pdfs:
        return None
    alt = read_last_attempt(ordner, fin)
    return FinDownloadResult(
        fin=fin, files=sorted(pdfs),
        available=alt.available if alt else 0,
        status="Übersprungen (PDF bereits vorhanden)",
        last_attempt_at=alt.last_attempt_at if alt else "",
    )


def _quicktest_fin_vollstaendig(ordner: Path, fin: str) -> FinDownloadResult | None:
    """Nur nachweislich vollstaendige FINs ohne neue Edge-Anmeldung ueberspringen.

    Bei einem frueheren Abruf mit 1/14 PDFs muss die FIN erneut durchsucht
    werden. Die eigentlichen, bereits vorhandenen PDFs werden pro Sitzung
    zugeordnet und nicht nochmals aus dem Portal geladen.
    """
    lokal = lokal_vorhandene_pdf(ordner, fin)
    if lokal is None:
        return None
    alt = read_last_attempt(ordner, fin)
    if alt is None or alt.available == 0:
        # Rueckwaertskompatibilitaet fuer Altbestaende ohne Sitzungszaehler.
        # Die Vollstaendigkeit dieser Altbestaende ist nicht beweisbar.
        return lokal
    if (
        alt.status == "Erfolgreich"
        and len(lokal.files) + len(alt.no_quicktest_sessions) >= alt.available
    ):
        return lokal
    return None


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
        pdf_timeout_seconds: int = 60,
        user_id: str = "",
        password: str = "",
        retry_recent: bool = False,
        action_interval_seconds: float = 1.5,
        kurz_fin_erlaubt: bool = False,
        nur_fehlende_pdfs: bool = False,
        serielle_sso: bool = False,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.profile_dir = Path(profile_dir)
        self.login_timeout_seconds = login_timeout_seconds
        self.result_timeout_seconds = result_timeout_seconds
        self.pdf_timeout_seconds = pdf_timeout_seconds
        self.user_id = user_id
        self.password = password
        self.retry_recent = retry_recent
        self.kurz_fin_erlaubt = kurz_fin_erlaubt
        self.nur_fehlende_pdfs = nur_fehlende_pdfs
        self.serielle_sso = serielle_sso
        self._sso_bereits_bestaetigt = False
        self._sso_im_aktuellen_suchlauf = False
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

    @staticmethod
    def _fin_suchbereich(page):
        """FIN-Suchfeld auf der Hauptseite oder in einem eingebetteten Frame finden.

        Die Bereitschaft wird nicht allein aus der URL oder dem PING-ID-Dialog
        abgeleitet. Fuer den anschliessenden Suchklick denselben Scope nutzen.
        """
        for scope in [page, *getattr(page, "frames", [])]:
            try:
                feld = scope.locator('input[name="finVin"]')
                if feld.count() and feld.is_visible():
                    return scope
            except Exception as exc:
                if _browser_verloren(exc):
                    raise BrowserSessionLost(
                        "Edge-Verbindung waehrend der SSO-Erkennung verloren."
                    ) from exc
                # Ein Frame kann gerade navigieren; die naechste Runde versucht es erneut.
                continue
        return None

    def _login(self, context, page, progress: Progress, cancel: Event):
        deadline = time.monotonic() + self.login_timeout_seconds
        clicked_sso = False
        submitted = {"user": False, "password": False}
        viewer_aufgerufen: dict[int, float] = {}
        viewer_neu_geladen: set[int] = set()
        naechster_hinweis = time.monotonic() + 20
        progress("Edge: SSO öffnen. Benutzer-ID und Passwort werden bei Verfügbarkeit eingetragen.")
        while time.monotonic() < deadline:
            self._check_cancel(cancel)
            try:
                browser = getattr(context, "browser", None)
                if browser is not None and not browser.is_connected():
                    raise BrowserSessionLost(
                        "Edge-Browser ist waehrend der SSO-Anmeldung abgestuerzt."
                    )
                candidates = list(context.pages)
            except Exception as exc:
                if _browser_verloren(exc):
                    raise BrowserSessionLost("Edge-Verbindung waehrend der Anmeldung verloren.") from exc
                raise
            for candidate in candidates:
                try:
                    if candidate.is_closed():
                        continue
                    hostname = urlsplit(candidate.url).hostname
                    if hostname == VIEWER_HOST:
                        if self._fin_suchbereich(candidate) is not None:
                            progress("PING ID abgeschlossen. Diagnosis Viewer ist bereit.")
                            return candidate
                        # Der authentifizierte Viewer kann nach einem Redirect ein
                        # unvollstaendiges Suchformular zeigen. Maximal einmal
                        # kontrolliert neu laden, niemals PING ID umgehen.
                        identitaet = id(candidate)
                        jetzt = time.monotonic()
                        viewer_aufgerufen.setdefault(identitaet, jetzt)
                        if (
                            identitaet not in viewer_neu_geladen
                            and jetzt - viewer_aufgerufen[identitaet] >= 15
                        ):
                            viewer_neu_geladen.add(identitaet)
                            progress(
                                "Diagnosis Viewer ist geöffnet, aber das FIN-Suchfeld "
                                "fehlt noch. Die Viewer-Seite wird einmal neu geladen."
                            )
                            candidate.reload(
                                wait_until="domcontentloaded", timeout=15000
                            )
                            continue
                    if self._is_login_host(candidate.url):
                        self._sso_im_aktuellen_suchlauf = True
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
                except (DownloadCancelled, BrowserSessionLost):
                    raise
                except Exception as exc:
                    if _browser_verloren(exc):
                        raise BrowserSessionLost(
                            "Edge-Verbindung waehrend der SSO-Anmeldung verloren."
                        ) from exc
                    # Login-Redirects koennen waehrend der Abfrage navigieren.
                    continue
            if time.monotonic() >= naechster_hinweis:
                progress(
                    "SSO: warte auf das sichtbare FIN-Suchfeld im Diagnosis Viewer. "
                    "Falls die Seite bereits offen ist, ihren Ladezustand prüfen."
                )
                naechster_hinweis = time.monotonic() + 20
            # Auch waehrend der Wartezeit ist der Abbruch unmittelbar wirksam.
            if cancel.wait(0.7):
                self._check_cancel(cancel)
        raise TimeoutError(
            "SSO-/PING-ID-Anmeldung nicht rechtzeitig abgeschlossen oder "
            "FIN-Suchfeld im Diagnosis Viewer nicht sichtbar. "
            "Bitte die Browserseite und die PING-ID-Freigabe prüfen."
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
            moegliche_vollfin: set[str] = set()
            for index in range(rows.count()):
                cells = rows.nth(index).locator("td")
                if cells.count() < 11:
                    continue
                angezeigte_fins = [
                    cells.nth(3).inner_text().strip().upper(),
                    cells.nth(4).inner_text().strip().upper(),
                ]
                for angezeigt in angezeigte_fins:
                    if not fin_passt_zu_anfrage(fin, angezeigt):
                        continue
                    matching.add(index)
                    bereinigt = re.sub(r"[\s-]+", "", angezeigt)
                    if len(fin) == 14 and len(bereinigt) == 17:
                        moegliche_vollfin.add(bereinigt)
            # Zwei verschiedene Voll-FINs mit gleicher Kurz-FIN duerfen
            # niemals als ein Fahrzeug zusammengefasst werden.
            if len(moegliche_vollfin) > 1:
                raise ValueError(
                    "Kurz-FIN mehrdeutig: Diagnosis Viewer zeigt unterschiedliche "
                    "17-stellige Fahrzeugkennungen. Bitte vollstaendige FIN verwenden."
                )
            if matching:
                # Rows with Quicktest Count=0 have no clickable PDF icon.
                return [row for row in candidates if row.position in matching]
            page.wait_for_timeout(850)
        raise TimeoutError(
            "Zeitüberschreitung: keine Ergebnisse für die angeforderte FIN geladen."
        )

    @staticmethod
    def _watch_no_quicktest_message(page) -> bool:
        """Watch *new* S3 notices, not a toast left from the previous row.

        This observer only watches DOM changes. It does not change the Diagnosis
        Viewer or its authentication state.
        """
        try:
            page.evaluate(
                """(needle) => {
                    const key = '__ntfInsightQuicktestS3Watcher';
                    const old = window[key];
                    if (old?.observer) old.observer.disconnect();
                    const state = { matched: false, observer: null };
                    const expected = needle.toLowerCase();
                    const root = document.body || document.documentElement;
                    if (!root) return;
                    state.observer = new MutationObserver((mutations) => {
                        for (const mutation of mutations) {
                            const nodes = mutation.type === 'characterData'
                                ? [mutation.target]
                                : Array.from(mutation.addedNodes || []);
                            if (nodes.some((node) =>
                                (node.textContent || '').toLowerCase().includes(expected)
                            )) {
                                state.matched = true;
                                break;
                            }
                        }
                    });
                    state.observer.observe(root, {
                        subtree: true, childList: true, characterData: true
                    });
                    window[key] = state;
                }""",
                NO_QUICKTEST_DATA_MESSAGE,
            )
            return True
        except Exception:
            # Fallback: detect a newly visible DOM message after clicking.
            return False

    @staticmethod
    def _no_quicktest_visible(page) -> bool:
        try:
            matching = page.get_by_text(NO_QUICKTEST_DATA_MESSAGE, exact=False)
            return bool(matching.count() and matching.first.is_visible())
        except Exception:
            # The page may be navigating while the toast is rendered.
            return False

    @staticmethod
    def _no_quicktest_observed(page) -> bool:
        try:
            return bool(page.evaluate(
                "() => Boolean(window.__ntfInsightQuicktestS3Watcher?.matched)"
            ))
        except Exception:
            return False

    @staticmethod
    def _stop_no_quicktest_watcher(page) -> None:
        try:
            page.evaluate("""() => {
                const key = '__ntfInsightQuicktestS3Watcher';
                if (window[key]?.observer) window[key].observer.disconnect();
                delete window[key];
            }""")
        except Exception:
            pass

    def _download_or_skip(
        self, page, icon, cancel: Event, *, progress: Progress | None = None,
    ):
        """PDF ueber Download-Event ODER beobachtete Inline-Netzwerkantwort sichern.

        Der offizielle Edge-PDF-Viewer oeffnet eine Vorschau ohne
        Playwright-Download. Vor dem Icon-Klick auf PDF-HTTP-Antworten lauschen,
        damit auch die erste Antwort im Popup nicht verloren geht. Kein
        direkter Request an unbekannte Hosts oder globale PDF-Downloads.
        """
        self._check_cancel(cancel)
        self._pace(cancel)
        melden = progress or (lambda _: None)
        initially_visible = self._no_quicktest_visible(page)
        observer_installed = self._watch_no_quicktest_message(page)
        downloads: list[object] = []
        pdf_antworten: list[object] = []
        notices: list[str] = []
        unexpected_dialog = [False]
        popup_pages: list[object] = []
        popup_pdf_uebernommen = False
        versuchte_popup_urls: set[str] = set()
        erste_popup_zeit: float | None = None
        context = getattr(page, "context", None)

        def on_download(download) -> None:
            downloads.append(download)

        def on_response(response) -> None:
            # Noch NICHT response.body() im Eventhandler aufrufen:
            # die Antwort kann gerade erst mit dem Streaming begonnen haben.
            if _beobachtete_pdf_antwort(response) and len(pdf_antworten) < 8:
                pdf_antworten.append(response)

        def on_dialog(dialog) -> None:
            if NO_QUICKTEST_DATA_MESSAGE.casefold() in dialog.message.casefold():
                notices.append(NO_QUICKTEST_DATA_MESSAGE)
            else:
                unexpected_dialog[0] = True
            dialog.dismiss()

        def on_popup(popup) -> None:
            nonlocal erste_popup_zeit
            if popup in popup_pages:
                return
            popup_pages.append(popup)
            if erste_popup_zeit is None:
                erste_popup_zeit = time.monotonic()
            melden(
                "QuickTest: Neues PDF-Fenster erkannt; warte auf Download "
                "oder pruefe die PDF-Netzwerkantwort."
            )
            try:
                popup.on("download", on_download)
            except Exception:
                pass

        def on_context_page(candidate) -> None:
            try:
                opener = candidate.opener()
            except Exception:
                return
            if opener is page:
                on_popup(candidate)

        def inline_pdf_uebernehmen():
            nonlocal popup_pdf_uebernommen
            # 1. Tatsächlich gelieferte PDF-Antwort der gerade geklickten
            # Seite oder eines direkten Popup-Tabs bevorzugen.
            if pdf_antworten:
                pdf = pdf_aus_browser_antworten(pdf_antworten, page, popup_pages)
                if pdf is not None:
                    melden(
                        "QuickTest: PDF-Daten aus Browser-Netzwerkantwort "
                        "uebernommen; speichere Originaldatei."
                    )
                    popup_pdf_uebernommen = True
                    return pdf
            # 2. Ausschliesslich den vom Klick bereits geoeffneten Popup-URL
            # mit der bestehenden SSO-Session laden. Externe Redirects,
            # fremde Hosts und Login-HTML sind strikt ausgeschlossen.
            for popup in popup_pages:
                try:
                    popup_url = popup.url
                except Exception:
                    continue
                if not isinstance(popup_url, str) or not popup_url:
                    continue
                if popup_url in versuchte_popup_urls:
                    continue
                versuchte_popup_urls.add(popup_url)
                pdf = pdf_aus_popup_url(context, popup_url, VIEWER_HOST)
                if pdf is not None:
                    melden(
                        "QuickTest: PDF aus bereits geoeffneter Viewer-Adresse "
                        "in angemeldeter Sitzung geladen."
                    )
                    popup_pdf_uebernommen = True
                    return pdf
                pdf = pdf_aus_popup_blob(page, popup_url, VIEWER_HOST)
                if pdf is not None:
                    melden(
                        "QuickTest: Original-PDF aus Viewer-Vorschau "
                        "uebernommen."
                    )
                    popup_pdf_uebernommen = True
                    return pdf
            return None

        page.on("download", on_download)
        page.on("dialog", on_dialog)
        page.on("popup", on_popup)
        if context is not None:
            context.on("page", on_context_page)
            context.on("response", on_response)
        try:
            deadline = time.monotonic() + self.pdf_timeout_seconds
            try:
                icon.click(timeout=min(15000, max(1, int(self.pdf_timeout_seconds * 1000))))
            except Exception as exc:
                # Beim Aufruf eines eingebetteten PDF-Viewers kann der Click
                # durch eine Navigation/Tab-Schliessung abbrechen, obwohl die
                # PDF-Antwort bereits geliefert wurde.
                if downloads:
                    return downloads[0]
                if popup_pages or pdf_antworten:
                    gerettet = inline_pdf_uebernehmen()
                    if gerettet is not None:
                        return gerettet
                    melden(
                        "QuickTest: PDF-Fenster geoeffnet, danach "
                        "Browseraktion abgebrochen; keine gueltigen PDF-Bytes gefunden."
                    )
                if _browser_verloren(exc):
                    if context is not None and _browser_verbunden(context):
                        raise ViewerTabClosed(
                            "Diagnosis-Viewer-Tab beim PDF-Klick geschlossen; "
                            "Edge noch verbunden."
                        ) from exc
                    raise BrowserSessionLost(
                        "Edge-/Playwright-Kontext beim PDF-Klick beendet."
                    ) from exc
                raise
            while True:
                self._check_cancel(cancel)
                if downloads:
                    return downloads[0]
                if notices or self._no_quicktest_observed(page):
                    raise QuickTestDataUnavailable(NO_QUICKTEST_DATA_MESSAGE)
                if unexpected_dialog[0]:
                    raise RuntimeError("Unerwartetes Dialogfenster beim PDF-Abruf.")
                if not initially_visible and self._no_quicktest_visible(page):
                    raise QuickTestDataUnavailable(NO_QUICKTEST_DATA_MESSAGE)
                if context is not None and not _browser_verbunden(context):
                    # Nach unerwartetem Kontextende noch einen bereits
                    # empfangenen PDF-Puffer versuchen (kein neuer Request).
                    gerettet = pdf_aus_browser_antworten(
                        pdf_antworten, page, popup_pages
                    )
                    if gerettet is not None:
                        return gerettet
                    raise BrowserSessionLost(
                        "Die Edge-Verbindung ist waehrend des PDF-Downloads abgebrochen."
                    )
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    gerettet = inline_pdf_uebernehmen()
                    if gerettet is not None:
                        return gerettet
                    if popup_pages:
                        raise QuickTestPopupOhneDownload(
                            "PDF-Vorschaufenster erkannt, aber kein Download gestartet "
                            "und keine gueltige PDF-Netzwerkantwort erhalten. "
                            "Edge-Einstellung 'PDF-Dateien immer herunterladen' "
                            "und Unternehmensrichtlinie pruefen."
                        )
                    raise TimeoutError(
                        f"Nach {self.pdf_timeout_seconds:g} Sekunden wurde "
                        "kein PDF-Download gestartet und keine gueltige "
                        "PDF-Netzwerkantwort erkannt."
                    )
                # Bei PDF-Vorschauen erst kurz auf ein normales Download-Event
                # warten, damit kein zweiter Request unnoetig ausgelöst wird.
                popup_wartezeit = min(2.0, self.pdf_timeout_seconds / 3)
                if (
                    pdf_antworten or
                    (erste_popup_zeit is not None
                     and time.monotonic() - erste_popup_zeit >= popup_wartezeit)
                ):
                    gerettet = inline_pdf_uebernehmen()
                    if gerettet is not None:
                        return gerettet
                try:
                    tick = page
                    if page.is_closed():
                        tick = next(
                            (p for p in popup_pages if not p.is_closed()), None
                        )
                        if tick is None:
                            raise ViewerTabClosed(
                                "Diagnosis-Viewer-Tab geschlossen; "
                                "kein aktives PDF-Fenster vorhanden."
                            )
                    tick.wait_for_timeout(
                        max(1, int(min(0.25, remaining) * 1000))
                    )
                except (ViewerTabClosed, BrowserSessionLost):
                    raise
                except Exception as exc:
                    if _browser_verloren(exc):
                        # Eine lokale Tab-Schliessung ist kein nachgewiesener
                        # Verlust des gesamten Edge-Browsers.
                        if context is not None and _browser_verbunden(context):
                            raise ViewerTabClosed(
                                "Diagnosis-Viewer-Tab beim PDF-Abruf geschlossen."
                            ) from exc
                        raise BrowserSessionLost(
                            "Edge-/Playwright-Verbindung beim PDF-Abruf verloren."
                        ) from exc
                    raise
        finally:
            for event, callback in (
                ("download", on_download), ("dialog", on_dialog),
                ("popup", on_popup),
            ):
                try:
                    page.remove_listener(event, callback)
                except Exception:
                    pass
            if context is not None:
                for event, callback in (
                    ("page", on_context_page), ("response", on_response),
                ):
                    try:
                        context.remove_listener(event, callback)
                    except Exception:
                        pass
            for popup in popup_pages:
                try:
                    popup.remove_listener("download", on_download)
                except Exception:
                    pass
            if observer_installed:
                self._stop_no_quicktest_watcher(page)
            if popup_pdf_uebernommen:
                # Die Bytes sind bereits im Speicher, daher darf die
                # Viewer-Vorschau geschlossen werden. Das verhindert
                # 18 oder mehr offene PDF-Tabs pro Fahrzeug.
                for popup in popup_pages:
                    try:
                        if not popup.is_closed():
                            popup.close()
                    except Exception:
                        pass

    def _one_fin(self, context, page, fin: str, progress: Progress, cancel: Event) -> tuple[FinDownloadResult, object]:
        # Bereits vorhandene PDFs werden in den neuen Status uebernommen.
        # Ein Edge-Absturz darf keine erfolgreichen Sitzungen ausblenden.
        vorhanden = lokal_vorhandene_pdf(self.output_dir, fin)
        letzter_abruf = read_last_attempt(self.output_dir, fin)
        result = FinDownloadResult(
            fin=fin, status="Abruf gestartet",
            files=list(vorhanden.files) if vorhanden is not None else [],
            # Bei erneutem Edge-Absturz schon vor der Ergebnistabelle darf
            # der vorherige Zaehler 1/14 nicht verloren gehen.
            available=letzter_abruf.available if letzter_abruf is not None else 0,
            last_attempt_at=datetime.now(timezone.utc).isoformat(),
        )
        folder = self.output_dir / fin
        _write_manifest(folder, result)
        try:
            self._check_cancel(cancel)
            progress(f"{fin}: Diagnosis Viewer öffnen …")
            anmeldung = (
                serielle_sso_anmeldung(status=progress, abbruch=cancel)
                if self.serielle_sso else nullcontext()
            )
            self._sso_im_aktuellen_suchlauf = False
            with anmeldung as phase:
                if phase is not None:
                    phase.neue_anmeldung = not self._sso_bereits_bestaetigt
                try:
                    self._pace(cancel)
                    page.goto(
                        search_url(fin, kurz_erlaubt=self.kurz_fin_erlaubt),
                        wait_until="domcontentloaded", timeout=45000,
                    )
                except DownloadCancelled:
                    raise
                except Exception as exc:
                    if _browser_verloren(exc):
                        raise BrowserSessionLost(
                            "Edge-Verbindung beim Oeffnen des Diagnosis Viewers verloren."
                        ) from exc
                    # Eine legitime SSO-Weiterleitung kann die Navigation unterbrechen.
                page = self._login(context, page, progress, cancel)
                self._sso_bereits_bestaetigt = True
                if phase is not None:
                    phase.neue_anmeldung |= self._sso_im_aktuellen_suchlauf
            suchbereich = self._fin_suchbereich(page) or page
            field = suchbereich.locator('input[name="finVin"]')
            self._pace(cancel)
            field.fill(fin)
            search = suchbereich.get_by_role(
                "button", name=re.compile(r"^(Search|Suchen)$", re.I),
            )
            self._pace(cancel)
            search.click(timeout=15000)
            progress(f"{fin}: Ergebnisse werden geladen …")
            self._pace(cancel)
            rows = self._wait_results(suchbereich, cancel, fin)
            result.available = len(rows)
            _write_manifest(folder, result)
            if not rows:
                result.status = "Keine Quicktests"
                progress(f"{fin}: keine herunterladbaren Quicktests.")
                return result, page
            # Gleiche Zeitstempel und Quellen koennen vorkommen. Ohne eine
            # eindeutige Sitzungsidentitaet nicht anhand des Dateinamens skippen.
            doppelte = Counter((row.timestamp, row.source) for row in rows)
            for number, descriptor in enumerate(rows, 1):
                self._check_cancel(cancel)
                try:
                    key = (descriptor.timestamp, descriptor.source)
                    vorhandene_pdf = (
                        _vorhandene_sitzungs_pdf(folder, descriptor)
                        if not self.retry_recent and doppelte[key] == 1
                        else None
                    )
                    if vorhandene_pdf is not None:
                        if vorhandene_pdf not in result.files:
                            result.files.append(vorhandene_pdf)
                        progress(
                            f"{fin}: PDF {number}/{len(rows)} bereits lokal gespeichert – "
                            "Sitzung übersprungen."
                        )
                        _write_manifest(folder, result)
                        continue
                    progress(f"{fin}: PDF {number}/{len(rows)} wird geladen …")
                    icon = suchbereich.locator("tbody tr").nth(descriptor.position).locator(
                        "span.cursor-pointer:has(svg.lucide-file-down)"
                    )
                    downloaded = self._download_or_skip(
                        page, icon.first, cancel, progress=progress,
                    )
                    failure = downloaded.failure()
                    if failure:
                        raise RuntimeError(f"PDF-Download fehlgeschlagen: {failure}")
                    saved = _save_pdf(downloaded, folder, descriptor)
                    if saved not in result.files:
                        result.files.append(saved)
                    # Checkpoint direkt nach jeder PDF, nicht erst nach der FIN.
                    _write_manifest(folder, result)
                except QuickTestDataUnavailable:
                    result.no_quicktest_sessions.append(
                        f"Sitzung {number} ({descriptor.timestamp})"
                    )
                    progress(
                        f"{fin}: Sitzung {number}/{len(rows)} – "
                        "keine QuickTest-Daten in S3, übersprungen."
                    )
                    _write_manifest(folder, result)
                except (DownloadCancelled, BrowserSessionLost, ViewerTabClosed):
                    raise
                except QuickTestPopupOhneDownload as exc:
                    result.errors.append(f"PDF {number}/{len(rows)}: {exc}")
                    result.status = "PDF-Fenster ohne Download"
                    progress(
                        f"{fin}: PDF {number}/{len(rows)}: Fenster ohne PDF-Download. "
                        "FIN-Lauf unterbrochen; vorhandene PDFs bleiben erhalten."
                    )
                    return result, page
                except TimeoutError as exc:
                    if _browser_verloren(exc):
                        raise BrowserSessionLost(
                            "Edge-Verbindung beim QuickTest-Download verloren."
                        ) from exc
                    result.errors.append(
                        f"Sitzung {number} ({descriptor.timestamp}): "
                        f"PDF-Timeout nach {self.pdf_timeout_seconds:g} Sekunden."
                    )
                    progress(
                        f"{fin}: Sitzung {number}/{len(rows)} – "
                        "PDF-Timeout, nächste Sitzung."
                    )
                    _write_manifest(folder, result)
                except Exception as exc:
                    if _browser_verloren(exc):
                        if _browser_verbunden(context):
                            raise ViewerTabClosed(
                                f"PDF {number}/{len(rows)}: Viewer-Tab geschlossen "
                                f"({type(exc).__name__}), Edge bleibt verbunden."
                            ) from exc
                        raise BrowserSessionLost(
                            f"PDF {number}/{len(rows)}: Edge-/Playwright-Verbindung verloren "
                            f"({type(exc).__name__})."
                        ) from exc
                    result.errors.append(
                        f"Sitzung {number} ({descriptor.timestamp}): {exc}"
                    )
                    _write_manifest(folder, result)
            result.status = (
                "Erfolgreich" if result.files and not result.errors
                else "Teilweise erfolgreich" if result.files
                else "Keine Quicktests" if result.no_quicktest_sessions and not result.errors
                else "Fehler"
            )
            progress(
                f"{fin}: {len(result.files)} PDF(s), "
                f"{len(result.no_quicktest_sessions)} ohne QuickTest, "
                f"{len(result.errors)} Fehler."
            )
            return result, page
        except (DownloadCancelled, InterruptedError):
            result.status = "Abgebrochen"
            return result, page
        except BrowserSessionLost as exc:
            result.status = "Browser-Verbindung verloren"
            result.errors.append(str(exc))
            progress(f"{fin}: Edge-Verbindung verloren; weitere Sitzungen nicht angeklickt.")
            return result, page
        except ViewerTabClosed as exc:
            result.status = "Viewer-Tab geschlossen"
            result.errors.append(str(exc))
            progress(
                f"{fin}: Viewer-Tab geschlossen, aber Edge weiterhin verbunden. "
                "Einmalige Tab-Wiederherstellung wird versucht."
            )
            return result, page
        except Exception as exc:
            result.status = "Browser-Verbindung verloren" if _browser_verloren(exc) else "Fehler"
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
        """CLI-Resume pro PDF-Sitzung; GUI behaelt die 24-h-Sperre."""
        validated = parse_fins("\n".join(fins), kurz_erlaubt=self.kurz_fin_erlaubt)
        progress = progress or (lambda message: None)
        cancel = cancel or Event()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        results_by_fin: dict[str, FinDownloadResult] = {}
        pending: list[str] = []
        for fin in validated:
            if self.retry_recent:
                previous = None
            elif self.nur_fehlende_pdfs:
                previous = _quicktest_fin_vollstaendig(self.output_dir, fin)
            else:
                previous = recently_attempted(self.output_dir, fin)
            if previous is None:
                pending.append(fin)
            else:
                results_by_fin[fin] = previous
                if self.nur_fehlende_pdfs:
                    progress(f"{fin}: PDF im FIN-Ordner vorhanden und Abrufstand vollstaendig – uebersprungen.")
                else:
                    progress(f"{fin}: letzter Abruf < 24 Stunden – übersprungen.")
        if not pending:
            progress(
                "Alle FINs sind laut lokalem Abrufstand bereits vollstaendig."
                if self.nur_fehlende_pdfs
                else "Alle FINs wurden innerhalb der letzten 24 Stunden bereits abgerufen."
            )
            return [results_by_fin[fin] for fin in validated]
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError("Playwright fehlt. Bitte die App mit Browser-Unterstützung installieren.") from exc
        progress(
            f"FIN {len(results_by_fin)}/{len(validated)} bereits erledigt (Resume)."
        )
        with sync_playwright() as playwright:
            def starte_edge():
                try:
                    context = playwright.chromium.launch_persistent_context(
                        user_data_dir=str(self.profile_dir),
                        channel="msedge",
                        headless=False,
                        accept_downloads=True,
                        no_viewport=True,
                    )
                    context._ntf_context_geschlossen = False
                    if hasattr(context, "on"):
                        context.on(
                            "close",
                            lambda: setattr(context, "_ntf_context_geschlossen", True),
                        )
                    return context
                except Exception as exc:
                    raise RuntimeError(
                        "Microsoft Edge konnte nicht gestartet werden. "
                        "Edge muss installiert sein und das NTF-Browserprofil darf "
                        "nicht von einem zweiten Programm verwendet werden. "
                        + str(exc)
                    ) from exc

            context = starte_edge()
            neustarts = 0
            try:
                page = context.pages[0] if context.pages else context.new_page()
                for fin in pending:
                    if cancel.is_set():
                        break
                    while True:
                        result, page = self._one_fin(
                            context, page, fin, progress, cancel,
                        )
                        if (
                            result.status not in ("Browser-Verbindung verloren", "Viewer-Tab geschlossen")
                            or neustarts >= 1 or cancel.is_set()
                        ):
                            break
                        # Einmaliger Wiederanlauf, lokale Sitzungs-PDFs werden
                        # ueber ihre Kennung weiterverwendet.
                        neustarts += 1
                        if result.status == "Viewer-Tab geschlossen" and _browser_verbunden(context):
                            progress(
                                f"{fin}: Nur Viewer-Tab geschlossen; "
                                "einmalig neues Tab oeffnen (kein Edge-Neustart)."
                            )
                            try:
                                page = context.new_page()
                                continue
                            except Exception:
                                pass
                        progress(
                            f"{fin}: Edge-Verbindung verloren. Einmaliger "
                            "Browserneustart; bereits gespeicherte PDFs bleiben erhalten. "
                            "PING ID ggf. erneut bestaetigen."
                        )
                        try:
                            context.close()
                        except Exception:
                            pass
                        try:
                            time.sleep(1)
                            context = starte_edge()
                            page = context.pages[0] if context.pages else context.new_page()
                        except Exception as exc:
                            result.status = "Fehler"
                            result.errors.append(
                                f"Automatischer Edge-Neustart fehlgeschlagen: {exc}"
                            )
                            _write_manifest(self.output_dir / fin, result)
                            progress(
                                f"{fin}: Edge-Neustart fehlgeschlagen. "
                                "Abrufstand gespeichert; spaeter fortsetzen."
                            )
                            break
                    results_by_fin[fin] = result
                    progress(
                        f"FIN-Fortschritt: {len(results_by_fin)}/{len(validated)} "
                        f"bearbeitet · zuletzt {fin}: {result.status}"
                    )
                    if result.status in (
                        "Abgebrochen", "Browser-Verbindung verloren",
                        "Viewer-Tab geschlossen", "PDF-Fenster ohne Download",
                    ):
                        break
                    if (
                        result.status == "Fehler"
                        and any("Edge-Neustart fehlgeschlagen" in e for e in result.errors)
                    ):
                        break
            finally:
                try:
                    context.close()
                except Exception:
                    pass
                self.password = ""
        return [results_by_fin[fin] for fin in validated if fin in results_by_fin]
