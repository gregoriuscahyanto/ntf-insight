"""Offline-Tests fuer den Edge-Diagnosis-Viewer-Abruf (ohne SSO-Zugriff)."""

import json
import sys
import time
from threading import Event
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from ntf_insight.acquisition.diagnosis_viewer import (
    DIAGNOSIS_VIEWER, DownloadRow, FinDownloadResult,
    _save_pdf, _visible_rows, _write_manifest, parse_fins, search_url,
    DiagnosisViewerDownloader, DownloadCancelled, format_last_attempt,
    read_last_attempt, recently_attempted, scan_local_quicktests, lokal_vorhandene_pdf,
    ViewerTabClosed, BrowserSessionLost, QuickTestPopupOhneDownload,
)

from ntf_insight.acquisition.credentials import (
    LoginCredentials, clear_saved_credentials, load_saved_credentials, save_credentials,
)

FIN = "WDD12345678901234"


def test_fin_validation_and_deduplication():
    assert parse_fins(f"{FIN.lower()}; {FIN}") == [FIN]
    with pytest.raises(ValueError):
        parse_fins("123")
    with pytest.raises(ValueError):
        parse_fins("WDD1234567890O234")


def test_source_url_matches_reference():
    assert search_url(FIN) == (
        f"{DIAGNOSIS_VIEWER}?fin={FIN}&sources=XD%2CXD%28AQT%29%2CTD%2CDAS"
    )


class FakeDownload:
    suggested_filename = "quicktest.pdf"

    def __init__(self, content):
        self.content = content

    def save_as(self, filename):
        Path(filename).write_bytes(self.content)


def test_pdf_verified_and_deduplicated(tmp_path):
    row = DownloadRow(0, "XD", "2026-10-12 12:00:00")
    first = _save_pdf(FakeDownload(b"%PDF-1.7\nTest A"), tmp_path / FIN, row)
    assert first.is_file()
    assert _save_pdf(FakeDownload(b"%PDF-1.7\nTest A"), tmp_path / FIN, row) == first
    assert _save_pdf(FakeDownload(b"%PDF-1.7\nTest B"), tmp_path / FIN, row) != first
    with pytest.raises(ValueError):
        _save_pdf(FakeDownload(b"<html>Login</html>"), tmp_path / FIN, row)


class Locator:
    def __init__(self, items):
        self.items = items

    def count(self):
        return len(self.items)

    def nth(self, i):
        return self.items[i]


class Row:
    def __init__(self, columns, clickable):
        self.columns = columns
        self.clickable = clickable

    def inner_text(self):
        return " ".join(self.columns)

    def locator(self, selector):
        if selector == "td":
            return Locator([SimpleNamespace(inner_text=lambda x=value: x) for value in self.columns])
        if selector == "span.cursor-pointer:has(svg.lucide-file-down)":
            return Locator([object()] if self.clickable else [])
        raise AssertionError(selector)


class Page:
    def __init__(self, rows):
        self.rows = rows

    def locator(self, selector):
        assert selector == "tbody tr"
        return Locator(self.rows)


def test_only_active_download_icons_are_selected():
    columns = ["XD", "2026-10-12 12:00:00", "", FIN, FIN, "123", "3", "", "200", "", ""]
    rows, empty = _visible_rows(Page([Row(columns, True), Row(columns, False)]))
    assert rows == [DownloadRow(0, "XD", "2026-10-12 12:00:00")]
    assert empty is False
    assert _visible_rows(Page([Row(["No Results Found"], False)])) == ([], True)


def test_manifest_is_fin_scoped(tmp_path):
    result = FinDownloadResult(fin=FIN, status="Keine Quicktests")
    _write_manifest(tmp_path / FIN, result)
    metadata = json.loads((tmp_path / FIN / "abrufstatus.json").read_text(encoding="utf-8"))
    assert metadata["fin"] == FIN
    assert metadata["status"] == "Keine Quicktests"
    assert metadata["pdf_dateien"] == []



def test_recent_24h_attempt_skipped_even_if_failed(tmp_path):
    attempt = (datetime.now(timezone.utc) - timedelta(hours=23)).isoformat()
    result = FinDownloadResult(fin=FIN, status="Fehler", last_attempt_at=attempt)
    _write_manifest(tmp_path / FIN, result)
    skipped = recently_attempted(tmp_path, FIN)
    assert skipped is not None
    assert skipped.status.startswith("Übersprungen")
    assert skipped.last_attempt_at == attempt
    assert DiagnosisViewerDownloader(tmp_path, tmp_path / "edge-profile").run([FIN])[0].status.startswith(
        "Übersprungen"
    )
    # A skipped FIN does not start Edge or create an empty Edge profile.
    assert not (tmp_path / "edge-profile").exists()
    assert format_last_attempt(attempt) != "Noch kein Abruf"


