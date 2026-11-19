"""Offline-Regression: QuickTests erhalten ohne Profileingabe immer ein frisches Edge-Profil.

Keine echten Browser, FIN-Abfragen, PING-ID-Daten oder PDF-Berichte erforderlich.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

from ntf_insight.acquisition import diagnosis_viewer as backend
from ntf_insight.acquisition.diagnosis_viewer import (
    DiagnosisViewerDownloader, FinDownloadResult,
)


FIN = "WDD12345678901234"
FIN_ZWEI = "WDD12345678901235"


def _edge_mock(monkeypatch, tmp_path):
    contexts = []
    original_temp = backend.tempfile.TemporaryDirectory

    def temp_profil(**kwargs):
        return original_temp(dir=tmp_path, **kwargs)

    monkeypatch.setattr(backend.tempfile, "TemporaryDirectory", temp_profil)
    monkeypatch.setattr(backend.time, "sleep", lambda _seconds: None)

    class FakeContext:
        def __init__(self, options):
            self.profil = Path(options["user_data_dir"])
            self.pages = [object()]
            self.closed = False
            self.listeners = {}
            contexts.append(self)

        def on(self, event, handler):
            self.listeners[event] = handler

        def close(self):
            self.closed = True
            if "close" in self.listeners:
                self.listeners["close"]()

    class FakePlaywright:
        def __enter__(self):
            return SimpleNamespace(chromium=SimpleNamespace(
                launch_persistent_context=lambda **kwargs: FakeContext(kwargs),
            ))

        def __exit__(self, *_args):
            return False

    module = ModuleType("playwright.sync_api")
    module.sync_playwright = lambda: FakePlaywright()
    monkeypatch.setitem(sys.modules, "playwright.sync_api", module)
    return contexts


def test_automatisch_frisches_profil_bei_jedem_edge_neustart_ohne_altdatenverlust(
    tmp_path, monkeypatch,
):
    contexts = _edge_mock(monkeypatch, tmp_path)
    ausgabe = tmp_path / "pdf-berichte"
    downloader = DiagnosisViewerDownloader(
        ausgabe, None, nur_fehlende_pdfs=True,
    )
    aufrufe = []
    gespeichert = ausgabe / FIN / "test-alt.pdf"

    def abruf(context, page, fin, progress, cancel):
        assert context.profil.exists()
        aufrufe.append((fin, context.profil))
        if len(aufrufe) == 1:
            gespeichert.parent.mkdir(parents=True)
            gespeichert.write_bytes(b"%PDF-1.7\nBereits gespeicherte Testdatei")
            return FinDownloadResult(
                fin=fin, status="Browser-Verbindung verloren", errors=["Target closed"],
            ), page
        assert gespeichert.is_file()
        return FinDownloadResult(fin=fin, status="Erfolgreich", files=[gespeichert]), page

    monkeypatch.setattr(downloader, "_one_fin", abruf)
    status = []
    ergebnis = downloader.run([FIN], progress=status.append)
    assert ergebnis[0].status == "Erfolgreich"
    assert len(contexts) == 2
    assert contexts[0].profil != contexts[1].profil
    assert all(c.profil.name.startswith("ntf-quicktests-edge-") for c in contexts)
    assert all(c.closed for c in contexts)
    assert all(not c.profil.exists() for c in contexts)  # Normaler Ausstieg raeumt auf.
    assert gespeichert.read_bytes().startswith(b"%PDF-")
    assert any("Neues, separates Edge-Profil" in m for m in status)


def test_ein_profil_fuer_mehrere_fins_innerhalb_eines_laufs(tmp_path, monkeypatch):
    contexts = _edge_mock(monkeypatch, tmp_path)
    downloader = DiagnosisViewerDownloader(
        tmp_path / "downloads", None, nur_fehlende_pdfs=True,
    )
    aufrufe = []

    def abruf(context, page, fin, progress, cancel):
        aufrufe.append((fin, context.profil))
        return FinDownloadResult(fin=fin, status="Keine Quicktests"), page

    monkeypatch.setattr(downloader, "_one_fin", abruf)
    ergebnis = downloader.run([FIN, FIN_ZWEI])
    assert len(ergebnis) == 2
    assert len(contexts) == 1
    assert aufrufe == [(FIN, contexts[0].profil), (FIN_ZWEI, contexts[0].profil)]
    assert not contexts[0].profil.exists()


def test_bewusst_ausgewaehltes_festes_profil_wird_nicht_geloescht(
    tmp_path, monkeypatch,
):
    contexts = _edge_mock(monkeypatch, tmp_path)
    profil = tmp_path / "mein_bewusstes_profil"
    profil.mkdir()
    datei = profil / "benutzerdaten.txt"
    datei.write_text("Behalten", encoding="utf-8")
    downloader = DiagnosisViewerDownloader(
        tmp_path / "downloads", profil, nur_fehlende_pdfs=True,
    )
    monkeypatch.setattr(downloader, "_one_fin", lambda context, page, fin, progress, cancel: (
        FinDownloadResult(fin=fin, status="Keine Quicktests"), page,
    ))
    assert downloader.run([FIN])[0].status == "Keine Quicktests"
    assert contexts[0].profil == profil
    assert profil.is_dir()
    assert datei.read_text(encoding="utf-8") == "Behalten"


def test_kein_automatisches_profil_bei_vollstaendigem_resume(
    tmp_path, monkeypatch,
):
    contexts = _edge_mock(monkeypatch, tmp_path)
    monkeypatch.setattr(
        backend, "_quicktest_fin_vollstaendig",
        lambda _basis, fin: FinDownloadResult(
            fin=fin, status="Erfolgreich",
        ),
    )
    downloader = DiagnosisViewerDownloader(
        tmp_path / "downloads", None, nur_fehlende_pdfs=True,
    )
    ergebnis = downloader.run([FIN])
    assert ergebnis[0].status == "Erfolgreich"
    assert contexts == []
    assert not list(tmp_path.glob("ntf-quicktests-edge-*"))
