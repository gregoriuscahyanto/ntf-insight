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
                        help="Gemeinsame TXT mit FINs; bei ausschliesslich TIPS auch Fallnummern")
    parser.add_argument("--tips-eingabe", type=Path,
                        help="Optionale separate TXT fuer TIPS: FINs oder Fallnummern; "
                             "andere Quellen erhalten weiterhin --eingabe")
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
    parser.add_argument("--benennung", "--keyword", dest="benennung",
                        help="QEC: Benennung enthaelt Text (z. B. DCDC), ohne Sachnummer moeglich")
    parser.add_argument("--anhaenge", choices=("referenz", "alle"),
                        help="QEC: referenz (Standard) oder alle Dateien aus Fall-Popups")
    parser.add_argument("--ohne-quicktest-json", action="store_true",
                        help="QuickTest-PDFs nicht automatisch in lokale JSONs konvertieren")
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


def _eingabe_pruefen(
    pfad: Path, quellen: list[str] | None = None, *,
    tips_separat: bool = False,
) -> int:
    """Kurz-FIN je tatsaechlichem Eingabe-Verbraucher validieren."""
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
        verbraucher = set(quellen or ())
        if tips_separat:
            verbraucher.discard("tips")
        ungeeignet = sorted(verbraucher - {"dcdc223", "quicktests", "qec"})
        if ungeeignet:
            raise ValueError(
                "Die FIN-Liste enthaelt 14-stellige Kurz-FINs. "
                "Fuer diese sind 'vedoc-historie'/'dcdc223', 'quicktests' "
                "und 'qec' vorgesehen; nicht: "
                + ", ".join(ungeeignet)
                + ". Fuer TIPS eine separate --tips-eingabe angeben, "
                "fuer WEM/SA-Codes eine vollstaendige 17-stellige FIN-Liste."
            )
    # QEC-Sachnummern gehoeren nur in den einzelnen QEC-CLI-Lauf.
    return len(fins)


def _tips_eingabe_pruefen(pfad: Path) -> int:
    """TIPS-Quellliste vor SSO pruefen: 17-stellige FIN oder Fallnummer."""
    from ntf_insight.acquisition.fin_format import ist_gueltige_fin
    from ntf_insight.acquisition.portal_cli import lese_eingabe
    from ntf_insight.acquisition.tips_writer import parse_tips_queries

    raw = lese_eingabe(pfad)
    tokens = [
        wert.upper()
        for zeile in raw.splitlines()
        for wert in zeile.replace(",", " ").replace(";", " ").split()
    ]
    if any(
        len(wert) == 14
        and any("A" <= zeichen <= "Z" for zeichen in wert)
        and ist_gueltige_fin(wert, kurz_erlaubt=True)
        for wert in tokens
    ):
        raise ValueError(
            "Die FIN-Liste enthaelt 14-stellige Kurz-FINs. "
            "TIPS unterstuetzt nur vollstaendige 17-stellige FINs "
            "oder numerische TIPS-Fallnummern."
        )
    return len(parse_tips_queries(raw))


