"""Lokaler QuickTest-PDF-zu-JSON-Export mit dem bestehenden XENTRY-Parser.

Der Konverter braucht weder Edge noch SSO und sendet keinerlei Daten an
externe Dienste. Er verarbeitet nur PDF-Dateien direkt unter
diagnosis_viewer_quicktests/<FIN>/ und prueft die FIN aus dem PDF.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from ntf_insight.acquisition.fin_format import fin_passt_zu_anfrage, ist_gueltige_fin
from ntf_insight.ingestion.quicktest_detailed import extract_quicktest

PDF_ORDNER = "diagnosis_viewer_quicktests"
JSON_ORDNER = "diagnosis_viewer_quicktests_json"
PARSER_VERSION = "quicktest-structure-v4-json-v1"
MAX_PDF_BYTES = 80 * 1024 * 1024
Fortschritt = Callable[[str], None]


@dataclass(frozen=True, slots=True)
class KonvertierungsErgebnis:
    gefunden: int = 0
    konvertiert: int = 0
    uebersprungen: int = 0
    fehler: int = 0
    statusdatei: Path | None = None


def _ordner(pfad: Path) -> Path:
    """Sowohl den Batch-Basisordner als auch den QuickTest-PDF-Ordner erlauben."""
    angefragt = Path(pfad).expanduser()
    if angefragt.name != PDF_ORDNER:
        angefragt = angefragt / PDF_ORDNER
    if angefragt.is_symlink() or not angefragt.is_dir():
        raise ValueError(
            f"QuickTest-PDF-Unterordner fehlt oder ist ein Link: {angefragt}. "
            "Bitte den Basisordner mit diagnosis_viewer_quicktests angeben."
        )
    return angefragt.resolve()


def _zielordner(quellenordner: Path, ausgabe: Path | None) -> Path:
    ziel = (Path(ausgabe).expanduser() if ausgabe is not None
            else quellenordner.parent / JSON_ORDNER)
    if ziel.is_symlink():
        raise ValueError("Der JSON-Ausgabeordner darf kein symbolischer Link sein.")
    ziel = ziel.resolve()
    if ziel == quellenordner or ziel.is_relative_to(quellenordner):
        raise ValueError("JSON-Ausgabe muss ausserhalb des PDF-Quellordners liegen.")
    return ziel


def _sha256(path: Path) -> str:
    if path.stat().st_size > MAX_PDF_BYTES:
        raise ValueError("QuickTest-PDF ueberschreitet 80 MB Parser-Sicherheitslimit.")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        if stream.read(5) != b"%PDF-":
            raise ValueError("Datei hat keinen gueltigen PDF-Dateikopf.")
        stream.seek(0)
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomar_json(ziel: Path, daten: dict) -> None:
    ziel.parent.mkdir(parents=True, exist_ok=True)
    if ziel.is_symlink():
        raise ValueError("JSON-Zieldatei darf kein symbolischer Link sein.")
    temporaer: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=ziel.parent,
            prefix=".quicktest_", suffix=".tmp", delete=False,
        ) as stream:
            temporaer = Path(stream.name)
            json.dump(daten, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
        os.replace(temporaer, ziel)
    finally:
        if temporaer is not None:
            temporaer.unlink(missing_ok=True)


def _ist_aktuell(ziel: Path, hashwert: str, ordner_fin: str) -> bool:
    if not ziel.is_file() or ziel.is_symlink():
        return False
    try:
        daten = json.loads(ziel.read_text(encoding="utf-8"))
        meta = daten.get("quell_pdf", {})
        return (
            isinstance(daten, dict)
            and daten.get("parser_version") == PARSER_VERSION
            and meta.get("sha256") == hashwert
            and daten.get("source_sha256") == hashwert
            and fin_passt_zu_anfrage(ordner_fin, str(daten.get("fin", "")))
            and isinstance(daten.get("ecus"), list)
            and isinstance(daten.get("page_texts"), list)
        )
    except (OSError, ValueError, TypeError, AttributeError):
        return False


def konvertiere_quicktests(
    ordner: Path,
    *,
    ausgabe: Path | None = None,
    erneut: bool = False,
    erlaubte_fins: set[str] | None = None,
    fortschritt: Fortschritt | None = None,
) -> KonvertierungsErgebnis:
    """FIN-gepruefte JSON-Spiegelstruktur; keine PDFs veraendern oder downloaden.

    Ein fehlerhaftes PDF blockiert nicht die naechsten Dateien. Ein JSON gilt
    nur als aktuell, wenn Parser-Version, PDF-SHA und innere FIN stimmen.
    """
    melden = fortschritt or (lambda _text: None)
    pdf_root = _ordner(ordner)
    ziel_root = _zielordner(pdf_root, ausgabe)
    ziel_root.mkdir(parents=True, exist_ok=True)
    if ziel_root.is_symlink():
        raise ValueError("JSON-Ausgabeordner ist ein symbolischer Link.")
    anzahl = neu = vorhanden = fehler = 0
    protokoll: list[dict] = []
    fins = sorted(
        path for path in pdf_root.iterdir()
        if path.is_dir() and not path.is_symlink()
        and ist_gueltige_fin(path.name, kurz_erlaubt=True)
        and (erlaubte_fins is None or path.name in erlaubte_fins)
    )
    for fin_ordner in fins:
        for pdf in sorted(fin_ordner.iterdir()):
            if not pdf.is_file() or pdf.is_symlink() or pdf.suffix.casefold() != ".pdf":
                continue
            anzahl += 1
            ziel = ziel_root / fin_ordner.name / f"{pdf.name}.json"
            eintrag = {
                "fin_ordner": fin_ordner.name,
                "pdf": pdf.name,
                "json": f"{fin_ordner.name}/{pdf.name}.json",
            }
            try:
                digest = _sha256(pdf)
                if not erneut and _ist_aktuell(ziel, digest, fin_ordner.name):
                    vorhanden += 1
                    eintrag["status"] = "Bereits vorhanden"
                    melden(f"{fin_ordner.name}: {pdf.name} – JSON aktuell, uebersprungen.")
                else:
                    parsed = extract_quicktest(pdf, digest).quicktest_report
                    if not isinstance(parsed, dict):
                        raise ValueError("QuickTest-Parser hat keinen Bericht erzeugt.")
                    volle_fin = str(parsed.get("fin", "")).upper()
                    if not fin_passt_zu_anfrage(fin_ordner.name, volle_fin):
                        raise ValueError(
                            "PDF-FIN passt nicht zur FIN des Quellordners; "
                            "keine Zuordnung zum falschen Fahrzeug."
                        )
                    daten = {
                        "schema_version": 1,
                        "parser_version": PARSER_VERSION,
                        "quelle": "Diagnosis Viewer QuickTest PDF",
                        "fin_ordner": fin_ordner.name,
                        "quell_pdf": {
                            "name": pdf.name,
                            "relativer_pfad": f"{PDF_ORDNER}/{fin_ordner.name}/{pdf.name}",
                            "sha256": digest,
                            "groesse_bytes": pdf.stat().st_size,
                        },
                        "konvertiert_am_utc": datetime.now(timezone.utc).isoformat(),
                        **parsed,
                    }
                    _atomar_json(ziel, daten)
                    neu += 1
                    eintrag["status"] = "Konvertiert"
                    melden(
                        f"{fin_ordner.name}: {pdf.name} – JSON erstellt; "
                        f"{len(parsed['ecus'])} ECU-Eintraege, "
                        f"{parsed['observed_dtc_count']} DTCs."
                    )
            except Exception as exc:
                # Fehlerhafte/verschluesselte PDFs duerfen weitere Dateien nicht blockieren.
                fehler += 1
                eintrag["status"] = "Fehler"
                eintrag["fehler"] = f"{type(exc).__name__}: {exc}"
                melden(f"{fin_ordner.name}: {pdf.name} – nicht konvertiert ({exc}).")
            protokoll.append(eintrag)
        # Nach jeder FIN gesichert; ein Abbruch verliert keine fertigen JSONs.
        _atomar_json(ziel_root / "konvertierungsstatus.json", {
            "schema_version": 1,
            "parser_version": PARSER_VERSION,
            "stand_utc": datetime.now(timezone.utc).isoformat(),
            "pdfs": anzahl,
            "konvertiert": neu,
            "uebersprungen": vorhanden,
            "fehler": fehler,
            "dateien": protokoll,
        })
    statusdatei = ziel_root / "konvertierungsstatus.json"
    if not fins:
        _atomar_json(statusdatei, {
            "schema_version": 1,
            "parser_version": PARSER_VERSION,
            "stand_utc": datetime.now(timezone.utc).isoformat(),
            "pdfs": 0, "konvertiert": 0, "uebersprungen": 0,
            "fehler": 0, "dateien": [],
        })
    return KonvertierungsErgebnis(
        gefunden=anzahl, konvertiert=neu,
        uebersprungen=vorhanden, fehler=fehler, statusdatei=statusdatei,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Bereits lokal heruntergeladene Diagnosis-Viewer-QuickTest-PDFs "
            "FIN-geprueft in strukturierte JSONs konvertieren; ohne Browser/SSO."
        ),
    )
    parser.add_argument(
        "--ordner", type=Path, required=True,
        help="Basisordner mit diagnosis_viewer_quicktests/ oder dieser PDF-Unterordner selbst",
    )
    parser.add_argument(
        "--ausgabe", type=Path, default=None,
        help="JSON-Zielordner (Standard: sibling diagnosis_viewer_quicktests_json/)",
    )
    parser.add_argument(
        "--erneut", action="store_true",
        help="Auch aktuelle JSONs erneut aus den lokalen PDFs erzeugen",
    )
    args = parser.parse_args(argv)
    try:
        resultat = konvertiere_quicktests(
            args.ordner, ausgabe=args.ausgabe, erneut=args.erneut,
            fortschritt=lambda meldung: print(meldung, flush=True),
        )
    except (OSError, ValueError) as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return 2
    print(
        f"QuickTest-JSON: {resultat.gefunden} PDF(s) gefunden | "
        f"{resultat.konvertiert} konvertiert | "
        f"{resultat.uebersprungen} bereits aktuell | "
        f"{resultat.fehler} Fehler | "
        f"Status: {resultat.statusdatei}",
        flush=True,
    )
    return 1 if resultat.fehler else 0


if __name__ == "__main__":
    raise SystemExit(main())
