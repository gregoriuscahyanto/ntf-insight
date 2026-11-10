"""Format- und Identitaetspruefung fuer Mercedes-FINs in lesenden CLI-Abrufen.

Wichtig: Eine 14-stellige Kurz-FIN (Baumuster + 8 Stellen) ist keine
vollstaendige 17-stellige VIN. Niemals eine unbekannte WMI-Praefix raten:
Der Browser sucht die Eingabe unveraendert und bestaetigt anschliessend
eine exakt passende Kurz-FIN bzw. eine Voll-FIN mit genau diesem Suffix.
"""

from __future__ import annotations

import re

_FIN_14 = re.compile(r"[A-HJ-NPR-Z0-9]{14}\Z")
_FIN_17 = re.compile(r"[A-HJ-NPR-Z0-9]{17}\Z")


def ist_gueltige_fin(fin: str, *, kurz_erlaubt: bool = False) -> bool:
    """Syntaxpruefung, keine Aussage ueber die Existenz eines Fahrzeugs."""
    return bool(_FIN_17.fullmatch(fin) or (
        kurz_erlaubt and _FIN_14.fullmatch(fin)
    ))


def fin_passt_zu_anfrage(angefragt: str, angezeigt: str) -> bool:
    """Vergleiche eine Kurz-FIN nur mit identischer oder vollstaendiger VIN.

    Keine unscharfen Substring-Treffer: bei 17-stelligen Anzeigen duerfen
    nur die ersten 3 Zeichen (WMI) vom 14-stelligen Suchwert abweichen.
    """
    gesucht = angefragt.strip().upper()
    gefunden = re.sub(r"[\s-]+", "", angezeigt).upper()
    if not (ist_gueltige_fin(gesucht, kurz_erlaubt=True)
            and ist_gueltige_fin(gefunden, kurz_erlaubt=True)):
        return False
    return gefunden == gesucht or (
        len(gesucht) == 14 and len(gefunden) == 17
        and gefunden[3:] == gesucht
    )
