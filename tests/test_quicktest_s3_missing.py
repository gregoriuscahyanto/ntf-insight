"""Offline-Regressionen für fehlende S3-QuickTests und PDF-Timeouts.

Es werden weder das Mercedes-Intranet noch Anmeldedaten benötigt.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest

from ntf_insight.acquisition.diagnosis_viewer import (
    DiagnosisViewerDownloader,
    DownloadCancelled,
    DownloadRow,
    NO_QUICKTEST_DATA_MESSAGE,
    QuickTestDataUnavailable,
    read_last_attempt,
)

FIN = "WDD12345678901234"


class FakeDownload:
    suggested_filename = "bericht.pdf"

    def failure(self):
        return None

    def save_as(self, path):
        Path(path).write_bytes(b"%PDF-1.7\nsynthetischer QuickTest")


class FakeToast:
    def __init__(self, page):
        self.page = page
        self.first = self

    def count(self):
        return int(self.page.visible)

    def is_visible(self):
        return self.page.visible


class FakeDialog:
    def __init__(self, message):
        self.message = message
        self.dismissed = False

    def dismiss(self):
        self.dismissed = True


class FakePage:
    """Minimal Playwright-Double mit echtem Zeitablauf für Timeout-Tests."""

    def __init__(self, kind, *, stale_toast=False):
        self.kind = kind
        self.visible = stale_toast
        self.observed = False
        self.watching = False
        self.handlers = {"download": [], "dialog": []}
        self.wait_count = 0
        self.dialog = None

    def on(self, event, callback):
        self.handlers[event].append(callback)

    def remove_listener(self, event, callback):
        self.handlers[event].remove(callback)

    def evaluate(self, script, arg=None):
        if "delete window[key]" in script:
            self.watching = False
            return None
        if "const key = '__ntfInsightQuicktestS3Watcher'" in script:
            self.watching = True
            self.observed = False
            return None
        if "() => Boolean(window.__ntfInsightQuicktestS3Watcher?.matched)" in script:
            return self.observed
        raise AssertionError("Unbekannter Javascript-Ausdruck")

    def get_by_text(self, message, exact=False):
        assert message == NO_QUICKTEST_DATA_MESSAGE
        assert not exact
        return FakeToast(self)

    def wait_for_timeout(self, milliseconds):
        self.wait_count += 1
        if self.wait_count == 1:
            if self.kind == "s3-toast":
                self.visible = True
                if self.watching:
                    self.observed = True
            elif self.kind == "native-dialog":
                self.dialog = FakeDialog(NO_QUICKTEST_DATA_MESSAGE)
                for callback in list(self.handlers["dialog"]):
                    callback(self.dialog)
            elif self.kind == "download":
                for callback in list(self.handlers["download"]):
                    callback(FakeDownload())
        if self.kind == "timeout":
            time.sleep(milliseconds / 1000)


class FakeIcon:
    def __init__(self):
        self.clicked = 0

    def click(self, **kwargs):
        self.clicked += 1


def _downloader(tmp_path, seconds=0.07):
    return DiagnosisViewerDownloader(
        tmp_path / "quicktests", tmp_path / "edge",
        pdf_timeout_seconds=seconds, action_interval_seconds=0,
    )


def test_default_pdf_timeout_is_one_minute(tmp_path):
    downloader = DiagnosisViewerDownloader(tmp_path, tmp_path / "edge")
    assert downloader.pdf_timeout_seconds == 60


@pytest.mark.parametrize("kind", ["s3-toast", "native-dialog"])
def test_missing_s3_payload_skips_immediately_without_waiting_for_timeout(tmp_path, kind):
    downloader = _downloader(tmp_path)
    page = FakePage(kind)
    icon = FakeIcon()
    before = time.monotonic()
    with pytest.raises(QuickTestDataUnavailable, match="Diagnosis payload loaded"):
        downloader._download_or_skip(page, icon, Event())
    assert time.monotonic() - before < 0.5
    assert icon.clicked == 1
    assert not page.handlers["download"] and not page.handlers["dialog"]
    assert not page.watching
    if page.dialog is not None:
        assert page.dialog.dismissed


def test_stale_s3_message_does_not_skip_next_valid_download(tmp_path):
    page = FakePage("download", stale_toast=True)
    download = _downloader(tmp_path)._download_or_skip(page, FakeIcon(), Event())
    assert isinstance(download, FakeDownload)
    assert not page.handlers["download"]


def test_pdf_timeout_moves_on_after_configured_interval(tmp_path):
    downloader = _downloader(tmp_path, seconds=0.045)
    page = FakePage("timeout")
    start = time.monotonic()
    with pytest.raises(TimeoutError, match="kein PDF-Download gestartet"):
        downloader._download_or_skip(page, FakeIcon(), Event())
    elapsed = time.monotonic() - start
    assert 0.03 <= elapsed < 0.8
    assert not page.handlers["download"]


def test_cancellation_during_download_wait_is_propagated(tmp_path):
    cancel = Event()
    page = FakePage("timeout")

    def stop_on_wait(milliseconds):
        cancel.set()

    page.wait_for_timeout = stop_on_wait
    with pytest.raises(DownloadCancelled):
        _downloader(tmp_path)._download_or_skip(page, FakeIcon(), cancel)


class FakeViewerPage:
    """Only the interfaces needed by _one_fin are faked."""

    def goto(self, *args, **kwargs):
        return None

    def locator(self, selector):
        if selector == 'input[name="finVin"]':
            return SimpleNamespace(fill=lambda vin: None)
        assert selector == "tbody tr"
        return SimpleNamespace(nth=lambda i: SimpleNamespace(
            locator=lambda css: SimpleNamespace(first=FakeIcon())
        ))

    def get_by_role(self, *args, **kwargs):
        return SimpleNamespace(click=lambda **kw: None)


def test_one_fin_skips_s3_then_timeout_then_downloads_next_pdf(tmp_path, monkeypatch):
    downloader = _downloader(tmp_path, seconds=0.05)
    page = FakeViewerPage()
    monkeypatch.setattr(downloader, "_login", lambda context, page, progress, cancel: page)
    monkeypatch.setattr(downloader, "_wait_results", lambda page, cancel, fin: [
        DownloadRow(i, "TD", f"2026-10-13 10:0{i}:00") for i in range(3)
    ])
    attempted = []

    def next_session(page, icon, cancel):
        attempted.append(len(attempted))
        if len(attempted) == 1:
            raise QuickTestDataUnavailable(NO_QUICKTEST_DATA_MESSAGE)
        if len(attempted) == 2:
            raise TimeoutError("Test-Timeout")
        return FakeDownload()

    monkeypatch.setattr(downloader, "_download_or_skip", next_session)
    progress = []
    result, returned_page = downloader._one_fin(None, page, FIN, progress.append, Event())
    assert returned_page is page
    assert attempted == [0, 1, 2]
    assert result.status == "Teilweise erfolgreich"
    assert len(result.files) == 1 and result.files[0].is_file()
    assert len(result.no_quicktest_sessions) == 1
    assert len(result.errors) == 1
    assert "Timeout nach 0.05 Sekunden" in result.errors[0]
    assert any("übersprungen" in message for message in progress)
    assert any("nächste Sitzung" in message for message in progress)

    manifest = json.loads(
        (tmp_path / "quicktests" / FIN / "abrufstatus.json").read_text(encoding="utf-8")
    )
    assert len(manifest["ohne_quicktest"]) == 1
    assert len(manifest["fehler"]) == 1
    assert len(manifest["pdf_dateien"]) == 1
    stored = read_last_attempt(tmp_path / "quicktests", FIN)
    assert len(stored.no_quicktest_sessions) == 1


def test_one_fin_all_s3_missing_is_not_a_download_error(tmp_path, monkeypatch):
    downloader = _downloader(tmp_path)
    page = FakeViewerPage()
    monkeypatch.setattr(downloader, "_login", lambda context, page, progress, cancel: page)
    monkeypatch.setattr(downloader, "_wait_results", lambda page, cancel, fin: [
        DownloadRow(0, "XD", "2026-10-13 11:00:00")
    ])
    def missing(page, icon, cancel):
        raise QuickTestDataUnavailable(NO_QUICKTEST_DATA_MESSAGE)
    monkeypatch.setattr(downloader, "_download_or_skip", missing)
    result, _ = downloader._one_fin(None, page, FIN, lambda message: None, Event())
    assert result.status == "Keine Quicktests"
    assert result.errors == []
    assert len(result.no_quicktest_sessions) == 1
