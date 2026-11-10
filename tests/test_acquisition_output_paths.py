"""Offline-Tests fuer sichere Listenordner, Dateien und Win-Pfadregeln."""

from __future__ import annotations

from pathlib import Path

import pytest

from ntf_insight.acquisition.output_paths import (
    ausgabe_in_gruppe,
    quellennamen,
    sicherer_listenname,
    standard_ausgabe,
)

EINGABE = Path(r"C:\FIN") / "FIN-Liste DCDC223 SensorIssue.txt"


def test_beispielname_bleibt_lesbar():
    assert sicherer_listenname(EINGABE) == "FIN-Liste DCDC223 SensorIssue"


def test_alle_sechs_quellen_je_liste_getrennt():
    erwartete = {
        "dcdc223": "vedoc_dcdc223",
        "wem": "diagnosis_viewer_warn_error/warnings_errors.json",
        "sa-codes": "vedoc_codes/vedoc_codes.json",
        "quicktests": "diagnosis_viewer_quicktests",
        "qec": "qec",
        "tips": "tips_writer",
    }
    assert set(quellennamen()) == set(erwartete)
    for quelle, relativ in erwartete.items():
        ausgabe = standard_ausgabe(EINGABE, quelle)
        assert ausgabe == Path("data/processed/FIN-Liste DCDC223 SensorIssue") / relativ
        assert ausgabe == ausgabe_in_gruppe(
            Path("data/processed/FIN-Liste DCDC223 SensorIssue"), quelle,
        )


@pytest.mark.parametrize(("name", "erwartet"), [
    ("FIN: Sensor?Issue*.txt", "FIN_ Sensor_Issue_"),
    ("  FIN-Liste. .txt", "FIN-Liste"),
    ("CON.txt", "_CON"),
    ("nul.TXT", "_nul"),
    ("COM1.txt", "_COM1"),
    ("LPT9.txt", "_LPT9"),
    ("....txt", "FIN-Liste"),
    ("Reparatur\u202eNotiz.txt", "Reparatur_Notiz"),
    ("FIN/Teil.txt", "Teil"),
    ("Schäden _ Kühlmittelpumpe.txt", "Schäden _ Kühlmittelpumpe"),
])
def test_dateinamenbereinigung(name, erwartet):
    assert sicherer_listenname(Path(name)) == erwartet


def test_lange_namen_werden_reproduzierbar_und_kollisionsarm():
    a = Path("L" * 110 + "A.txt")
    b = Path("L" * 110 + "B.txt")
    alpha = sicherer_listenname(a)
    assert len(alpha) <= 80
    assert alpha == sicherer_listenname(a)
    assert alpha != sicherer_listenname(b)


def test_einzelquellen_bleiben_unter_dem_ordner():
    root = Path("D:/NTF-Projekt")
    assert ausgabe_in_gruppe(root, "wem") == root / "diagnosis_viewer_warn_error" / "warnings_errors.json"
    assert ausgabe_in_gruppe(root, "qec") == root / "qec"


def test_unbekannte_datenquelle_ist_fehler():
    with pytest.raises(ValueError, match="Unbekannte"):
        standard_ausgabe(Path("fins.txt"), "../anders")


def test_sonderzeichen_generieren_keine_pfadspruenge():
    p = standard_ausgabe(Path("FIN:A?B.txt"), "tips")
    assert p.parts[:2] == ("data", "processed")
    assert len(p.parts) == 4
    assert p.parts[2] == "FIN_A_B"
