"""Kompaktes, fallbezogenes KI-Analysepaket: keine Originaldateien.

Der Export bildet ein HINWEIS-/Analysepaket, keinen Unternehmens-Datenfreigabe-
mechanismus. Pseudonyme ersetzen FINs und QEC-IDs, verhindern aber nicht
zwangsläufig eine Reidentifizierung aus seltenen technischen Merkmalen.
Die reale Zuordnung bleibt stets als gesonderte lokale Datei außerhalb der ZIP.
"""
from __future__ import annotations

import csv
import hashlib
import hmac
import io
import json
import os
import re
import secrets
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

from ntf_insight.domain.case import NTFCase
from ntf_insight.ingestion.artifacts import SourceType
from ntf_insight.ingestion.service import SourceImportService
from ntf_insight.storage.quicktest_store import QuickTestStore
from ntf_insight.storage.source_knowledge_store import SourceKnowledgeStore
from ntf_insight.ingestion.qec_json import list_downloaded_qec_reports
from ntf_insight.ingestion.artifacts import sha256_file
from ntf_insight.reporting.chatgpt_exchange import (
    ChatGPTAnalyseStore, ergebnis_schema, ergebnis_vorlage,
)
from ntf_insight.reporting.qec_originalbelege import (
    plan_qec_originale, write_qec_originale,
)

EXPORT_VERSION = 2
_FIN_RE = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$", re.I)
_SAFE_CODE_RE = re.compile(r"^[A-Za-z0-9_.:/+\-]{1,45}$")
MAX_QEC_RECORDS = 200_000


@dataclass(frozen=True)
class AnalysepaketErgebnis:
    pfad: Path
    private_zuordnung: Path
    fahrzeuge: int
    faelle: int
    quicktests: int
    dtcs: int
    qec_berichte: int
    freitexte: bool
    qec_originale: int = 0
    fehlende_qec_originale: int = 0


