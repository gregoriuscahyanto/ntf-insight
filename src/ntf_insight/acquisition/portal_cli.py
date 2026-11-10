"""CLI-Einstiege fuer die vorhandenen QEC- und XENTRY-TIPS-Downloader.

Ausschliesslich die bereits von der GUI genutzten Playwright-Klassen werden
verwendet. SSO/PING-ID finden im sichtbaren Edge statt; keine Browser- oder
SSO-Geheimnisse in Eingabe-/Ausgabe- oder Protokolldateien ablegen.
"""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

from ntf_insight.acquisition.credentials import LoginCredentials, load_saved_credentials
from ntf_insight.acquisition.diagnosis_viewer import parse_fins
from ntf_insight.acquisition.output_paths import standard_ausgabe
from ntf_insight.acquisition.qec_tool import QecDownloader, QecResult, parse_qec_targets
from ntf_insight.acquisition.tips_writer import TipsResult, TipsWriterDownloader

QEC_AUSGABE = Path("data/processed/qec")
TIPS_AUSGABE = Path("data/processed/tips_writer")
QEC_PROFIL = Path.home() / ".ntf-insight" / "edge-qec-cli-profile"
TIPS_PROFIL = Path.home() / ".ntf-insight" / "edge-tips-writer-cli-profile"
_FEHLERSTATUS = {"Fehler", "Abgebrochen", "Teilweise erfolgreich", "Ergebnispruefung erforderlich"}


def lese_eingabe(pfad: Path) -> str:
    """FIN-TXT, optional mit QEC-Sachnummer; keine Netzaktion vor der Validierung."""
    if pfad.suffix.lower() != ".txt":
        raise ValueError("--eingabe muss eine .txt-Datei mit FINs sein.")
    inhalt = pfad.expanduser().read_text(encoding="utf-8-sig")
    return "\n".join(zeile.partition("#")[0].strip() for zeile in inhalt.splitlines())


def _parser(quelle: str, *, ausgabe: Path, profil: Path) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=f"{quelle} per FIN mit dem vorhandenen GUI-Downloader abrufen."
    )
    parser.add_argument("--eingabe", type=Path, required=True,
                        help="TXT mit FINs, eine FIN pro Zeile (QEC: optional ; Sachnummer)")
    parser.add_argument("--ausgabe", type=Path, default=None,
                        help=f"Lokales Zielverzeichnis (Standard unter data/processed/<TXT-Name>; bisher {ausgabe})")
    parser.add_argument("--profil", type=Path, default=profil,
                        help="Eigenes, dauerhaftes Microsoft-Edge-CLI-Profil")
    parser.add_argument("--anmelde-timeout", type=int, default=300,
                        help="SSO-/PING-ID-Wartezeit in Sekunden (30-900)")
    parser.add_argument("--login-manuell", action="store_true",
                        help="Betriebssystem-Tresor nicht lesen; Anmeldung manuell in Edge")
    parser.add_argument("--passwort-abfragen", action="store_true",
                        help="SSO-Passwort verdeckt fuer diesen Lauf im Terminal abfragen")
    parser.add_argument("--benutzer-id", default="",
                        help="Benutzerkennung, nur mit --passwort-abfragen")
    return parser


def _pruefe_argumente(args: argparse.Namespace) -> tuple[Path, Path]:
    if args.login_manuell and (args.passwort_abfragen or args.benutzer_id.strip()):
        raise ValueError("--login-manuell schliesst --passwort-abfragen/--benutzer-id aus.")
    if args.benutzer_id.strip() and not args.passwort_abfragen:
        raise ValueError("--benutzer-id nur zusammen mit --passwort-abfragen verwenden.")
    if not 30 <= args.anmelde_timeout <= 900:
        raise ValueError("--anmelde-timeout muss zwischen 30 und 900 Sekunden liegen.")
    ausgabe = args.ausgabe.expanduser().resolve()
    profil = args.profil.expanduser().resolve()
    if ausgabe.is_file() or profil.is_file():
        raise ValueError("--ausgabe und --profil muessen Verzeichnisse sein.")
    # Nie Edge-SSO-Cookies im Downloadordner oder darunter speichern.
    if ausgabe == profil or ausgabe in profil.parents or profil in ausgabe.parents:
        raise ValueError("Edge-Profil und Ausgabeverzeichnis muessen getrennt sein.")
    return ausgabe, profil


