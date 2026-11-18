"""Tests der einfachen Webscraper-GUI ohne Portalzugriff."""

from __future__ import annotations

import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QFileDialog, QInputDialog, QMessageBox

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
    monkeypatch.setattr(QInputDialog, "getText", lambda *args, **kwargs: ("DCDC", True))
    monkeypatch.setattr(
        gui, "abruf_befehl", lambda *_, **_kwargs: (
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


@pytest.mark.parametrize("suchbegriff", ["DCDC", "DCDC223", "DCDC,DC/DC"])
def test_qec_suchbegriff_wird_als_cli_parameter_uebergeben(
    tmp_path, suchbegriff,
):
    datei = tmp_path / "FIN-Liste.txt"
    datei.write_text("WDD12345678901234\n", encoding="utf-8")
    argv, _ = gui.abruf_befehl("qec", datei, qec_benennung=suchbegriff)
    assert argv[argv.index("--benennung") + 1] == suchbegriff
    assert argv.count("--benennung") == 1


def test_qec_standard_und_andere_quellen_bleiben_unveraendert(tmp_path):
    datei = tmp_path / "FIN-Liste.txt"
    datei.write_text("WDD12345678901234\n", encoding="utf-8")
    qec, _ = gui.abruf_befehl("qec", datei, qec_benennung="")
    quicktests, _ = gui.abruf_befehl("quicktests", datei)
    assert "--benennung" not in qec
    assert "--benennung" not in quicktests
    with pytest.raises(ValueError, match="nur bei QEC"):
        gui.abruf_befehl("quicktests", datei, qec_benennung="DCDC")
    with pytest.raises(ValueError, match="Benennung"):
        gui.abruf_befehl("qec", datei, qec_benennung="DCDC;ungültig")


def test_abgebrochener_qec_dialog_startet_keinen_scraper(tmp_path, monkeypatch, app):
    fin = tmp_path / "FIN-Liste.txt"
    fin.write_text("WDD12345678901234\n", encoding="utf-8")
    monkeypatch.setattr(QInputDialog, "getText", lambda *args, **kwargs: ("DCDC", False))
    fenster = gui.ScraperFenster()
    fenster._datei = fin
    fenster._buttons_aktualisieren(laeuft=False)
    fenster.quellen_buttons["qec"].click()
    assert fenster._prozess is None
    assert fenster._qec_benennung == ""
    assert fenster.quellen_buttons["qec"].isEnabled()
    fenster.close()


def test_qec_gui_fragt_benennung_ab_und_merkt_letzte_auswahl(
    tmp_path, monkeypatch, app,
):
    fin = tmp_path / "FIN-Liste.txt"
    fin.write_text("WDD12345678901234\n", encoding="utf-8")
    eingaben = []

    def dialog(*args, **kwargs):
        eingaben.append(kwargs.get("text"))
        return "DCDC", True

    monkeypatch.setattr(QInputDialog, "getText", dialog)
    befehle = []

    def befehl(quelle, datei, *, qec_benennung):
        befehle.append((quelle, datei, qec_benennung))
        return [sys.executable, "-u", "-c", "print('Synthetischer QEC-Test')"], tmp_path

    monkeypatch.setattr(gui, "abruf_befehl", befehl)
    fenster = gui.ScraperFenster()
    fenster._datei = fin
    fenster._buttons_aktualisieren(laeuft=False)
    fenster.quellen_buttons["qec"].click()
    assert eingaben == [""]
    assert befehle == [("qec", fin, "DCDC")]
    assert "Benennung: DCDC" in fenster.status_label.text()

    deadline = time.monotonic() + 5
    while fenster._prozess is not None and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert fenster._prozess is None
    assert fenster._qec_benennung == "DCDC"
    fenster.close()
