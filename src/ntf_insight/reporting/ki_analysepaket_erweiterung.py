"""Ergaenzende, strikt getrennte KI-Exporttabellen aus bereits gespeicherten Quellen.

Ausschliesslich technische Vor-Tausch-Beobachtungen gehoeren ins Clustering.
Werkstattmassnahmen, Lieferantenbefunde und Nach-Tausch-Daten sind spaetere
Pruefbelege. Quell-SHA, FIN, Fall- und Teilenummern bleiben in der lokalen
privaten Zuordnung. Unkontrollierte Freitexte erfordern die Opt-in-Freigabe.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Callable

from ntf_insight.domain.case import NTFCase
from ntf_insight.ingestion.artifacts import SourceArtifact, SourceType
from ntf_insight.ingestion.real_source_parsers import canonical_fin
from ntf_insight.ingestion.service import SourceImportService

MAX_AUTOEXPORT_EXPORT_ROWS = 1_000_000
_CODE = re.compile(r"^[A-Za-z0-9_.:/+\-]{1,45}$")
_FIN = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$", re.I)
_SHA = re.compile(r"raw:([0-9a-f]{64})", re.I)


@dataclass
class ZusatzTabellen:
    tabellen: dict[str, tuple[tuple[str, ...], list[dict]]]
    private_zuordnungen: list[dict]
    statistiken: dict[str, int]


def autoexport_fins(service: SourceImportService) -> set[str]:
    """Alle tatsaechlich gespeicherten AutoExport-FINs; auch ohne QEC-Fall."""
    with service.store.connect() as con:
        rows = con.execute(
            "SELECT DISTINCT fin FROM source_knowledge_rows "
            "WHERE category IN ('autoexport_dtc','autoexport_repair','autoexport_tips') "
            "AND fin IS NOT NULL"
        ).fetchall()
    return {
        fin
        for (raw,) in rows
        if (fin := canonical_fin(raw)) is not None
    }


def _code(value: object) -> str:
    result = str(value or "").strip()
    return result if _CODE.fullmatch(result) and not _FIN.fullmatch(result) else ""


def _number(value: object) -> int | None:
    try:
        result = int(str(value).strip())
    except (ValueError, TypeError):
        return None
    return result if 0 <= result <= 2_000_000_000 else None


def _timestamp(value: object) -> str:
    text = str(value or "").strip()
    if not re.fullmatch(r"\d{4}-\d\d-\d\d(?:[T ][0-9:.+\-Zz]+)?", text):
        return ""
    try:
        date.fromisoformat(text[:10])
    except ValueError:
        return ""
    return text[:40]


def _relative(observed: str, replacement: object) -> tuple[str, int | None]:
    if replacement is None:
        return "kein_tausch", None
    if not observed:
        return "zeitlich_unklar", None
    try:
        diff = (date.fromisoformat(observed[:10]) - replacement.occurred_at.date()).days
    except (ValueError, TypeError, AttributeError):
        return "zeitlich_unklar", None
    # Date-only repair anchors and mixed source timezones cannot justify
    # a same-day ordering even when an AutoExport timestamp contains a clock.
    if diff == 0:
        return "zeitlich_unklar", 0
    return ("vor_tausch" if diff < 0 else "nach_tausch"), diff


def _event_timestamp(event: object) -> str:
    value = getattr(event, "occurred_at", None)
    return value.isoformat() if isinstance(value, datetime) else ""


def build_zusatztabellen(
    service: SourceImportService,
    cases: list[NTFCase],
    fahrzeug_ids: dict[str, str],
    fall_ids: dict[str, str],
    teil_ids: dict[str, str],
    *,
    secret: bytes,
    mit_freitext: bool,
    artifacts: list[SourceArtifact],
    quicktest_fallbezug: list[dict],
    quicktests: list[dict],
    progress: Callable[[str], None] | None = None,
) -> ZusatzTabellen:
    """Alle relevanten lokalen Quellen, ohne spaetere Ergebnis-Labels in cluster_input."""
    tables: dict[str, tuple[tuple[str, ...], list[dict]]] = {}
    private: list[dict] = []
    source_ids: dict[str, str] = {}
    original_aliases: dict[tuple[str, str], str] = {}
    by_fin: dict[str, list[NTFCase]] = defaultdict(list)
    for case in cases:
        by_fin[case.vin].append(case)

    def pseudonym(kind: str, value: object, prefix: str) -> str:
        original = str(value or "").strip()
        if not original:
            return ""
        key = (kind, original)
        if key not in original_aliases:
            digest = hmac.new(
                secret, (kind + "\0" + original).encode("utf-8"), hashlib.sha256,
            ).hexdigest()[:16].upper()
            alias = prefix + digest
            original_aliases[key] = alias
            private.append({
                "art": kind, "pseudonym": alias, "original_wert": original,
            })
        return original_aliases[key]

    def quellen_id(sha: str) -> str:
        if sha not in source_ids:
            alias = pseudonym("quelle", sha, "QU")
            source_ids[sha] = alias
            # Die SHA ist ausschliesslich in der lokalen Mapping-Datei.
        return source_ids[sha]

    def teil_id(raw: object) -> str:
        original = str(raw or "").strip()
        if not original:
            return ""
        if original not in teil_ids:
            teil_ids[original] = f"T{len(teil_ids) + 1:04d}"
        return teil_ids[original]

    def source_ref(event: object) -> str:
        raw = str(getattr(event, "source_ref", "") or "")
        match = _SHA.search(raw)
        return quellen_id(match.group(1).lower()) if match else ""

    def add_table(name: str, columns: tuple[str, ...], values: list[dict]) -> None:
        tables[name] = (columns, values)

    if progress:
        progress("AutoExport-Diagnosen, Reparaturen und TIPS sicher exportieren ...")
    dtcs: list[dict] = []
    relations: list[dict] = []
    repairs: list[dict] = []
    tips: list[dict] = []
    ecu_versions: list[dict] = []
    quality_auto = defaultdict(Counter)
    row_number = 0
    skipped = 0
    # Streaming aus DuckDB: keine zweite grosse Liste mit Roh-Payloads halten.
    with service.store.connect() as con:
        cursor = con.execute(
            "SELECT source_sha256,record_number,category,fin,payload_json "
            "FROM source_knowledge_rows "
            "WHERE category IN ('autoexport_dtc','autoexport_repair','autoexport_tips') "
            "ORDER BY source_sha256,record_number"
        )
        while True:
            batch = cursor.fetchmany(4000)
            if not batch:
                break
            for sha, record_number, category, fin_raw, raw_json in batch:
                row_number += 1
                if row_number > MAX_AUTOEXPORT_EXPORT_ROWS:
                    raise ValueError(
                        "Mehr als 1.000.000 AutoExport-Quellzeilen: "
                        "vollstaendigen Export bitte in freigegebene Teilpakete aufteilen."
                    )
                try:
                    data = json.loads(raw_json)
                except (ValueError, TypeError):
                    skipped += 1
                    continue
                if not isinstance(data, dict):
                    skipped += 1
                    continue
                fin = canonical_fin(fin_raw) or canonical_fin(data.get("Fin"))
                if not fin or fin not in fahrzeug_ids:
                    skipped += 1
                    continue
                vid = fahrzeug_ids[fin]
                sid = quellen_id(str(sha))
                q = _number(record_number)
                if category == "autoexport_dtc":
                    obs_id = f"AE{len(dtcs) + 1:07d}"
                    observed = _timestamp(data.get("DiagStartTs") or data.get("DiagStartDt"))
                    sw = _code(data.get("EcuSwVersionTxt"))
                    hw = _code(data.get("EcuSuppHwVersionTxt"))
                    ecu = _code(data.get("EcuNm"))
                    code = _code(data.get("EcuFaultNm"))
                    km = _number(data.get("KmReadingNum"))
                    dtcs.append({
                        "beobachtung_id": obs_id, "fahrzeug_id": vid,
                        "quelle_id": sid, "quellzeile": q,
                        "diagnosezeitpunkt": observed,
                        "zeitpraezision": "zeitpunkt" if "T" in observed else "datum" if observed else "unbekannt",
                        "km": km, "steuergeraet": ecu, "dtc_code": code,
                        "dtc_status": _code(data.get("EcuFaultStateTxt")),
                        "haeufigkeit": _number(data.get("FrequencyCounter")),
                        "dtc_text_opt_in": str(data.get("EcuFaultTxt") or "")[:4000] if mit_freitext else "",
                        "softwarestand": sw, "hardwarestand": hw,
                        "ecu_teilenummer_id": teil_id(data.get("EcuHwPartnumberCd")),
                    })
                    if sw or hw:
                        ecu_versions.append({
                            "fahrzeug_id": vid, "fall_id": "",
                            "quelle": "AutoExport", "quelle_id": sid,
                            "zeitpunkt": observed, "km": km,
                            "steuergeraet": ecu, "softwarestand": sw, "hardwarestand": hw,
                            "codierung": "",
                        })
                    for case in by_fin.get(fin, ()):
                        fid = fall_ids[case.case_id]
                        phase, days = _relative(observed, case.investigated_replacement())
                        relations.append({
                            "fall_id": fid, "beobachtung_id": obs_id,
                            "lage_zum_pumpentausch": phase, "tage_relativ_zum_tausch": days,
                        })
                        quality_auto[fid][phase] += 1
                elif category == "autoexport_repair":
                    km1 = _number(data.get("KmReadingNum"))
                    km2 = _number(data.get("KmReadingNum__2"))
                    conflict = km1 is not None and km2 is not None and km1 != km2
                    repairs.append({
                        "reparatur_id": f"AR{len(repairs) + 1:07d}",
                        "fahrzeug_id": vid, "quelle_id": sid, "quellzeile": q,
                        "reparaturdatum": _timestamp(data.get("RepairDt")),
                        "km": None if conflict else km1, "km_widerspruch": int(conflict),
                        "teilegruppe": teil_id(data.get("PartLetterCd")),
                        "fall_ids_kandidaten": ";".join(
                            fall_ids[c.case_id] for c in by_fin.get(fin, ())
                        ),
                        "beanstandung_opt_in": str(data.get("ComplDsc") or "")[:4000] if mit_freitext else "",
                        "massnahme_opt_in": str(data.get("RepairTypeNmGerman") or "")[:4000] if mit_freitext else "",
                        "werkstattnotiz_opt_in": str(data.get("WorksVisitDsc") or "")[:4000] if mit_freitext else "",
                    })
                elif category == "autoexport_tips":
                    tips.append({
                        "tips_beobachtung_id": f"AT{len(tips) + 1:07d}",
                        "fahrzeug_id": vid, "quelle_id": sid, "quellzeile": q,
                        "erstellungsdatum": _timestamp(data.get("CreationDate")),
                        "tips_referenz_id": pseudonym("tips_ref", data.get("CaseId"), "TP"),
                        "fall_ids_kandidaten": ";".join(
                            fall_ids[c.case_id] for c in by_fin.get(fin, ())
                        ),
                        "beanstandung_opt_in": str(
                            data.get("InitialWorkshopMessageCustomerComplaint") or ""
                        )[:4000] if mit_freitext else "",
                        "werkstattbefund_opt_in": str(
                            data.get("InitialWorkshopMessageWorkshopFindings") or ""
                        )[:4000] if mit_freitext else "",
                        "massnahme_opt_in": str(
                            data.get("InitialWorkshopMessagePerformedActions") or ""
                        )[:4000] if mit_freitext else "",
                    })

    # Fallereignisse sind getrennt von AutoExport-Rohbeobachtungen:
    # eine AutoExport-Diagnose wird nicht automatisch zum vollstaendigen QT.
    swap_rows: list[dict] = []
    fall_events: list[dict] = []
    supplier_rows: list[dict] = []
    for case in cases:
        fid = fall_ids[case.case_id]
        vid = fahrzeug_ids[case.vin]
        anchor = case.investigated_replacement()
        for event in case.replacements:
            swap_rows.append({
                "fall_id": fid, "fahrzeug_id": vid,
                "tausch_id": f"PT{len(swap_rows) + 1:06d}",
                "untersuchter_tausch": int(anchor is not None and anchor.event_id == event.event_id),
                "datum": _event_timestamp(event),
                "zeitpraezision": _code(getattr(event, "time_precision", "datetime")),
                "km": event.mileage_km,
                "alte_teilegruppe": teil_id(event.old_part_number),
                "neue_teilegruppe": teil_id(event.new_part_number),
                "lieferant_id": pseudonym("lieferant", event.supplier, "L"),
                "seriennummer_id": pseudonym("seriennummer", event.serial_number, "SN"),
                "charge_id": pseudonym("charge", event.batch, "CH"),
                "quelle_id": source_ref(event),
            })
        for kind, values in (
            ("diagnosesitzung", case.diagnostic_sessions),
            ("dtc", case.diagnostics),
            ("ecu_stand", case.ecu_states),
            ("reparatur", case.repairs),
            ("software_ereignis", case.software_events),
        ):
            for event in values:
                details = (
                    getattr(event, "complaint", None)
                    or getattr(event, "action", None)
                    or getattr(event, "dtc_text", None)
                    or ""
                )
                fall_events.append({
                    "ereignis_id": f"FE{len(fall_events) + 1:07d}",
                    "fall_id": fid, "fahrzeug_id": vid, "art": kind,
                    "zeitpunkt": _event_timestamp(event),
                    "zeitpraezision": _code(getattr(event, "time_precision", "datetime")),
                    "km": event.mileage_km, "quelle_id": source_ref(event),
                    "steuergeraet": _code(getattr(event, "ecu", None)),
                    "dtc_code": _code(getattr(event, "dtc_code", None)),
                    "dtc_status": _code(getattr(event, "status", None)),
                    "haeufigkeit": _number(getattr(event, "occurrence_count", None)),
                    "softwarestand": _code(getattr(event, "software_version", None)),
                    "hardwarestand": _code(getattr(event, "hardware_version", None)),
                    "diagnosesitzung_dtc_anzahl": _number(getattr(event, "dtc_count", None)),
                    "beschreibung_opt_in": str(details)[:4000] if mit_freitext else "",
                    "freeze_frame_opt_in": json.dumps(
                        getattr(event, "freeze_frame", {}), ensure_ascii=False, default=str,
                    )[:4000] if mit_freitext and kind == "dtc" else "",
                })
                if kind == "ecu_stand":
                    ecu_versions.append({
                        "fahrzeug_id": vid, "fall_id": fid,
                        "quelle": "Fallereignis", "quelle_id": source_ref(event),
                        "zeitpunkt": _event_timestamp(event), "km": event.mileage_km,
                        "steuergeraet": _code(event.ecu),
                        "softwarestand": _code(event.software_version),
                        "hardwarestand": _code(event.hardware_version),
                        "codierung": _code(event.coding),
                    })
        for finding in case.supplier_findings:
            supplier_rows.append({
                "fall_id": fid, "fahrzeug_id": vid,
                "befund_id": f"LB{len(supplier_rows) + 1:06d}",
                "befunddatum": _event_timestamp(finding),
                "lieferant_id": pseudonym("lieferant", finding.supplier, "L"),
                "ergebnis_nachtraeglich": (
                    str(getattr(finding.result, "value", finding.result))
                    if str(getattr(finding.result, "value", finding.result))
                    in {"NTF", "Fault Found", "Other", "Unknown"} else ""
                ),
                "beanstandung_reproduziert": (
                    "ja" if finding.complaint_reproduced is True else
                    "nein" if finding.complaint_reproduced is False else "unbekannt"
                ),
                "fehlerart_opt_in": str(finding.failure_mode or "")[:4000] if mit_freitext else "",
                "notizen_opt_in": str(finding.notes or "")[:4000] if mit_freitext else "",
                "quelle_id": source_ref(finding),
                "hinweis": "NUR NACH CLUSTERBILDUNG",
            })

    seen_versions: set[tuple] = set()
    unique_versions = []
    for row in ecu_versions:
        key = tuple(row.get(k) for k in (
            "fahrzeug_id", "quelle", "zeitpunkt", "km", "steuergeraet",
            "softwarestand", "hardwarestand", "codierung",
        ))
        if key not in seen_versions:
            seen_versions.add(key)
            unique_versions.append(row)

    qt_by_case: dict[str, Counter] = defaultdict(Counter)
    qt_counts = {r["quicktest_id"]: r.get("dtc_anzahl") for r in quicktests}
    for rel in quicktest_fallbezug:
        qt_by_case[rel["fall_id"]][rel["lage_zum_pumpentausch"]] += 1
        if rel["lage_zum_pumpentausch"] == "nach_tausch" and qt_counts.get(rel["quicktest_id"]) == 0:
            qt_by_case[rel["fall_id"]]["nachtest_gesamtfahrzeug_ohne_dtc"] += 1

    quality_rows = []
    for case in cases:
        fid = fall_ids[case.case_id]
        qt = qt_by_case[fid]
        auto = quality_auto[fid]
        sessions = Counter(
            _relative(_event_timestamp(event), case.investigated_replacement())[0]
            for event in case.diagnostic_sessions
        )
        no_dtc_post_sessions = sum(
            _relative(_event_timestamp(event), case.investigated_replacement())[0]
            == "nach_tausch" and event.dtc_count == 0
            for event in case.diagnostic_sessions
        )
        quality_rows.append({
            "fall_id": fid, "fahrzeug_id": fahrzeug_ids[case.vin],
            "tauschanker_vorhanden": int(case.investigated_replacement() is not None),
            "quicktests_vor": qt["vor_tausch"], "quicktests_nach": qt["nach_tausch"],
            "quicktests_zeitlich_unklar": qt["zeitlich_unklar"] + qt["kein_tausch"],
            "vollstaendige_fahrzeug_nachtests_ohne_dtc": qt["nachtest_gesamtfahrzeug_ohne_dtc"],
            "autoexport_dtc_vor_positiv": auto["vor_tausch"],
            "autoexport_dtc_nach_positiv": auto["nach_tausch"],
            "autoexport_dtc_unklar": auto["zeitlich_unklar"] + auto["kein_tausch"],
            "beidseitige_quicktests": int(qt["vor_tausch"] > 0 and qt["nach_tausch"] > 0),
            "diagnosesitzungen_fallmodell_vor": sessions["vor_tausch"],
            "diagnosesitzungen_fallmodell_nach": sessions["nach_tausch"],
            "diagnosesitzungen_fallmodell_unklar": (
                sessions["zeitlich_unklar"] + sessions["kein_tausch"]
            ),
            "diagnosesitzungen_fallmodell_nach_ohne_dtc": no_dtc_post_sessions,
            "beidseitig_vollstaendige_sitzungen": int(
                (qt["vor_tausch"] + sessions["vor_tausch"] > 0)
                and (qt["nach_tausch"] + sessions["nach_tausch"] > 0)
            ),
            "hinweis": "AutoExport-DTC-Zeilen sind KEIN vollstaendiger Test",
        })

    supplier_sources = []
    for artifact in artifacts:
        if artifact.source_type != SourceType.SUPPLIER_FINDING:
            continue
        linked = fall_ids.get(artifact.case_id_hint or "", "")
        supplier_sources.append({
            "quelle_id": quellen_id(artifact.sha256),
            "fall_id_explizit": linked,
            "dateityp": _code(Path(artifact.original_name).suffix.lower()),
            "groesse_bytes": artifact.size_bytes,
            "status": "expliziter_fallhinweis" if linked else "fallbezug_nicht_verifiziert",
            "original_im_zip": 0,
            "hinweis": "Separater Lieferantenbeleg: nicht in QEC-Anhaengen enthalten",
        })

    add_table("autoexport_diagnosen", (
        "beobachtung_id", "fahrzeug_id", "quelle_id", "quellzeile",
        "diagnosezeitpunkt", "zeitpraezision", "km", "steuergeraet", "dtc_code",
        "dtc_status", "haeufigkeit", "dtc_text_opt_in",
        "softwarestand", "hardwarestand", "ecu_teilenummer_id",
    ), dtcs)
    add_table("autoexport_fallbezug", (
        "fall_id", "beobachtung_id", "lage_zum_pumpentausch", "tage_relativ_zum_tausch",
    ), relations)
    add_table("werkstatt_historie", (
        "reparatur_id", "fahrzeug_id", "quelle_id", "quellzeile", "reparaturdatum",
        "km", "km_widerspruch", "teilegruppe", "fall_ids_kandidaten",
        "beanstandung_opt_in", "massnahme_opt_in", "werkstattnotiz_opt_in",
    ), repairs)
    add_table("autoexport_tips", (
        "tips_beobachtung_id", "fahrzeug_id", "quelle_id", "quellzeile",
        "erstellungsdatum", "tips_referenz_id", "fall_ids_kandidaten",
        "beanstandung_opt_in", "werkstattbefund_opt_in", "massnahme_opt_in",
    ), tips)
    add_table("pumpentausch_historie", (
        "fall_id", "fahrzeug_id", "tausch_id", "untersuchter_tausch",
        "datum", "zeitpraezision", "km", "alte_teilegruppe", "neue_teilegruppe",
        "lieferant_id", "seriennummer_id", "charge_id", "quelle_id",
    ), swap_rows)
    add_table("fall_ereignisse", (
        "ereignis_id", "fall_id", "fahrzeug_id", "art", "zeitpunkt",
        "zeitpraezision", "km", "quelle_id", "steuergeraet", "dtc_code",
        "dtc_status", "haeufigkeit", "softwarestand", "hardwarestand",
        "diagnosesitzung_dtc_anzahl", "beschreibung_opt_in", "freeze_frame_opt_in",
    ), fall_events)
    add_table("ecu_versionshistorie", (
        "fahrzeug_id", "fall_id", "quelle", "quelle_id", "zeitpunkt",
        "km", "steuergeraet", "softwarestand", "hardwarestand", "codierung",
    ), unique_versions)
    add_table("diagnose_qualitaet", (
        "fall_id", "fahrzeug_id", "tauschanker_vorhanden", "quicktests_vor",
        "quicktests_nach", "quicktests_zeitlich_unklar",
        "vollstaendige_fahrzeug_nachtests_ohne_dtc", "autoexport_dtc_vor_positiv",
        "autoexport_dtc_nach_positiv", "autoexport_dtc_unklar",
        "beidseitige_quicktests", "diagnosesitzungen_fallmodell_vor",
        "diagnosesitzungen_fallmodell_nach", "diagnosesitzungen_fallmodell_unklar",
        "diagnosesitzungen_fallmodell_nach_ohne_dtc",
        "beidseitig_vollstaendige_sitzungen", "hinweis",
    ), quality_rows)
    add_table("lieferantenbefunde_NICHT_CLUSTER", (
        "fall_id", "fahrzeug_id", "befund_id", "befunddatum",
        "lieferant_id", "ergebnis_nachtraeglich",
        "beanstandung_reproduziert", "fehlerart_opt_in",
        "notizen_opt_in", "quelle_id", "hinweis",
    ), supplier_rows)
    add_table("lieferantenquellen_bestand_NICHT_CLUSTER", (
        "quelle_id", "fall_id_explizit", "dateityp",
        "groesse_bytes", "status", "original_im_zip", "hinweis",
    ), supplier_sources)
    stats = {
        "autoexport_quellzeilen": row_number,
        "autoexport_uebersprungene_zeilen": skipped,
        "autoexport_dtc_zeilen": len(dtcs),
        "autoexport_werkstatt_zeilen": len(repairs),
        "autoexport_tips_zeilen": len(tips),
        "fallereignisse": len(fall_events),
        "lieferantenbefunde": len(supplier_rows),
        "lieferanten_originale_nur_inventar": len(supplier_sources),
    }
    return ZusatzTabellen(tables, private, stats)
