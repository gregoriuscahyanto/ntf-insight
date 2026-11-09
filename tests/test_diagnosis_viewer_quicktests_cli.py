"""Offline-Tests fuer den QuickTest-CLI-Einstieg (ohne Firmenzugang)."""

from __future__ import annotations

from pathlib import Path

import pytest

from ntf_insight.acquisition import diagnosis_viewer_cli as cli
from ntf_insight.acquisition.credentials import LoginCredentials
from ntf_insight.acquisition.diagnosis_viewer import FinDownloadResult

FIN = "WDD12345678901234"
FIN_ZWEI = "WDD12345678901235"


def _eingabe(tmp_path: Path) -> Path:
    pfad = tmp_path / "fins.txt"
    pfad.write_text(f"{FIN}\n{FIN_ZWEI}\n", encoding="utf-8")
    return pfad


def _fake_downloader(monkeypatch, ergebnisse=None):
    aufrufe = []

    class Downloader:
        def __init__(self, ausgabe, profil, **kwargs):
            aufrufe.append((ausgabe, profil, kwargs))

        def run(self, fins, *, progress):
            aufrufe.append(list(fins))
            progress("Synthetischer Abruf")
            return ergebnisse if ergebnisse is not None else [
                FinDownloadResult(fin=fin, status="Erfolgreich") for fin in fins
            ]

    monkeypatch.setattr(cli, "DiagnosisViewerDownloader", Downloader)
    return aufrufe


def test_lade_fins_kommentare_bom_trennzeichen_und_deduplizierung(tmp_path):
    pfad = tmp_path / "fins.txt"
    pfad.write_text(
        f"\ufeff# Test-FINs\n{FIN.lower()}; {FIN} # Dublette\n{FIN_ZWEI},\n",
        encoding="utf-8",
    )
    assert cli.lade_fins(pfad) == [FIN, FIN_ZWEI]


@pytest.mark.parametrize("text", ["123\n", "WDD1234567890O234\n", "# leer\n"])
def test_ungueltige_eingaben_stoppen_vor_browserstart(tmp_path, monkeypatch, text):
    pfad = tmp_path / "fins.txt"
    pfad.write_text(text, encoding="utf-8")
    aufrufe = _fake_downloader(monkeypatch)
    assert cli.main(["--eingabe", str(pfad)]) == 2
    assert aufrufe == []


def test_nur_txt_erlaubt(tmp_path):
    pfad = tmp_path / "fins.csv"
    pfad.write_text(FIN, encoding="utf-8")
    with pytest.raises(ValueError, match=".txt"):
        cli.lade_fins(pfad)


def test_standardpfad_und_automatischer_login_aus_gui_tresor(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "load_saved_credentials", lambda: LoginCredentials("beispiel-id", "test-passwort"))
    aufrufe = _fake_downloader(monkeypatch)
    assert cli.main(["--eingabe", str(_eingabe(tmp_path))]) == 0
    ausgabe, profil, kwargs = aufrufe[0]
    assert ausgabe == (tmp_path / cli.STANDARD_AUSGABE).resolve()
    assert profil == cli.STANDARD_PROFIL.resolve()
    assert kwargs["user_id"] == "beispiel-id"
    assert kwargs["password"] == "test-passwort"
    assert kwargs["login_timeout_seconds"] == 300
    assert kwargs["retry_recent"] is False
    assert aufrufe[1] == [FIN, FIN_ZWEI]
    ausgabe_text = capsys.readouterr().out
    assert "PING ID" in ausgabe_text
    assert "test-passwort" not in ausgabe_text


def test_ausgabe_profil_erneut_und_deaktivierter_tresor(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "load_saved_credentials", lambda: pytest.fail("Tresor darf nicht gelesen werden"))
    aufrufe = _fake_downloader(monkeypatch)
    ausgabe = tmp_path / "export"
    profil = tmp_path / "eigenes-profil"
    assert cli.main([
        "--eingabe", str(_eingabe(tmp_path)),
        "--ausgabe", str(ausgabe), "--profil", str(profil),
        "--erneut", "--login-manuell", "--anmelde-timeout", "600",
    ]) == 0
    assert aufrufe[0][0] == ausgabe
    assert aufrufe[0][1] == profil
    assert aufrufe[0][2]["retry_recent"] is True
    assert aufrufe[0][2]["login_timeout_seconds"] == 600
    assert aufrufe[0][2]["user_id"] == ""


def test_manuelle_passwortabfrage_nur_im_speicher(tmp_path, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt: "neue-id")
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: "neues-passwort")
    monkeypatch.setattr(cli, "load_saved_credentials", lambda: pytest.fail("Tresor nicht verwenden"))
    aufrufe = _fake_downloader(monkeypatch)
    assert cli.main(["--eingabe", str(_eingabe(tmp_path)), "--passwort-abfragen"]) == 0
    assert aufrufe[0][2]["user_id"] == "neue-id"
    assert aufrufe[0][2]["password"] == "neues-passwort"


def test_tresor_nicht_verfuegbar_erlaubt_browser_login(tmp_path, monkeypatch, capsys):
    def kein_tresor():
        raise RuntimeError("Tresor nicht erreichbar")

    monkeypatch.setattr(cli, "load_saved_credentials", kein_tresor)
    aufrufe = _fake_downloader(monkeypatch)
    assert cli.main(["--eingabe", str(_eingabe(tmp_path))]) == 0
    assert aufrufe[0][2]["user_id"] == ""
    assert aufrufe[0][2]["password"] == ""
    assert "SSO in Edge manuell" in capsys.readouterr().err


def test_24h_sperre_vermeidet_passwortzugriff(tmp_path, monkeypatch):
    monkeypatch.setattr(
        cli, "recently_attempted", lambda root, fin: FinDownloadResult(fin=fin)
    )
    monkeypatch.setattr(cli, "load_saved_credentials", lambda: pytest.fail("Nicht benoetigt"))
    ergebnisse = [FinDownloadResult(fin=FIN, status="Übersprungen (< 24 h)"),
                  FinDownloadResult(fin=FIN_ZWEI, status="Übersprungen (< 24 h)")]
    aufrufe = _fake_downloader(monkeypatch, ergebnisse)
    assert cli.main(["--eingabe", str(_eingabe(tmp_path))]) == 0
    assert aufrufe[0][2]["password"] == ""


def test_teilerfolg_mit_fehler_liefert_exitcode_eins(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "load_saved_credentials", lambda: None)
    ergebnisse = [
        FinDownloadResult(fin=FIN, status="Teilweise erfolgreich", errors=["PDF-Timeout"]),
        FinDownloadResult(fin=FIN_ZWEI, status="Keine Quicktests", no_quicktest_sessions=["S1"]),
    ]
    _fake_downloader(monkeypatch, ergebnisse)
    assert cli.main(["--eingabe", str(_eingabe(tmp_path))]) == 1


@pytest.mark.parametrize("weitere", [
    ["--login-manuell", "--passwort-abfragen"],
    ["--anmelde-timeout", "20"],
    ["--benutzer-id", "id-ohne-passwort"],
])
def test_ungueltige_cli_kombinationen(tmp_path, monkeypatch, weitere):
    _fake_downloader(monkeypatch)
    assert cli.main(["--eingabe", str(_eingabe(tmp_path)), *weitere]) == 2