def _safe_tabular(value):
    """Keep untrusted source text literal in Excel AND spreadsheet-opened CSV."""
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def _csv_file(headers: tuple[str, ...], rows: list[dict]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=headers, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    for item in rows:
        writer.writerow({
            name: "" if item.get(name) is None else _safe_tabular(item.get(name))
            for name in headers
        })
    return ("\ufeff" + stream.getvalue()).encode("utf-8")


def _zip_entry(archive: ZipFile, name: str, content: bytes) -> None:
    # No local filesystem paths, account names or creation timestamps in ZIP headers.
    info = ZipInfo(name, (1980, 1, 1, 0, 0, 0))
    info.compress_type = ZIP_DEFLATED
    info.external_attr = 0o600 << 16
    archive.writestr(info, content)


def _key_order(secret: bytes, domain: str, value: str) -> str:
    return hmac.new(secret, (domain + "\0" + value).encode("utf-8"), "sha256").hexdigest()


def _code(value: object) -> str:
    text = str(value or "").strip()
    if not _SAFE_CODE_RE.fullmatch(text):
        return ""
    if _FIN_RE.fullmatch(text):
        return ""
    return text


def _model_series(value: object) -> str:
    text = _code(value)
    return text[:24]


def _date(value: object) -> str:
    return value.date().isoformat() if isinstance(value, datetime) else ""


def _phase(diagnosed: datetime, replacement) -> tuple[str, int | None]:
    if replacement is None:
        return "kein_tausch", None
    swap = replacement.occurred_at
    if diagnosed.date() == swap.date() and getattr(replacement, "time_precision", "") == "date":
        return "zeitlich_unklar", 0
    if diagnosed == swap:
        return "zeitlich_unklar", 0
    return ("vor_tausch" if diagnosed < swap else "nach_tausch"), (diagnosed.date() - swap.date()).days


def _safe_value(value: object, kind: str) -> str:
    """Only non-identifying scalar literals; no uncontrolled QEC/Workshop text."""
    text = str(value or "").strip()
    if kind in {"checkbox", "radio"} and text.casefold() in {"ja", "nein", "true", "false", "0", "1"}:
        return text.casefold()
    if kind in {"number", "numeric", "integer"} and re.fullmatch(r"[+\-]?\d{1,10}(?:[.,]\d{1,5})?", text):
        return text
    return ""


def _excel_summary(tables: dict[str, tuple[tuple[str, ...], list[dict]]], stats: dict) -> bytes:
    workbook = Workbook()
    summary = workbook.active
    summary.title = "Übersicht"
    summary.append(["NTF Insight | KI-Analysepaket"])
    summary.append(["Stand", "Pseudonymisierte, strukturierte Quelldaten"])
    summary.append(["Fahrzeuge", stats["fahrzeuge"]])
    summary.append(["QEC-/NTF-Fälle", stats["faelle"]])
    summary.append(["QuickTest-Berichte", stats["quicktests"]])
    summary.append(["DTC-Beobachtungen", stats["dtcs"]])
    summary.append(["QEC-JSON-Berichte", stats["qec_berichte"]])
    summary.append(["Freitext aus QEC/TIPS", "Enthalten" if stats["freitexte"] else "Nicht enthalten"])
    summary.append(["Hinweis", "Private Zuordnung bleibt lokal; Freitext kann echte Identifikatoren enthalten."])
    summary.append(["Methodik", "Clustermerkmale vor Tausch; spätere Befunde/Bewertungen separat."])
    for sheet_name, table_name in (
        ("Fallliste", "faelle"),
        ("Falldaten", "fallmerkmale"),
        ("Belege", "qec_felder"),
        ("Methodik", "methodik"),
    ):
        headers, rows = tables[table_name]
        sheet = workbook.create_sheet(sheet_name)
        sheet.append(headers)
        # Compact workbook is a human-readable companion; CSV is complete.
        for row in rows[:5000]:
            sheet.append([
                str(_safe_tabular(row.get(header) or ""))[:30000]
                if not isinstance(row.get(header), (int, float)) else row[header]
                for header in headers
            ])
        sheet.freeze_panes = "B2"
        sheet.auto_filter.ref = f"A1:{sheet.cell(1, len(headers)).column_letter}{sheet.max_row}"
        sheet.sheet_view.showGridLines = False
        for col in sheet.columns:
            letter = col[0].column_letter
            sheet.column_dimensions[letter].width = min(
                44, max(15, len(str(col[0].value or "")) + 3)
            )
        for cell in sheet[1]:
            cell.fill = PatternFill(fill_type="solid", fgColor="171717")
            cell.font = Font(color="FFFFFF", bold=True)
            cell.alignment = Alignment(wrap_text=True, vertical="center")
        sheet.row_dimensions[1].height = 34
    summary.column_dimensions["A"].width = 29
    summary.column_dimensions["B"].width = 79
    summary.sheet_view.showGridLines = False
    summary["A1"].font = Font(size=17, color="171717", bold=True)
    for row in summary.iter_rows(min_row=2, max_col=1):
        row[0].font = Font(bold=True, color="555555")
    buffer = io.BytesIO()
    workbook.save(buffer)
    workbook.close()
    return buffer.getvalue()


def export_ki_analysepaket(
    service: SourceImportService,
    destination: Path,
    *,
    mit_freitext: bool = False,
    mit_qec_originalen: bool = False,
    progress: Callable[[str], None] | None = None,
) -> AnalysepaketErgebnis:
    """Export structured local evidence, with no source files or source IDs.

    Separate case/vehicle/QEC reference identifiers are random per export.
    The ONLY reversible mapping is created alongside the archive, never inside.
    Free text is optional, explicitly sensitive and NOT reliably anonymized.
    """
    target = Path(destination).expanduser().absolute()
    if target.suffix.lower() != ".zip":
        raise ValueError("KI-Analysepaket benötigt eine .zip-Endung.")
    if not target.parent.is_dir():
        raise ValueError("Bitte einen bereits existierenden Zielordner auswählen.")
    mapping_path = target.with_name(target.stem + "_NICHT_HOCHLADEN_ZUORDNUNG.csv")
    if target.exists() or mapping_path.exists():
        raise FileExistsError("Analyse-ZIP oder lokale Zuordnung existiert bereits.")

    def advance(note: str) -> None:
        if progress:
            progress(note)

    advance("Lokale QEC-Fälle und Datenbankstände erfassen …")
    cases: list[NTFCase] = service.store.load_cases()
    QuickTestStore(service.store)
    SourceKnowledgeStore(service.store)
    documents = [
        doc for doc in SourceKnowledgeStore(service.store).documents()
        if doc["source_kind"] == "qec_live_report"
    ]
    artifacts = service.list_artifacts()
    if mit_qec_originalen:
        # Important: original QEC downloads not yet processed into DuckDB
        # must not disappear from an explicitly requested evidence package.
        # Only exact FIN+reference-bound schema-v2 JSON is accepted.
        known = {doc["source_sha256"] for doc in documents}
        unreadable = 0
        for report_path in list_downloaded_qec_reports(service.archive.root.parent):
            if report_path.stat().st_size > 32 * 1024 * 1024:
                unreadable += 1
                continue
            digest = sha256_file(report_path)
            if digest in known:
                continue
            try:
                raw = json.loads(report_path.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError, UnicodeError):
                unreadable += 1
                continue
            fin = report_path.parent.parent.name
            reference = report_path.parent.name.removeprefix("ref_")
            if (
                not isinstance(raw, dict) or raw.get("schema_version") != 2
                or raw.get("fin") != fin
                or str(raw.get("referenznummer") or "") != reference
            ):
                unreadable += 1
                continue
            documents.append({
                "source_sha256": digest,
                "source_kind": "qec_local_unparsed",
                "metadata": {
                    "fin": fin, "reference": reference,
                    "part_number": str(raw.get("sachnummer") or ""),
                    "fresh_complete": False,
                    "sections": len(raw.get("abschnitte") or []),
                    "fresh_sections": 0,
                    "fields": 0, "values": 0, "table_rows": 0,
                    "attachments": len(raw.get("anhaenge") or []),
                },
            })
            known.add(digest)
        if unreadable:
            raise ValueError(
                f"{unreadable} lokale QEC-Originaldatei(en) können keinem "
                "gültigen Fall zugeordnet werden. Bitte unter Datenquellen "
                "prüfen und gegebenenfalls mit dem Parser-Diagnose-ZIP untersuchen."
            )

    with service.store.connect() as con:
        reports = con.execute(
            "SELECT report_id,fin,diagnosed_at,mileage_km,ecu_count,dtc_count "
            "FROM quicktest_reports ORDER BY report_id"
        ).fetchall()
        dtcs = con.execute(
            "SELECT report_id,ecu_code,dtc_code,status,frequency_counter "
            "FROM quicktest_dtcs ORDER BY report_id,ecu_index,dtc_index"
        ).fetchall()
        software = con.execute(
            "SELECT report_id,ecu_code,metadata_json "
            "FROM quicktest_ecus ORDER BY report_id,ecu_index"
        ).fetchall()
        qec_rows = con.execute(
            "SELECT source_sha256,category,source_location,label,payload_json "
            "FROM source_knowledge_rows WHERE category IN ('qec_field', 'qec_table_row') "
            "ORDER BY source_sha256,record_number LIMIT ?",
            [MAX_QEC_RECORDS + 1],
        ).fetchall()
        tips_counts = dict(con.execute(
            "SELECT fin,COUNT(*) FROM source_knowledge_rows "
            "WHERE category='autoexport_tips' AND fin IS NOT NULL GROUP BY fin"
        ).fetchall())
        has_qec_decisions = bool(con.execute(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_schema='main' AND table_name='qec_workflow_decisions'"
        ).fetchone()[0])
        saved_qec_decisions = (
            con.execute("SELECT case_id,decision FROM qec_workflow_decisions").fetchall()
            if has_qec_decisions else []
        )
    if len(qec_rows) > MAX_QEC_RECORDS:
        raise ValueError("Mehr als 200.000 QEC-Detailzeilen; Export bitte eingrenzen.")

    fins = (
        {case.vin for case in cases}
        | {row[1] for row in reports}
        | {str(doc["metadata"].get("fin")) for doc in documents if doc["metadata"].get("fin")}
        | {fin for fin in tips_counts if _FIN_RE.fullmatch(str(fin or ""))}
        | {
            str(art.vin_hint).strip().upper() for art in artifacts
            if art.source_type == SourceType.SMR_D and _FIN_RE.fullmatch(
                str(art.vin_hint or "").strip().upper()
            )
        }
    )
    fins = {fin for fin in fins if fin}
    secret = secrets.token_bytes(32)
    paket_id = secrets.token_hex(16)
    aliases = {
        fin: f"V{i:04d}"
        for i, fin in enumerate(sorted(fins, key=lambda x: _key_order(secret, "fin", x)), 1)
    }
    case_aliases = {
        case.case_id: f"F{i:04d}"
        for i, case in enumerate(
            sorted(cases, key=lambda c: _key_order(secret, "fall", c.case_id)), 1
        )
    }
    report_aliases = {
        report[0]: f"QT{i:05d}"
        for i, report in enumerate(
            sorted(reports, key=lambda x: _key_order(secret, "quicktest", x[0])), 1
        )
    }
    qec_aliases = {
        doc["source_sha256"]: f"Q{i:05d}"
        for i, doc in enumerate(
            sorted(documents, key=lambda d: _key_order(secret, "qec", d["source_sha256"])), 1
        )
    }
    part_numbers = {
        str(doc["metadata"].get("part_number") or "").strip()
        for doc in documents if doc["metadata"].get("part_number")
    } | {
        str(getattr(c, "qec_part_number", "") or "").strip()
        for c in cases if getattr(c, "qec_part_number", "")
    }
    part_aliases = {
        number: f"T{i:04d}"
        for i, number in enumerate(
            sorted(part_numbers, key=lambda x: _key_order(secret, "teil", x)), 1
        )
    }

    by_fin: dict[str, list[NTFCase]] = defaultdict(list)
    for case in cases:
        by_fin[case.vin].append(case)
    docs_by_fin_ref: dict[tuple[str, str], list[dict]] = defaultdict(list)
    docs_by_sha = {doc["source_sha256"]: doc for doc in documents}
    for doc in documents:
        m = doc["metadata"]
        docs_by_fin_ref[(str(m.get("fin") or ""), str(m.get("reference") or ""))].append(doc)

    def same_part(left: object, right: object) -> bool:
        a = "".join(c for c in str(left or "").upper() if c.isalnum())
        b = "".join(c for c in str(right or "").upper() if c.isalnum())
        return not a or not b or a == b

    def linked_cases(fin: str, reference: str, part_number: object = "") -> list[NTFCase]:
        return [
            c for c in by_fin.get(fin, ())
            if str(getattr(c, "qec_reference", "") or "") == reference
            and same_part(getattr(c, "qec_part_number", ""), part_number)
        ]

    advance("QuickTests, CPC3-DTCs und Tauschzeitbezug extrahieren …")
    report_to_fin = {report[0]: report[1] for report in reports}
    reports_by_fin: dict[str, list[tuple]] = defaultdict(list)
    for report in reports:
        reports_by_fin[report[1]].append(report)
    dtcs_by_report: dict[str, list[tuple]] = defaultdict(list)
    for row in dtcs:
        dtcs_by_report[row[0]].append(row)
    total_tips_by_fin = Counter(tips_counts)
    decision_values: dict[str, set[str]] = defaultdict(set)
    for original_case_id, decision in saved_qec_decisions:
        if decision in {"NTF", "Kein NTF"}:
            decision_values[original_case_id].add(decision)

    fahrzeuge = []
    for fin in sorted(fins, key=lambda x: aliases[x]):
        models = {_model_series(c.vehicle.model_series) for c in by_fin.get(fin, [])}
        fahrzeuge.append({
            "fahrzeug_id": aliases[fin],
            "baureihe": ";".join(sorted(m for m in models if m)),
            "anzahl_faelle": len(by_fin.get(fin, [])),
            "anzahl_quicktests": len(reports_by_fin.get(fin, [])),
            "tips_autoexport_rohzeilen": total_tips_by_fin.get(fin, 0),
        })

    fall_quicktests: list[dict] = []
    features: list[dict] = []
    faelle = []
    bewertungen = []
    for case in sorted(cases, key=lambda c: case_aliases[c.case_id]):
        replacement = case.investigated_replacement()
        cid = case_aliases[case.case_id]
        fin = case.vin
        doc_matches = docs_by_fin_ref.get((fin, str(getattr(case, "qec_reference", "") or "")), [])
        pre_faults: set[tuple[str, str]] = set()
        post_faults: set[tuple[str, str]] = set()
        pre_tests = post_tests = uncertain_tests = 0
        for report in reports_by_fin.get(fin, []):
            phase, days = _phase(report[2], replacement)
            if phase == "vor_tausch":
                pre_tests += 1
                pre_faults.update(
                    (_code(row[1]).upper(), _code(row[2]).upper())
                    for row in dtcs_by_report.get(report[0], [])
                    if _code(row[1]) and _code(row[2])
                )
            elif phase == "nach_tausch":
                post_tests += 1
                post_faults.update(
                    (_code(row[1]).upper(), _code(row[2]).upper())
                    for row in dtcs_by_report.get(report[0], [])
                    if _code(row[1]) and _code(row[2])
                )
            else:
                uncertain_tests += 1
            fall_quicktests.append({
                "fall_id": cid,
                "quicktest_id": report_aliases[report[0]],
                "lage_zum_pumpentausch": phase,
                "tage_relativ_zum_tausch": days,
                "km_relativ_zum_tausch": (
                    report[3] - replacement.mileage_km
                    if report[3] is not None and replacement is not None
                    and replacement.mileage_km is not None else None
                ),
            })
        qa = [d["metadata"] for d in doc_matches]
        all_unparsed = bool(doc_matches) and not any(
            d["source_kind"] == "qec_live_report" for d in doc_matches
        )
        part_conflict = any(
            not same_part(getattr(case, "qec_part_number", ""), m.get("part_number"))
            for m in qa
        )
        komplett = any(m.get("fresh_complete") is True for m in qa) and not part_conflict
        missing = min((len(m.get("missing_sections") or []) for m in qa), default=5)
        qa_status = (
            "pruefbedarf" if part_conflict else
            "nicht_geparst" if all_unparsed else
            "vollstaendig" if komplett else "teilweise" if doc_matches else "nicht_erfasst"
        )
        faelle.append({
            "fall_id": cid,
            "fahrzeug_id": aliases.get(fin, ""),
            "bauteilprofil": _code(case.component_profile_id),
            "baureihe": _model_series(case.vehicle.model_series),
            "tauschanker_vorhanden": int(replacement is not None),
            "qec_bericht_status": qa_status,
            "qec_berichte": len(doc_matches),
            "tips_verknuepft": len(case.tips_observations),
            "quicktests_gesamt": len(reports_by_fin.get(fin, [])),
        })
        features.append({
            "fall_id": cid,
            "fahrzeug_id": aliases.get(fin, ""),
            "baureihe": _model_series(case.vehicle.model_series),
            "teilegruppe": part_aliases.get(str(getattr(case, "qec_part_number", "") or "").strip(), ""),
            "tausch_km": replacement.mileage_km if replacement else None,
            "qt_vor_tausch": pre_tests,
            "qt_nach_tausch": post_tests,
            "qt_ungekl": uncertain_tests,
            "ecu_dtc_kombinationen_vor": len(pre_faults),
            "cpc3_dtc_kombinationen_vor": sum(ecu.startswith("CPC3") for ecu, _ in pre_faults),
            "cpc3_dtc_kombinationen_nach": sum(ecu.startswith("CPC3") for ecu, _ in post_faults),
            "gleiche_cpc3_dtc_beidseits": sum(
                ecu.startswith("CPC3") for ecu, _ in pre_faults & post_faults
            ),
            "qec_erfassungsstand": qa_status,
            "qec_fehlende_reiter_min": missing,
            "tips_faelle": len(case.tips_observations),
            "smrd_bezug_bestaetigt": 0,
        })
        assessment = case.assessment
        decided = decision_values.get(case.case_id, set())
        decision_label = (
            next(iter(decided)) if len(decided) == 1 else
            "widerspruechlich" if len(decided) > 1 else ""
        )
        bewertungen.append({
            "fall_id": cid,
            "ntf_urteil_fachlich": decision_label,
            "ursachenkategorie_bewertet": str(assessment.root_cause.value) if assessment else "",
            "lieferantenbeteiligung_bewertet": (
                str(assessment.supplier_involvement.value) if assessment else ""
            ),
            "bewertung_sicherheit": str(assessment.confidence.value) if assessment else "",
            "lieferantenbefund_ntf_vorhanden": int(any(
                str(finding.result.value).upper() == "NTF" for finding in case.supplier_findings
            )),
            "lieferantenbefund_fehler_vorhanden": int(any(
                "FAULT" in str(finding.result.value).upper() for finding in case.supplier_findings
            )),
            "hinweis": "Ziel-/Nachbefunde: NICHT als Clustermerkmale verwenden",
        })

    quicktest_rows = [{
        "quicktest_id": report_aliases[row[0]],
        "fahrzeug_id": aliases.get(row[1], ""),
        "ecu_anzahl": row[4],
        "dtc_anzahl": row[5],
        "km_beim_test": row[3],
    } for row in reports]
    dtc_rows = [{
        "quicktest_id": report_aliases.get(row[0], ""),
        "fahrzeug_id": aliases.get(report_to_fin.get(row[0], ""), ""),
        "steuergeraet": _code(row[1]),
        "dtc_code": _code(row[2]),
        "dtc_status": _code(row[3]),
        "haeufigkeit": row[4],
    } for row in dtcs]

    software_rows = []
    for qt_id, ecu, payload in software:
        try:
            metadata = json.loads(payload)
        except ValueError:
            metadata = {}
        if not isinstance(metadata, dict):
            metadata = {}
        software_rows.append({
            "quicktest_id": report_aliases.get(qt_id, ""),
            "fahrzeug_id": aliases.get(report_to_fin.get(qt_id, ""), ""),
            "steuergeraet": _code(ecu),
            "softwarestand": _code(metadata.get("software_version")),
            "hardwarestand": _code(metadata.get("hardware_version")),
        })

    advance("QEC-Reiter und TIPS-Beobachtungen fallbezogen zusammenstellen …")
    qec_reports = []
    for doc in documents:
        m = doc["metadata"]
        reference = str(m.get("reference") or "")
        fin = str(m.get("fin") or "")
        affected = linked_cases(fin, reference, m.get("part_number"))
        qec_reports.append({
            "qec_bericht_id": qec_aliases[doc["source_sha256"]],
            "fahrzeug_id": aliases.get(fin, ""),
            "fall_ids": ";".join(case_aliases[c.case_id] for c in affected),
            "teilegruppe": part_aliases.get(str(m.get("part_number") or "").strip(), ""),
            "erfassungsstand": (
                "nicht_geparst" if doc.get("source_kind") == "qec_local_unparsed" else
                "vollstaendig" if m.get("fresh_complete") else "teilweise"
            ),
            "reiter_gesamt": m.get("sections"),
            "reiter_frisch": m.get("fresh_sections"),
            "formularfelder": m.get("fields"),
            "werte": m.get("values"),
            "tabellenzeilen": m.get("table_rows"),
            "anhaenge_anzahl": m.get("attachments"),
        })
    qec_fields: list[dict] = []
    for sha, category, location, label, raw in qec_rows:
        alias = qec_aliases.get(sha)
        if alias is None:
            continue
        try:
            value = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(value, dict):
            continue
        doc = docs_by_sha.get(sha)
        if doc is None:
            continue
        kind = str(value.get("typ") or "")
        if category == "qec_table_row":
            kind = "tabelle"
        form_name = str(value.get("name") or value.get("beschriftung") or "").strip()
        comparable = category == "qec_field" and bool(form_name)
        # The same named field in the same section gets the same pseudonym
        # across QEC reports. Unnamed/table rows get source-local IDs, never
        # incorrectly treated as identical merely because the row numbers match.
        basis = (
            "feld:" + str(value.get("bereich") or "") + ":" + kind + ":" + form_name
            if comparable else "einmalig:" + sha + ":" + location
        )
        field_alias = "QF" + _key_order(secret, "qec_feld", basis)[:12].upper()
        qec_fields.append({
            "qec_bericht_id": alias,
            "fahrzeug_id": aliases.get(str(doc["metadata"].get("fin") or ""), ""),
            "fall_ids": ";".join(
                case_aliases[c.case_id] for c in linked_cases(
                    str(doc["metadata"].get("fin") or ""),
                    str(doc["metadata"].get("reference") or ""),
                    doc["metadata"].get("part_number"),
                )
            ),
            "reiter": str(value.get("bereich") or ""),
            "feld_id": field_alias,
            "uebergreifend_vergleichbar": int(comparable),
            "feldart": _code(kind),
            "wert_strukturiert": _safe_value(value.get("wert"), kind),
            "alter_reiter": int(value.get("aus_vorherigem_abruf") is True),
            "original_bezeichnung": str(label or "")[:500] if mit_freitext else "",
            "original_wert": (
                str(value.get("wert") or "")[:4000]
                if category == "qec_field" and mit_freitext
                else json.dumps(value.get("zellen") or [], ensure_ascii=False)[:4000]
                if category == "qec_table_row" and mit_freitext else ""
            ),
        })
    tips_rows = []
    for case in cases:
        for i, observation in enumerate(case.tips_observations, 1):
            tips_rows.append({
                "fall_id": case_aliases[case.case_id],
                "fahrzeug_id": aliases.get(case.vin, ""),
                "tips_id": f"{case_aliases[case.case_id]}-T{i:03d}",
                "beschwerde_vorhanden": int(bool(observation.complaint)),
                "werkstattbefund_vorhanden": int(bool(observation.workshop_findings)),
                "massnahme_vorhanden": int(bool(observation.performed_actions)),
                "beschwerde_original": (
                    str(observation.complaint or "")[:4000] if mit_freitext else ""
                ),
                "werkstattbefund_original": (
                    str(observation.workshop_findings or "")[:4000] if mit_freitext else ""
                ),
                "massnahme_original": (
                    str(observation.performed_actions or "")[:4000] if mit_freitext else ""
                ),
            })

    # SMR-D is recognized as an archived source, but there is not yet a
    # supported raw XML/JSON feature parser. No misleading derived DTCs.
    smrd_rows = []
    smr_artifacts = sorted(
        (art for art in artifacts if art.source_type == SourceType.SMR_D),
        key=lambda a: _key_order(secret, "smrd", a.sha256),
    )
    for index, art in enumerate(smr_artifacts, 1):
        fin = str(art.vin_hint or "").strip().upper()
        smrd_rows.append({
            "smrd_id": f"SM{i:04d}",
            "fahrzeug_id": aliases.get(fin, "") if _FIN_RE.fullmatch(fin) else "",
            "struktur_parsebar": 0,
            "stand": "nur_quelldatei_archiviert",
            "byte_anzahl": art.size_bytes,
        })

    for row in features:
        # Only explicit FIN hints link SMR-D. Never infer an identity from a path.
        row["smrd_bezug_bestaetigt"] = int(any(
            smr["fahrzeug_id"] == row["fahrzeug_id"] and smr["fahrzeug_id"]
            for smr in smrd_rows
        ))

    methodik = [
        {"thema": "Cluster-Eingaben", "regel": "Nur vor dem Tausch beobachtete DTCs und sachlich zeitunabhaengige Fahrzeug-/Teilemerkmale als Ursachencluster nutzen."},
        {"thema": "Zeit", "regel": "DTC nach Pumpentausch und gleichdatige unklare Beobachtungen separat analysieren. Kein fehlender DTC = kein Fehler."},
        {"thema": "Ergebnis-Leakage", "regel": "Bewertungen, Lieferantenurteile, SSL-Ergebnisse und QEC-Nachanalysen sind Ziel-/Kontextdaten, keine Clustermerkmale."},
        {"thema": "FIN-Identitaet", "regel": "Nur Pseudonyme in ZIP. Die eindeutige Zuordnung wird getrennt und lokal gespeichert."},
        {"thema": "QEC-Freitext", "regel": "Standard ohne Freitext. Optionaler Freitext ist NICHT anonymisiert; interne Freigabe erforderlich."},
        {"thema": "SMR-D", "regel": "Ohne strukturellen Parser nur Inventar-/Vollstaendigkeitsnachweis, keine vorgetaeuschten SMR-D-Diagnosefeatures."},
        {"thema": "Dateien", "regel": "Keine PDF-, JSON-, XML-, SMR-D-, TIPS-Originale, Anhaenge, CSV-Rohquellen, ZIP-Archive oder Pfade enthalten."},
        {"thema": "Quelle", "regel": "Strukturierte Daten aus der lokalen NTF-Insight-DuckDB. Nicht belegte oder mehrdeutige Verknuepfung bleibt offen."},
        {"thema": "Einsatz", "regel": "Dieses Paket ist nicht automatisch freigegeben/anonym. Datenschutz und Informationsschutz vor Upload pruefen."},
    ]

    # Strict clustering input: no outcomes, no QEC supplier findings, no
    # after-swap DTC data. Full history remains available for later validation.
    cluster_columns = (
        "fall_id", "fahrzeug_id", "baureihe", "teilegruppe",
        "qt_vor_tausch", "ecu_dtc_kombinationen_vor",
        "cpc3_dtc_kombinationen_vor",
    )
    cluster_input = [
        {column: item.get(column) for column in cluster_columns}
        for item in features
    ]

    table_items = {
        "cluster_input": (cluster_columns, cluster_input),
        "fahrzeuge": (("fahrzeug_id", "baureihe", "anzahl_faelle", "anzahl_quicktests", "tips_autoexport_rohzeilen"), fahrzeuge),
        "faelle": (("fall_id", "fahrzeug_id", "bauteilprofil", "baureihe", "tauschanker_vorhanden", "qec_bericht_status", "qec_berichte", "tips_verknuepft", "quicktests_gesamt"), faelle),
        "fallmerkmale": (("fall_id", "fahrzeug_id", "baureihe", "teilegruppe", "tausch_km", "qt_vor_tausch", "qt_nach_tausch", "qt_ungekl", "ecu_dtc_kombinationen_vor", "cpc3_dtc_kombinationen_vor", "cpc3_dtc_kombinationen_nach", "gleiche_cpc3_dtc_beidseits", "qec_erfassungsstand", "qec_fehlende_reiter_min", "tips_faelle", "smrd_bezug_bestaetigt"), features),
        "quicktests": (("quicktest_id", "fahrzeug_id", "ecu_anzahl", "dtc_anzahl", "km_beim_test"), quicktest_rows),
        "quicktest_fallbezug": (("fall_id", "quicktest_id", "lage_zum_pumpentausch", "tage_relativ_zum_tausch", "km_relativ_zum_tausch"), fall_quicktests),
        "dtc_beobachtungen": (("quicktest_id", "fahrzeug_id", "steuergeraet", "dtc_code", "dtc_status", "haeufigkeit"), dtc_rows),
        "ecu_staende": (("quicktest_id", "fahrzeug_id", "steuergeraet", "softwarestand", "hardwarestand"), software_rows),
        "qec_berichte": (("qec_bericht_id", "fahrzeug_id", "fall_ids", "teilegruppe", "erfassungsstand", "reiter_gesamt", "reiter_frisch", "formularfelder", "werte", "tabellenzeilen", "anhaenge_anzahl"), qec_reports),
        "qec_felder": (("qec_bericht_id", "fahrzeug_id", "fall_ids", "reiter", "feld_id", "uebergreifend_vergleichbar", "feldart", "wert_strukturiert", "alter_reiter", "original_bezeichnung", "original_wert"), qec_fields),
        "tips": (("fall_id", "fahrzeug_id", "tips_id", "beschwerde_vorhanden", "werkstattbefund_vorhanden", "massnahme_vorhanden", "beschwerde_original", "werkstattbefund_original", "massnahme_original"), tips_rows),
        "smrd_bestand": (("smrd_id", "fahrzeug_id", "struktur_parsebar", "stand", "byte_anzahl"), smrd_rows),
        "bewertungen_NICHT_CLUSTER": (("fall_id", "ntf_urteil_fachlich", "ursachenkategorie_bewertet", "lieferantenbeteiligung_bewertet", "bewertung_sicherheit", "lieferantenbefund_ntf_vorhanden", "lieferantenbefund_fehler_vorhanden", "hinweis"), bewertungen),
        "methodik": (("thema", "regel"), methodik),
    }

    stats = {
        "fahrzeuge": len(fahrzeuge), "faelle": len(faelle),
        "quicktests": len(reports), "dtcs": len(dtcs),
        "qec_berichte": len(qec_reports), "freitexte": mit_freitext,
        "smrd_originalquellen_nur_inventar": len(smrd_rows),
        "datenstand": "lokale DuckDB",
        "qec_originale_angefordert": mit_qec_originalen,
        "qec_nur_original_nicht_geparst": sum(
            doc.get("source_kind") == "qec_local_unparsed" for doc in documents
        ),
    }
    advance("Kompakte CSV-Dateien und Excel-Fallübersicht erstellen …")
    files: dict[str, bytes] = {}
    for name, (headers, rows) in table_items.items():
        files[f"{name}.csv"] = _csv_file(headers, rows)
    files["Auswertung.xlsx"] = _excel_summary(table_items, stats)
    files["chatgpt_ergebnis_vorlage.json"] = json.dumps(
        ergebnis_vorlage(paket_id), ensure_ascii=False, indent=2,
    ).encode("utf-8")
    files["chatgpt_ergebnis_schema.json"] = json.dumps(
        ergebnis_schema(), ensure_ascii=False, indent=2,
    ).encode("utf-8")
    files["CHATGPT_ANWEISUNG.txt"] = (
        "NTF INSIGHT / CHATGPT ANALYSE-VERTRAG v1\n\n"
        "Aus diesem ZIP eine fallbezogene Ursachen-/Clusteranalyse durchführen.\n"
        "Als RÜCKGABE NUR chatgpt_ergebnis.json im JSON-Format erzeugen,\n"
        "kompatibel zu chatgpt_ergebnis_schema.json.\n"
        "paket_id und alle Fall-, QEC- und QuickTest-Pseudonyme unverändert verwenden.\n"
        "Alle ausgewerteten Fälle aufnehmen, auch Nicht-bewertbare.\n"
        "Cluster anhand VOR-Tausch-DTCs und zulässiger technischer Merkmale bilden.\n"
        "QEC-/SSL-Endbefunde, Nach-Tausch-DTCs und NTF-Klassifikationen\n"
        "nur für Ursachenprüfung/Validierung verwenden (keine Leakage).\n"
        "NTF-Bewertung: NTF plausibel / NTF fraglich / Kein reiner NTF /\n"
        "Nicht bewertbar / Nicht bewertet. Keine unbelegte Schuldzuweisung.\n"
        "Sicherheit der Zuordnung: Belegt / Plausibel / Offen.\n"
        "Für jeden Fall Belege mit Quelle, Quelle-ID und genauer Fundstelle angeben.\n"
        "Falls ein QEC-Dokument fehlt, ausdrücklich als Datenlücke kennzeichnen.\n"
        "JSON niemals mit echten FINs, QEC-Referenzen oder internen Dateipfaden füllen.\n"
        "Die private NICHT_HOCHLADEN-Zuordnung wird niemals an ChatGPT gegeben.\n"
        "Weder QEC-Originale noch die KI-Antwort sind automatisch anonymisiert.\n"
    ).encode("utf-8")
    qec_plan = None
    if mit_qec_originalen:
        advance("Freigegebene QEC-Originalberichte und Anhänge für vertrauliches Paket prüfen …")
        qec_plan = plan_qec_originale(
            service.archive.root.parent, documents, qec_aliases, artifacts,
        )
    files["README.txt"] = (
        "NTF INSIGHT · KI-ANALYSEPAKET\n\n"
        "Dieses ZIP enthält strukturierte CSV-Tabellen und eine Excel-Übersicht.\n"
        + (
            "VERTRAULICH: Unveränderte QEC-JSON-Originalberichte und Anhänge\n"
            "liegen unter qec_originale/. Darin können FINs enthalten sein!\n"
            if mit_qec_originalen else
            "Es enthält KEINE Originaldateien, Quellpfade oder Roh-SHA-256.\n"
        )
        + "Anmeldedaten oder Browserprofile sind nicht enthalten.\n"
        "FINs und QEC-Referenzen wurden\n"
        "in den strukturierten Schlüsselfeldern durch Pseudonyme ersetzt.\n"
        "ACHTUNG: Opt-in-Freitext kann dennoch echte FINs und Namen enthalten.\n"
        "Fahrzeug- und Fallpseudonyme verbinden alle Tabellen innerhalb der ZIP.\n"
        "Die NICHT_HOCHLADEN-Zuordnung wird SEPARAT auf dem lokalen PC abgelegt.\n\n"
        "REIHENFOLGE FÜR DIE ANALYSE:\n"
        "1. cluster_input.csv als sichere Ausgangsmatrix. DTC-Codes ueber\n"
        "   quicktest_fallbezug.csv (NUR vor_tausch) mit dtc_beobachtungen.csv verbinden.\n"
        "2. qec_berichte.csv und qec_felder.csv zur Befunderklärung.\n"
        "3. tips.csv fuer Werkstattkontext, smrd_bestand.csv fuer Datenlücken.\n"
        "4. fallmerkmale.csv enthaelt AUCH NACH-Tausch-Beobachtungen: NICHT\n"
        "   ungeprueft als Cluster-Features verwenden!\n"
        "5. bewertungen_NICHT_CLUSTER.csv erst NACH dem Clustering ansehen.\n"
        "6. CHATGPT_ANWEISUNG.txt, chatgpt_ergebnis_vorlage.json und\n"
        "   chatgpt_ergebnis_schema.json geben das Rückgabeformat vor.\n\n"
        "WARNUNG: Pseudonymisierung ist KEINE garantierte Anonymisierung.\n"
        "Seltene technische Konstellationen koennen reidentifizierend sein.\n"
        "Alle technischen Daten unterliegen der Unternehmensfreigabe.\n"
        + (
            "ERHOEHTER SCHUTZBEDARF: QEC-Originaltexte und/oder TIPS-Freitexte\n"
            "sind enthalten und NICHT anonymisiert! Nicht ungeprueft hochladen.\n"
            if (mit_freitext or mit_qec_originalen) else
            "Ohne QEC-/TIPS-Originalfreitext; Detailfelder fehlen absichtlich.\n"
        )
    ).encode("utf-8")
    files["manifest.json"] = json.dumps({
        "schema_version": EXPORT_VERSION,
        "paket_id": paket_id,
        "generiert": "NTF Insight (lokal)",
        "pseudonymisiert": not mit_freitext and not mit_qec_originalen,
        "qec_originaldateien_enthalten": bool(qec_plan and qec_plan.dateien),
        "qec_originaldateien_anzahl": qec_plan.anzahl_dateien if qec_plan else 0,
        "qec_originaldateien_nicht_in_standard_sha_liste": mit_qec_originalen,
        "fehlende_qec_originalberichte": list(qec_plan.fehlende_berichte) if qec_plan else [],
        "fehlende_qec_anhaenge": list(qec_plan.fehlende_anhaenge) if qec_plan else [],
        "anonymisiert_garantiert": False,
        "fachfreitexte_enthalten": mit_freitext,
        "datenreihen": stats,
        "dateien_sha256": {
            name: hashlib.sha256(data).hexdigest()
            for name, data in files.items()
        },
    }, ensure_ascii=False, indent=2).encode("utf-8")

    # Real mapping on local disk only. Include all joins the user may need
    # for validation, and never put this content into the analysis ZIP.
    mapping_rows = []
    for fin in sorted(fins, key=lambda x: aliases[x]):
        mapping_rows.append({
            "art": "fahrzeug", "pseudonym": aliases[fin],
            "fin": fin, "fall_id_original": "",
            "qec_referenz_original": "", "sachnummer_original": "",
        })
    for case in sorted(cases, key=lambda x: case_aliases[x.case_id]):
        mapping_rows.append({
            "art": "fall", "pseudonym": case_aliases[case.case_id],
            "fin": case.vin, "fall_id_original": case.case_id,
            "qec_referenz_original": str(getattr(case, "qec_reference", "") or ""),
            "sachnummer_original": str(getattr(case, "qec_part_number", "") or ""),
        })
    for doc in documents:
        mapping_rows.append({
            "art": "qec_bericht", "pseudonym": qec_aliases[doc["source_sha256"]],
            "fin": str(doc["metadata"].get("fin") or ""),
            "fall_id_original": "",
            "qec_referenz_original": str(doc["metadata"].get("reference") or ""),
            "sachnummer_original": str(doc["metadata"].get("part_number") or ""),
        })
    for number, alias in part_aliases.items():
        mapping_rows.append({
            "art": "teil", "pseudonym": alias,
            "fin": "", "fall_id_original": "",
            "qec_referenz_original": "", "sachnummer_original": number,
        })
    for qid, pseudonym in report_aliases.items():
        mapping_rows.append({
            "art": "quicktest", "pseudonym": pseudonym, "fin": report_to_fin.get(qid, ""),
            "fall_id_original": "", "qec_referenz_original": "",
            "sachnummer_original": "", "quelle_id_original": qid,
        })
    for entry in mapping_rows:
        entry["paket_id"] = paket_id
        entry.setdefault("quelle_id_original", "")
        if entry["art"] == "qec_bericht":
            entry["quelle_id_original"] = next(
                sha for sha, pseudonym in qec_aliases.items()
                if pseudonym == entry["pseudonym"]
            )
    private_bytes = _csv_file(
        (
            "paket_id", "art", "pseudonym", "fin", "fall_id_original",
            "qec_referenz_original", "sachnummer_original", "quelle_id_original",
        ),
        mapping_rows,
    )
    advance("ZIP und getrennte lokale Zuordnung sicher speichern …")
    zip_handle, zip_temp = tempfile.mkstemp(
        prefix=".ntf-ki-analyse-", suffix=".zip", dir=target.parent,
    )
    map_handle, map_temp = tempfile.mkstemp(
        prefix=".ntf-ki-privat-", suffix=".csv", dir=target.parent,
    )
    os.close(zip_handle)
    os.close(map_handle)
    try:
        with ZipFile(zip_temp, "w", compression=ZIP_DEFLATED) as zip_file:
            for name, data in files.items():
                _zip_entry(zip_file, name, data)
            if qec_plan is not None:
                write_qec_originale(zip_file, qec_plan)
        Path(map_temp).write_bytes(private_bytes)
        if target.exists() or mapping_path.exists():
            raise FileExistsError("Exportdateien wurden zwischenzeitlich bereits erstellt.")
        os.replace(zip_temp, target)
        try:
            os.replace(map_temp, mapping_path)
        except Exception:
            target.unlink(missing_ok=True)
            raise
    finally:
        Path(zip_temp).unlink(missing_ok=True)
        Path(map_temp).unlink(missing_ok=True)
    # The identity map lives in DuckDB (also transferred with .ntfbackup)
    # and in the separate local CSV. It is NEVER inside the analysis ZIP.
    ChatGPTAnalyseStore(service.store).save_mapping(paket_id, mapping_rows)
    advance("KI-Analysepaket und private Zuordnung erfolgreich lokal gespeichert.")
    return AnalysepaketErgebnis(
        pfad=target, private_zuordnung=mapping_path,
        fahrzeuge=len(fahrzeuge), faelle=len(faelle),
        quicktests=len(reports), dtcs=len(dtcs),
        qec_berichte=len(qec_reports), freitexte=mit_freitext,
        qec_originale=qec_plan.anzahl_dateien if qec_plan else 0,
        fehlende_qec_originale=(
            len(qec_plan.fehlende_berichte) + len(qec_plan.fehlende_anhaenge)
            if qec_plan else 0
        ),
    )