def test_24h_expired_is_not_skipped(tmp_path):
    previous = FinDownloadResult(
        fin=FIN, status="Erfolgreich",
        last_attempt_at=(datetime.now(timezone.utc) - timedelta(hours=25)).isoformat(),
    )
    _write_manifest(tmp_path / FIN, previous)
    assert recently_attempted(tmp_path, FIN) is None
    assert read_last_attempt(tmp_path, FIN).status == "Erfolgreich"


def test_untrusted_json_path_cannot_escape_fin_folder(tmp_path):
    root = tmp_path / FIN
    root.mkdir()
    (tmp_path / "outside.pdf").write_bytes(b"%PDF-")
    (root / "abrufstatus.json").write_text(
        json.dumps({
            "fin": FIN, "stand_utc": datetime.now(timezone.utc).isoformat(),
            "pdf_dateien": ["../outside.pdf"], "status": "Erfolgreich"
        }), encoding="utf-8"
    )
    assert read_last_attempt(tmp_path, FIN).files == []


class Field:
    def __init__(self, visible=False):
        self.visible = visible
        self.filled = ""
        self.clicked = 0

    def count(self):
        return 1

    def is_visible(self):
        return self.visible

    def fill(self, value):
        self.filled = value

    def click(self, **kwargs):
        self.clicked += 1


class LoginPage:
    def __init__(self, url):
        self.url = url
        self.fields = {
            "#userid": Field(visible=True),
            "#next-btn": Field(visible=True),
            "#password": Field(visible=False),
            "#loginSubmitButton": Field(visible=False),
            "#c-s-bn": Field(visible=False),
        }

    def locator(self, selector):
        return self.fields[selector]


def test_ssologin_enters_id_and_password_once_and_never_logs_password(tmp_path):
    downloader = DiagnosisViewerDownloader(
        tmp_path, tmp_path / "profile",
        user_id="test-uid", password="secret-value",
    )
    page = LoginPage("https://login.mercedes-benz.com/example")
    done = {"user": False, "password": False}
    messages = []
    downloader._enter_credentials(page, done, messages.append)
    assert page.fields["#userid"].filled == "test-uid"
    assert page.fields["#next-btn"].clicked == 1
    page.fields["#userid"].visible = False
    page.fields["#password"].visible = True
    downloader._enter_credentials(page, done, messages.append)
    downloader._enter_credentials(page, done, messages.append)
    assert page.fields["#password"].filled == "secret-value"
    assert page.fields["#loginSubmitButton"].clicked == 1
    assert done == {"user": True, "password": True}
    assert not any("secret-value" in item for item in messages)
    # Never autofill credentials on similar-looking, untrusted domains.
    spoofed = LoginPage("https://login.mercedes-benz.com.attack.invalid")
    downloader._enter_credentials(spoofed, {"user": False, "password": False}, messages.append)
    assert not spoofed.fields["#userid"].filled
    assert not downloader._is_login_host("http://login.mercedes-benz.com")


def test_credentials_are_stored_only_in_mocked_keyring(monkeypatch):
    storage = {}
    ring = SimpleNamespace(
        get_keyring=lambda: SimpleNamespace(priority=10),
        get_password=lambda name, account: storage.get((name, account)),
        set_password=lambda name, account, pw: storage.__setitem__((name, account), pw),
        delete_password=lambda name, account: storage.pop((name, account), None),
    )
    monkeypatch.setitem(sys.modules, "keyring", ring)
    assert load_saved_credentials() is None
    save_credentials("uid", "pw")
    assert load_saved_credentials() == LoginCredentials("uid", "pw")
    clear_saved_credentials()
    assert load_saved_credentials() is None



