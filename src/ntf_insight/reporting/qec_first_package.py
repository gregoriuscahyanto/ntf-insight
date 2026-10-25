"""Erste LLM-Runde: ausschliesslich QEC-FIN-Liste (01) und QEC-Berichte (02).

Der Export greift bewusst NICHT auf QuickTests, AutoExport, TIPS, SMR-D oder
spaetere Lieferanten-/Clusteranalysen zu. Fachtexte/Originale sind Opt-in.
Die private Identitaetszuordnung bleibt ausserhalb der Analyse-ZIP.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from zipfile import ZIP_DEFLATED, ZipFile

from ntf_insight.ingestion.service import SourceImportService
from ntf_insight.ingestion.qec_json import QEC_SECTIONS
from ntf_insight.reporting.chatgpt_exchange import (
    ChatGPTAnalyseStore, ergebnis_schema, ergebnis_vorlage,
)
from ntf_insight.reporting.ki_analysepaket import (
    AnalysepaketErgebnis, EXPORT_VERSION, MAX_QEC_RECORDS, _code,
    _csv_file, _excel_summary, _key_order, _model_series, _safe_value, _zip_entry,
)
from ntf_insight.reporting.qec_originalbelege import (
    plan_qec_originale, write_qec_originale,
)
from ntf_insight.storage.cluster_evidence_store import part_key
from ntf_insight.storage.source_knowledge_store import SourceKnowledgeStore
from ntf_insight.storage.qec_project_scope import qec_case_matches_project
from ntf_insight.storage.workflow_projects import WorkflowProjectStore


def _safe_count(value: object) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _captured_at(doc: dict) -> datetime:
    raw = str(doc["metadata"].get("downloaded_at_utc") or "")
    try:
        result = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return result if result.tzinfo else result.replace(tzinfo=timezone.utc)
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)


def export_qec_first_package(
    service: SourceImportService,
    destination: Path,
    *,
    profile_id: str,
    part_number: str,
    selected_fins: set[str],
    selected_case_ids: set[str],
    mit_freitext: bool = False,
    mit_qec_originalen: bool = False,
    progress: Callable[[str], None] | None = None,
) -> AnalysepaketErgebnis:
    """Echte QEC-Fallkohoerte, keine FIN-weite Uebernahme fremder Schadteile."""
    target = Path(destination).expanduser().absolute()
    private_path = target.with_name(
        target.stem + "_NICHT_HOCHLADEN_ZUORDNUNG.csv"
    )
    if target.suffix.casefold() != ".zip" or not target.parent.is_dir():
        raise ValueError("Bitte einen vorhandenen Zielordner und .zip waehlen.")
    if target.exists() or private_path.exists():
        raise FileExistsError("Erste Analyse-ZIP oder private Zuordnung existiert bereits.")
    if not part_key(part_number) or not selected_fins or not selected_case_ids:
        raise ValueError("Keine eindeutige QEC-Sachnummern-/Fallauswahl in Schritt 01.")
    fins = {str(item).strip().upper() for item in selected_fins}
    case_ids = set(selected_case_ids)
    def tell(message: str) -> None:
        if progress is not None:
            progress(message)

    tell("Schritt 01: QEC-Faelle und Sachnummer exakt abgleichen ...")
    # Fremdprofile und doppelt belegte Sachnummern werden nicht vermischt.
    # Ein unbekanntes Quellprofil ist nur bei EINDEUTIGEM registriertem
    # Sachnummernprojekt erlaubt (z. B. HV-Batterie oder DC/DC-Wandler).
    projects = WorkflowProjectStore(service.store).list_projects()
    all_cases = service.store.load_cases()
    # QEC-Original ohne Sachnummer nur eindeutig per FIN+Referenz
    # einem einzigen Sachnummernkontext zuordnen.
    parts_by_qec_ref: dict[tuple[str, str], set[str]] = defaultdict(set)
    for source_case in all_cases:
        key = (
            source_case.vin.strip().upper(),
            str(source_case.qec_reference or "").strip(),
        )
        if key[0] and key[1]:
            parts_by_qec_ref[key].add(
                part_key(str(source_case.qec_part_number or ""))
            )
    chosen = [
        case for case in all_cases
        if case.case_id in case_ids
        and case.vin.strip().upper() in fins
        and qec_case_matches_project(
            case_part_number=str(case.qec_part_number or ""),
            source_profile_id=case.component_profile_id,
            project_profile_id=profile_id,
            project_part_number=part_number,
            projects=projects,
        )
        and str(case.qec_reference or "").strip()
    ]
    if len(chosen) != len(case_ids):
        raise ValueError(
            "Die QEC-Faelle aus Schritt 01 stimmen nicht vollstaendig mit "
            "dem gespeicherten Sachnummernprojekt ueberein. "
            "QEC-Liste erneut pruefen; kein projektfremder Fall wird exportiert."
        )
    chosen.sort(key=lambda c: (c.vin, c.case_id))
    if len({case.case_id for case in chosen}) != len(chosen):
        raise ValueError("Mehrdeutige QEC-Fallkennungen im Projekt.")

    secret = secrets.token_bytes(32)
    paket_id = secrets.token_hex(16)
    fin_alias = {
        fin: f"V{i:04d}" for i, fin in enumerate(
            sorted({c.vin for c in chosen}, key=lambda x: _key_order(secret, "fin", x)), 1
        )
    }
    case_alias = {
        case.case_id: f"F{i:04d}" for i, case in enumerate(
            sorted(chosen, key=lambda c: _key_order(secret, "fall", c.case_id)), 1
        )
    }
    tell("Schritt 02: QEC-Berichte nach FIN, Referenz und Sachnummer pruefen ...")
    documents = [
        doc for doc in SourceKnowledgeStore(service.store).documents()
        if doc["source_kind"] == "qec_live_report"
        and str(doc["metadata"].get("fin") or "").strip().upper() in fin_alias
    ]
    by_key: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for doc in documents:
        meta = doc["metadata"]
        by_key[(
            str(meta.get("fin") or "").strip().upper(),
            str(meta.get("reference") or "").strip(),
        )].append(doc)

    chosen_docs: dict[str, dict] = {}
    report_details: dict[str, tuple[str, str, str]] = {}
    gaps: list[dict] = []
    report_rows: list[dict] = []
    ready = 0
    for case in chosen:
        fin = case.vin.strip().upper()
        ref = str(case.qec_reference or "").strip()
        candidates = by_key.get((fin, ref), [])
        status, reason, doc = (
            "Nicht vorhanden", "Kein QEC-Bericht/keine Dokumente fuer diesen Fall", None
        )
        if candidates:
            newest = max(_captured_at(item) for item in candidates)
            latest = [item for item in candidates if _captured_at(item) == newest]
            if len({item["source_sha256"] for item in latest}) > 1:
                status, reason = "Pruefbedarf", "Mehrere QEC-Originale mit gleicher Abrufzeit"
            else:
                candidate = latest[0]
                doc_part = part_key(str(candidate["metadata"].get("part_number") or ""))
                if doc_part and doc_part != part_key(part_number):
                    status, reason = "Pruefbedarf", "Widerspruechliche QEC-Sachnummer"
                elif (
                    not doc_part
                    and parts_by_qec_ref.get((fin, ref), set())
                    != {part_key(part_number)}
                ):
                    status, reason = (
                        "Pruefbedarf",
                        "QEC-Bericht ohne Sachnummer ist projektuebergreifend "
                        "nicht eindeutig zuordenbar",
                    )
                else:
                    doc = candidate
                    meta = candidate["metadata"]
                    has_errors = bool(_safe_count(meta.get("download_errors")))
                    complete = (
                        meta.get("fresh_complete") is True
                        and _safe_count(meta.get("sections")) >= len(QEC_SECTIONS)
                        and _safe_count(meta.get("fresh_sections")) >= len(QEC_SECTIONS)
                        and not meta.get("missing_sections")
                        and not meta.get("stale_sections")
                        and not has_errors
                    )
                    status = "Vollstaendig" if complete else "Teilweise"
                    reason = (
                        "" if status == "Vollstaendig"
                        else "QEC-Reiter fehlen, sind alt oder Abruf ist unvollstaendig"
                    )
                    if has_errors:
                        reason += "; QEC-Abruf meldet Fehler"
                    if not doc_part:
                        reason = (
                            (reason + "; " if reason else "")
                            + "Sachnummer fehlt im Bericht; FIN/QEC-Referenz "
                            "ist im lokalen Datenbestand eindeutig"
                        )
                    ready += 1
                    chosen_docs[candidate["source_sha256"]] = candidate
        report_details[case.case_id] = (status, reason, doc["source_sha256"] if doc else "")
    # Zero-Report-Projekte sind ein gueltiger Anwendungsfall: alle Faelle
    # behalten ihre Platzhalter und werden als unbelegt/nicht bewertbar
    # gekennzeichnet. Weder fehlende PDFs noch fehlende QEC-Reiter blockieren.
    report_alias = {
        sha: f"Q{i:05d}" for i, sha in enumerate(
            sorted(chosen_docs, key=lambda x: _key_order(secret, "qec", x)), 1
        )
    }

    vehicles = [
        {
            "fahrzeug_id": fin_alias[fin],
            "baureihe": ";".join(sorted({
                _model_series(c.vehicle.model_series) for c in chosen
                if c.vin == fin and _model_series(c.vehicle.model_series)
            })),
            "anzahl_faelle": sum(c.vin == fin for c in chosen),
        }
        for fin in sorted(fin_alias, key=lambda x: fin_alias[x])
    ]
    cases_rows, features, ssl_rows = [], [], []
    for case in chosen:
        fid = case_alias[case.case_id]
        vid = fin_alias[case.vin]
        status, reason, sha = report_details[case.case_id]
        report = chosen_docs.get(sha)
        meta = report["metadata"] if report else {}
        # Ein anderer Import kann Tauschereignisse zu einem QEC-Fall
        # hinzufuegen. In Runde 1 gilt ausschliesslich der QEC-Excel-Anker
        # aus GENAU derselben Originalzeile wie der ausgewählte QEC-Fall.
        candidate_swap = case.investigated_replacement()
        case_source = str(case.source_ref or "")
        swap = (
            candidate_swap if candidate_swap is not None
            and case_source.startswith("raw:")
            and str(candidate_swap.source_ref or "") == case_source
            else None
        )
        swap_month = swap.occurred_at.strftime("%Y-%m") if swap else ""
        row = {
            "fall_id": fid, "fahrzeug_id": vid,
            "bauteilprofil": profile_id, "teilegruppe": "T0001",
            "baureihe": _model_series(case.vehicle.model_series),
            "tauschanker_vorhanden": int(swap is not None),
            "tausch_monat": swap_month,
            "tausch_km": swap.mileage_km if swap else None,
            "qec_bericht_id": report_alias.get(sha, ""),
            "qec_bericht_status": status,
            "qec_reiter_frisch": _safe_count(meta.get("fresh_sections")),
        }
        cases_rows.append(row)
        features.append(dict(row))
        ssl_rows.append({
            "fall_id": fid, "ssl_endbefund_code": _code(case.qec_ssl_end_code),
            "ssl_endbefund_text_opt_in": (
                str(case.qec_ssl_end_finding or "") if mit_freitext else ""
            ),
            "hinweis": "QEC-Endbefund ist ein Vorbefund, kein Ursachenbeweis.",
        })
        gaps.append({
            "fall_id": fid, "qec_bericht_status": status,
            "datenluecke": reason,
            "qec_tauschanker_fehlend": int(swap is None),
            "fehlende_reiter": ";".join(
                str(value) for value in (meta.get("missing_sections") or [])
            ) if report else ";".join(QEC_SECTIONS),
            "aeltere_reiter": ";".join(
                str(value) for value in (meta.get("stale_sections") or [])
            ),
            "fachtexte_ausgeblendet": int(not mit_freitext),
            "anhaenge_nicht_analysiert": int(
                bool(meta.get("attachments")) and not mit_qec_originalen
            ),
        })
        report_rows.append({
            "qec_bericht_id": report_alias.get(sha, ""),
            "fall_id": fid, "fahrzeug_id": vid,
            "erfassungsstand": status, "pruefhinweis": reason,
            "reiter_gesamt": _safe_count(meta.get("sections")),
            "reiter_frisch": _safe_count(meta.get("fresh_sections")),
            "formularfelder": _safe_count(meta.get("fields")),
            "tabellenzeilen": _safe_count(meta.get("table_rows")),
            "anhaenge_anzahl": _safe_count(meta.get("attachments")),
        })

    # Nur die ausgewaehlten, genau zugeordneten QEC-Dokumente lesen.
    # Keine AutoExport-/TIPS-/QuickTest-Tabellen oder spaeteren Label laden.
    evidence_rows: list[dict] = []
    row_count = 0
    shas = tuple(sorted(chosen_docs))
    if shas:
        query = (
            "SELECT source_sha256,category,source_location,label,payload_json "
            "FROM source_knowledge_rows WHERE source_sha256 IN ("
            + ",".join("?" for _ in shas) + ") AND category IN "
            "('qec_section','qec_field','qec_value','qec_table_row','qec_attachment') "
            "ORDER BY source_sha256,record_number"
        )
        with service.store.connect() as con:
            cursor = con.execute(query, list(shas))
            while True:
                batch = cursor.fetchmany(2000)
                if not batch:
                    break
                for sha, category, location, label, raw_json in batch:
                    row_count += 1
                    if row_count > MAX_QEC_RECORDS:
                        raise ValueError(
                            "Mehr als 200.000 QEC-Belegzeilen; "
                            "bitte die Fallauswahl eingrenzen."
                        )
                    data = json.loads(raw_json)
                    if not isinstance(data, dict):
                        continue
                    kind = str(data.get("typ") or "")
                    if category == "qec_section":
                        kind = "reiter"
                    elif category == "qec_table_row":
                        kind = "tabelle"
                    elif category == "qec_attachment":
                        kind = "anhang"
                    if category == "qec_field":
                        literal = _safe_value(data.get("wert"), kind.lower())
                        original = str(data.get("wert") or "")
                    elif category == "qec_value":
                        # Normalisierte Formular-/Tabellenwerte sind oft
                        # fachlich relevanter als reine Feldrohtexte.
                        kind = "normalisierter_wert"
                        literal = _safe_value(data.get("wert"), "text")
                        original = str(data.get("wert") or "")
                    elif category == "qec_section":
                        literal = ""
                        original = str(data.get("sichtbarer_text") or "")
                    elif category == "qec_table_row":
                        literal = ""
                        original = json.dumps(
                            data.get("zellen") or [], ensure_ascii=False
                        )
                    else:
                        literal = ""
                        original = json.dumps({
                            "dateiname": data.get("dateiname", ""),
                            "linktext": data.get("linktext", ""),
                        }, ensure_ascii=False)
                    evidence_rows.append({
                        "qec_bericht_id": report_alias[sha],
                        "feld_id": f"QF{row_count:07d}",
                        "reiter": str(data.get("bereich") or (
                            label if category == "qec_section" else ""
                        )),
                        "fundstelle": str(location),
                        "belegart": kind,
                        "wert_strukturiert": literal,
                        "original_beschriftung_opt_in": (
                            str(label or "") if mit_freitext else ""
                        ),
                        "original_wert_opt_in": original if mit_freitext else "",
                        "aus_vorherigem_abruf": int(
                            data.get("aus_vorherigem_abruf") is True
                        ),
                    })
                tell(f"QEC-Belege erfasst: {row_count} Zeilen ...")

    table_items = {
        "fahrzeuge": (("fahrzeug_id", "baureihe", "anzahl_faelle"), vehicles),
        "faelle": (tuple(cases_rows[0]), cases_rows),
        "fallmerkmale": (tuple(features[0]), features),
        "qec_berichte": (tuple(report_rows[0]), report_rows),
        "qec_felder": ((
            "qec_bericht_id", "feld_id", "reiter", "fundstelle",
            "belegart", "wert_strukturiert", "original_beschriftung_opt_in",
            "original_wert_opt_in", "aus_vorherigem_abruf",
        ), evidence_rows),
        "qec_datenluecken": (tuple(gaps[0]), gaps),
        "bewertungen_NICHT_CLUSTER": (tuple(ssl_rows[0]), ssl_rows),
        "methodik": (("thema", "regel"), [
            {"thema": "Analyseumfang", "regel": "Nur Workflow-Schritt 01 und 02. Keine QuickTests, AutoExport, TIPS, SMR-D oder technische Unterlagen aus Schritt 04."},
            {"thema": "NTF", "regel": "QEC-SSL-Endbefunde und Lieferantenaussagen sind nachgelagerte Bewertungen, kein Beweis fuer die Ursache und keine Clustermerkmale."},
            {"thema": "Erstentscheidung", "regel": "Nur pro Fall eine vorlaeufige NTF-Einstufung und einen begruendeten moeglichen Verursachungsbereich abgeben. KEINE Clusterbildung."},
            {"thema": "Datenluecken", "regel": "Nicht vorhandene QEC-Reiter, vorangegangene Abrufe, unanalysierte Anhaenge und fehlende Freitextfreigabe je Fall beruecksichtigen."},
            {"thema": "Fachtexte", "regel": "QEC-Freitexte nur nach gesondertem Opt-in enthalten; sie sind NICHT anonymisiert. Standardexport kann eine NTF-Hypothese nicht fuer jeden Fall absichern."},
            {"thema": "Zweite Runde", "regel": "Erst nach dieser ersten QEC-Auswertung die Zusatzquellen aus Schritt 04 in Schritt 05 gesondert interpretieren."},
        ]),
    }
    stats = {
        "fahrzeuge": len(vehicles), "faelle": len(chosen),
        "quicktests": 0, "dtcs": 0, "qec_berichte": ready,
        "freitexte": mit_freitext,
        "qec_berichte_vollstaendig": sum(
            value[0] == "Vollstaendig" for value in report_details.values()
        ),
        "qec_berichte_fehlen_oder_pruefbedarf": sum(
            item[0] in {"Nicht vorhanden", "Pruefbedarf"}
            for item in report_details.values()
        ),
        "qec_berichte_teilweise": sum(
            item[0] == "Teilweise" for item in report_details.values()
        ),
        "qec_berichte_nicht_vorhanden": sum(
            item[0] == "Nicht vorhanden" for item in report_details.values()
        ),
        "analyseumfang": "workflow_01_02_qec",
    }
    tell("QEC-Analyse-Tabellen und vorlaeufige LLM-Vorlage erzeugen ...")
    files = {
        f"{name}.csv": _csv_file(headers, rows)
        for name, (headers, rows) in table_items.items()
    }
    files["Auswertung.xlsx"] = _excel_summary(table_items, stats)
    template = ergebnis_vorlage(paket_id)
    template["verwendete_merkmale"] = [
        "QEC-Faelle aus Schritt 01 und QEC-Befunde aus Schritt 02",
    ]
    files["chatgpt_ergebnis_vorlage.json"] = json.dumps(
        template, ensure_ascii=False, indent=2
    ).encode("utf-8")
    files["chatgpt_ergebnis_schema.json"] = json.dumps(
        ergebnis_schema(), ensure_ascii=False, indent=2
    ).encode("utf-8")
    files["CHATGPT_ANWEISUNG.txt"] = (
        "NTF INSIGHT / LLM-DURCHLAUF 1: VORLAEUFIGE NTF-ENTSCHEIDUNG\n\n"
        "ZIEL: Jeden ausgewaehlten QEC-Fall einzeln und ausschliesslich "
        "auf Basis der QEC-Fallliste (01) und vorhandenen QEC-Befunde (02) "
        "vorlaeufig einstufen, ob der Fall ein plausibler NTF, ein "
        "fraglicher NTF oder kein reiner NTF ist.\n"
        "AUSGABE: Ausschliesslich eine Ergebnis-JSON gemaess "
        "chatgpt_ergebnis_schema.json und der Vorlage "
        "chatgpt_ergebnis_vorlage.json erzeugen. paket_id, analyse_id "
        "und F-/Q-Pseudonyme beibehalten. Fuer jeden Fall EINEN "
        "Datensatz in faelle[] ausgeben; keinen Fall auslassen.\n"
        "ntf_bewertung ist exakt eine dieser Aussagen:\n"
        "  - NTF plausibel: QEC-Befunde lassen einen im untersuchten "
        "Bauteil nicht reproduzierbaren Fehler begruendet plausibel "
        "erscheinen, ohne Fehlerfreiheit zu behaupten.\n"
        "  - NTF fraglich: QEC-Befunde sind unvollstaendig, unsicher "
        "oder widerspruechlich; eine NTF-Einstufung ist nicht belastbar.\n"
        "  - Kein reiner NTF: Es gibt konkrete QEC-Indizien fuer einen "
        "tatsaechlichen technischen Fehler oder eine andere Stoerungsursache.\n"
        "  - Nicht bewertbar / Nicht zuordenbar: Es fehlen geeignete "
        "QEC-Dokumente, Pruefbelege oder die Zuordnung ist unsicher. "
        "Niemals einen Nachweis erfinden.\n"
        "Bei fehlenden QEC-Berichten immer 'Nicht bewertbar' oder "
        "'Nicht zuordenbar' verwenden und die Datenluecke in "
        "pruefungen_grenzen nennen. Keine automatische NTF-Annahme.\n"
        "MOEGLICHEN VERURSACHUNGSBEREICH getrennt von ntf_bewertung "
        "in verursachungsbereich angeben: z. B. Bauteil/Lieferant, "
        "Ansteuerung/Netzwerk, Stecker/Leitung/Versorgung, "
        "Montage/Transport, Werkstatt oder Nicht zuordenbar. "
        "Immer sicherheit_zuordnung und begruendung_zuordnung "
        "ausfuellen. Lieferantenverantwortung nie ohne technische "
        "Belege behaupten.\n"
        "Konkrete Originalbefunde mit quelle=qec_berichte oder "
        "quelle=qec_felder, zugehoeriger Q-Kennung und der wirklichen "
        "feldgenauen Fundstelle belegen. SSL-Endbefund, "
        "QEC-Fachentscheidungen und Lieferantenstellungen sind "
        "Kontext, kein Beweis fuer Verursachung.\n"
        "WICHTIG: RUNDE 1 ENTHAELT KEINE CLUSTERUNG. "
        "cluster muss [] sein, clustermethode muss '' sein und "
        "cluster_id jedes Falls muss null bleiben. "
        "KEINE umfassende Ursachenpruefung, DTC-Wiederkehranalyse, "
        "Vollfahrzeugdiagnose oder technische Cluster ableiten. "
        "Diese Aufgaben erfolgen erst in LLM-DURCHLAUF 2 (Schritt 05) "
        "mit den zusaetzlichen Unterlagen aus Schritt 04.\n"
        "Alle Hinweise in qec_datenluecken.csv beruecksichtigen, "
        "insbesondere fehlende oder alte Reiter und nicht freigegebene "
        "Fachtexte. Sind QEC-Fachtexte nicht freigegeben, "
        "die reduzierte Aussagekraft angeben.\n"
        "Keine echten FINs, Originalreferenzen oder lokalen Pfade in "
        "das Ergebnis aufnehmen. Private *_NICHT_HOCHLADEN_ZUORDNUNG.csv "
        "niemals hochladen. Nur mit Unternehmensfreigabe verarbeiten.\n"
    ).encode("utf-8")
    files["README.txt"] = (
        "NTF INSIGHT - QEC-ERSTANALYSE - NUR SCHRITTE 01 UND 02\n\n"
        "Dieses ZIP enthaelt ausschliesslich QEC-Fallliste, "
        "strukturiert eingelesene QEC-Berichte und Datenluecken.\n"
        "KEINE QuickTests, KEIN AutoExport, KEINE separaten TIPS-Berichte "
        "und KEINE technischen Unterlagen aus Schritt 04/05.\n"
        "Fehlende QEC-Berichte, einzelne Dokumente oder Reiter sind "
        "ausdruecklich ZULAESSIG und blockieren den Export nicht. "
        "Alle Faelle aus Schritt 01 bleiben im Paket; ohne Beleg "
        "nur 'Nicht bewertbar' statt erfundener Aussage. "
        "RUNDE 1: EINZELFALLBEWERTUNG UND MOEGLICHER VERURSACHUNGSBEREICH, "
        "KEINE CLUSTERUNG. Umfassende Pruefung erst in Runde 2.\n"
        + ("ACHTUNG: NICHT ANONYMISIERTE QEC-FACHTEXTE ENTHALTEN.\n"
           if mit_freitext else
           "QEC-Freitexte sind NICHT enthalten; Befundtiefe ist begrenzt.\n")
        + ("ACHTUNG: QEC-ORIGINALDATEIEN MIT FINs ENTHALTEN.\n"
           if mit_qec_originalen else
           "QEC-Originaldateien und Anhaenge sind NICHT enthalten.\n")
        + "Pseudonymisierung garantiert KEINE Anonymisierung. "
        "Vor externer Weitergabe eine Unternehmensfreigabe einholen.\n"
        "Die private Fall-/FIN-Zuordnung wird separat gespeichert "
        "und darf NICHT hochgeladen werden.\n"
    ).encode("utf-8")

    original_plan = None
    if mit_qec_originalen:
        tell("Freigegebene QEC-Originale und Anhaenge pruefen ...")
        original_plan = plan_qec_originale(
            service.archive.root.parent,
            list(chosen_docs.values()),
            report_alias,
            service.list_artifacts(),
        )
    files["manifest.json"] = json.dumps({
        "schema_version": EXPORT_VERSION,
        "analyseumfang": "workflow_01_02_qec",
        "analysezweck": "ntf_erstentscheidung_ohne_cluster",
        "projektprofil": profile_id,
        "teilgruppe_pseudonym": "T0001",
        "paket_id": paket_id,
        "pseudonymisiert": not mit_freitext and not mit_qec_originalen,
        "anonymisiert_garantiert": False,
        "fachfreitexte_enthalten": mit_freitext,
        "qec_originaldateien_enthalten": bool(
            original_plan and original_plan.dateien
        ),
        "qec_originaldateien_anzahl": (
            original_plan.anzahl_dateien if original_plan else 0
        ),
        "fehlende_qec_originalberichte": (
            list(original_plan.fehlende_berichte) if original_plan else []
        ),
        "fehlende_qec_anhaenge": (
            list(original_plan.fehlende_anhaenge) if original_plan else []
        ),
        "datenreihen": stats,
        "dateien_sha256": {
            name: hashlib.sha256(data).hexdigest()
            for name, data in files.items()
        },
    }, ensure_ascii=False, indent=2).encode("utf-8")

    mapping_rows: list[dict] = []
    for fin, alias in fin_alias.items():
        mapping_rows.append({
            "art": "fahrzeug", "pseudonym": alias, "fin": fin,
        })
    for case in chosen:
        mapping_rows.append({
            "art": "fall", "pseudonym": case_alias[case.case_id],
            "fin": case.vin, "fall_id_original": case.case_id,
            "qec_referenz_original": str(case.qec_reference or ""),
            "sachnummer_original": str(case.qec_part_number or ""),
        })
    mapping_rows.append({
        "art": "teil", "pseudonym": "T0001",
        "sachnummer_original": part_number,
    })
    for sha, alias in report_alias.items():
        meta = chosen_docs[sha]["metadata"]
        mapping_rows.append({
            "art": "qec_bericht", "pseudonym": alias,
            "fin": str(meta.get("fin") or ""),
            "qec_referenz_original": str(meta.get("reference") or ""),
            "quelle_id_original": sha,
        })
    for row in mapping_rows:
        row["paket_id"] = paket_id
        row.setdefault("fin", "")
        row.setdefault("fall_id_original", "")
        row.setdefault("qec_referenz_original", "")
        row.setdefault("sachnummer_original", "")
        row.setdefault("quelle_id_original", "")
        row.setdefault("original_wert", "")
    private_bytes = _csv_file((
        "paket_id", "art", "pseudonym", "fin", "fall_id_original",
        "qec_referenz_original", "sachnummer_original", "quelle_id_original",
        "original_wert",
    ), mapping_rows)

    tell("QEC-Analyse-ZIP und private Fallzuordnung sicher speichern ...")
    zip_fd, zip_temp = tempfile.mkstemp(
        prefix=".ntf-qec-erstanalyse-", suffix=".zip", dir=target.parent
    )
    map_fd, map_temp = tempfile.mkstemp(
        prefix=".ntf-qec-privat-", suffix=".csv", dir=target.parent
    )
    os.close(zip_fd)
    os.close(map_fd)
    try:
        with ZipFile(zip_temp, "w", compression=ZIP_DEFLATED) as archive:
            for name, data in files.items():
                _zip_entry(archive, name, data)
            if original_plan is not None:
                write_qec_originale(archive, original_plan)
        Path(map_temp).write_bytes(private_bytes)
        if target.exists() or private_path.exists():
            raise FileExistsError("Exportziel wurde zwischenzeitlich belegt.")
        os.replace(zip_temp, target)
        try:
            os.replace(map_temp, private_path)
        except Exception:
            target.unlink(missing_ok=True)
            raise
    finally:
        Path(zip_temp).unlink(missing_ok=True)
        Path(map_temp).unlink(missing_ok=True)
    ChatGPTAnalyseStore(service.store).save_mapping(paket_id, mapping_rows)
    tell("QEC-Neuauswertung bereit. Weitere technische Quellen erst in Schritt 05.")
    return AnalysepaketErgebnis(
        pfad=target, private_zuordnung=private_path,
        fahrzeuge=len(vehicles), faelle=len(chosen),
        quicktests=0, dtcs=0, qec_berichte=ready,
        freitexte=mit_freitext,
        qec_originale=original_plan.anzahl_dateien if original_plan else 0,
        fehlende_qec_originale=(
            len(original_plan.fehlende_berichte)
            + len(original_plan.fehlende_anhaenge)
            if original_plan else 0
        ),
    )
