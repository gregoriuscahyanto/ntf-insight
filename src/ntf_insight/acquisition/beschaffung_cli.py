"""Mehrere unabhängige Datenquellen parallel aus der gleichen FIN-Liste abrufen.

Jeder Abruf laeuft als separater Python-Prozess mit dem bestehenden CLI-Einstieg
und dessen eigenem Edge-Profil. Nie zwei Instanzen derselben Quelle starten:
Downloads und Checkpoints einer Quelle bleiben seriell und wiederaufnehmbar.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from ntf_insight.acquisition.diagnosis_viewer import parse_fins
from ntf_insight.acquisition.output_paths import (
    ausgabe_in_gruppe, quellennamen, sicherer_listenname,
)

# Statische, fest hinterlegte Entry-Points; Nutzereingaben werden niemals als
# Code oder Shell-Befehle ausgefuehrt.
_EINSTIEGE = {
    "dcdc223": ("scripts.vedoc_dcdc223_seriennummern", "main"),
    "wem": ("scripts.diagnosis_viewer_warn_error", "main"),
    "sa-codes": ("ntf_insight.acquisition.vedoc_codes", "main"),
    "quicktests": ("ntf_insight.acquisition.diagnosis_viewer_cli", "main"),
    "qec": ("ntf_insight.acquisition.portal_cli", "qec_main"),
    "tips": ("ntf_insight.acquisition.portal_cli", "tips_main"),
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Mehrere NTF-Datenquellen parallel je FIN-Liste herunterladen."
    )
    parser.add_argument("--eingabe", type=Path, required=True,
                        help="Gemeinsame TXT mit FINs (eine FIN pro Zeile)")
    parser.add_argument("--ausgabe", type=Path,
                        help="Optionaler Basisordner fuer alle Quellen; Standard: "
                             "data/processed/<bereinigter TXT-Name>")
    parser.add_argument("--quellen", default="alle",
                        help="Kommagetrennt: dcdc223 (Alias vedoc-historie),wem,sa-codes,quicktests,qec,tips "
                             "(Standard: alle)")
    parser.add_argument("--parallel", type=int, default=2,
                        help="Maximale Anzahl gleichzeitiger Datenquellen (1-6; Standard: 2)")
    parser.add_argument("--objekt", "--steuergeraet", dest="objekt",
                        help="VeDoc-Hardwareobjekt fuer die Quelle dcdc223, z. B. CPC3")
    parser.add_argument("--attribut",
                        help="VeDoc-Historienattribut fuer dcdc223, Standard: Seriennummer")
    parser.add_argument("--sachnummer",
                        help="QEC: exakte Sachnummer fuer alle FINs, z. B. A 123 456 78 90")
    parser.add_argument("--anhaenge", choices=("referenz", "alle"),
                        help="QEC: referenz (Standard) oder alle Dateien aus Fall-Popups")
    parser.add_argument("--login-manuell", action="store_true",
                        help="Alle Quellen mit manueller Anmeldung im sichtbaren Edge starten")
    return parser


def _quellen(text: str) -> list[str]:
    auswahl = list(quellennamen()) if text.strip().lower() == "alle" else [
        "dcdc223" if teil.strip().lower() == "vedoc-historie" else teil.strip().lower()
        for teil in text.split(",")
    ]
    if not auswahl or any(teil not in _EINSTIEGE for teil in auswahl):
        raise ValueError(
            "--quellen: erlaubt sind dcdc223 (Alias vedoc-historie),wem,sa-codes,quicktests,qec,tips oder alle."
        )
    # Doppelte Quellen duerfen niemals dieselben FIN-Checkpoints parallel schreiben.
    if len(auswahl) != len(set(auswahl)):
        raise ValueError("--quellen enthaelt dieselbe Datenquelle mehrfach.")
    return auswahl


def _eingabe_pruefen(pfad: Path, quellen: list[str] | None = None) -> int:
    """Kurz-FIN nur erlauben, wenn alle ausgewaehlten Quellen sie verarbeiten."""
    if pfad.suffix.lower() != ".txt":
        raise ValueError("--eingabe muss eine .txt-Datei sein.")
    zeilen = [
        zeile.partition("#")[0]
        for zeile in pfad.expanduser().read_text(encoding="utf-8-sig").splitlines()
    ]
    fins = parse_fins("\n".join(zeilen), kurz_erlaubt=True)
    # Andere Quellen haben eigene strengere 17-Zeichen-Validierung.
    # Keine halben Batch-Ergebnisse erzeugen, deren Ursache bereits feststeht.
    if any(len(fin) == 14 for fin in fins):
        ungeeignet = sorted(set(quellen or ()) - {"dcdc223", "quicktests"})
        if ungeeignet:
            raise ValueError(
                "Die FIN-Liste enthaelt 14-stellige Kurz-FINs. "
                "Fuer diese werden derzeit nur 'vedoc-historie'/'dcdc223' "
                "und 'quicktests' unterstuetzt; nicht: "
                + ", ".join(ungeeignet)
                + ". Bitte --quellen vedoc-historie,quicktests verwenden "
                "oder fuer weitere Quellen vollstaendige 17-stellige FINs bereitstellen."
            )
    # QEC-Sachnummern gehoeren nur in den einzelnen QEC-CLI-Lauf.
    return len(fins)


def _befehl(
    quelle: str, eingabe: Path, ausgabe: Path, manuell: bool,
    objekt: str | None = None, attribut: str | None = None,
    sachnummer: str | None = None, anhaenge: str | None = None,
) -> list[str]:
    modul, funktion = _EINSTIEGE[quelle]
    # -u gibt Fortschritt ohne Pufferung an den Sammelprozess weiter.
    code = f"from {modul} import {funktion}; raise SystemExit({funktion}())"
    argv = [
        sys.executable, "-u", "-c", code,
        "--eingabe", str(eingabe),
        "--ausgabe", str(ausgabe),
    ]
    if quelle == "dcdc223":
        if objekt is not None:
            argv.extend(("--objekt", objekt))
        if attribut is not None:
            argv.extend(("--attribut", attribut))
    if quelle == "qec":
        if sachnummer is not None:
            argv.extend(("--sachnummer", sachnummer))
        if anhaenge is not None:
            argv.extend(("--anhaenge", anhaenge))
    if manuell:
        argv.append("--login-manuell")
    return argv


def _starte_quelle(
    quelle: str, eingabe: Path, ausgabe: Path, manuell: bool,
    aktiv: dict[str, subprocess.Popen[str]], sperre: threading.Lock,
    abbruch: threading.Event, objekt: str | None = None,
    attribut: str | None = None,
    sachnummer: str | None = None, anhaenge: str | None = None,
) -> int:
    if abbruch.is_set():
        return 130
    # Ohne shell=True: Leerzeichen/Sonderzeichen in FIN-Listenpfaden sicher.
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    prozess = subprocess.Popen(
        _befehl(quelle, eingabe, ausgabe, manuell, objekt, attribut, sachnummer, anhaenge),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        bufsize=1, text=True, encoding="utf-8", errors="replace", env=env,
    )
    with sperre:
        aktiv[quelle] = prozess
        if abbruch.is_set():
            prozess.terminate()
    try:
        if prozess.stdout is not None:
            with prozess.stdout:
                for zeile in prozess.stdout:
                    print(f"[{quelle}] {zeile.rstrip()}", flush=True)
        return prozess.wait()
    finally:
        with sperre:
            aktiv.pop(quelle, None)


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    argumente = parser.parse_args(argv)
    try:
        auswahl = _quellen(argumente.quellen)
        if (argumente.objekt is not None or argumente.attribut is not None) and "dcdc223" not in auswahl:
            raise ValueError("--objekt und --attribut sind nur mit der VeDoc-Historienquelle dcdc223 erlaubt.")
        if argumente.objekt is not None or argumente.attribut is not None:
            from scripts.vedoc_dcdc223_seriennummern import pruefe_historienziel
            if argumente.objekt is not None:
                argumente.objekt = pruefe_historienziel(argumente.objekt, feld="--objekt")
            if argumente.attribut is not None:
                argumente.attribut = pruefe_historienziel(argumente.attribut, feld="--attribut")
        if (argumente.sachnummer is not None or argumente.anhaenge is not None
                ) and "qec" not in auswahl:
            raise ValueError("--sachnummer und --anhaenge sind nur mit der Quelle qec erlaubt.")
        if argumente.sachnummer is not None:
            from ntf_insight.acquisition.qec_tool import pruefe_sachnummer
            argumente.sachnummer = pruefe_sachnummer(argumente.sachnummer)
        if not 1 <= argumente.parallel <= len(_EINSTIEGE):
            raise ValueError("--parallel muss zwischen 1 und 6 liegen.")
        anzahl_fins = _eingabe_pruefen(argumente.eingabe, auswahl)
        gruppe = (
            argumente.ausgabe.expanduser()
            if argumente.ausgabe is not None
            else Path("data") / "processed" / sicherer_listenname(argumente.eingabe)
        ).resolve()
        if gruppe.is_file():
            raise ValueError("--ausgabe muss ein Verzeichnis sein.")
        eingabe = argumente.eingabe.expanduser().resolve()
        # Eine frei gewaehlte Hardware-Historie nutzt den neutralen Quellordner.
        generisch = (
            argumente.objekt is not None or argumente.attribut is not None
            or "vedoc-historie" in [teil.strip().lower()
                                   for teil in argumente.quellen.split(",")]
        )
        arbeitsliste = [
            (q, ausgabe_in_gruppe(
                gruppe, "vedoc-historie" if q == "dcdc223" and generisch else q,
            ))
            for q in auswahl
        ]
    except (OSError, ValueError) as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return 2

    print(
        f"FINs: {anzahl_fins} | Quellen: {len(arbeitsliste)} | "
        f"Parallel: {min(argumente.parallel, len(arbeitsliste))} | Basisordner: {gruppe}",
        flush=True,
    )
    print(
        "Eigenstaendige Edge-Fenster je Quelle. VeDoc-Historie und QuickTests "
        "melden sich nacheinander per PING ID an; nach erfolgreicher Anmeldung "
        "laufen ihre FIN-Abrufe parallel. Smartphone-Freigaben nacheinander bestaetigen.",
        flush=True,
    )
    for quelle, ziel in arbeitsliste:
        print(f"[{quelle}] Ablage: {ziel}", flush=True)

    aktiv: dict[str, subprocess.Popen[str]] = {}
    sperre = threading.Lock()
    abbruch = threading.Event()
    ergebnisse: dict[str, int] = {}
    with ThreadPoolExecutor(max_workers=min(argumente.parallel, len(arbeitsliste))) as pool:
        futures = {
            pool.submit(
                _starte_quelle, quelle, eingabe, ziel, argumente.login_manuell,
                aktiv, sperre, abbruch,
                argumente.objekt, argumente.attribut,
                argumente.sachnummer, argumente.anhaenge,
            ): quelle
            for quelle, ziel in arbeitsliste
        }
        try:
            for future in as_completed(futures):
                quelle = futures[future]
                try:
                    status = future.result()
                except OSError as exc:
                    print(f"[{quelle}] Prozess konnte nicht starten: {exc}",
                          file=sys.stderr, flush=True)
                    status = 2
                ergebnisse[quelle] = status
                print(f"[{quelle}] beendet mit Exitcode {status}", flush=True)
        except KeyboardInterrupt:
            abbruch.set()
            with sperre:
                for prozess in aktiv.values():
                    if prozess.poll() is None:
                        prozess.terminate()
            for future in futures:
                future.cancel()
            print(
                "Sammelabruf abgebrochen. Bereits gespeicherte Quelldateien bleiben erhalten.",
                file=sys.stderr, flush=True,
            )
            return 130

    anzahl_fehler = sum(code != 0 for code in ergebnisse.values())
    print(
        f"Sammelabruf abgeschlossen: {len(ergebnisse) - anzahl_fehler}/"
        f"{len(arbeitsliste)} Datenquellen erfolgreich. Basisordner: {gruppe}",
        flush=True,
    )
    return 1 if anzahl_fehler else 0


if __name__ == "__main__":
    raise SystemExit(main())
