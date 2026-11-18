"""Synthetische GUI-Tests: kein Browser, keine FIN-Echtdaten."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QComboBox, QDialog, QFileDialog, QLineEdit, QMessageBox

from ntf_insight.app import scraper_gui as gui
from ntf_insight.app.dialogs.scraper_optionen_dialog import ScraperOptionenDialog


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def fin(tmp_path):
    datei = tmp_path / "FIN Liste.txt"
    datei.write_text("WDD12345678901234\n", encoding="utf-8")
    return datei


def test_cli_aufruf_und_private_ablage(tmp_path, monkeypatch, fin):
    monkeypatch.setenv("NTF_INSIGHT_DATA_DIR", str(tmp_path / "privat"))
    befehl, basis = gui.abruf_befehl("qec", fin)
    assert befehl[1:3] == ["-u", "-c"]
    assert "from ntf_insight.acquisition.portal_cli import qec_main" in befehl[3]
    assert befehl[befehl.index("--eingabe") + 1] == str(fin)
    assert befehl[befehl.index("--ausgabe") + 1] == str(basis / "qec")
    assert basis == tmp_path / "privat" / "abrufe" / "FIN Liste"
    assert "--login-manuell" not in befehl
    assert "--anhaenge" not in befehl


def test_ungueltige_quelle_und_datei(tmp_path):
    with pytest.raises(ValueError, match="Unbekannte"):
        gui.abruf_befehl("beliebiger-befehl", tmp_path / "fins.txt")
    with pytest.raises(ValueError, match="TXT-Datei"):
        gui.abruf_befehl("qec", tmp_path / "fehlend.txt")


def test_dateiauswahl_aktiviert_sechs_buttons(tmp_path, monkeypatch, app, fin):
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName",
        lambda *args, **kwargs: (str(fin), "Textdateien (*.txt)"),
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
    tmp_path, monkeypatch, app, fin, exitcode,
):
    monkeypatch.setattr(ScraperOptionenDialog, "exec", lambda _self: QDialog.Accepted)
    monkeypatch.setattr(
        ScraperOptionenDialog, "werte",
        lambda _self: {"benennung": "DCDC", "anhaenge": "alle"},
    )
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
    assert "Anhänge: alle" in fenster.status_label.text()
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
def test_qec_suchbegriff_wird_als_cli_parameter_uebergeben(fin, suchbegriff):
    argv, _ = gui.abruf_befehl("qec", fin, qec_benennung=suchbegriff)
    assert argv[argv.index("--benennung") + 1] == suchbegriff
    assert argv.count("--benennung") == 1


def test_qec_alle_anhaenge_und_sachnummer_mit_options_dialog(fin):
    argv, _ = gui.abruf_befehl("qec", fin, optionen={
        "benennung": "DCDC", "sachnummer": "A 123 456 78 90",
        "anhaenge": "alle", "login-manuell": True, "alle-bauteile": True,
    })
    assert argv[argv.index("--benennung") + 1] == "DCDC"
    assert argv[argv.index("--sachnummer") + 1] == "A 123 456 78 90"
    assert argv[argv.index("--anhaenge") + 1] == "alle"
    assert "--alle-bauteile" in argv
    assert "--login-manuell" in argv
    assert "--passwort-abfragen" not in argv


def test_qec_standard_und_andere_quellen_bleiben_unveraendert(fin):
    qec, _ = gui.abruf_befehl("qec", fin, qec_benennung="")
    quicktests, _ = gui.abruf_befehl("quicktests", fin)
    assert "--benennung" not in qec
    assert "--benennung" not in quicktests
    with pytest.raises(ValueError, match="nur bei QEC"):
        gui.abruf_befehl("quicktests", fin, qec_benennung="DCDC")
    with pytest.raises(ValueError, match="Benennung"):
        gui.abruf_befehl("qec", fin, qec_benennung="DCDC;ungültig")


def test_dialog_abbruch_startet_keinen_prozess(monkeypatch, app, fin):
    monkeypatch.setattr(ScraperOptionenDialog, "exec", lambda _self: QDialog.Rejected)
    fenster = gui.ScraperFenster()
    fenster._datei = fin
    fenster._buttons_aktualisieren(laeuft=False)
    for quelle in gui.QUELLEN_NAMEN:
        fenster.quellen_buttons[quelle].click()
        assert fenster._prozess is None
        assert quelle not in fenster._optionen_je_quelle
        assert fenster.quellen_buttons[quelle].isEnabled()
    fenster.close()


def test_popup_fuer_jeden_scraper_hat_spezifische_flags(app):
    erwartete = {
        "qec": {"benennung", "anhaenge", "sachnummer", "alle-bauteile"},
        "quicktests": {"erneut", "ohne-json", "anmelde-timeout"},
        "tips": {"anmelde-timeout", "profil"},
        "wem": {"aktualisieren", "erneut", "nur-aufteilen", "seiten-timeout"},
        "sa-codes": {"anmeldezeit", "ladezeit", "pause"},
        "dcdc223": {"objekt", "attribut", "historie-wartezeit", "url"},
    }
    for quelle, felder in erwartete.items():
        dialog = ScraperOptionenDialog(quelle, gui.QUELLEN_NAMEN[quelle])
        assert felder.issubset(dialog.felder)
        assert "ausgabe" in dialog.felder
        assert "login-manuell" in dialog.felder
        assert dialog.werte()["ausgabe"] == ""
        dialog.close()


def test_qec_dialog_anhangauswahl_und_suchbegriff(app):
    dialog = ScraperOptionenDialog("qec", gui.QUELLEN_NAMEN["qec"])
    combo = dialog.felder["anhaenge"]
    assert isinstance(combo, QComboBox)
    assert combo.currentData() == "referenz"
    combo.setCurrentIndex(combo.findData("alle"))
    benennung = dialog.felder["benennung"]
    assert isinstance(benennung, QLineEdit)
    benennung.setText("DCDC")
    assert dialog.werte()["anhaenge"] == "alle"
    assert dialog.werte()["benennung"] == "DCDC"
    dialog._pruefen_und_starten()
    assert dialog.result() == QDialog.Accepted
    dialog.close()


def test_qec_dialog_merkt_je_quelle_letzte_auswahl(
    tmp_path, monkeypatch, app, fin,
):
    eingaben = []
    gewaehlte_optionen = {"benennung": "DCDC", "anhaenge": "alle"}

    def dialog_bauen(quelle, _name, vorbelegung, _parent):
        eingaben.append((quelle, vorbelegung))
        return ScraperOptionenDialog(quelle, gui.QUELLEN_NAMEN[quelle], vorbelegung)

    monkeypatch.setattr(gui, "ScraperOptionenDialog", dialog_bauen)
    monkeypatch.setattr(ScraperOptionenDialog, "exec", lambda _self: QDialog.Accepted)
    monkeypatch.setattr(
        ScraperOptionenDialog, "werte", lambda _self: dict(gewaehlte_optionen),
    )
    befehle = []

    def befehl(quelle, datei, *, optionen):
        befehle.append((quelle, datei, optionen))
        return [sys.executable, "-u", "-c", "print('Test')"], tmp_path

    monkeypatch.setattr(gui, "abruf_befehl", befehl)
    fenster = gui.ScraperFenster()
    fenster._datei = fin
    fenster._buttons_aktualisieren(laeuft=False)
    fenster.quellen_buttons["qec"].click()
    assert eingaben == [("qec", None)]
    assert befehle == [("qec", fin, gewaehlte_optionen)]
    assert "Benennung: DCDC" in fenster.status_label.text()
    assert "Anhänge: alle" in fenster.status_label.text()

    deadline = time.monotonic() + 5
    while fenster._prozess is not None and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert fenster._prozess is None
    assert fenster._optionen_je_quelle["qec"] == gewaehlte_optionen
    fenster.close()


def test_alle_quellen_optionen_erzeugen_nur_erlaubte_cli_parameter(fin):
    varianten = {
        "quicktests": ({"erneut": True, "ohne-json": True}, ["--erneut", "--ohne-json"]),
        "tips": ({"login-manuell": True}, ["--login-manuell"]),
        "wem": ({"aktualisieren": True, "seiten-timeout": 110.0}, ["--aktualisieren", "--seiten-timeout"]),
        "sa-codes": ({"erneut": True, "pause": 2.5}, ["--erneut", "--pause"]),
        "dcdc223": ({"objekt": "CPC3", "attribut": "Hardwarestand"}, ["--objekt", "--attribut"]),
    }
    for quelle, (werte, schalter) in varianten.items():
        argv, _ = gui.abruf_befehl(quelle, fin, optionen=werte)
        for schalter in schalter:
            assert schalter in argv
        assert "--benennung" not in argv
        assert "--anhaenge" not in argv


def test_eigener_ausgabeort_nur_an_richtige_dateiart(fin, tmp_path):
    export = tmp_path / "WEM Berichte.json"
    argv, returned = gui.abruf_befehl("wem", fin, optionen={"ausgabe": str(export)})
    assert argv[argv.index("--ausgabe") + 1] == str(export)
    assert returned == export
    with pytest.raises(ValueError, match="JSON-Datei"):
        gui.abruf_befehl("wem", fin, optionen={"ausgabe": str(tmp_path / "falsch")})
    with pytest.raises(ValueError, match="getrennt"):
        gui.abruf_befehl("qec", fin, optionen={
            "ausgabe": str(tmp_path / "out"), "profil": str(tmp_path),
        })
