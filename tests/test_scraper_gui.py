"""Tests der einfachen Webscraper-GUI ohne Portalzugriff."""

from __future__ import annotations

import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from ntf_insight.app import scraper_gui as gui


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def test_cli_aufruf_und_private_ablage(tmp_path, monkeypatch):
    monkeypatch.setenv("NTF_INSIGHT_DATA_DIR", str(tmp_path / "privat"))
    fin = tmp_path / "FIN Liste.txt"
    fin.write_text("WDD12345678901234\n", encoding="utf-8")
    befehl, basis = gui.abruf_befehl("qec", fin)
    assert befehl[1:3] == ["-u", "-c"]
    assert "from ntf_insight.acquisition.portal_cli import qec_main" in befehl[3]
    assert befehl[befehl.index("--eingabe") + 1] == str(fin)
    assert befehl[befehl.index("--ausgabe") + 1] == str(basis / "qec")
    assert basis == tmp_path / "privat" / "abrufe" / "FIN Liste"
    assert "--login-manuell" not in befehl


def test_ungueltige_quelle_und_datei(tmp_path):
    with pytest.raises(ValueError, match="Unbekannte"):
        gui.abruf_befehl("beliebiger-befehl", tmp_path / "fins.txt")
    with pytest.raises(ValueError, match="TXT-Datei"):
        gui.abruf_befehl("qec", tmp_path / "fehlend.txt")


def test_dateiauswahl_aktiviert_sechs_buttons(tmp_path, monkeypatch, app):
    fin = tmp_path / "synthetisch.txt"
    fin.write_text("WDD12345678901234\n", encoding="utf-8")
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName", lambda *args, **kwargs: (str(fin), "Textdateien (*.txt)")
    )
    fenster = gui.ScraperFenster()
    assert len(fenster.quellen_buttons) == 6
    assert all(not b.isEnabled() for b in fenster.quellen_buttons.values())
    fenster.datei_button.click()
    assert fenster.dateiname_label.text() == fin.name
    assert all(b.isEnabled() for b in fenster.quellen_buttons.values())
    fenster.close()


@pytest.mark.parametrize("exitcode", [0, 2])
def test_button_startet_cli_ohne_fenster_zu_blockieren(
    tmp_path, monkeypatch, app, exitcode,
):
    fin = tmp_path / "fins.txt"
    fin.write_text("WDD12345678901234\n", encoding="utf-8")
    monkeypatch.setattr(
        gui, "abruf_befehl", lambda *_: (
            [sys.executable, "-u", "-c", f"print('Synthetischer Lauf'); raise SystemExit({exitcode})"],
            tmp_path / "ausgabe",
        ),
    )
    warnungen = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnungen.append(args[-1]))
    fenster = gui.ScraperFenster()
    fenster._datei = fin
    fenster._buttons_aktualisieren(laeuft=False)
    fenster.quellen_buttons["qec"].click()
    assert fenster._prozess is not None
    assert not fenster.datei_button.isEnabled()
    assert fenster.abbruch_button.isEnabled()
    deadline = time.monotonic() + 5
    while fenster._prozess is not None and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()
    assert fenster._prozess is None
    assert fenster.datei_button.isEnabled()
    assert not fenster.abbruch_button.isEnabled()
    if exitcode:
        assert "Fehler" in fenster.status_label.text()
        assert warnungen and "Synthetischer Lauf" in warnungen[0]
    else:
        assert "abgeschlossen" in fenster.status_label.text()
    fenster.close()