def _befehl(
    quelle: str, eingabe: Path, ausgabe: Path, manuell: bool,
    objekt: str | None = None, attribut: str | None = None,
    sachnummer: str | None = None, anhaenge: str | None = None,
    benennung: str | None = None,
    tips_eingabe: Path | None = None,
    ohne_quicktest_json: bool = False,
) -> list[str]:
    modul, funktion = _EINSTIEGE[quelle]
    # -u gibt Fortschritt ohne Pufferung an den Sammelprozess weiter.
    code = f"from {modul} import {funktion}; raise SystemExit({funktion}())"
    quelle_eingabe = (
        tips_eingabe if quelle == "tips" and tips_eingabe is not None else eingabe
    )
    argv = [
        sys.executable, "-u", "-c", code,
        "--eingabe", str(quelle_eingabe),
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
        if benennung is not None:
            argv.extend(("--benennung", benennung))
    if quelle == "quicktests" and ohne_quicktest_json:
        argv.append("--ohne-json")
    if manuell:
        argv.append("--login-manuell")
    return argv


def _starte_quelle(
    quelle: str, eingabe: Path, ausgabe: Path, manuell: bool,
    aktiv: dict[str, subprocess.Popen[str]], sperre: threading.Lock,
    abbruch: threading.Event, objekt: str | None = None,
    attribut: str | None = None,
    sachnummer: str | None = None, anhaenge: str | None = None,
    benennung: str | None = None,
    tips_eingabe: Path | None = None,
    ohne_quicktest_json: bool = False,
) -> int:
    if abbruch.is_set():
        return 130
    # Ohne shell=True: Leerzeichen/Sonderzeichen in FIN-Listenpfaden sicher.
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    prozess = subprocess.Popen(
        _befehl(
            quelle, eingabe, ausgabe, manuell, objekt, attribut,
            sachnummer, anhaenge, benennung, tips_eingabe, ohne_quicktest_json,
        ),
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
        if argumente.ohne_quicktest_json and "quicktests" not in auswahl:
            raise ValueError("--ohne-quicktest-json ist nur mit der Quelle quicktests erlaubt.")
        if (argumente.objekt is not None or argumente.attribut is not None) and "dcdc223" not in auswahl:
            raise ValueError("--objekt und --attribut sind nur mit der VeDoc-Historienquelle dcdc223 erlaubt.")
        if argumente.objekt is not None or argumente.attribut is not None:
            from scripts.vedoc_dcdc223_seriennummern import pruefe_historienziel
            if argumente.objekt is not None:
                argumente.objekt = pruefe_historienziel(argumente.objekt, feld="--objekt")
            if argumente.attribut is not None:
                argumente.attribut = pruefe_historienziel(argumente.attribut, feld="--attribut")
        if (argumente.sachnummer is not None or argumente.anhaenge is not None
                or argumente.benennung is not None) and "qec" not in auswahl:
            raise ValueError("--sachnummer, --benennung und --anhaenge sind nur mit der Quelle qec erlaubt.")
        if argumente.sachnummer is not None:
            from ntf_insight.acquisition.qec_tool import pruefe_sachnummer
            argumente.sachnummer = pruefe_sachnummer(argumente.sachnummer)
        if argumente.benennung is not None:
            from ntf_insight.acquisition.qec_tool import pruefe_benennung
            argumente.benennung = pruefe_benennung(argumente.benennung)
        if not 1 <= argumente.parallel <= len(_EINSTIEGE):
            raise ValueError("--parallel muss zwischen 1 und 6 liegen.")
        if argumente.tips_eingabe is not None and "tips" not in auswahl:
            raise ValueError("--tips-eingabe ist nur mit der Quelle tips erlaubt.")
        if auswahl == ["tips"] and argumente.tips_eingabe is None:
            anzahl_fins = _tips_eingabe_pruefen(argumente.eingabe)
        else:
            anzahl_fins = _eingabe_pruefen(
                argumente.eingabe, auswahl,
                tips_separat=argumente.tips_eingabe is not None,
            )
        if argumente.tips_eingabe is not None:
            tips_anzahl = _tips_eingabe_pruefen(argumente.tips_eingabe)
        else:
            tips_anzahl = None
        gruppe = (
            argumente.ausgabe.expanduser()
            if argumente.ausgabe is not None
            else Path("data") / "processed" / sicherer_listenname(argumente.eingabe)
        ).resolve()
        if gruppe.is_file():
            raise ValueError("--ausgabe muss ein Verzeichnis sein.")
        eingabe = argumente.eingabe.expanduser().resolve()
        tips_eingabe = (
            argumente.tips_eingabe.expanduser().resolve()
            if argumente.tips_eingabe is not None else None
        )
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
        f"Eingaben: {anzahl_fins} | Quellen: {len(arbeitsliste)} | "
        f"Parallel: {min(argumente.parallel, len(arbeitsliste))} | Basisordner: {gruppe}",
        flush=True,
    )
    print(
        "Eigenstaendige Edge-Fenster je Quelle. Alle sechs CLI-Quellen "
        "melden sich nacheinander per SSO/PING ID an; nach erfolgreicher Anmeldung "
        "laufen ihre FIN-Abrufe parallel. Smartphone-Freigaben einzeln bestaetigen.",
        flush=True,
    )
    for quelle, ziel in arbeitsliste:
        if quelle == "tips" and tips_eingabe is not None:
            print(
                f"[tips] Separate TIPS-Liste: {tips_eingabe} "
                f"({tips_anzahl} FIN-/Fallnummernziele).",
                flush=True,
            )
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
                argumente.sachnummer, argumente.anhaenge, argumente.benennung,
                tips_eingabe,
                argumente.ohne_quicktest_json,
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
