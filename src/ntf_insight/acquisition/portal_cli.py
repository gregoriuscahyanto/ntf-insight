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
from ntf_insight.acquisition.output_paths import standard_ausgabe
from ntf_insight.acquisition.qec_tool import (
    QecDownloader, QecResult, QecTarget, parse_qec_targets, pruefe_sachnummer,
    pruefe_benennung,
)
from ntf_insight.acquisition.tips_writer import TipsResult, TipsWriterDownloader, parse_tips_queries

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
        identitaet = (
            f"TIPS-Fall {item.suchwert}"
            + (f" | FIN {item.fin}" if item.fin else "")
            if quelle == "TIPS" and getattr(item, "suchtyp", "") == "fallnummer"
            else item.fin
        )
        print(
            f"{identitaet}: {item.status} | {extra} | Anhaenge: {anhaenge} | "
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


def _qec_ziele(raw: str, sachnummer: str | None = None) -> list[QecTarget]:
    """Optional dieselbe exakte Sachnummer auf alle FINs anwenden.

    Bereits in der TXT angegebene Sachnummern haben Vorrang, duerfen aber
    nicht still mit dem globalen Filter kollidieren.
    """
    ziele = parse_qec_targets(raw)
    if sachnummer is None:
        return ziele
    global_part = pruefe_sachnummer(sachnummer)
    compare = global_part.replace(" ", "").replace("-", "")
    result: list[QecTarget] = []
    for ziel in ziele:
        if ziel.part_number and ziel.part_number.replace(" ", "").replace("-", "") != compare:
            raise ValueError(
                f"FIN {ziel.fin}: Sachnummer in TXT widerspricht --sachnummer. "
                "Bitte eine eindeutige Sachnummer pro FIN verwenden."
            )
        result.append(QecTarget(ziel.fin, ziel.part_number or global_part, ziel.reference))
    return result


def qec_main(argv: list[str] | None = None) -> int:
    parser = _parser("QEC", ausgabe=QEC_AUSGABE, profil=QEC_PROFIL)
    parser.add_argument("--alle-bauteile", action="store_true",
                        help="Ohne Sachnummer nicht nur nach Kuehlmittelpumpen filtern")
    parser.add_argument("--sachnummer", metavar="NUMMER",
                        help="Exakte Sachnummer fuer alle FINs; Alternative zu FIN;Sachnummer in der TXT")
    parser.add_argument("--benennung", "--keyword", dest="benennung", metavar="TEXT",
                        help="QEC-Benennung enthaelt TEXT (ohne Sachnummer moeglich); "
                             "Gross-/Kleinschreibung egal, mehrere Begriffe mit Komma = ODER")
    parser.add_argument("--anhaenge", choices=("referenz", "alle"), default="referenz",
                        help="referenz: nur Referenz im Dateinamen (Standard); "
                             "alle: alle im Fall-Popup sichtbaren Anhaenge, Zuordnung ungeprueft")
    args = parser.parse_args(argv)
    try:
        if args.ausgabe is None:
            args.ausgabe = standard_ausgabe(args.eingabe, "qec")
        ausgabe, profil = _pruefe_argumente(args)
        ziele = _qec_ziele(lese_eingabe(args.eingabe), args.sachnummer)
        args.benennung = pruefe_benennung(args.benennung) if args.benennung is not None else ""
        login = _lade_login(args)
        print(
            f"QEC: {len(ziele)} FIN-/Sachnummernziel(e), "
            f"Anhangmodus: {args.anhaenge}. "
            f"Benennung: {args.benennung or 'Pumpenfilter/Sachnummer'}. "
            "SSO/PING ID bei Aufforderung in Edge/auf dem Smartphone bestaetigen.",
            flush=True,
        )
        if args.anhaenge == "alle":
            print(
                "Alle Dateien aus dem QEC-Fall-Popup werden abgerufen. "
                "Eine Referenzzuordnung ohne Dateinamen-Beleg ist NICHT verifiziert; "
                "vor der KI-/ChatGPT-Auswertung separat pruefen.",
                flush=True,
            )
        downloader = QecDownloader(
            ausgabe, profil,
            login_timeout_seconds=args.anmelde_timeout,
            user_id=login.user_id if login else "",
            password=login.password if login else "",
            pump_only=not args.alle_bauteile,
            benennung=args.benennung,
            serielle_sso=True,
            attachment_policy=args.anhaenge,
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
    parser.description = (
        "XENTRY TIPS Writer: 17-stellige FINs oder numerische TIPS-Fallnummern "
        "(4-16 Ziffern) aus einer TXT laden; auch gemischte Listen."
    )
    for option in parser._actions:
        if option.dest == "eingabe":
            option.help = (
                "TXT mit vollstaendigen 17-stelligen FINs und/oder "
                "numerischen TIPS-Fallnummern (4-16 Ziffern)"
            )
            break
    args = parser.parse_args(argv)
    try:
        if args.ausgabe is None:
            args.ausgabe = standard_ausgabe(args.eingabe, "tips")
        ausgabe, profil = _pruefe_argumente(args)
        ziele = parse_tips_queries(lese_eingabe(args.eingabe))
        anzahl_fin = sum(len(wert) == 17 for wert in ziele)
        login = _lade_login(args)
        print(
            f"TIPS: {anzahl_fin} FIN(s), {len(ziele) - anzahl_fin} Fallnummer(n). "
            "SSO/PING ID bei Aufforderung in Edge/auf dem Smartphone bestaetigen.",
            flush=True,
        )
        downloader = TipsWriterDownloader(
            ausgabe, profil,
            serielle_sso=True,
            login_timeout_seconds=args.anmelde_timeout,
            user_id=login.user_id if login else "",
            password=login.password if login else "",
            click_delay_seconds=0.85,
        )
        ergebnisse = downloader.run(ziele, progress=lambda m: print(m, flush=True))
        return _auswertung(ergebnisse, len(ziele), "TIPS", ausgabe)
    except KeyboardInterrupt:
        print("\nTIPS unterbrochen. Bereits heruntergeladene Dateien bleiben erhalten.",
              file=sys.stderr)
        return 130
    except (OSError, ValueError, RuntimeError, EOFError) as exc:
        print(f"TIPS-Fehler: {exc}", file=sys.stderr)
        return 2
