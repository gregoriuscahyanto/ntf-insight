"""Belegorientierte zeitliche Beziehung zwischen Diagnose und Bauteiltausch.

Ein QuickTest am gleichen Kalendertag ist nicht automatisch "nach Tausch"
oder "kein Vortausch-QT". Der Kilometerstand liefert eine ZEITLICHE
HYPOTHESE, aber ohne genaue Austauschzeit / Kilometer-Provenienz
keinen sicheren Nachweis fuer die Reihenfolge oder die Ursache.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class QuicktestSwapRelation:
    phase: str
    days: int | None
    km_difference: int | None
    confidence: str
    explanation: str


def compare_quicktest_to_swap(
    diagnosed_at: datetime, diagnosis_km: int | None,
    swapped_at: datetime, swap_km: int | None,
) -> QuicktestSwapRelation:
    """Date primary; same-day odometer differences are *indicia*.

    The caller must independently ensure identical FIN and a proven,
    project-scoped QEC replacement anchor. Clock part of swapped_at is
    ignored because a QEC date-import may assign synthetic 00:00 time.
    """
    days = (diagnosed_at.date() - swapped_at.date()).days
    km_delta = (
        int(diagnosis_km) - int(swap_km)
        if diagnosis_km is not None and swap_km is not None
        else None
    )
    if days < 0:
        if km_delta is not None and km_delta > 0:
            return QuicktestSwapRelation(
                "datum_km_widerspruch", days, km_delta, "Widerspruechlich",
                "Diagnosedatum liegt vor dem Tauschtag, Diagnose-km aber "
                "ueber Tausch-km. Datenqualitaet pruefen; "
                "keine eindeutige Reihenfolge behaupten.",
            )
        return QuicktestSwapRelation(
            "vor_tausch", days, km_delta, "Datumsbasiert",
            "QuickTest an frueherem Kalendertag als QEC-belegter Tausch. "
            "FIN- und Bauteilzuordnung separat pruefen.",
        )
    if days > 0:
        if km_delta is not None and km_delta < 0:
            return QuicktestSwapRelation(
                "datum_km_widerspruch", days, km_delta, "Widerspruechlich",
                "Diagnosedatum liegt nach dem Tauschtag, Diagnose-km "
                "aber unter Tausch-km. Datenqualitaet pruefen.",
            )
        return QuicktestSwapRelation(
            "nach_tausch", days, km_delta, "Datumsbasiert",
            "QuickTest an spaeterem Kalendertag als QEC-belegter Tausch. "
            "Gespeicherte historische DTCs sind kein Wiederkehrnachweis.",
        )
    if km_delta is None:
        return QuicktestSwapRelation(
            "zeitlich_unklar_gleicher_tag", days, None, "Offen",
            "QuickTest und Tausch am selben Kalendertag; ohne "
            "vergleichbaren Kilometerstand oder Tausch-Uhrzeit "
            "ist die Reihenfolge unbekannt.",
        )
    if km_delta < 0:
        return QuicktestSwapRelation(
            "gleicher_tag_km_vor_tausch_indiz", days, km_delta,
            "Kilometer-Indiz",
            "QuickTest am Tauschtag bei niedrigerem Kilometerstand als "
            "im QEC-Tausch dokumentiert: plausibler VOR-Tausch-Kandidat, "
            "aber ohne nachgewiesene Tausch-Uhrzeit NICHT sicher vor Tausch.",
        )
    if km_delta > 0:
        return QuicktestSwapRelation(
            "gleicher_tag_km_nach_tausch_indiz", days, km_delta,
            "Kilometer-Indiz",
            "QuickTest am Tauschtag bei hoeherem Kilometerstand: "
            "plausibler NACH-Tausch-Kandidat, kein Beweis fuer "
            "eine erneute DTC-Entstehung.",
        )
    return QuicktestSwapRelation(
        "zeitlich_unklar_gleicher_tag", days, km_delta, "Offen",
        "QuickTest und QEC-Tausch am selben Kalendertag und "
        "gleichen Kilometerstand: Reihenfolge nicht sicher bestimmbar.",
    )
