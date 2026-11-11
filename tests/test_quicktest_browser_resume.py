"""Offline-Regressionsfaelle: QuickTest-Resume, SSO und Browserverlust.

Keine echte FIN, keine PDF aus dem Unternehmensnetz und kein Mercedes-SSO.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from threading import Event
from types import ModuleType, SimpleNamespace


from ntf_insight.acquisition import diagnosis_viewer as backend
from ntf_insight.acquisition.diagnosis_viewer import (
    DIAGNOSIS_VIEWER, DiagnosisViewerDownloader, DownloadRow,
    FinDownloadResult, _quicktest_fin_vollstaendig, _save_pdf,
    _vorhandene_sitzungs_pdf, _write_manifest,
)

FIN = "WDD12345678901234"
FIN_ZWEI = "WDD12345678901235"
ROWS = [
    DownloadRow(0, "XD", "2026-10-13 10:01:00"),
    DownloadRow(1, "XD", "2026-10-13 10:02:00"),
]


class PdfDownload:
    suggested_filename = "quicktest.pdf"

    def save_as(self, path):
        Path(path).write_bytes(b"%PDF-1.7\nsynthetisches Test-PDF")

    def failure(self):
        return None


class Field:
    first = None

    def __init__(self, visible=True):
        self.visible = visible
        self.filled = []

    def count(self):
        return int(self.visible)

    def is_visible(self):
        return self.visible

    def fill(self, value):
        self.filled.append(value)

    def click(self, **_kwargs):
        pass


class FakePage:
    frames = ()

    def __init__(self):
        self.url = DIAGNOSIS_VIEWER
        self.field = Field()

    def goto(self, *args, **kwargs):
        pass

    def locator(self, selector):
        if selector == 'input[name="finVin"]':
            return self.field
        if selector == "tbody tr":
            return SimpleNamespace(nth=lambda index: SimpleNamespace(
                locator=lambda _selector: SimpleNamespace(first=Field())
            ))
        raise AssertionError(selector)

    def get_by_role(self, *_args, **_kwargs):
        return Field()


def _one_fin_downloader(tmp_path, monkeypatch):
    downloader = DiagnosisViewerDownloader(
        tmp_path / "pdfs", tmp_path / "edge",
        action_interval_seconds=0,
    )
    page = FakePage()
    monkeypatch.setattr(
        downloader, "_login",
        lambda context, page, progress, cancel: page,
    )
    monkeypatch.setattr(
        downloader, "_wait_results",
        lambda page, cancel, fin: list(ROWS),
    )
    return downloader, page


def test_kurzfristiger_abbruch_hat_nur_eine_von_14_pdfs(tmp_path):
    folder = tmp_path / FIN
    first = _save_pdf(PdfDownload(), folder, ROWS[0])
    _write_manifest(
        folder,
        FinDownloadResult(
            fin=FIN, files=[first], available=14, status="Fehler",
            errors=["Edge wurde geschlossen"],
        ),
    )
    assert _quicktest_fin_vollstaendig(tmp_path, FIN) is None
    assert _vorhandene_sitzungs_pdf(folder, ROWS[0]) == first
    assert _vorhandene_sitzungs_pdf(folder, ROWS[1]) is None


def test_vollstaendiger_fin_abruf_kann_ohne_edge_uebersprungen_werden(tmp_path):
    folder = tmp_path / FIN
    first = _save_pdf(PdfDownload(), folder, ROWS[0])
    second = _save_pdf(PdfDownload(), folder, ROWS[1])
    _write_manifest(
        folder,
        FinDownloadResult(
            fin=FIN, files=[first, second], available=2,
            status="Erfolgreich",
        ),
    )
    result = _quicktest_fin_vollstaendig(tmp_path, FIN)
    assert result is not None
    assert result.files == sorted([first, second])


def test_session_resume_verwendet_vorhandene_pdf_und_laedet_nur_fehlende(
    tmp_path, monkeypatch,
):
    downloader, page = _one_fin_downloader(tmp_path, monkeypatch)
    folder = tmp_path / "pdfs" / FIN
    first = _save_pdf(PdfDownload(), folder, ROWS[0])
    aufrufe = []
    monkeypatch.setattr(
        downloader, "_download_or_skip",
        lambda page, icon, cancel: (aufrufe.append("download"), PdfDownload())[1],
    )
    meldungen = []
    result, _ = downloader._one_fin(
        SimpleNamespace(), page, FIN, meldungen.append, Event(),
    )
    assert result.status == "Erfolgreich"
    assert len(aufrufe) == 1
    assert first in result.files and len(result.files) == 2
    assert any("bereits lokal gespeichert" in meldung for meldung in meldungen)
    status = json.loads((folder / "abrufstatus.json").read_text("utf-8"))
    assert status["verfuegbare_sitzungen"] == 2
    assert len(status["pdf_dateien"]) == 2


def test_verlorener_browser_stoppt_sofort_weitere_pdf_klicks(
    tmp_path, monkeypatch,
):
    downloader, page = _one_fin_downloader(tmp_path, monkeypatch)
    klicks = []

    def kaputt(page, icon, cancel):
        klicks.append("PDF")
        raise RuntimeError(
            "Download.failure: Target page, context or browser has been closed"
        )

    monkeypatch.setattr(downloader, "_download_or_skip", kaputt)
    result, _ = downloader._one_fin(
        SimpleNamespace(), page, FIN, lambda _m: None, Event(),
    )
    assert result.status == "Browser-Verbindung verloren"
    assert len(klicks) == 1
    status = json.loads(
        (tmp_path / "pdfs" / FIN / "abrufstatus.json").read_text("utf-8")
    )
    assert status["status"] == "Browser-Verbindung verloren"
    assert status["verfuegbare_sitzungen"] == 2


def test_ssologin_erkennt_suchfeld_in_neuem_tab_und_frame(tmp_path):
    class Frame:
        def locator(self, selector):
            assert selector == 'input[name="finVin"]'
            return Field()

    frame = Frame()
    class Page:
        url = DIAGNOSIS_VIEWER
        frames = [frame]

        def is_closed(self):
            return False

        def locator(self, selector):
            return Field(visible=False)

    current_page = Page()
    downloader = DiagnosisViewerDownloader(
        tmp_path / "pdfs", tmp_path / "edge",
        action_interval_seconds=0,
    )
    meldungen = []
    result = downloader._login(
        SimpleNamespace(pages=[current_page]), object(), meldungen.append, Event(),
    )
    assert result is current_page
    assert downloader._fin_suchbereich(current_page) is frame
    assert any("Diagnosis Viewer ist bereit" in m for m in meldungen)


def _playwright_simulieren(monkeypatch):
    contexts = []

    class Context:
        pages = [object()]

        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    def launch_persistent_context(**_kwargs):
        ctx = Context()
        contexts.append(ctx)
        return ctx

    class Manager:
        def __enter__(self):
            return SimpleNamespace(chromium=SimpleNamespace(
                launch_persistent_context=launch_persistent_context,
            ))

        def __exit__(self, *_args):
            return False

    module = ModuleType("playwright.sync_api")
    module.sync_playwright = lambda: Manager()
    monkeypatch.setitem(sys.modules, "playwright.sync_api", module)
    monkeypatch.setattr(backend.time, "sleep", lambda _seconds: None)
    return contexts


def test_browser_neustart_einmal_und_resume_bestehender_pdfs(
    tmp_path, monkeypatch,
):
    contexts = _playwright_simulieren(monkeypatch)
    downloader = DiagnosisViewerDownloader(
        tmp_path / "pdfs", tmp_path / "edge",
        nur_fehlende_pdfs=True,
    )
    aufrufe = []

    def one_fin(context, page, fin, progress, cancel):
        aufrufe.append(fin)
        folder = tmp_path / "pdfs" / FIN
        first = _save_pdf(PdfDownload(), folder, ROWS[0])
        if len(aufrufe) == 1:
            _write_manifest(folder, FinDownloadResult(
                fin=FIN, available=14, files=[first],
                status="Browser-Verbindung verloren",
            ))
            return FinDownloadResult(
                fin=FIN, files=[first], status="Browser-Verbindung verloren",
                errors=["Target closed"],
            ), page
        assert first.is_file()
        return FinDownloadResult(
            fin=FIN, files=[first], status="Erfolgreich",
        ), page

    monkeypatch.setattr(downloader, "_one_fin", one_fin)
    result = downloader.run([FIN])
    assert aufrufe == [FIN, FIN]
    assert len(contexts) == 2
    assert all(ctx.closed for ctx in contexts)
    assert result[0].status == "Erfolgreich"


def test_zweiter_browserabsturz_stoppt_ohne_weitere_fins(
    tmp_path, monkeypatch,
):
    contexts = _playwright_simulieren(monkeypatch)
    downloader = DiagnosisViewerDownloader(
        tmp_path / "pdfs", tmp_path / "edge",
        nur_fehlende_pdfs=True,
    )
    aufrufe = []

    def one_fin(context, page, fin, progress, cancel):
        aufrufe.append(fin)
        return FinDownloadResult(
            fin=fin, status="Browser-Verbindung verloren",
            errors=["Target closed"],
        ), page

    monkeypatch.setattr(downloader, "_one_fin", one_fin)
    results = downloader.run([FIN, FIN_ZWEI])
    assert aufrufe == [FIN, FIN]
    assert len(contexts) == 2
    assert len(results) == 1
    assert results[0].status == "Browser-Verbindung verloren"


def test_ssologin_laedet_unvollstaendige_viewer_seite_einmal_neu(
    tmp_path, monkeypatch,
):
    zaehler = {"t": 0}

    def schnelle_zeit():
        zaehler["t"] += 20
        return zaehler["t"]

    monkeypatch.setattr(backend.time, "monotonic", schnelle_zeit)
    page = FakePage()
    page.field.visible = False
    page.frames = ()
    page.reload_count = 0
    page.is_closed = lambda: False

    def neu_laden(**_kwargs):
        page.reload_count += 1
        page.field.visible = True

    page.reload = neu_laden
    downloader = DiagnosisViewerDownloader(
        tmp_path / "pdfs", tmp_path / "edge",
        login_timeout_seconds=300, action_interval_seconds=0,
    )
    messages = []
    result = downloader._login(
        SimpleNamespace(pages=[page]), page, messages.append, Event(),
    )
    assert result is page
    assert page.reload_count == 1
    assert any("einmal neu geladen" in msg for msg in messages)


def test_nach_browserabsturz_bleibt_bisheriger_sitzungszaehler_erhalten(
    tmp_path, monkeypatch,
):
    downloader, page = _one_fin_downloader(tmp_path, monkeypatch)
    folder = tmp_path / "pdfs" / FIN
    pdf = _save_pdf(PdfDownload(), folder, ROWS[0])
    _write_manifest(folder, FinDownloadResult(
        fin=FIN, files=[pdf], available=14, status="Browser-Verbindung verloren",
    ))
    page.goto = lambda *args, **kwargs: (_ for _ in ()).throw(
        RuntimeError("Target page, context or browser has been closed")
    )
    result, _ = downloader._one_fin(
        SimpleNamespace(), page, FIN, lambda _m: None, Event(),
    )
    assert result.status == "Browser-Verbindung verloren"
    status = json.loads((folder / "abrufstatus.json").read_text("utf-8"))
    assert status["verfuegbare_sitzungen"] == 14
    assert status["pdf_dateien"] == [pdf.name]
    assert _quicktest_fin_vollstaendig(tmp_path / "pdfs", FIN) is None
