"""Offline-Regressionsfaelle fuer QEC-/TIPS-CLI und sechs Wheel-Einstiegspunkte."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from ntf_insight.acquisition import portal_cli
from ntf_insight.acquisition.credentials import LoginCredentials
from ntf_insight.acquisition.qec_tool import QecResult, QecTarget
from ntf_insight.acquisition.tips_writer import TipsResult

FIN = "WDD12345678901234"
FIN2 = "WDD12345678901235"
ROOT = Path(__file__).resolve().parents[1]


def _liste(tmp_path: Path, text: str | None = None) -> Path:
    datei = tmp_path / "fins.txt"
    datei.write_text(f"{FIN}\n{FIN2}\n" if text is None else text, encoding="utf-8")
    return datei


def _fake_qec(monkeypatch, results=None):
    aufrufe = []

    class Downloader:
        def __init__(self, ausgabe, profil, **options):
            aufrufe.append(("init", ausgabe, profil, options))

        def run(self, targets, *, progress):
            aufrufe.append(("run", targets))
            progress("QEC: synthetischer Test")
            return results if results is not None else [
                QecResult(fin=x.fin, status="Erfolgreich") for x in targets
            ]

    monkeypatch.setattr(portal_cli, "QecDownloader", Downloader)
    return aufrufe


def _fake_tips(monkeypatch, results=None):
    aufrufe = []

    class Downloader:
        def __init__(self, ausgabe, profil, **options):
            aufrufe.append(("init", ausgabe, profil, options))

        def run(self, fins, *, progress):
            aufrufe.append(("run", fins))
            progress("TIPS: synthetischer Test")
            return results if results is not None else [
                TipsResult(fin=fin, status="Erfolgreich") for fin in fins
            ]

    monkeypatch.setattr(portal_cli, "TipsWriterDownloader", Downloader)
    return aufrufe


def test_qec_bom_kommentare_sachnummer_und_duplikate(tmp_path, monkeypatch):
    monkeypatch.setattr(portal_cli, "load_saved_credentials", lambda: None)
    aufrufe = _fake_qec(monkeypatch)
    eingabe = _liste(tmp_path, f"\ufeff# Kommentar\n{FIN.lower()}; A 123 456 78 90\n"
                           f"{FIN}; A 123 456 78 90 # doppelt\n{FIN2}\n")
    assert portal_cli.qec_main(["--eingabe", str(eingabe)]) == 0
    assert aufrufe[1][1] == [
        QecTarget(fin=FIN, part_number="A 123 456 78 90"),
        QecTarget(fin=FIN2, part_number=""),
    ]


def test_qec_standard_ordner_und_tresor_login(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        portal_cli, "load_saved_credentials",
        lambda: LoginCredentials("synthetische-id", "test-geheim"),
    )
    aufrufe = _fake_qec(monkeypatch)
    assert portal_cli.qec_main(["--eingabe", str(_liste(tmp_path))]) == 0
    _, output, profile, kwargs = aufrufe[0]
    assert output == (tmp_path / "data/processed/fins/qec").resolve()
    assert profile == portal_cli.QEC_PROFIL.resolve()
    assert kwargs["pump_only"] is True
    assert kwargs["user_id"] == "synthetische-id"
    assert kwargs["password"] == "test-geheim"
    assert kwargs["login_timeout_seconds"] == 300
    assert "test-geheim" not in capsys.readouterr().out


def test_qec_alle_bauteile_und_eigener_ausgabeordner(tmp_path, monkeypatch):
    monkeypatch.setattr(portal_cli, "load_saved_credentials", lambda: None)
    aufrufe = _fake_qec(monkeypatch)
    ausgabe, profil = tmp_path / "export", tmp_path / "edge"
    assert portal_cli.qec_main([
        "--eingabe", str(_liste(tmp_path)), "--ausgabe", str(ausgabe),
        "--profil", str(profil), "--alle-bauteile", "--anmelde-timeout", "600",
    ]) == 0
    assert aufrufe[0][1:3] == (ausgabe, profil)
    assert aufrufe[0][3]["pump_only"] is False
    assert aufrufe[0][3]["login_timeout_seconds"] == 600


def test_tips_fin_liste_ohne_duplikate_und_standardpfad(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(portal_cli, "load_saved_credentials", lambda: None)
    aufrufe = _fake_tips(monkeypatch)
    eingabe = _liste(tmp_path, f"{FIN.lower()};{FIN}\n# Kommentar\n{FIN2}\n")
    assert portal_cli.tips_main(["--eingabe", str(eingabe)]) == 0
    assert aufrufe[0][1] == (tmp_path / "data/processed/fins/tips_writer").resolve()
    assert aufrufe[0][2] == portal_cli.TIPS_PROFIL.resolve()
    assert aufrufe[1][1] == [FIN, FIN2]


@pytest.mark.parametrize("quelle", ["qec", "tips"])
def test_ungueltige_fin_verhindert_browser_und_tresorzugriff(tmp_path, monkeypatch, quelle):
    monkeypatch.setattr(
        portal_cli, "load_saved_credentials",
        lambda: pytest.fail("Keine Anmeldung bei ungueltiger FIN"),
    )
    aufrufe = _fake_qec(monkeypatch) if quelle == "qec" else _fake_tips(monkeypatch)
    main = portal_cli.qec_main if quelle == "qec" else portal_cli.tips_main
    assert main(["--eingabe", str(_liste(tmp_path, "WDD1234567890123O\n"))]) == 2
    assert aufrufe == []


@pytest.mark.parametrize("quelle", ["qec", "tips"])
def test_nur_txt_und_leer_verweigert(tmp_path, monkeypatch, quelle):
    aufrufe = _fake_qec(monkeypatch) if quelle == "qec" else _fake_tips(monkeypatch)
    main = portal_cli.qec_main if quelle == "qec" else portal_cli.tips_main
    falscher_pfad = tmp_path / "fins.csv"
    falscher_pfad.write_text(FIN, encoding="utf-8")
    assert main(["--eingabe", str(falscher_pfad)]) == 2
    assert main(["--eingabe", str(_liste(tmp_path, "# Kommentar\n"))]) == 2
    assert aufrufe == []


def test_qec_widerspruechliche_sachnummern_vor_login_abgewiesen(tmp_path, monkeypatch):
    monkeypatch.setattr(portal_cli, "load_saved_credentials",
                        lambda: pytest.fail("Login vor Validierung"))
    aufrufe = _fake_qec(monkeypatch)
    text = f"{FIN};A 123 456 78 90\n{FIN};A 456 789 01 23"
    assert portal_cli.qec_main(["--eingabe", str(_liste(tmp_path, text))]) == 2
    assert aufrufe == []


@pytest.mark.parametrize("quelle", ["qec", "tips"])
def test_manuelles_login_nutzt_keinen_keyring(tmp_path, monkeypatch, quelle):
    monkeypatch.setattr(portal_cli, "load_saved_credentials",
                        lambda: pytest.fail("Manuelles Login darf Tresor nicht lesen"))
    aufrufe = _fake_qec(monkeypatch) if quelle == "qec" else _fake_tips(monkeypatch)
    main = portal_cli.qec_main if quelle == "qec" else portal_cli.tips_main
    assert main(["--eingabe", str(_liste(tmp_path)), "--login-manuell"]) == 0
    kwargs = aufrufe[0][3]
    assert kwargs["user_id"] == ""
    assert kwargs["password"] == ""


def test_terminal_passwortabfrage_bleibt_unsichtbar(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(portal_cli, "load_saved_credentials", lambda: pytest.fail("Tresor"))
    monkeypatch.setattr(portal_cli.getpass, "getpass", lambda _: "test-passwort")
    aufrufe = _fake_tips(monkeypatch)
    assert portal_cli.tips_main([
        "--eingabe", str(_liste(tmp_path)), "--passwort-abfragen", "--benutzer-id", "uid",
    ]) == 0
    assert aufrufe[0][3]["user_id"] == "uid"
    assert aufrufe[0][3]["password"] == "test-passwort"
    captured = capsys.readouterr()
    assert "test-passwort" not in captured.out + captured.err


def test_keyring_fehlt_nutzt_browser_login(tmp_path, monkeypatch):
    def kein_tresor():
        raise RuntimeError("Tresor nicht verfuegbar")

    monkeypatch.setattr(portal_cli, "load_saved_credentials", kein_tresor)
    aufrufe = _fake_tips(monkeypatch)
    assert portal_cli.tips_main(["--eingabe", str(_liste(tmp_path))]) == 0
    assert aufrufe[0][3]["password"] == ""


@pytest.mark.parametrize("extra", [
    ["--login-manuell", "--passwort-abfragen"],
    ["--login-manuell", "--benutzer-id", "uid"],
    ["--benutzer-id", "uid"],
    ["--anmelde-timeout", "10"],
    ["--anmelde-timeout", "1000"],
])
def test_unzulaessige_argumente_stoppen_vor_login(tmp_path, monkeypatch, extra):
    monkeypatch.setattr(portal_cli, "load_saved_credentials",
                        lambda: pytest.fail("Falsche Parameter duerfen kein Login ausloesen"))
    aufrufe = _fake_tips(monkeypatch)
    assert portal_cli.tips_main(["--eingabe", str(_liste(tmp_path)), *extra]) == 2
    assert aufrufe == []


def test_edge_profil_darf_nicht_im_ausgabeordner_liegen(tmp_path, monkeypatch):
    monkeypatch.setattr(portal_cli, "load_saved_credentials",
                        lambda: pytest.fail("Bei ungueltigem Profil nicht anmelden"))
    aufrufe = _fake_tips(monkeypatch)
    ausgabe = tmp_path / "export"
    profil = ausgabe / "edge"
    assert portal_cli.tips_main([
        "--eingabe", str(_liste(tmp_path)),
        "--ausgabe", str(ausgabe), "--profil", str(profil),
    ]) == 2
    assert aufrufe == []


def test_qec_teilerfolg_ist_nicht_gruen(tmp_path, monkeypatch):
    monkeypatch.setattr(portal_cli, "load_saved_credentials", lambda: None)
    _fake_qec(monkeypatch, [
        QecResult(fin=FIN, status="Teilweise erfolgreich", warnings=["Reiter fehlt"]),
        QecResult(fin=FIN2, status="Keine passenden Schadteile"),
    ])
    assert portal_cli.qec_main(["--eingabe", str(_liste(tmp_path))]) == 1


def test_tips_fehler_ist_nicht_gruen(tmp_path, monkeypatch):
    monkeypatch.setattr(portal_cli, "load_saved_credentials", lambda: None)
    _fake_tips(monkeypatch, [
        TipsResult(fin=FIN, status="Erfolgreich"),
        TipsResult(fin=FIN2, status="Fehler", errors=["Fall fehlgeschlagen"]),
    ])
    assert portal_cli.tips_main(["--eingabe", str(_liste(tmp_path))]) == 1


def test_fehlendes_ergebnis_ist_fehler(tmp_path, monkeypatch):
    monkeypatch.setattr(portal_cli, "load_saved_credentials", lambda: None)
    _fake_tips(monkeypatch, [TipsResult(fin=FIN, status="Keine TIPS-Faelle")])
    assert portal_cli.tips_main(["--eingabe", str(_liste(tmp_path))]) == 1


def test_keyboardinterrupt_gibt_exitcode_130(tmp_path, monkeypatch):
    monkeypatch.setattr(portal_cli, "load_saved_credentials", lambda: None)

    class Abgebrochen:
        def __init__(self, *args, **kwargs):
            pass

        def run(self, fins, *, progress):
            raise KeyboardInterrupt

    monkeypatch.setattr(portal_cli, "TipsWriterDownloader", Abgebrochen)
    assert portal_cli.tips_main(["--eingabe", str(_liste(tmp_path))]) == 130


def test_alle_sechs_wheel_entrypoints_und_script_paket():
    with (ROOT / "pyproject.toml").open("rb") as file:
        config = tomllib.load(file)
    entrypoints = config["project"]["scripts"]
    assert {
        "ntf-insight-vedoc-dcdc223",
        "ntf-insight-wem",
        "ntf-insight-vedoc-codes",
        "ntf-insight-quicktests",
        "ntf-insight-qec",
        "ntf-insight-tips",
        "ntf-insight-beschaffung",
    } <= entrypoints.keys()
    assert entrypoints["ntf-insight-wem"] == "scripts.diagnosis_viewer_warn_error:main"
    assert entrypoints["ntf-insight-vedoc-dcdc223"] == "scripts.vedoc_dcdc223_seriennummern:main"
    assert (ROOT / "scripts" / "__init__.py").is_file()
    assert config["tool"]["setuptools"]["package-dir"]["scripts"] == "scripts"
