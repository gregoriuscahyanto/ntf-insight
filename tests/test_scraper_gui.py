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
        if quelle == "dcdc223":
            assert Path(argv[argv.index("--ausgabe") + 1]).name == "vedoc_historie"


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


def test_gui_zeigt_laufende_qec_anhangmeldungen_ohne_fertigmeldung(app):
    """Die CLI darf nicht still im Hintergrund arbeiten, bis alles beendet ist."""
    class FakeProcess:
        def __init__(self):
            self.chunks = [
                "QEC: Anhangfenster geoeffnet; ",
                "2 QEC-Dateilinks erkannt\n",
            ]

        def readAllStandardOutput(self):
            return self.chunks.pop(0).encode("utf-8")

    fenster = gui.ScraperFenster()
    fenster._aktive_quelle = "qec"
    fenster._prozess = FakeProcess()
    fenster._ausgabe_lesen()
    assert "Dateilinks erkannt" not in fenster.status_label.text()
    fenster._ausgabe_lesen()
    assert "2 QEC-Dateilinks erkannt" in fenster.status_label.text()
    assert "abgeschlossen" not in fenster.status_label.text()
    fenster._prozess = None
    fenster.close()


def test_parallel_zwei_quellen_dritte_gesperrt_und_sso_env(monkeypatch, app, fin, tmp_path):
    """Gleichzeitige unterschiedliche Prozesse, keine doppelte Quelle."""
    monkeypatch.setattr(ScraperOptionenDialog, "exec", lambda _dlg: QDialog.Accepted)
    monkeypatch.setattr(ScraperOptionenDialog, "werte", lambda _dlg: {})
    launched = []

    def command(quelle, _datei, *, optionen):
        launched.append((quelle, optionen))
        return [
            sys.executable, "-u", "-c",
            "import time; print('FIN 2/80 bearbeitet', flush=True); time.sleep(1.1)",
        ], tmp_path / quelle

    monkeypatch.setattr(gui, "abruf_befehl", command)
    fenster = gui.ScraperFenster()
    fenster.parallel_spin.setValue(2)
    fenster.sso_pause_spin.setValue(50)
    fenster._datei = fin
    fenster._buttons_aktualisieren()

    fenster.quellen_buttons["qec"].click()
    fenster.quellen_buttons["quicktests"].click()
    assert len(fenster._prozesse) == 2
    assert len(launched) == 2
    assert not fenster.quellen_buttons["qec"].isEnabled()
    assert not fenster.quellen_buttons["tips"].isEnabled()
    assert not fenster.datei_button.isEnabled()
    assert not fenster.parallel_spin.isEnabled()
    assert all(p.processEnvironment().value("NTF_SSO_PAUSE_S") == "50"
               for p in fenster._prozesse.values())

    deadline = time.monotonic() + 3
    while time.monotonic() < deadline and not all(
        "FIN 2/80" in fenster.quellen_status[q].text()
        for q in ("qec", "quicktests")
    ):
        app.processEvents()
        time.sleep(0.015)
    assert "FIN 2/80" in fenster.quellen_status["qec"].text()
    assert "FIN 2/80" in fenster.quellen_status["quicktests"].text()

    fenster.abruf_abbrechen("qec")
    deadline = time.monotonic() + 4
    while "qec" in fenster._prozesse and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert "qec" not in fenster._prozesse
    assert "quicktests" in fenster._prozesse
    assert fenster.quellen_buttons["tips"].isEnabled()
    fenster.alle_abbrechen()
    deadline = time.monotonic() + 4
    while fenster._prozesse and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert fenster._prozesse == {}
    assert fenster.datei_button.isEnabled()
    fenster.close()


