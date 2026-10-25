"""Belegbewusster Zeitvergleich QuickTest versus untersuchter Bauteiltausch.

Am gleichen Datum kann der Kilometerstand die Abfolge plausibilisieren,
nicht aber die unbekannte Uhrzeit des Ein-/Ausbaus ersetzen.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class QuickTestSwapTiming:
    phase: str
    days: int | None
    km_difference: int | None
    hint: str
    rule: str


def classify_quicktest_swap_timing(
    qt_time: datetime | None,
    qt_km: int | None,
    swap_time: datetime | None,
    swap_km: int | None,
    *,
    verified_swap: bool,
) -> QuickTestSwapTiming:
    """Keine erfundene Tauschuhrzeit, kein vermeintlich fehlender QT."""
    if not verified_swap or swap_time is None or qt_time is None:
        return QuickTestSwapTiming(
            "tauschdatum_nicht_belegt", None, None, "zeitlage_unbekannt",
            "Kein sicherer QEC-Tauschanker: QT weder vor noch nach Tausch einordnen.",
        )
    days = (qt_time.date() - swap_time.date()).days
    km_difference = (
        int(qt_km) - int(swap_km)
        if qt_km is not None and swap_km is not None
        and qt_km >= 0 and swap_km >= 0 else None
    )
    if days < 0:
        contradicts = km_difference is not None and km_difference > 0
        return QuickTestSwapTiming(
            "vor_tausch", days, km_difference,
            "datum_vor_tausch_km_widerspruch" if contradicts
            else "datum_vor_tausch",
            "QT-Datum vor QEC-Tauschdatum."
            + (" Kilometerstand liegt dennoch ueber dem Tauschstand: "
               "Datenwiderspruch pruefen." if contradicts else ""),
        )
    if days > 0:
        contradicts = km_difference is not None and km_difference < 0
        return QuickTestSwapTiming(
            "nach_tausch", days, km_difference,
            "datum_nach_tausch_km_widerspruch" if contradicts
            else "datum_nach_tausch",
            "QT-Datum nach QEC-Tauschdatum."
            + (" Kilometerstand liegt darunter: "
               "Datenwiderspruch pruefen." if contradicts else ""),
        )
    if km_difference is None:
        hint = "gleicher_tag_km_vergleich_fehlt"
        rule = (
            "QT am Tauschtag vorhanden; Tauschuhrzeit und/oder "
            "Kilometerstand unbekannt. Weder Vortausch noch Nachtausch belegt."
        )
    elif km_difference < 0:
        hint = "gleicher_tag_qt_km_kleiner"
        rule = (
            "QT am Tauschtag mit niedrigerem km als QEC-Tauschstand: "
            "plausibles Vortausch-Indiz, ohne Tauschuhrzeit NICHT bewiesen."
        )
    elif km_difference > 0:
        hint = "gleicher_tag_qt_km_groesser"
        rule = (
            "QT am Tauschtag mit hoeherem km als QEC-Tauschstand: "
            "plausibles Nachtausch-Indiz, ohne Tauschuhrzeit NICHT bewiesen."
        )
    else:
        hint = "gleicher_tag_qt_km_gleich"
        rule = (
            "QT und Tausch am gleichen Tag und km: keine Reihenfolge "
            "belegt. Nicht als fehlenden QuickTest behandeln."
        )
    return QuickTestSwapTiming(
        "zeitlich_unklar_gleicher_tag", 0, km_difference, hint, rule,
    )