def test_local_inventory_includes_all_fins_and_legacy_pdfs(tmp_path):
    """Older FIN folders without JSON manifests must appear in the GUI."""
    second_fin = "WDD12345678901235"
    (tmp_path / FIN).mkdir()
    (tmp_path / FIN / "one.pdf").write_bytes(b"%PDF-1.7\nLegacy")
    _write_manifest(
        tmp_path / FIN,
        FinDownloadResult(
            fin=FIN, status="Erfolgreich",
            last_attempt_at="2026-10-12T08:20:00+00:00",
        ),
    )
    (tmp_path / second_fin).mkdir()
    (tmp_path / second_fin / "two.pdf").write_bytes(b"%PDF-1.7\nPDF2")
    (tmp_path / second_fin / "THREE.PDF").write_bytes(b"%PDF-1.7\nPDF3")
    (tmp_path / "not-a-fin").mkdir()
    (tmp_path / "not-a-fin" / "junk.pdf").write_bytes(b"%PDF-1.7")

    inventory = scan_local_quicktests(tmp_path)
    assert [entry.fin for entry in inventory] == [FIN, second_fin]
    assert [len(entry.files) for entry in inventory] == [1, 2]
    assert inventory[0].status == "Erfolgreich"
    assert inventory[1].status == "PDFs lokal (ohne Abrufprotokoll)"
    assert inventory[1].last_attempt_at == ""
    assert recently_attempted(tmp_path, second_fin) is None


def test_action_pacing_is_fixed_and_interruptible(tmp_path):
    downloader = DiagnosisViewerDownloader(
        tmp_path, tmp_path / "edge", action_interval_seconds=0.03
    )
    assert downloader.action_interval_seconds == 0.03
    downloader._pace()
    before = time.monotonic()
    downloader._pace()
    assert time.monotonic() - before >= 0.028
    stopped = Event()
    stopped.set()
    with pytest.raises(DownloadCancelled):
        downloader._pace(stopped)



def test_search_waits_for_rows_from_requested_fin(tmp_path):
    second = "WDD12345678901235"
    def columns(fin):
        return ["TD", "2026-10-12 10:00", "", fin, fin, "167", "1", "", "2000", "", ""]
    class ChangingPage(Page):
        def __init__(self):
            super().__init__([Row(columns(FIN), True)])
            self.waits = 0

        def wait_for_timeout(self, milliseconds):
            self.waits += 1
            self.rows = [Row(columns(second), True)]

    downloader = DiagnosisViewerDownloader(
        tmp_path, tmp_path / "profile", result_timeout_seconds=3
    )
    page = ChangingPage()
    selected = downloader._wait_results(page, Event(), second)
    assert len(selected) == 1
    assert page.waits == 1



KURZ_FIN = "1671061B000001"
VOLL_FIN = "W1N" + KURZ_FIN


def test_kurz_fin_ist_nur_auf_ausdruecklichen_opt_in_zulaessig():
    assert parse_fins(KURZ_FIN, kurz_erlaubt=True) == [KURZ_FIN]
    assert parse_fins(KURZ_FIN.lower() + ", " + KURZ_FIN, kurz_erlaubt=True) == [KURZ_FIN]
    with pytest.raises(ValueError, match="17"):
        parse_fins(KURZ_FIN)
    with pytest.raises(ValueError, match="17"):
        search_url(KURZ_FIN)
    assert search_url(KURZ_FIN, kurz_erlaubt=True).startswith(
        f"{DIAGNOSIS_VIEWER}?fin={KURZ_FIN}&"
    )


def test_kurz_fin_mit_vollfin_in_diagnoseergebnissen_vergleichen(tmp_path):
    def spalten(fin):
        return ["XD", "2026-10-12 12:00", "", fin, fin, "123", "3", "", "200", "", ""]
    downloader = DiagnosisViewerDownloader(
        tmp_path, tmp_path / "profile", kurz_fin_erlaubt=True,
    )
    angefragt = Page([
        Row(spalten("W1N1671061B000002"), True),  # Anderes Fahrzeug
        Row(spalten(VOLL_FIN), True),
        Row(spalten("W1N1671061B000003"), True),
    ])
    ausgewaehlt = downloader._wait_results(angefragt, Event(), KURZ_FIN)
    assert [row.position for row in ausgewaehlt] == [1]


def test_kurz_fin_mehrdeutige_17stellige_treffer_abweisen(tmp_path):
    def spalten(fin):
        return ["XD", "2026-10-12 12:00", "", fin, fin, "123", "3", "", "200", "", ""]
    downloader = DiagnosisViewerDownloader(
        tmp_path, tmp_path / "profile", kurz_fin_erlaubt=True,
    )
    seite = Page([
        Row(spalten(VOLL_FIN), True),
        Row(spalten("WDD" + KURZ_FIN), True),
    ])
    with pytest.raises(ValueError, match="mehrdeutig"):
        downloader._wait_results(seite, Event(), KURZ_FIN)


