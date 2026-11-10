"""CLI fuer den QuickTest-PDF-Abruf aus dem Diagnosis Viewer.

Die GUI und diese CLI verwenden denselben DiagnosisViewerDownloader. Mercedes-SSO
kann den sicheren NTF-Insight-Tresor nutzen; die PING-ID-Freigabe bleibt manuell.
"""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

from ntf_insight.acquisition.credentials import LoginCredentials, load_saved_credentials
from ntf_insight.acquisition.output_paths import standard_ausgabe
from ntf_insight.acquisition.diagnosis_viewer import (
    DiagnosisViewerDownloader,
    FinDownloadResult,
    parse_fins,
    lokal_vorhandene_pdf,
)

STANDARD_AUSGABE = Path("data/processed/diagnosis_viewer_quicktests")
STANDARD_PROFIL = Path.home() / ".ntf-insight" / "edge-diagnosis-viewer-cli-profile"


def lade_fins(pfad: Path) -> list[str]:
    """TXT mit einer FIN je Zeile (auch BOM, Kommentare, Trennzeichen)."""
    if pfad.suffix.lower() != ".txt":
        raise ValueError("--eingabe muss auf eine .txt-Datei mit FINs zeigen.")
    inhalt = pfad.expanduser().read_text(encoding="utf-8-sig")
    zeilen = [zeile.partition("#")[0] for zeile in inhalt.splitlines()]
    return parse_fins("\n".join(zeilen), kurz_erlaubt=True)


