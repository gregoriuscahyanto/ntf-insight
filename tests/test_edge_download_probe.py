"""Sichere Offline-Tests fuer die lokale Edge-/Playwright-Downloadprobe."""

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import ntf_insight.acquisition.edge_download_probe as probe


def test_probe_bewertet_zweiten_profilabsturz_nicht_als_ssologin():
    erfolgreich = probe.ProbeResult(0, ("ERGEBNIS PDF-erfolgreich",))
    geschlossen = probe.ProbeResult(3221225477, ("PHASE Unerwartetes-Kontextende",))
    text = probe._bewertung(erfolgreich, geschlossen, erfolgreich)
    assert "Wiederverwendung" in text
    assert "PING-ID" in text
    assert "Keine Absturzreproduktion" in probe._bewertung(
        erfolgreich, erfolgreich, None,
    )
    assert "Schon der erste" in probe._bewertung(geschlossen, erfolgreich, None)


def test_zwei_separate_prozesse_und_kontrolle_verwenden_nur_temporaere_profile(
    monkeypatch, capsys,
):
    sequence = [0, 3221225477, 0]
    runs = []

    def fake_run(profile, output):
        runs.append((profile, output))
        return probe.ProbeResult(sequence.pop(0), ("PHASE Synthetischer-PDF-Klick",))

    monkeypatch.setattr(probe, "_subprocess_lauf", fake_run)
    assert probe.main([]) == 1
    assert len(runs) == 3
    assert runs[0][0] == runs[1][0]
    assert runs[2][0] != runs[0][0]
    assert all("ntf-edge-pdf-probe-" in str(a) for a, _ in runs)
    assert len({str(a.parent) for a, _ in runs}) == 1
    assert all(not a.exists() for a, _ in runs)
    output = capsys.readouterr().out
    assert "Versuch 1" in output and "Versuch 2" in output
    assert "Kontrollversuch" in output
    assert "Wiederverwendung" in output


def test_zwei_erfolgreiche_proben_erfordern_keine_dritte_anmeldung(
    monkeypatch, capsys,
):
    runs = []

    def fake_run(profile, output):
        runs.append(profile)
        return probe.ProbeResult(0, ("ERGEBNIS PDF-erfolgreich",))

    monkeypatch.setattr(probe, "_subprocess_lauf", fake_run)
    assert probe.main([]) == 0
    assert len(runs) == 2
    assert "Keine Absturzreproduktion" in capsys.readouterr().out


def test_child_nutzt_nur_synthetische_datei_und_schliesst_edge(
    monkeypatch, tmp_path, capsys,
):
    closed = []
    seen = []

    class FakeDownload:
        def save_as(self, output):
            Path(output).write_bytes(probe.PROBE_BYTES)

    class Capture:
        value = FakeDownload()

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    class FakePage:
        def set_content(self, html):
            seen.append(html)

        def expect_download(self, **_kwargs):
            return Capture()

        def locator(self, selector):
            assert selector == "#probe"
            return SimpleNamespace(click=lambda **_kwargs: None)

    class FakeContext:
        pages = [FakePage()]

        def on(self, event, callback):
            assert event == "close"
            self.callback = callback

        def close(self):
            closed.append(True)
            self.callback()

    class Playwright:
        def __enter__(self):
            return SimpleNamespace(chromium=SimpleNamespace(
                launch_persistent_context=lambda **_kwargs: FakeContext(),
            ))

        def __exit__(self, *_args):
            return False

    fake_api = ModuleType("playwright.sync_api")
    fake_api.sync_playwright = lambda: Playwright()
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake_api)
    profile = tmp_path / "nur-probe"
    output = tmp_path / "ergebnis.pdf"
    assert probe._child(profile, output) == 0
    assert output.read_bytes() == probe.PROBE_BYTES
    assert closed == [True]
    assert "data:application/pdf;base64" in seen[0]
    assert "ntf_probe.pdf" in seen[0]
    assert "Unerwartetes-Kontextende" not in capsys.readouterr().out


def test_probe_kopiert_kein_browser_stderr_in_diagnose(monkeypatch, tmp_path):
    fake = SimpleNamespace(
        returncode=2,
        stdout="PHASE Browserstart\nERGEBNIS Fehlerart-TargetClosedError\n"
               "Cookie=VERTRAULICH\n",
        stderr="Cookie=NICHT-PROTOKOLLIEREN\n",
    )
    monkeypatch.setattr(probe.subprocess, "run", lambda *a, **kw: fake)
    out = probe._subprocess_lauf(tmp_path / "profil", tmp_path / "out.pdf")
    assert out.returncode == 2
    assert out.messages == ("PHASE Browserstart", "ERGEBNIS Fehlerart-TargetClosedError")
    assert not any("Cookie" in line for line in out.messages)