def test_kurz_fin_im_lokalen_quicktest_bestand_sichtbar(tmp_path):
    (tmp_path / KURZ_FIN).mkdir()
    (tmp_path / KURZ_FIN / "quicktest.pdf").write_bytes(b"%PDF-1.7\nTest")
    results = scan_local_quicktests(tmp_path)
    assert [x.fin for x in results] == [KURZ_FIN]
    assert len(results[0].files) == 1


def test_downloader_run_kurz_fin_beharrt_auf_optin_ohne_browser(tmp_path):
    with pytest.raises(ValueError, match="17"):
        DiagnosisViewerDownloader(tmp_path, tmp_path / "edge").run([KURZ_FIN])
    result = FinDownloadResult(
        fin=KURZ_FIN,
        status="Erfolgreich",
        last_attempt_at=datetime.now(timezone.utc).isoformat(),
    )
    _write_manifest(tmp_path / KURZ_FIN, result)
    daten = DiagnosisViewerDownloader(
        tmp_path, tmp_path / "edge", kurz_fin_erlaubt=True,
    ).run([KURZ_FIN])
    assert daten[0].status.startswith("Übersprungen")
    assert not (tmp_path / "edge").exists()



def test_cli_ueberspringt_nur_pdf_in_exaktem_fin_ordner(tmp_path):
    fin_dir = tmp_path / FIN
    fin_dir.mkdir()
    status = FinDownloadResult(
        fin=FIN, status="Fehler",
        last_attempt_at=datetime.now(timezone.utc).isoformat(),
    )
    _write_manifest(fin_dir, status)
    assert recently_attempted(tmp_path, FIN) is not None  # Alte GUI-Regel weiterhin aktiv
    assert lokal_vorhandene_pdf(tmp_path, FIN) is None  # CLI startet erneut
    (fin_dir / "dummy.pdf").write_bytes(b"<html>SSO abgelaufen</html>")
    assert lokal_vorhandene_pdf(tmp_path, FIN) is None
    (fin_dir / "partial.pdf").write_bytes(b"")
    assert lokal_vorhandene_pdf(tmp_path, FIN) is None
    (tmp_path / "andere-fahrzeuge").mkdir()
    (tmp_path / "andere-fahrzeuge" / "fremd.pdf").write_bytes(b"%PDF-1.7\nTest")
    assert lokal_vorhandene_pdf(tmp_path, FIN) is None
    original = fin_dir / "quicktest.pdf"
    original.write_bytes(b"%PDF-1.7\nOffline-Test")
    gefunden = lokal_vorhandene_pdf(tmp_path, FIN)
    assert gefunden is not None
    assert gefunden.files == [original]
    assert "PDF bereits vorhanden" in gefunden.status
    assert lokal_vorhandene_pdf(tmp_path, "WDD12345678901235") is None


def test_cli_ueberspringt_vorhandene_pdf_auch_nach_mehr_als_24_stunden(tmp_path):
    fin_dir = tmp_path / FIN
    alt = datetime.now(timezone.utc) - timedelta(days=7)
    _write_manifest(
        fin_dir,
        FinDownloadResult(fin=FIN, status="Fehler", last_attempt_at=alt.isoformat()),
    )
    (fin_dir / "diagnose.PDF").write_bytes(b"%PDF-1.7\nPDF-Test")
    assert recently_attempted(tmp_path, FIN) is None
    aufrufe = []
    downloader = DiagnosisViewerDownloader(
        tmp_path, tmp_path / "edge", nur_fehlende_pdfs=True,
    )
    result = downloader.run([FIN], progress=aufrufe.append)
    assert result[0].files == [fin_dir / "diagnose.PDF"]
    assert "PDF bereits vorhanden" in result[0].status
    assert not (tmp_path / "edge").exists()
    assert any("PDF im FIN-Ordner vorhanden" in s for s in aufrufe)


