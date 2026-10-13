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
    read_last_attempt, recently_attempted, scan_local_quicktests,
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
