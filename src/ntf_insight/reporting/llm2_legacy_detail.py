"""Kompatibilitaet fuer das alte, frei erweiterte LLM2-Detail-JSON.

Der original empfangene JSON-Text bleibt im Importarchiv erhalten.
Nur die interne, streng validierte Fallansicht wird kanonisiert. Der
Adapter ist bewusst KEIN generelles extra=allow fuer beliebige LLM-Daten.
"""
from __future__ import annotations

from copy import deepcopy
import re

_LEGACY_CASE = {
    "fahrzeug_id", "qec_bericht_id", "baureihe", "sachnummer_pseudonym",
    "tausch_monat", "tausch_km", "cluster_alt", "ntf_bewertung_alt",
    "aenderung_gegenueber_erstlauf", "qt_anzahl", "qt_zeitkategorien",
    "vortausch_dtc_codes", "vortausch_ecu_versionen",
    "datumsbezogen_vor_tausch_qt", "gleicher_tag_km_vor_tausch_indiz_qt",
    "dato_km_widerspruch_qt", "nach_tausch_neuer_ereigniskm_dtc",
    "fall_duplikat_pruefen",
}
_CATEGORY = {
    "Kurzschluss/Sicherung": "Kurzschluss / Sicherung",
    "Bus/Kommunikation": "Bus / Kommunikation",
    "Leistung/Temperatur": "Leistung / Funktion / Temperatur",
    "Feuchte/Korrosion": "Feuchte / Korrosion / Abdichtung",
    "Mechanik": "Mechanik / Geräusch / Beschädigung",
    "Ansteuerung": "Ansteuerung / Software / Regelung",
    "Versorgung/Masse": "Versorgung / Spannung / Masse",
    "Leitung/Stecker": "Sonstige Symptome",
    "Unbekannt": "Unbekannt",
}
_STATUS = {
    "Werkstattangabe": "Werkstattangabe",
    "Diagnosehinweis": "Diagnostisch belegt",
    "Labor-Sichtbefund": "Laborbefund",
    "Nicht zuordenbar": "Hypothese / unbestätigt",
}
_PROFILE = {
    "Kein materialer Sichtbefund als NOK verifiziert":
        "Laborfehler nicht reproduziert",
    "Optischer Sichtbefund NOK": "Laborbefund optisch auffällig",
    "Kein geeigneter zeitnaher pumpenbezogener Vortausch-DTC nach heuristischem 90-Tage-Fenster":
        "Datenlage unzureichend",
    "QuickTest an Kalendertag vor Tausch": "Diagnose vor Tausch (Datum)",
    "Taggleicher Vortausch-Kandidat, Uhrzeit unbekannt":
        "Diagnose am Tauschtag (km-Indiz vor)",
    "Gleicher ECU/DTC neu nach Tausch registriert":
        "Diagnose nach Tausch (Datum)",
}


def _check_metadata(row: dict) -> None:
    for field, pattern in (
        ("fahrzeug_id", r"V\d{4,6}"),
        ("qec_bericht_id", r"Q\d{5,7}"),
    ):
        if not isinstance(row.get(field), str) or not re.fullmatch(
            pattern, row[field],
        ):
            raise ValueError(f"Ungueltiges Fall-Pseudonym: {field}.")
    for field in (
        "baureihe", "sachnummer_pseudonym", "tausch_monat",
        "ntf_bewertung_alt", "aenderung_gegenueber_erstlauf",
        "vortausch_dtc_codes",
    ):
        if not isinstance(row.get(field), str) or len(row[field]) > 2000:
            raise ValueError(f"Ungueltiges LLM2-Zusatzfeld: {field}.")
    if row.get("cluster_alt") is not None and (
        not isinstance(row["cluster_alt"], str)
        or len(row["cluster_alt"]) > 90
    ):
        raise ValueError("Alte Clusterkennung ungueltig.")
    for field in (
        "tausch_km", "qt_anzahl", "datumsbezogen_vor_tausch_qt",
        "gleicher_tag_km_vor_tausch_indiz_qt", "dato_km_widerspruch_qt",
        "nach_tausch_neuer_ereigniskm_dtc",
    ):
        value = row.get(field)
        if field == "tausch_km" and value is None:
            continue
        if type(value) is not int or not 0 <= value <= 100000000:
            raise ValueError(f"Ungueltiges LLM2-Zahlenfeld: {field}.")
    phases = row.get("qt_zeitkategorien")
    if not isinstance(phases, dict) or len(phases) > 20 or any(
        not isinstance(k, str) or len(k) > 90 or type(v) is not int
        or not 0 <= v <= 1000000 for k, v in phases.items()
    ):
        raise ValueError("Alte QuickTest-Zeitkategorien ungueltig.")
    versions = row.get("vortausch_ecu_versionen")
    if not isinstance(versions, list) or len(versions) > 50 or any(
        not isinstance(v, dict)
        or set(v) != {"ecu", "softwarestand", "hardwarestand"}
        or any(not isinstance(x, str) or len(x) > 200 for x in v.values())
        for v in versions
    ):
        raise ValueError("Alte ECU-Staende ungueltig.")
    duplicates = row.get("fall_duplikat_pruefen")
    if not isinstance(duplicates, list) or len(duplicates) > 50 or any(
        not isinstance(s, str) or re.fullmatch(r"F\d{4,6}", s) is None
        for s in duplicates
    ):
        raise ValueError("Alte Fall-Duplikatbelege ungueltig.")