def test_cli_versucht_neu_bei_24h_status_ohne_pdf_ohne_echten_browser(
    tmp_path, monkeypatch,
):
    import sys
    from types import ModuleType

    status = FinDownloadResult(
        fin=FIN, status="Fehler",
        last_attempt_at=datetime.now(timezone.utc).isoformat(),
    )
    _write_manifest(tmp_path / FIN, status)
    called = []

    class Kontext:
        pages = [object()]

        def close(self):
            pass

    class Manager:
        def __enter__(self):
            return SimpleNamespace(chromium=SimpleNamespace(
                launch_persistent_context=lambda **kwargs: Kontext(),
            ))

        def __exit__(self, *_args):
            return False

    sync_api = ModuleType("playwright.sync_api")
    sync_api.sync_playwright = lambda: Manager()
    monkeypatch.setitem(sys.modules, "playwright.sync_api", sync_api)
    downloader = DiagnosisViewerDownloader(
        tmp_path, tmp_path / "edge", nur_fehlende_pdfs=True,
    )

    def one_fin(context, page, fin, progress, cancel):
        called.append(fin)
        return FinDownloadResult(fin=fin, status="Keine Quicktests"), page

    monkeypatch.setattr(downloader, "_one_fin", one_fin)
    results = downloader.run([FIN])
    assert called == [FIN]
    assert len(results) == 1
    assert results[0].status == "Keine Quicktests"


def test_pdf_check_schliesst_symlinks_aus(tmp_path):
    ziel = tmp_path / "source.pdf"
    ziel.write_bytes(b"%PDF-1.7\nTest")
    folder = tmp_path / FIN
    folder.mkdir()
    try:
        (folder / "alias.pdf").symlink_to(ziel)
    except (NotImplementedError, OSError):
        pytest.skip("Windows-Testsystem erlaubt keine Symlinks")
    assert lokal_vorhandene_pdf(tmp_path, FIN) is None



def test_quicktest_ping_sperre_vor_portal_navigation_und_nicht_waehrend_download(
    tmp_path, monkeypatch,
):
    from contextlib import contextmanager

    import ntf_insight.acquisition.diagnosis_viewer as backend

    reihenfolge = []

    @contextmanager
    def gate(*, status, abbruch):
        reihenfolge.append("sso-lock")
        yield
        reihenfolge.append("sso-unlock")

    class FakeField:
        def fill(self, value):
            reihenfolge.append("fin-suchfeld")

        def click(self, **kwargs):
            reihenfolge.append("search")

    class FakePage:
        def goto(self, url, **kwargs):
            reihenfolge.append("goto")

        def locator(self, selector):
            return FakeField()

        def get_by_role(self, *args, **kwargs):
            return FakeField()

    monkeypatch.setattr(backend, "serielle_sso_anmeldung", gate)
    downloader = DiagnosisViewerDownloader(
        tmp_path, tmp_path / "profile", serielle_sso=True, action_interval_seconds=0,
    )
    page = FakePage()

    def login(context, seite, progress, cancel):
        reihenfolge.append("login")
        return seite

    def results(seite, cancel, fin):
        reihenfolge.append("results")
        return []

    monkeypatch.setattr(downloader, "_login", login)
    monkeypatch.setattr(downloader, "_wait_results", results)
    result, _ = downloader._one_fin(
        SimpleNamespace(), page, FIN, lambda _: None, Event(),
    )
    assert result.status == "Keine Quicktests"
    assert reihenfolge == [
        "sso-lock", "goto", "login", "sso-unlock",
        "fin-suchfeld", "search", "results",
    ]



class _Events:
    def __init__(self):
        self.listeners = {}

    def on(self, event, callback):
        self.listeners.setdefault(event, []).append(callback)

    def remove_listener(self, event, callback):
        if callback in self.listeners.get(event, []):
            self.listeners[event].remove(callback)

    def emit(self, event, item):
        for callback in list(self.listeners.get(event, [])):
            callback(item)


class _PdfContext(_Events):
    def __init__(self):
        super().__init__()
        self.browser = SimpleNamespace(is_connected=lambda: True)


class _PdfPage(_Events):
    def __init__(self, context, opener=None):
        super().__init__()
        self.context = context
        self._opener = opener
        self.closed = False

    def opener(self):
        return self._opener

    def is_closed(self):
        return self.closed

    def wait_for_timeout(self, ms):
        time.sleep(ms / 1000)


def _offline_download_dl(tmp_path, monkeypatch):
    dl = DiagnosisViewerDownloader(
        tmp_path, tmp_path / "profil", action_interval_seconds=0,
        pdf_timeout_seconds=0.12,
    )
    monkeypatch.setattr(dl, "_watch_no_quicktest_message", lambda _: False)
    monkeypatch.setattr(dl, "_no_quicktest_visible", lambda _: False)
    monkeypatch.setattr(dl, "_no_quicktest_observed", lambda _: False)
    return dl