def test_gui_zeigt_zielzaehler_auch_bei_resume(monkeypatch, app, fin, tmp_path):
    monkeypatch.setattr(ScraperOptionenDialog, "exec", lambda _dlg: QDialog.Accepted)
    monkeypatch.setattr(ScraperOptionenDialog, "werte", lambda _dlg: {})
    monkeypatch.setattr(gui, "abruf_befehl", lambda *_, **__: (
        [sys.executable, "-u", "-c",
         "print('Ziel 17/80 bereits erledigt (Resume).', flush=True)"], tmp_path,
    ))
    fenster = gui.ScraperFenster()
    fenster._datei = fin
    fenster._buttons_aktualisieren()
    fenster.quellen_buttons["tips"].click()
    deadline = time.monotonic() + 4
    while fenster._prozesse and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert fenster._prozesse == {}
    assert "Ziel 17/80" in fenster.quellen_status["tips"].text()
    fenster.close()


def test_quicktests_sso_status_zeigt_verifizierte_anmeldung_statt_ping_aufforderung(app):
    """Live-CLI-Ausgabe darf nach erkanntem FIN-Suchfeld nicht beim SSO-Prompt bleiben."""
    class FakeProcess:
        def __init__(self):
            self.messages = [
                "SSO wird im sichtbaren Microsoft Edge bearbeitet. PING ID bei "
                "Aufforderung auf dem Smartphone bestaetigen.\n",
                "PING ID abgeschlossen. Diagnosis Viewer ist bereit.\n",
                "PING ID: Anmeldung erfolgreich; 45s Abstand bis zur naechsten.\n",
                "PING ID: Anmelde-Sperre freigegeben; Datenabruf kann parallel laufen.\n",
                "FIN-Fortschritt: 2/80 bearbeitet · zuletzt WDD12345678901234: Erfolgreich\n",
                "Edge: SSO öffnen. Benutzer-ID und Passwort werden bei "
                "Verfügbarkeit eingetragen.\n",
                "SSO gestartet. PING ID nach der Passwort-Anmeldung bestätigen.\n",
                "PING ID abgeschlossen. Diagnosis Viewer ist bereit.\n",
            ]

        def readAllStandardOutput(self):
            return self.messages.pop(0).encode("utf-8")

    fenster = gui.ScraperFenster()
    fake = FakeProcess()
    fenster._prozesse["quicktests"] = fake
    fenster._laufstatus["quicktests"] = {
        "ablage": None, "text": "", "rest": "", "abbruch": False,
        "fortschritt": "", "anmeldung_bestaetigt": False,
    }
    try:
        fenster._ausgabe_lesen("quicktests")
        assert "PING ID" in fenster.quellen_status["quicktests"].text()
        assert "Angemeldet" not in fenster.quellen_status["quicktests"].text()

        fenster._ausgabe_lesen("quicktests")
        bestaetigt = fenster.quellen_status["quicktests"].text()
        assert "Angemeldet" in bestaetigt
        assert "Diagnosis Viewer bereit" in bestaetigt
        assert "bestätigen" not in bestaetigt.lower()
        assert "Angemeldet" in fenster.status_label.text()

        fenster._ausgabe_lesen("quicktests")
        fenster._ausgabe_lesen("quicktests")
        assert fenster.quellen_status["quicktests"].text() == bestaetigt

        fenster._ausgabe_lesen("quicktests")
        fortschritt = fenster.quellen_status["quicktests"].text()
        assert "Angemeldet" in fortschritt
        assert "FIN 2/80" in fortschritt
        assert "WDD12345678901234" not in fortschritt

        fenster._ausgabe_lesen("quicktests")
        assert fenster.quellen_status["quicktests"].text() == fortschritt

        fenster._ausgabe_lesen("quicktests")
        erneut = fenster.quellen_status["quicktests"].text()
        assert "Angemeldet" not in erneut
        assert "PING ID" in erneut

        fenster._ausgabe_lesen("quicktests")
        assert "Angemeldet" in fenster.quellen_status["quicktests"].text()
    finally:
        fenster._prozesse.clear()
        fenster._laufstatus.clear()
        fenster.close()
