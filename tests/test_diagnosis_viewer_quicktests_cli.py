"""Offline-Tests fuer den QuickTest-CLI-Einstieg (ohne Firmenzugang)."""

from __future__ import annotations

from pathlib import Path

import pytest

from ntf_insight.acquisition import diagnosis_viewer_cli as cli
from ntf_insight.acquisition.credentials import LoginCredentials
from ntf_insight.acquisition.diagnosis_viewer import FinDownloadResult
from ntf_insight.acquisition.quicktest_json import KonvertierungsErgebnis

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
    monkeypatch.setattr(
        cli, "konvertiere_quicktests",
        lambda *_args, **_kwargs: KonvertierungsErgebnis(),
    )
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
    assert ausgabe == (tmp_path / "data/processed/fins/diagnosis_viewer_quicktests").resolve()
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


def test_vorhandene_pdf_vermeiden_login_unabhaengig_von_24h(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    ordner = tmp_path / "data/processed/fins/diagnosis_viewer_quicktests"
    for fin in (FIN, FIN_ZWEI):
        ziel = ordner / fin
        ziel.mkdir(parents=True)
        (ziel / "test.pdf").write_bytes(b"%PDF-1.7\\nOffline-Test")
    monkeypatch.setattr(cli, "load_saved_credentials", lambda: pytest.fail("Nicht benoetigt"))
    ergebnisse = [FinDownloadResult(fin=FIN, status="Übersprungen (PDF bereits vorhanden)"),
                  FinDownloadResult(fin=FIN_ZWEI, status="Übersprungen (PDF bereits vorhanden)")]
    aufrufe = _fake_downloader(monkeypatch, ergebnisse)
    assert cli.main(["--eingabe", str(_eingabe(tmp_path))]) == 0
    assert aufrufe[0][2]["password"] == ""
    assert aufrufe[0][2]["nur_fehlende_pdfs"] is True
    assert aufrufe[0][2]["serielle_sso"] is True


def test_keine_pdf_trotz_juengstem_fehler_erfordert_login(tmp_path, monkeypatch):
    """Ohne echte PDF im richtigen FIN-Ordner ist der Abruf nicht erledigt."""
    monkeypatch.setattr(
        cli, "load_saved_credentials", lambda: LoginCredentials("uid", "secret")
    )
    aufrufe = _fake_downloader(monkeypatch)
    ordner = tmp_path / "diagnose"
    ordner.mkdir()
    (ordner / FIN).mkdir()
    (ordner / FIN / "abrufstatus.json").write_text('{"status":"Fehler"}', encoding="utf-8")
    assert cli.main([
        "--eingabe", str(_eingabe(tmp_path)), "--ausgabe", str(ordner),
    ]) == 0
    assert aufrufe[0][2]["user_id"] == "uid"
    assert aufrufe[0][2]["nur_fehlende_pdfs"] is True


def test_erneut_umgeht_auch_vorhandene_pdfs(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "load_saved_credentials", lambda: LoginCredentials("uid", "pw"))
    ausgabe = tmp_path / "mit-pdfs"
    (ausgabe / FIN).mkdir(parents=True)
    (ausgabe / FIN / "quicktest.pdf").write_bytes(b"%PDF-1.7\\nOffline")
    aufrufe = _fake_downloader(monkeypatch)
    assert cli.main([
        "--eingabe", str(_eingabe(tmp_path)), "--ausgabe", str(ausgabe),
        "--erneut",
    ]) == 0
    assert aufrufe[0][2]["retry_recent"] is True
    assert aufrufe[0][2]["user_id"] == "uid"


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



def test_kurz_fin_als_cli_eingabe_und_downloader_opt_in(tmp_path, monkeypatch):
    """14 Zeichen duerfen vor dem SSO passieren, ohne eine WMI zu erfinden."""
    kurz = "1671061B000001"  # Synthetisch, keine reale FIN
    datei = tmp_path / "kurz.txt"
    datei.write_text(kurz + "\n", encoding="utf-8")
    monkeypatch.setattr(cli, "load_saved_credentials", lambda: None)
    aufrufe = _fake_downloader(monkeypatch)
    assert cli.lade_fins(datei) == [kurz]
    assert cli.main(["--eingabe", str(datei)]) == 0
    assert aufrufe[1] == [kurz]
    assert aufrufe[0][2]["kurz_fin_erlaubt"] is True



def test_quicktest_cli_konvertiert_auch_bei_pdf_skip_json_standardmaessig(
    tmp_path, monkeypatch,
):
    """JSON-Konvertierung laeuft ohne weitere PING ID auch bei alten PDFs."""
    source = tmp_path / "alte-downloads"
    pdf = source / FIN / "test.pdf"
    pdf.parent.mkdir(parents=True)
    pdf.write_bytes(b"%PDF-1.7\nSynthetisch")
    monkeypatch.setattr(
        cli, "load_saved_credentials",
        lambda: pytest.fail("Bei vorhandenen PDFs kein SSO-Tresor"),
    )
    _fake_downloader(monkeypatch, [
        FinDownloadResult(fin=FIN, status="Übersprungen (PDF bereits vorhanden)"),
        FinDownloadResult(fin=FIN_ZWEI, status="Keine Quicktests"),
    ])
    converter_calls = []

    def convert(ordner, **options):
        converter_calls.append((ordner, options))
        return KonvertierungsErgebnis(
            gefunden=1, konvertiert=1,
            statusdatei=ordner.parent / "diagnosis_viewer_quicktests_json/konvertierungsstatus.json",
        )

    monkeypatch.setattr(cli, "konvertiere_quicktests", convert)
    # 2. FIN hat kein PDF; fuer dieses Beispiel Login-Zugriff simulieren.
    monkeypatch.setattr(cli, "load_saved_credentials", lambda: None)
    assert cli.main([
        "--eingabe", str(_eingabe(tmp_path)), "--ausgabe", str(source),
    ]) == 0
    assert len(converter_calls) == 1
    assert converter_calls[0][0] == source
    assert converter_calls[0][1]["erlaubte_fins"] == {FIN, FIN_ZWEI}


def test_quicktest_cli_ohne_json_bewahrt_alten_pdf_ablauf(tmp_path, monkeypatch):
    _fake_downloader(monkeypatch)
    monkeypatch.setattr(
        cli, "konvertiere_quicktests",
        lambda *_args, **_kwargs: pytest.fail("Mit --ohne-json keine Konvertierung."),
    )
    monkeypatch.setattr(cli, "load_saved_credentials", lambda: None)
    assert cli.main([
        "--eingabe", str(_eingabe(tmp_path)), "--ohne-json",
    ]) == 0


def test_quicktest_cli_json_fehler_ist_nicht_stillschweigend_erfolgreich(
    tmp_path, monkeypatch,
):
    _fake_downloader(monkeypatch)
    monkeypatch.setattr(cli, "load_saved_credentials", lambda: None)
    monkeypatch.setattr(
        cli, "konvertiere_quicktests",
        lambda *_args, **_kwargs: KonvertierungsErgebnis(fehler=1, gefunden=2),
    )
    assert cli.main(["--eingabe", str(_eingabe(tmp_path))]) == 1
