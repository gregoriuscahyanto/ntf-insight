"""Reine Validierungstests für zusätzliche CLI-Argumente ohne Qt oder Portale."""

from __future__ import annotations

import pytest

from ntf_insight.app.scraper_optionen import QUELLEN_OPTIONEN, extra_argumente


@pytest.mark.parametrize("quelle", [
    "qec", "tips", "quicktests", "wem", "sa-codes", "dcdc223",
])
def test_alle_quellen_haben_ausgabe_und_manuellen_login(quelle):
    eintraege = [option.name for option in QUELLEN_OPTIONEN[quelle]]
    assert len(eintraege) == len(set(eintraege))
    assert {"ausgabe", "login-manuell"} <= set(eintraege)
    assert "passwort-abfragen" not in eintraege
    assert "benutzer-id" not in eintraege
    assert extra_argumente(quelle)[0] == []
    assert extra_argumente(quelle)[1] is None


def test_alle_anhaenge_werden_nur_an_qec_uebergeben():
    args, output = extra_argumente("qec", {"benennung": "DCDC", "anhaenge": "alle"})
    assert args == ["--benennung", "DCDC", "--anhaenge", "alle"]
    assert output is None
    with pytest.raises(ValueError, match="Nicht unterstützte"):
        extra_argumente("quicktests", {"anhaenge": "alle"})


def test_qec_sachnummer_und_pumpenfreie_suche():
    args, _ = extra_argumente("qec", {
        "sachnummer": "A 123 456 78 90", "alle-bauteile": True,
        "benennung": "DCDC,DC/DC",
    })
    assert "--sachnummer" in args
    assert "--alle-bauteile" in args
    assert args[args.index("--benennung") + 1] == "DCDC,DC/DC"
    with pytest.raises(ValueError, match="Benennung"):
        extra_argumente("qec", {"benennung": "DCDC;bad"})


def test_qec_anhaenge_muessen_bekannte_auswahl_sein():
    with pytest.raises(ValueError, match="ungültige Auswahl"):
        extra_argumente("qec", {"anhaenge": "alle;--login-manuell"})


def test_quicktest_pdfs_ohne_json_und_erneut():
    args, _ = extra_argumente("quicktests", {
        "erneut": True, "ohne-json": True, "anmelde-timeout": 450,
    })
    assert args == ["--erneut", "--ohne-json", "--anmelde-timeout", "450"]


def test_wem_offline_modi_sind_exklusiv():
    with pytest.raises(ValueError, match="alternativ"):
        extra_argumente("wem", {
            "nur-login": True, "nur-zusammenfassen": True,
        })
    with pytest.raises(ValueError, match="alternativ"):
        extra_argumente("wem", {
            "nur-aufteilen": True, "nur-zusammenfassen": True,
        })
    with pytest.raises(ValueError, match="schließen sich aus"):
        extra_argumente("wem", {
            "sso-tresor": True, "login-manuell": True,
        })
    args, _ = extra_argumente("wem", {
        "aktualisieren": True, "sitzungs-timeout": 8.5,
    })
    assert args == ["--aktualisieren", "--sitzungs-timeout", "8.5"]


def test_numerische_optionen_werden_im_gueltigen_bereich_geprueft():
    with pytest.raises(ValueError, match="außerhalb"):
        extra_argumente("quicktests", {"anmelde-timeout": 2})
    with pytest.raises(ValueError, match="außerhalb"):
        extra_argumente("wem", {"abschnitt-wartezeit": 0.1})
    with pytest.raises(ValueError, match="Zahl"):
        extra_argumente("sa-codes", {"anmeldezeit": "300;foo"})
    with pytest.raises(ValueError, match="Ja oder Nein"):
        extra_argumente("qec", {"alle-bauteile": "true"})


def test_custom_json_output_und_gesonderter_profilordner(tmp_path):
    output = tmp_path / "Berichte" / "wem.json"
    args, given = extra_argumente("wem", {
        "ausgabe": str(output), "profil": str(tmp_path / "privates-profil"),
    })
    assert given == output
    assert args == ["--profil", str(tmp_path / "privates-profil")]
    with pytest.raises(ValueError, match="JSON-Datei"):
        extra_argumente("wem", {"ausgabe": str(tmp_path / "nicht-json.txt")})
    with pytest.raises(ValueError, match="getrennt"):
        extra_argumente("qec", {
            "ausgabe": str(tmp_path / "out"), "profil": str(tmp_path),
        })


def test_vedoc_historie_erlaubt_freies_objekt_und_attribut():
    args, _ = extra_argumente("dcdc223", {
        "objekt": "CPC3", "attribut": "Hardwarestand",
        "timeout": 45, "browser": "chromium",
    })
    assert args == [
        "--objekt", "CPC3", "--attribut", "Hardwarestand",
        "--browser", "chromium", "--timeout", "45",
    ]


@pytest.mark.parametrize("quelle", ["qec", "tips", "quicktests", "wem", "sa-codes", "dcdc223"])
def test_beliebige_shell_schalter_werden_zurueckgewiesen(quelle):
    with pytest.raises(ValueError, match="Nicht unterstützte"):
        extra_argumente(quelle, {"--ungeprueft": "evil"})


def test_quellen_haben_keine_profildaten_in_gespeicherten_optionen():
    for quelle, specs in QUELLEN_OPTIONEN.items():
        keys = {spec.name for spec in specs}
        assert "passwort" not in keys
        assert "passwort-abfragen" not in keys
        assert "benutzer-id" not in keys
        assert len(keys) >= 2