def test_popup_pdf_download_wird_im_neuen_tab_statt_nur_im_haupttab_erfasst(
    tmp_path, monkeypatch,
):
    dl = _offline_download_dl(tmp_path, monkeypatch)
    context = _PdfContext()
    viewer = _PdfPage(context)
    popup = _PdfPage(context, viewer)
    download = FakeDownload(b"%PDF-1.7\nTest")
    calls = []

    class Icon:
        def click(self, **_kwargs):
            # Auch wenn context.page vor page.popup geliefert wird, darf
            # der Popup-Download nur einmal erfasst werden.
            context.emit("page", popup)
            viewer.emit("popup", popup)
            popup.emit("download", download)
            calls.append("clicked")

    result = dl._download_or_skip(
        viewer, Icon(), Event(), progress=calls.append,
    )
    assert result is download
    assert any("Neues PDF-Fenster" in msg for msg in calls)
    assert len(popup.listeners["download"]) == 0
    assert len(viewer.listeners["download"]) == 0
    assert len(context.listeners["page"]) == 0
    target = _save_pdf(result, tmp_path / FIN, DownloadRow(0, "XD", "2026-11-18"))
    assert target.is_file()


def test_popup_vorschau_ohne_download_wird_als_eigener_fehler_erkannt(
    tmp_path, monkeypatch,
):
    dl = _offline_download_dl(tmp_path, monkeypatch)
    context = _PdfContext()
    viewer = _PdfPage(context)
    popup = _PdfPage(context, viewer)

    class Icon:
        def click(self, **_kwargs):
            viewer.emit("popup", popup)

    with pytest.raises(QuickTestPopupOhneDownload, match="kein Download gestartet"):
        dl._download_or_skip(viewer, Icon(), Event())
    assert not viewer.listeners["popup"]
    assert not popup.listeners["download"]


def test_geschlossenes_viewer_tab_ist_nicht_zwangslaeufig_edge_absturz(
    tmp_path, monkeypatch,
):
    dl = _offline_download_dl(tmp_path, monkeypatch)
    viewer = _PdfPage(_PdfContext())

    class Icon:
        def click(self, **_kwargs):
            viewer.closed = True
            raise RuntimeError("Target page, context or browser has been closed")

    with pytest.raises(ViewerTabClosed, match="Edge noch verbunden"):
        dl._download_or_skip(viewer, Icon(), Event())


def test_browser_disconnect_wird_weiterhin_als_echter_verbindungsverlust_erkannt(
    tmp_path, monkeypatch,
):
    dl = _offline_download_dl(tmp_path, monkeypatch)
    context = _PdfContext()
    viewer = _PdfPage(context)
    context.browser = SimpleNamespace(is_connected=lambda: False)

    class Icon:
        def click(self, **_kwargs):
            pass

    with pytest.raises(BrowserSessionLost, match="Edge-Verbindung"):
        dl._download_or_skip(viewer, Icon(), Event())



def test_quicktest_pdf_popup_inline_antwort_schon_vor_popup_event_erfasst(
    tmp_path, monkeypatch,
):
    """Fruehe PDF-Response ist schon da, bevor Playwright das Popup meldet."""
    dl = _offline_download_dl(tmp_path, monkeypatch)
    context = _PdfContext()
    viewer = _PdfPage(context)
    popup = _PdfPage(context, viewer)
    content = b"%PDF-1.7\nInline-QuickTest synthetisch"
    url = "https://app.diagviewer.prod.gspp-eu.cloud.corpintra.net/file/quicktest.pdf"
    response = SimpleNamespace(
        url=url, headers={"content-type": "application/pdf"},
        request=SimpleNamespace(frame=SimpleNamespace(page=popup)),
        body=lambda: content,
    )
    messages = []

    class Icon:
        def click(self, **_kwargs):
            context.emit("response", response)  # Antwort vor Popup-Event
            context.emit("page", popup)
            viewer.emit("popup", popup)

    download = dl._download_or_skip(
        viewer, Icon(), Event(), progress=messages.append,
    )
    assert download.suggested_filename == "QuickTest.pdf"
    assert download.failure() is None
    target = _save_pdf(download, tmp_path / FIN, DownloadRow(0, "XD", "2026-11-18"))
    assert target.read_bytes() == content
    assert any("Browser-Netzwerkantwort" in line for line in messages)
    assert context.listeners["response"] == []