def _lade_login(args: argparse.Namespace) -> LoginCredentials | None:
    """Optionaler SSO-Tresor wie in der GUI; PING ID bleibt immer manuell."""
    if args.login_manuell:
        return None
    if args.passwort_abfragen:
        uid = args.benutzer_id.strip() or input("Mercedes-SSO-Benutzer-ID: ").strip()
        if not uid:
            raise ValueError("SSO-Benutzer-ID fehlt.")
        passwort = getpass.getpass("Mercedes-SSO-Passwort (verdeckt): ")
        if not passwort:
            raise ValueError("SSO-Passwort fehlt.")
        return LoginCredentials(user_id=uid, password=passwort)
    try:
        daten = load_saved_credentials()
    except RuntimeError:
        print("Kein sicherer SSO-Tresor erreichbar; bitte in Edge manuell anmelden.",
              file=sys.stderr)
        return None
    if daten:
        print("SSO-Zugangsdaten aus dem Betriebssystem-Tresor geladen.", flush=True)
    else:
        print("Kein gespeicherter SSO-Zugang: Anmeldung in Edge moeglich.", flush=True)
    return daten


def _auswertung(
    ergebnisse: list[QecResult] | list[TipsResult], erwartete: int, quelle: str,
    ordner: Path,
) -> int:
    mangelhaft = 0
    for item in ergebnisse:
        fehler = len(item.errors)
        warnungen = len(item.warnings)
        if quelle == "QEC":
            berichte = len(item.snapshots)
            anhaenge = len(item.files)
            extra = f"Fall-JSONs: {berichte}"
        else:
            berichte = len(item.reports)
            anhaenge = len(item.files)
            extra = f"TIPS-JSONs: {berichte}"
        print(
            f"{item.fin}: {item.status} | {extra} | Anhaenge: {anhaenge} | "
            f"Hinweise: {warnungen} | Fehler: {fehler}",
            flush=True,
        )
        if item.errors or item.status in _FEHLERSTATUS:
            mangelhaft += 1
    mangelhaft += max(0, erwartete - len(ergebnisse))
    print(
        f"{quelle}: {len(ergebnisse)}/{erwartete} FIN-/Fallabruf(e) bearbeitet; "
        f"{mangelhaft} fehlgeschlagen/unvollstaendig. Ausgabe: {ordner}",
        flush=True,
    )
    return 1 if mangelhaft else 0


def qec_main(argv: list[str] | None = None) -> int:
    parser = _parser("QEC", ausgabe=QEC_AUSGABE, profil=QEC_PROFIL)
    parser.add_argument("--alle-bauteile", action="store_true",
                        help="QEC nicht nur nach Kuehlmittelpumpen filtern")
    args = parser.parse_args(argv)
    try:
        if args.ausgabe is None:
            args.ausgabe = standard_ausgabe(args.eingabe, "qec")
        ausgabe, profil = _pruefe_argumente(args)
        ziele = parse_qec_targets(lese_eingabe(args.eingabe))
        login = _lade_login(args)
        print(
            f"QEC: {len(ziele)} FIN-/Sachnummernziel(e). "
            "SSO/PING ID bei Aufforderung in Edge/auf dem Smartphone bestaetigen.",
            flush=True,
        )
        downloader = QecDownloader(
            ausgabe, profil,
            login_timeout_seconds=args.anmelde_timeout,
            user_id=login.user_id if login else "",
            password=login.password if login else "",
            pump_only=not args.alle_bauteile,
            click_delay_seconds=0.85,
        )
        ergebnisse = downloader.run(ziele, progress=lambda m: print(m, flush=True))
        return _auswertung(ergebnisse, len(ziele), "QEC", ausgabe)
    except KeyboardInterrupt:
        print("\nQEC unterbrochen. Bereits heruntergeladene Dateien bleiben erhalten.",
              file=sys.stderr)
        return 130
    except (OSError, ValueError, RuntimeError, EOFError) as exc:
        print(f"QEC-Fehler: {exc}", file=sys.stderr)
        return 2


def tips_main(argv: list[str] | None = None) -> int:
    parser = _parser("XENTRY TIPS Writer", ausgabe=TIPS_AUSGABE, profil=TIPS_PROFIL)
    args = parser.parse_args(argv)
    try:
        if args.ausgabe is None:
            args.ausgabe = standard_ausgabe(args.eingabe, "tips")
        ausgabe, profil = _pruefe_argumente(args)
        fins = parse_fins(lese_eingabe(args.eingabe))
        login = _lade_login(args)
        print(
            f"TIPS: {len(fins)} FIN(s). "
            "SSO/PING ID bei Aufforderung in Edge/auf dem Smartphone bestaetigen.",
            flush=True,
        )
        downloader = TipsWriterDownloader(
            ausgabe, profil,
            login_timeout_seconds=args.anmelde_timeout,
            user_id=login.user_id if login else "",
            password=login.password if login else "",
            click_delay_seconds=0.85,
        )
        ergebnisse = downloader.run(fins, progress=lambda m: print(m, flush=True))
        return _auswertung(ergebnisse, len(fins), "TIPS", ausgabe)
    except KeyboardInterrupt:
        print("\nTIPS unterbrochen. Bereits heruntergeladene Dateien bleiben erhalten.",
              file=sys.stderr)
        return 130
    except (OSError, ValueError, RuntimeError, EOFError) as exc:
        print(f"TIPS-Fehler: {exc}", file=sys.stderr)
        return 2
