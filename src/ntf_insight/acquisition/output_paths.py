"""Einheitliche, Windows-sichere Standardablage fuer alle Datenbeschaffungs-CLIs.

Die Ausgabe wird ausschliesslich aus dem Dateinamen der FIN-TXT abgeleitet,
nicht aus deren Inhalt oder (moeglicherweise externen) Verzeichnisnamen.
Explizites --ausgabe ueberschreibt diese Vorgabe ohne Aenderung.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from pathlib import Path

_QUELLEN = {
    "dcdc223": ("vedoc_dcdc223", None),
    "vedoc-historie": ("vedoc_historie", None),
    "wem": ("diagnosis_viewer_warn_error", "warnings_errors.json"),
    "sa-codes": ("vedoc_codes", "vedoc_codes.json"),
    "quicktests": ("diagnosis_viewer_quicktests", None),
    "qec": ("qec", None),
    "tips": ("tips_writer", None),
}
_RESERVED = {
    "CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$",
    *(f"COM{n}" for n in range(1, 10)),
    *(f"LPT{n}" for n in range(1, 10)),
}
_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')


def sicherer_listenname(eingabe: Path) -> str:
    """Windows-verbotene Zeichen ersetzen, keine absoluten/relativen Pfade zulassen.

    Maximal 80 Zeichen, mit reproduzierbarem Hash bei Verkuerzung. Leerzeichen
    innerhalb eines Namens bleiben erhalten, damit der Listenname erkennbar ist.
    """
    original = unicodedata.normalize("NFC", Path(eingabe).stem)
    wert = "".join("_" if unicodedata.category(zeichen).startswith("C") else zeichen
                   for zeichen in original)
    wert = _INVALID.sub("_", wert)
    wert = re.sub(r"\s+", " ", wert).strip(" .")
    if not wert:
        wert = "FIN-Liste"
    if wert.split(".", 1)[0].upper() in _RESERVED:
        wert = "_" + wert
    if len(wert) > 80:
        ha = hashlib.sha256(original.encode("utf-8", errors="replace")).hexdigest()[:8]
        wert = wert[:71].rstrip(" ._") + "_" + ha
    return wert


def ausgabe_in_gruppe(gruppe: Path, quelle: str) -> Path:
    """Quelle immer unter einem eigenen Unterordner der Ausgabegruppe ablegen."""
    try:
        ordner, dateiname = _QUELLEN[quelle]
    except KeyError as exc:
        raise ValueError("Unbekannte Datenquelle.") from exc
    basis = Path(gruppe) / ordner
    return basis / dateiname if dateiname else basis


def standard_ausgabe(eingabe: Path, quelle: str) -> Path:
    """Pfad im CWD: data/processed/<sicherer TXT-Stamm>/<Quelle>[/Datei.json]."""
    gruppe = Path("data") / "processed" / sicherer_listenname(eingabe)
    return ausgabe_in_gruppe(gruppe, quelle)


def quellennamen() -> tuple[str, ...]:
    return tuple(name for name in _QUELLEN if name != "vedoc-historie")