def test_quicktest_pdf_popup_ohne_download_event_per_same_origin_get(
    tmp_path, monkeypatch,
):
    """Offizieller Edge-PDF-Viewer zeigt nur Vorschau, aber gleiche URL liefert PDF."""
    dl = _offline_download_dl(tmp_path, monkeypatch)
    context = _PdfContext()
    viewer = _PdfPage(context)
    popup = _PdfPage(context, viewer)
    popup.url = "https://app.diagviewer.prod.gspp-eu.cloud.corpintra.net/quicktest.pdf"
    calls = []
    pdf_bytes = b"%PDF-1.7\nProxy QuickTest"
    api_response = SimpleNamespace(
        status=200, headers={"content-type": "application/pdf"},
        body=lambda: pdf_bytes,
    )

    class Request:
        def get(self, url, *, timeout, max_redirects):
            calls.append((url, max_redirects))
            return api_response

    context.request = Request()

    class Icon:
        def click(self, **_kwargs):
            viewer.emit("popup", popup)

    messages = []
    download = dl._download_or_skip(
        viewer, Icon(), Event(), progress=messages.append,
    )
    saved = _save_pdf(download, tmp_path / FIN, DownloadRow(0, "XD", "2026-11-18"))
    assert saved.read_bytes() == pdf_bytes
    assert calls == [(popup.url, 0)]
    assert any("angemeldeter Sitzung" in line for line in messages)


def test_quicktest_popup_mit_pdf_antwort_wird_trotz_abgebrochenem_click_gerettet(
    tmp_path, monkeypatch,
):
    """Eine schliessende PDF-Vorschau darf bereits vorhandene Nutzdaten nicht verwerfen."""
    dl = _offline_download_dl(tmp_path, monkeypatch)
    context = _PdfContext()
    viewer = _PdfPage(context)
    popup = _PdfPage(context, viewer)
    content = b"%PDF-1.7\nSchon im Netzwerk angekommen"
    response = SimpleNamespace(
        url="https://app.diagviewer.prod.gspp-eu.cloud.corpintra.net/file.pdf",
        headers={"content-type": "application/pdf"},
        request=SimpleNamespace(frame=SimpleNamespace(page=popup)),
        body=lambda: content,
    )

    class Icon:
        def click(self, **_kwargs):
            context.emit("response", response)
            viewer.emit("popup", popup)
            raise RuntimeError("Target page, context or browser has been closed")

    download = dl._download_or_skip(viewer, Icon(), Event())
    assert download.failure() is None
    assert _save_pdf(
        download, tmp_path / FIN, DownloadRow(0, "XD", "2026-11-18"),
    ).read_bytes() == content


def test_popup_html_aus_login_redirect_wird_nicht_als_pdf_gespeichert(
    tmp_path, monkeypatch,
):
    dl = _offline_download_dl(tmp_path, monkeypatch)
    context = _PdfContext()
    viewer = _PdfPage(context)
    popup = _PdfPage(context, viewer)
    popup.url = "https://app.diagviewer.prod.gspp-eu.cloud.corpintra.net/report"
    response = SimpleNamespace(
        status=200, headers={"content-type": "text/html"},
        body=lambda: b"<html>Login</html>",
    )
    context.request = SimpleNamespace(get=lambda *a, **kw: response)

    class Icon:
        def click(self, **_kwargs):
            viewer.emit("popup", popup)

    with pytest.raises(QuickTestPopupOhneDownload, match="kein Download gestartet"):
        dl._download_or_skip(viewer, Icon(), Event())


def test_persistenter_edge_context_close_event_ist_echter_verbindungsverlust(
    tmp_path, monkeypatch,
):
    """BrowserContext.browser ist bei launch_persistent_context haeufig None."""
    dl = _offline_download_dl(tmp_path, monkeypatch)
    context = _PdfContext()
    context.browser = None
    context._ntf_context_geschlossen = False
    viewer = _PdfPage(context)

    class Icon:
        def click(self, **_kwargs):
            context._ntf_context_geschlossen = True
            raise RuntimeError("Target page, context or browser has been closed")

    with pytest.raises(BrowserSessionLost, match="Kontext"):
        dl._download_or_skip(viewer, Icon(), Event())
