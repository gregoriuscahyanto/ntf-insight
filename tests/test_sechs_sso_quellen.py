"""Offline: SSO/PING-ID-Sperre auch fuer QEC, TIPS, WEM und VeDoc-SA."""

from __future__ import annotations

import argparse
import sys
from contextlib import contextmanager
from threading import Event
from types import ModuleType, SimpleNamespace

import pytest

from ntf_insight.acquisition import qec_tool, tips_writer, vedoc_codes
from scripts import diagnosis_viewer_warn_error as wem


def _gate_und_browserfolge(monkeypatch, modul):
    reihenfolge = []

    @contextmanager
    def gate(*, status=None, abbruch=None):
        reihenfolge.append("lock")
        yield
        reihenfolge.append("unlock")

    monkeypatch.setattr(modul, "serielle_sso_anmeldung", gate)
    return reihenfolge


def test_qec_gibt_sperre_vor_fallauswertung_frei(tmp_path, monkeypatch):
    steps = _gate_und_browserfolge(monkeypatch, qec_tool)
    downloader = qec_tool.QecDownloader(
        tmp_path, tmp_path / "edge", serielle_sso=True, click_delay_seconds=0,
    )

    class Page:
        def goto(self, url, **kwargs):
            steps.append("goto")

    page = Page()

    def login(ctx, progress, cancel):
        steps.append("login")
        return page

    def pause(cancel):
        steps.append("fallabfrage")
        raise RuntimeError("nach Anmeldung")

    monkeypatch.setattr(downloader, "_wait_for_login", login)
    monkeypatch.setattr(downloader, "_pause", pause)
    with pytest.raises(RuntimeError, match="nach Anmeldung"):
        downloader._search(SimpleNamespace(), page, qec_tool.QecTarget(
            "WDD12345678901234"
        ), lambda _: None, Event())
    assert steps == ["lock", "goto", "login", "unlock", "fallabfrage"]


def test_tips_gibt_sperre_vor_fallauswertung_frei(tmp_path, monkeypatch):
    steps = _gate_und_browserfolge(monkeypatch, tips_writer)
    downloader = tips_writer.TipsWriterDownloader(
        tmp_path, tmp_path / "edge", serielle_sso=True, click_delay_seconds=0,
    )

    class Page:
        def goto(self, url, **kwargs):
            steps.append("goto")

    page = Page()

    def login(ctx, progress, cancel):
        steps.append("login")
        return page

    def consent(page, progress):
        steps.append("fallabfrage")
        raise RuntimeError("nach Anmeldung")

    monkeypatch.setattr(downloader, "_wait_login", login)
    monkeypatch.setattr(downloader, "_consent", consent)
    with pytest.raises(RuntimeError, match="nach Anmeldung"):
        downloader._search(SimpleNamespace(), page, "WDD12345678901234",
                           lambda _: None, Event())
    assert steps == ["lock", "goto", "login", "unlock", "fallabfrage"]


def test_wem_gibt_sperre_vor_diagnosesuche_frei(tmp_path, monkeypatch):
    steps = _gate_und_browserfolge(monkeypatch, wem)
    downloader = wem.DiagnosisViewerScraper(
        tmp_path / "wem.json", tmp_path / "edge", serielle_sso=True,
    )

    class Page:
        def goto(self, url, **kwargs):
            steps.append("goto")

        def locator(self, selector):
            steps.append("fin-suche")
            raise RuntimeError("nach Anmeldung")

    page = Page()

    def login(ctx):
        steps.append("login")
        return page

    monkeypatch.setattr(downloader, "_login", login)
    with pytest.raises(RuntimeError, match="nach Anmeldung"):
        downloader._search(SimpleNamespace(), page, "WDD12345678901234")
    assert steps == ["lock", "goto", "login", "unlock", "fin-suche"]


def test_vedoc_sa_codes_nur_login_benutzt_gemeinsame_sperre(tmp_path, monkeypatch):
    steps = _gate_und_browserfolge(monkeypatch, vedoc_codes)

    class Page:
        def goto(self, url, **kwargs):
            steps.append("goto")

    class Context:
        pages = [Page()]

        def close(self):
            steps.append("close")

    class Playwright:
        def __enter__(self):
            return SimpleNamespace(chromium=SimpleNamespace(
                launch_persistent_context=lambda **kwargs: Context(),
            ))

        def __exit__(self, *_args):
            return False

    sync_api = ModuleType("playwright.sync_api")
    sync_api.sync_playwright = lambda: Playwright()
    monkeypatch.setitem(sys.modules, "playwright.sync_api", sync_api)

    def browser_bereit(context, wartezeit, *, auto_login=True):
        steps.append("login")
        return context.pages[0]

    monkeypatch.setattr(vedoc_codes, "browser_bereit", browser_bereit)
    args = argparse.Namespace(
        nur_login=True, profil=tmp_path / "edge", pause=0,
        anmeldezeit=30, login_manuell=True,
    )
    assert vedoc_codes.abrufen(args) == 0
    assert steps == ["lock", "goto", "login", "unlock", "close"]