def normalize_legacy_llm2_detail(
    value: object, *, root_fields: set[str], case_fields: set[str],
) -> dict | None:
    """Nur bekannte alte Detailausgabe projizieren, sonst None zurueckgeben.

    Zusatzbelege aus Nachweisprofilen werden in belege[] aufgenommen,
    sodass sie dieselbe lokale Alias-/Fundstellenpruefung durchlaufen.
    """
    if not isinstance(value, dict) or "erklaerung_zusatzfelder" not in value:
        return None
    if value.get("fehlerbild_methodik") != "multilabel_symptom_nachweis_v2":
        raise ValueError("Erweiterte LLM2-Antwort ohne Methodikmarkierung.")
    if set(value) - root_fields != {"erklaerung_zusatzfelder"}:
        raise ValueError("Unbekannte LLM2-Zusatzfelder auf oberster Ebene.")
    explanation = value["erklaerung_zusatzfelder"]
    if not isinstance(explanation, str) or len(explanation) > 3000:
        raise ValueError("Ungueltige Erklaerung der LLM2-Zusatzfelder.")
    if not isinstance(value.get("faelle"), list):
        raise ValueError("Keine LLM2-Fallliste im Detailformat.")

    converted = deepcopy(value)
    converted.pop("erklaerung_zusatzfelder")
    for index, row in enumerate(converted["faelle"], 1):
        if not isinstance(row, dict) or set(row) - case_fields != _LEGACY_CASE:
            raise ValueError(f"Unbekannte LLM2-Zusatzfelder in Fall {index}.")
        _check_metadata(row)
        raw_symptoms = row.get("fehlerbilder")
        if not isinstance(raw_symptoms, list) or len(raw_symptoms) > 15:
            raise ValueError("Ungueltige LLM2-Fehlerbildliste.")
        by_category: dict[str, list[dict]] = {}
        for symptom in raw_symptoms:
            if not isinstance(symptom, dict) or set(symptom) != {
                "kategorie", "nachweisstatus", "sicherheit", "begruendung", "belege",
            }:
                raise ValueError("Ungueltiges LLM2-Fehlerbildobjekt.")
            category = _CATEGORY.get(symptom["kategorie"])
            status = _STATUS.get(symptom["nachweisstatus"])
            if category is None or status is None:
                raise ValueError("Unbekannte LLM2-Fehlerbildkategorie/-Nachweisstufe.")
            by_category.setdefault(category, []).append(symptom)
        normalized = []
        for category, findings in by_category.items():
            evidence = []
            for finding in findings:
                if not isinstance(finding["belege"], list):
                    raise ValueError("Ungueltige LLM2-Fehlerbildbelege.")
                for item in finding["belege"]:
                    if item not in evidence:
                        evidence.append(item)
            reasons = " | ".join(
                f"{finding['kategorie']} ({finding['nachweisstatus']}): "
                f"{finding['begruendung']}"
                for finding in findings
            )
            statuses = {_STATUS[f["nachweisstatus"]] for f in findings}
            normalized.append({
                "kategorie": category,
                "nachweisstatus": (
                    next(iter(statuses)) if len(statuses) == 1
                    else "Mehrfach belegt"
                ),
                # Unterschiedliche Quellen rechtfertigen keine hoehere Sicherheit.
                "sicherheit": (
                    findings[0]["sicherheit"] if len(findings) == 1
                    else "Niedrig"
                ),
                "begruendung": reasons,
                "belege": evidence,
            })
        row["fehlerbilder"] = normalized

        detailed_profiles = row.get("nachweisprofil")
        if not isinstance(detailed_profiles, list) or len(detailed_profiles) > 12:
            raise ValueError("Ungueltiges detailliertes LLM2-Nachweisprofil.")
        labels = []
        combined = list(row.get("belege", []))
        for entry in detailed_profiles:
            if not isinstance(entry, dict) or set(entry) != {
                "quelle", "nachweisstatus", "sicherheit", "begruendung", "belege",
            }:
                raise ValueError("Ungueltiges LLM2-Nachweisobjekt.")
            label = _PROFILE.get(entry["nachweisstatus"])
            if label is None:
                raise ValueError("Unbekannter LLM2-Nachweisprofilstatus.")
            if label not in labels:
                labels.append(label)
            if not isinstance(entry["belege"], list):
                raise ValueError("Ungueltige LLM2-Nachweisprofilbelege.")
            for evidence in entry["belege"]:
                if evidence not in combined:
                    combined.append(evidence)
        row["nachweisprofil"] = labels
        row["belege"] = combined
        for key in _LEGACY_CASE:
            row.pop(key)
    return converted