def erstelle_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="QuickTest-PDFs je FIN aus dem Mercedes-Benz Diagnosis Viewer herunterladen."
    )
    parser.add_argument("--eingabe", type=Path, required=True,
                        help="TXT-Datei mit 14-stelligen Mercedes-Kurz-FINs oder 17-stelligen FINs")
    parser.add_argument("--ausgabe", type=Path, default=None,
                        help="Zielordner (Standard: data/processed/<TXT-Name>/diagnosis_viewer_quicktests)")
    parser.add_argument("--profil", type=Path, default=STANDARD_PROFIL,
                        help="Separates lokales Edge-Profil fuer die CLI")
    parser.add_argument("--erneut", action="store_true",
                        help="Auch FINs mit bereits gespeicherter PDF erneut herunterladen"
    parser.add_argument("--login-manuell", action="store_true",
                        help="SSO-Anmeldedaten nicht aus dem Betriebssystem-Tresor laden")
    parser.add_argument("--passwort-abfragen", action="store_true",
                        help="Benutzer-ID und Passwort fuer diesen Lauf verdeckt abfragen")
    parser.add_argument("--benutzer-id", default="",
                        help="Nur zusammen mit --passwort-abfragen verwenden")
    parser.add_argument("--anmelde-timeout", type=int, default=300,
                        help="Wartezeit fuer SSO und manuelle PING-ID-Freigabe in Sekunden (30-900)")
    return parser


def _anmeldedaten(args: argparse.Namespace) -> LoginCredentials | None:
    """Keine Geheimnisse in Kommandozeilenargumenten, Dateien oder Logs."""
    if args.login_manuell:
        return None
    if args.passwort_abfragen:
        user_id = args.benutzer_id.strip() or input("Mercedes-Benz-Benutzer-ID: ").strip()
        if not user_id:
            raise ValueError("Die Benutzer-ID darf nicht leer sein.")
        password = getpass.getpass("Mercedes-Benz-Passwort (verdeckt): ")
        if not password:
            raise ValueError("Das Passwort darf nicht leer sein.")
        return LoginCredentials(user_id=user_id, password=password)
    if args.benutzer_id.strip():
        raise ValueError("--benutzer-id nur zusammen mit --passwort-abfragen verwenden.")
    try:
        gespeichert = load_saved_credentials()
    except RuntimeError:
        print("Kein sicherer Betriebssystem-Tresor verfuegbar: SSO in Edge manuell abschliessen.",
              file=sys.stderr)
        return None
    if gespeichert:
        print("Mercedes-SSO: Zugangsdaten aus dem Betriebssystem-Tresor geladen.", flush=True)
        return gespeichert
    print("Keine gespeicherten SSO-Zugangsdaten: vorhandene Edge-Sitzung nutzen "
          "oder Anmeldung im Browser abschliessen.", flush=True)
    return None


def _bericht(ergebnisse: list[FinDownloadResult], angefragt: int, ausgabe: Path) -> int:
    fehler = 0
    pdfs = 0
    ohne_quicktest = 0
    for eintrag in ergebnisse:
        pdfs += len(eintrag.files)
        ohne_quicktest += len(eintrag.no_quicktest_sessions)
        print(f"{eintrag.fin}: {eintrag.status} | PDFs: {len(eintrag.files)} | "
              f"ohne QuickTest: {len(eintrag.no_quicktest_sessions)} | "
              f"Fehler: {len(eintrag.errors)}", flush=True)
        for meldung in eintrag.errors:
            print(f"  Fehler: {meldung}", file=sys.stderr)
        if eintrag.errors or eintrag.status in {"Fehler", "Abgebrochen"}:
            fehler += 1
    fehler += max(0, angefragt - len(ergebnisse))
    print(f"Fertig: {len(ergebnisse)}/{angefragt} FIN(s), {pdfs} PDF(s), "
          f"{ohne_quicktest} Sitzung(en) ohne QuickTest; "
          f"{fehler} FIN(s) mit Fehler/Abbruch. Ablage: {ausgabe}", flush=True)
    return 1 if fehler else 0


def main(argv: list[str] | None = None) -> int:
    parser = erstelle_parser()
    args = parser.parse_args(argv)
    try:
        if args.login_manuell and args.passwort_abfragen:
            raise ValueError("--login-manuell und --passwort-abfragen schliessen sich aus.")
        if not 30 <= args.anmelde_timeout <= 900:
            raise ValueError("--anmelde-timeout muss zwischen 30 und 900 Sekunden liegen.")
        fins = lade_fins(args.eingabe)
        ausgabe = (args.ausgabe if args.ausgabe is not None
                   else standard_ausgabe(args.eingabe, "quicktests")).expanduser().resolve()
        profil = args.profil.expanduser().resolve()
        if ausgabe.is_file():
            raise ValueError("--ausgabe muss ein Verzeichnis sein, keine Datei.")
        # Nur lokale PDFs (nicht ein Abrufstatus ohne PDF) vermeiden neue SSO-Anmeldung.
        alles_aktuell = not args.erneut and all(
            lokal_vorhandene_pdf(ausgabe, fin) is not None for fin in fins
        )
        login = None if alles_aktuell else _anmeldedaten(args)
        print(f"{len(fins)} FIN(s) | Ausgabe: {ausgabe}", flush=True)
        print("SSO wird im sichtbaren Microsoft Edge bearbeitet. "
              "PING ID bei Aufforderung auf dem Smartphone bestaetigen.", flush=True)
        downloader = DiagnosisViewerDownloader(
            ausgabe, profil,
            user_id=login.user_id if login else "",
            password=login.password if login else "",
            retry_recent=args.erneut,
            nur_fehlende_pdfs=True,
            serielle_sso=True,
            login_timeout_seconds=args.anmelde_timeout,
            kurz_fin_erlaubt=True,
        )
        ergebnisse = downloader.run(fins, progress=lambda meldung: print(meldung, flush=True))
        return _bericht(ergebnisse, len(fins), ausgabe)
    except KeyboardInterrupt:
        print("\nAbgebrochen. Bereits gespeicherte PDFs und FIN-Statusdateien bleiben erhalten.",
              file=sys.stderr)
        return 130
    except (OSError, ValueError, RuntimeError, EOFError) as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
