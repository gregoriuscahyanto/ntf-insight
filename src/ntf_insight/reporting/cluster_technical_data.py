"""Projektgebundene, datenminimierte Technikbasis fuer ChatGPT-Durchlauf 2.

Sammeldateien werden niemals ungefiltert nach FIN in ein Projekt-ZIP kopiert.
QuickTests werden zuerst aus dem persistierten Parsermodell exportiert;
nur nicht geparste PDFs duerfen nach gesonderter Freigabe als Fallback rein.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable
from zipfile import ZipFile

from ntf_insight.domain.case import NTFCase
from ntf_insight.ingestion.artifacts import SourceType, sha256_file
from ntf_insight.storage.cluster_evidence_store import part_key
from ntf_insight.storage.duckdb_store import DuckDBStore
from ntf_insight.storage.qec_project_scope import qec_case_matches_project
from ntf_insight.storage.workflow_projects import WorkflowProjectStore

MAX_TECH_ROWS = 1_000_000
MAX_STRUCTURED_FILE_BYTES = 200 * 1024**2
_FIN = re.compile(r"(?<![A-Z0-9])[A-HJ-NPR-Z0-9]{17}(?![A-Z0-9])", re.I)


@dataclass(frozen=True)
class TechnicalScope:
    fins: dict[str, str]           # FIN -> Fahrzeugpseudonym der ersten Runde
    cases: dict[str, str]          # echte Fall-ID -> pseudonym
    selected_cases: tuple[NTFCase, ...]


@dataclass(frozen=True)
class QuickTestFallback:
    path: Path
    sha256: str
    fin: str
    reason: str


def _normal_fin(raw: object) -> str:
    fin = str(raw or "").strip().upper()
    if len(fin) == 20 and fin.startswith("MBC"):
        fin = fin[3:]
    return fin if _FIN.fullmatch(fin) else ""


def _redact(value: object, vins: set[str], *, max_chars: int = 12000) -> str:
    """Schutz gegen einfache FIN-Leaks, keine garantierte Anonymisierung."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    text = str(value)[:max_chars]
    for fin in vins:
        text = re.sub(re.escape(fin), "<FIN>", text, flags=re.I)
        text = re.sub(re.escape("MBC" + fin), "<FIN>", text, flags=re.I)
    text = _FIN.sub("<FIN>", text)
    return text


def _csv_safe(value: object) -> str:
    result = str(value or "")
    return "'" + result if result.lstrip().startswith(("=", "+", "-", "@")) else result


def _has_table(con, table: str) -> bool:
    return bool(con.execute(
        "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
        "WHERE table_schema='main' AND table_name=?)", [table],
    ).fetchone()[0])


def load_technical_scope(
    store: DuckDBStore, paket_id: str, first_archive: ZipFile,
    profile_id: str, part_number: str,
) -> TechnicalScope:
    """IDs ausschliesslich aus dem ersten ZIP plus lokalem Mapping ableiten."""
    with store.connect() as con:
        rows = con.execute(
            "SELECT art,pseudonym,original_id,fin,qec_reference "
            "FROM chatgpt_export_mapping WHERE paket_id=?",
            [paket_id],
        ).fetchall()
    mapping = {(str(art), str(pseudo)): (str(original), str(fin), str(ref))
               for art, pseudo, original, fin, ref in rows}
    expected_fins = {
        (row["fahrzeug_id"] or "") for row in csv.DictReader(
            io.StringIO(first_archive.read("fahrzeuge.csv").decode("utf-8-sig"))
        )
    }
    expected_cases = {
        (row["fall_id"] or "") for row in csv.DictReader(
            io.StringIO(first_archive.read("faelle.csv").decode("utf-8-sig"))
        )
    }
    vins = {
        _normal_fin(value[0]): alias
        for (art, alias), value in mapping.items() if art == "fahrzeug"
    }
    cases = {
        value[0]: alias for (art, alias), value in mapping.items()
        if art == "fall"
    }
    if (
        not vins or not cases or not all(vins)
        or set(vins.values()) != expected_fins
        or set(cases.values()) != expected_cases
    ):
        raise ValueError("Erste QEC-Basis und lokale FIN-/Fallzuordnung stimmen nicht ueberein.")
    project_store = WorkflowProjectStore(store)
    projects = project_store.list_projects()
    found = []
    for (art, alias), (case_id, fin, ref) in mapping.items():
        if art != "fall":
            continue
        case = store.get_case(case_id)
        if (
            case is None or case.vin != _normal_fin(fin)
            or case.qec_reference != ref
            or _normal_fin(fin) not in vins
            or not qec_case_matches_project(
                case_part_number=str(case.qec_part_number or ""),
                source_profile_id=case.component_profile_id,
                project_profile_id=profile_id,
                project_part_number=part_number,
                projects=projects,
            )
        ):
            raise ValueError(
                "QEC-Fall im ersten Export passt nicht mehr zum aktiven "
                "Bauteilprofil/Sachnummernprojekt."
            )
        found.append(case)
    return TechnicalScope(vins, cases, tuple(found))


def _iter_query(
    store: DuckDBStore, table: str, query: str, arguments: list[str],
    transform: Callable[[tuple], dict], headers: tuple[str, ...],
    archive: ZipFile, output: str,
    fins: set[str], progress: Callable[[str], None] | None = None,
) -> tuple[int, int]:
    """Streamt Zeilen in einen ZIP-CSV-Member statt Millionen Zeilen zu laden."""
    count = 0
    size = 0
    with archive.open(output, "w", force_zip64=True) as target:
        with io.TextIOWrapper(target, encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=headers, extrasaction="ignore",
                                    lineterminator="\n")
            writer.writeheader()
            with store.connect() as con:
                if _has_table(con, table):
                    cursor = con.execute(query, arguments)
                    while True:
                        batch = cursor.fetchmany(1000)
                        if not batch:
                            break
                        for raw in batch:
                            data = transform(raw)
                            if not data:
                                continue
                            count += 1
                            if count > MAX_TECH_ROWS:
                                raise ValueError(
                                    "Mehr als 1.000.000 Diagnosezeilen in einer Tabelle. "
                                    "Bitte Projekt/Unterlagen aufteilen."
                                )
                            safe = {
                                key: _csv_safe(_redact(data.get(key), fins))
                                for key in headers
                            }
                            size += sum(len(item.encode("utf-8")) for item in safe.values()) + 64
                            if size > MAX_STRUCTURED_FILE_BYTES:
                                raise ValueError(
                                    "Eine strukturierte Diagnosetabelle ist groesser als 200 MiB."
                                )
                            writer.writerow(safe)
                        if progress and count and count % 10000 < 1000:
                            progress(f"Diagnosezeilen {output}: {count:,} ...")
    return count, size


def export_parsed_diagnostics(
    archive: ZipFile,
    store: DuckDBStore,
    scope: TechnicalScope,
    *,
    include_fulltext: bool,
    progress: Callable[[str], None] | None = None,
) -> tuple[dict[str, int], set[str]]:
    """Fahrzeugdiagnosen nur fuer FINs der ersten Analyse exportieren."""
    fins = set(scope.fins)
    eligible = sorted(fins)
    placeholders = ",".join("?" for _ in eligible)
    # Leere FIN-Liste wird bereits in load_technical_scope abgewiesen.
    reports_query = (
        "SELECT report_id,fin,diagnosed_at,mileage_km,ecu_count,dtc_count "
        "FROM quicktest_reports WHERE fin IN (" + placeholders
        + ") ORDER BY diagnosed_at,report_id"
    )
    reports = []
    with store.connect() as con:
        if _has_table(con, "quicktest_reports"):
            reports = con.execute(reports_query, eligible).fetchall()
    reports = [row for row in reports if _normal_fin(row[1]) in fins]
    aliases = {
        str(row[0]): f"QT{i:06d}"
        for i, row in enumerate(reports, 1)
    }
    timestamp = {str(r[0]): r[2] for r in reports}
    source_shas: set[str] = set()
    if aliases:
        with store.connect() as con:
            if _has_table(con, "quicktest_sources"):
                query = (
                    "SELECT s.artifact_sha256 FROM quicktest_sources s "
                    "JOIN quicktest_reports r ON r.report_id=s.report_id "
                    "WHERE r.fin IN (" + placeholders + ")"
                )
                source_shas = {
                    str(row[0]) for row in con.execute(query, eligible).fetchall()
                }

    def write(table, query, headers, convert, required="quicktest_reports"):
        n, _size = _iter_query(
            store, required, query, eligible, convert, headers, archive,
            "diagnose/" + table + ".csv", fins, progress,
        )
        return n

    count_report = write(
        "quicktests",
        reports_query,
        ("quicktest_id", "fahrzeug_id", "diagnosezeitpunkt", "km",
         "ecu_anzahl", "dtc_anzahl", "hinweis"),
        lambda r: {
            "quicktest_id": aliases.get(str(r[0]), ""),
            "fahrzeug_id": scope.fins[_normal_fin(r[1])],
            "diagnosezeitpunkt": r[2], "km": r[3],
            "ecu_anzahl": r[4], "dtc_anzahl": r[5],
            "hinweis": "Gesamtfahrzeugdiagnose; keine automatische Bauteilursache",
        },
    )

    ecu_query = (
        "SELECT e.report_id,e.ecu_index,e.ecu_code,e.ecu_name,"
        "e.reported_fault_count,e.metadata_json,e.page_start,e.page_end "
        "FROM quicktest_ecus e JOIN quicktest_reports r ON r.report_id=e.report_id "
        "WHERE r.fin IN (" + placeholders + ") ORDER BY e.report_id,e.ecu_index"
    )
    def ecu_row(r):
        meta = {}
        try:
            meta = json.loads(r[5] or "{}")
        except (TypeError, ValueError):
            pass
        if not isinstance(meta, dict):
            meta = {}
        return {
            "quicktest_id": aliases.get(str(r[0]), ""),
            "ecu_index": r[1], "steuergeraet": r[2], "ecu_name": r[3],
            "reported_fault_count": r[4],
            "hardware_teilnummer": meta.get("hardware_partnumber") or "",
            "software_version": meta.get("software_version") or "",
            "hardware_version": meta.get("hardware_version") or "",
            "seite_von": r[6], "seite_bis": r[7],
        }
    count_ecu = write(
        "ecu_staende", ecu_query,
        ("quicktest_id", "ecu_index", "steuergeraet", "ecu_name",
         "reported_fault_count", "hardware_teilnummer",
         "software_version", "hardware_version", "seite_von", "seite_bis"),
        ecu_row, required="quicktest_ecus",
    )

    dtc_query = (
        "SELECT d.report_id,d.ecu_index,d.dtc_index,d.ecu_code,d.kind,d.dtc_code,"
        "d.description,d.status,d.frequency_counter,d.original_odometer_km,"
        "d.most_recent_odometer_km,d.ignition_cycle_counter,d.page_start,d.page_end "
        "FROM quicktest_dtcs d JOIN quicktest_reports r ON r.report_id=d.report_id "
        "WHERE r.fin IN (" + placeholders + ") "
        "ORDER BY d.report_id,d.ecu_index,d.dtc_index"
    )
    count_dtc = write(
        "dtc_beobachtungen", dtc_query,
        ("quicktest_id", "ecu_index", "dtc_index", "steuergeraet",
         "dtc_art", "dtc_code", "beschreibung", "status", "haeufigkeit",
         "km_erster_auftritt", "km_letzter_auftritt", "zuendzyklen",
         "seite_von", "seite_bis"),
        lambda r: dict(zip((
            "quicktest_id", "ecu_index", "dtc_index", "steuergeraet",
            "dtc_art", "dtc_code", "beschreibung", "status", "haeufigkeit",
            "km_erster_auftritt", "km_letzter_auftritt", "zuendzyklen",
            "seite_von", "seite_bis",
        ), (aliases.get(str(r[0]), ""), *r[1:]))),
        required="quicktest_dtcs",
    )

    params_query = (
        "SELECT p.report_id,p.ecu_index,p.dtc_index,p.parameter_index,"
        "p.parameter_name,p.first_value,p.last_value,p.page_number "
        "FROM quicktest_parameters p "
        "JOIN quicktest_reports r ON r.report_id=p.report_id "
        "WHERE r.fin IN (" + placeholders + ") "
        "ORDER BY p.report_id,p.ecu_index,p.dtc_index,p.parameter_index"
    )
    count_parameter = write(
        "dtc_parameter", params_query,
        ("quicktest_id", "ecu_index", "dtc_index", "parameter_index",
         "parameter", "wert_erst", "wert_letzt", "seite"),
        lambda r: dict(zip((
            "quicktest_id", "ecu_index", "dtc_index", "parameter_index",
            "parameter", "wert_erst", "wert_letzt", "seite",
        ), (aliases.get(str(r[0]), ""), *r[1:]))),
        required="quicktest_parameters",
    )

    # Diagnosetexte sind keine weitere Quelle, sondern die geparsten
    # Seiten der schon durch FIN zugeordneten Berichte; nach Freigabe.
    if include_fulltext:
        pages_query = (
            "SELECT p.report_id,p.page_number,p.text_content "
            "FROM quicktest_pages p "
            "JOIN quicktest_reports r ON r.report_id=p.report_id "
            "WHERE r.fin IN (" + placeholders + ") "
            "ORDER BY p.report_id,p.page_number"
        )
        count_pages = write(
            "quicktest_seitentexte", pages_query,
            ("quicktest_id", "seite", "geparster_text"),
            lambda r: {
                "quicktest_id": aliases.get(str(r[0]), ""),
                "seite": r[1], "geparster_text": r[2],
            },
            required="quicktest_pages",
        )
    else:
        count_pages = 0

    # FIN-Bezug ist fahrzeugweit, NICHT automatisch ein Nachweis des
    # Bauteilfehlers; Tauschphasen nur bei explizitem QEC-Originalanker.
    by_fin = {}
    for case in scope.selected_cases:
        by_fin.setdefault(case.vin, []).append(case)
    rel_rows = []
    for report_id, fin, diagnosed, _km, _ecu, _dtc in reports:
        for case in by_fin.get(fin, ()):
            anchor = case.investigated_replacement()
            source_ref = str(case.source_ref or "")
            if (
                anchor is None or not source_ref.startswith("raw:")
                or anchor.source_ref != source_ref
            ):
                phase = "tauschdatum_nicht_belegt"
                days = ""
            else:
                delta = (diagnosed.date() - anchor.occurred_at.date()).days
                if delta == 0:
                    phase = "zeitlich_unklar_gleicher_tag"
                else:
                    phase = "vor_tausch" if delta < 0 else "nach_tausch"
                days = delta
            rel_rows.append({
                "fall_id": scope.cases[case.case_id],
                "quicktest_id": aliases[str(report_id)],
                "lage_zum_tausch": phase, "tage_relativ_zum_tausch": days,
                "belegregel": "Nur Zeitvergleich; keine bewiesene Fehlerursache",
            })
    count_rel, _ = _iter_query(
        store, "quicktest_reports",
        "SELECT 1 WHERE 1=0", [],
        lambda r: {}, ("fall_id", "quicktest_id", "lage_zum_tausch",
                      "tage_relativ_zum_tausch", "belegregel"),
        archive, "diagnose/quicktest_fallbezug.csv", fins,
    ) if False else (0, 0)
    # Relationen kommen aus den bereits validierten Faellen und Berichten.
    with archive.open("diagnose/quicktest_fallbezug.csv", "w") as target:
        with io.TextIOWrapper(target, encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=(
                "fall_id", "quicktest_id", "lage_zum_tausch",
                "tage_relativ_zum_tausch", "belegregel",
            ), lineterminator="\n")
            writer.writeheader()
            writer.writerows(rel_rows)
    count_rel = len(rel_rows)

    stats = {
        "quicktests_geparst": count_report, "ecu_eintraege": count_ecu,
        "dtc_beobachtungen": count_dtc, "dtc_parameter": count_parameter,
        "quicktest_seitentexte": count_pages,
        "fall_zeitvergleiche": count_rel,
    }
    return stats, source_shas


def export_tp_filtered(
    archive: ZipFile, store: DuckDBStore, scope: TechnicalScope,
    progress: Callable[[str], None] | None = None,
) -> dict[str, int]:
    """TP-Dashboard-Sammel-CSV nur nach FIN im Parserbestand exportieren."""
    categories = {
        "autoexport_dtc": (
            "tp_dashboard_dtc.csv",
            ("beobachtung_id", "fahrzeug_id", "zeitpunkt", "km",
             "steuergeraet", "dtc_code", "dtc_status", "haeufigkeit",
             "softwarestand", "hardwarestand", "dtc_beschreibung"),
            ("DiagStartTs", "KmReadingNum", "EcuNm", "EcuFaultNm",
             "EcuFaultStateTxt", "FrequencyCounter", "EcuSwVersionTxt",
             "EcuSuppHwVersionTxt", "EcuFaultTxt"),
        ),
        "autoexport_repair": (
            "tp_dashboard_reparaturen.csv",
            ("beobachtung_id", "fahrzeug_id", "datum", "km",
             "beanstandung", "reparaturmassnahme", "werkstattnotiz"),
            ("RepairDt", "KmReadingNum", "ComplDsc",
             "RepairTypeNmGerman", "WorksVisitDsc"),
        ),
        "autoexport_tips": (
            "tp_dashboard_tips.csv",
            ("beobachtung_id", "fahrzeug_id", "datum",
             "beanstandung", "werkstattbefund", "massnahme"),
            ("CreationDate", "InitialWorkshopMessageCustomerComplaint",
             "InitialWorkshopMessageWorkshopFindings",
             "InitialWorkshopMessagePerformedActions"),
        ),
    }
    counts = {}
    # JOIN erzwingt echte TP-Dashboard-Provenienz, nicht beliebigen AutoExport.
    for category, (name, headers, fields) in categories.items():
        counter = 0
        query = (
            "SELECT r.fin,r.payload_json FROM source_knowledge_rows r "
            "JOIN source_knowledge_documents d ON d.source_sha256=r.source_sha256 "
            "WHERE r.category=? AND d.source_kind='autoexport_rows' "
            "AND json_extract_string(d.metadata_json,'$.source_type')='tp_dashboard' "
            "ORDER BY r.source_sha256,r.record_number"
        )
        with archive.open("diagnose/" + name, "w") as target:
            with io.TextIOWrapper(target, encoding="utf-8-sig", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=headers, lineterminator="\n")
                writer.writeheader()
                with store.connect() as con:
                    if _has_table(con, "source_knowledge_rows") and _has_table(
                        con, "source_knowledge_documents"
                    ):
                        cursor = con.execute(query, [category])
                        while True:
                            batch = cursor.fetchmany(1000)
                            if not batch:
                                break
                            for fin, raw in batch:
                                ident = _normal_fin(fin)
                                if ident not in scope.fins:
                                    continue
                                try:
                                    row = json.loads(raw)
                                except (ValueError, TypeError):
                                    continue
                                if not isinstance(row, dict):
                                    continue
                                counter += 1
                                if counter > MAX_TECH_ROWS:
                                    raise ValueError(
                                        "TP-Dashboard hat zu viele projektbezogene Zeilen."
                                    )
                                values = [_redact(row.get(f), set(scope.fins)) for f in fields]
                                if category == "autoexport_dtc":
                                    out = dict(zip(headers, (
                                        f"TP{counter:07d}", scope.fins[ident], *values,
                                    )))
                                else:
                                    out = dict(zip(headers, (
                                        f"TP{counter:07d}", scope.fins[ident], *values,
                                    )))
                                writer.writerow({k: _csv_safe(v) for k, v in out.items()})
                if progress:
                    progress(f"TP-Dashboard {category}: {counter} Projektzeilen")
        counts[category] = counter
    return counts


def collect_unparsed_quicktest_pdfs(
    store: DuckDBStore, scope: TechnicalScope, parsed_shas: set[str],
) -> list[QuickTestFallback]:
    """Nur nachgewiesen FIN-zugeordnete PDFs; keine PDF aus fremdem FIN-Ordner."""
    found: dict[str, QuickTestFallback] = {}
    root = store.path.parent / "quicktests"
    for fin in sorted(scope.fins):
        folder = root / fin
        if folder.is_symlink() or not folder.is_dir():
            continue
        for pdf in sorted(folder.glob("*.pdf")):
            if pdf.is_symlink() or not pdf.is_file():
                continue
            sha = sha256_file(pdf)
            if sha not in parsed_shas:
                found.setdefault(sha, QuickTestFallback(
                    pdf, sha, fin, "FIN-Ordner, Inhalt nicht einzeln verifiziert",
                ))
    for artifact in store.load_artifacts():
        if artifact.source_type != SourceType.SHORT_TEST:
            continue
        fin = _normal_fin(artifact.vin_hint)
        if fin not in scope.fins or artifact.sha256 in parsed_shas:
            continue
        path = Path(artifact.archived_path)
        if not path.is_symlink() and path.is_file() and path.suffix.lower() == ".pdf":
            if sha256_file(path) == artifact.sha256:
                found.setdefault(artifact.sha256, QuickTestFallback(
                    path, artifact.sha256, fin, "Archivierter FIN-Hinweis",
                ))
    return list(found.values())



@dataclass(frozen=True)
class OriginalInContext:
    path: Path
    sha256: str
    zip_path: str
    category: str
    assignment: str


def parsed_source_hashes(store: DuckDBStore, scope: TechnicalScope) -> set[str]:
    with store.connect() as con:
        if not _has_table(con, "quicktest_sources") or not _has_table(
            con, "quicktest_reports"
        ):
            return set()
        eligible = sorted(scope.fins)
        marks = ",".join("?" for _ in eligible)
        rows = con.execute(
            "SELECT s.artifact_sha256 FROM quicktest_sources s "
            "JOIN quicktest_reports r ON r.report_id=s.report_id "
            "WHERE r.fin IN (" + marks + ")", eligible,
        ).fetchall()
    return {str(row[0]) for row in rows}


def plan_original_context(
    store: DuckDBStore, scope: TechnicalScope,
    evidence: list, parsed_shas: set[str], *,
    include_originals: bool,
) -> tuple[list[dict], list[OriginalInContext]]:
    """Projekt-Archivdateien plus nur ungeparste DV-Fallbacks.

    TP-Sammeldateien niemals roh kopieren, da sie weitere FINs enthalten
    koennen. Die ausgewerteten FIN-Zeilen stehen separat in diagnose/.
    """
    artifacts = {a.sha256: a for a in store.load_artifacts()}
    entries: list[dict] = []
    originals: list[OriginalInContext] = []
    included: set[str] = set()

    def add(
        category: str, sha: str, source: Path,
        assigned: str, reason: str = "",
    ) -> None:
        index = len(entries) + 1
        name = ""
        present = False
        if sha in included:
            reason = "Doppelte Quelldatei bereits aufgenommen"
        elif not include_originals:
            reason = "Technische Originale nicht freigegeben"
        elif category == "tp_dashboard":
            reason = "TP-Sammeldatei enthaelt potentiell fremde FINs; nur FIN-Zeilen"
        elif category == "diagnosis_viewer" and sha in parsed_shas:
            reason = "Geparste Diagnosis-Viewer-Version ist in diagnose/ enthalten"
        elif not source.is_file() or source.is_symlink():
            reason = "Original nicht mehr vorhanden oder Symlink"
        elif source.stat().st_size > MAX_STRUCTURED_FILE_BYTES:
            raise ValueError("Eine technische Quelldatei ueberschreitet 200 MiB.")
        elif sha256_file(source) != sha:
            reason = "Pruefsumme stimmt nicht mit dem archivierten Original ueberein"
        else:
            suffix = source.suffix.lower() or ".bin"
            name = f"unterlagen/{category}/D{index:05d}{suffix}"
            originals.append(OriginalInContext(source, sha, name, category, assigned))
            included.add(sha)
            present = True
        entries.append({
            "beleg_id": f"D{index:05d}",
            "kategorie": category,
            "datei_im_paket": name or None,
            "original_aufgenommen": present,
            "zuordnung": assigned,
            "auslassungsgrund": reason,
        })

    for file in evidence:
        artifact = artifacts.get(file.sha256)
        mismatch = ""
        if artifact is not None:
            vin = _normal_fin(artifact.vin_hint)
            if vin and vin not in scope.fins:
                mismatch = "Dokument ist einem anderen Fahrzeug zugeordnet"
            elif artifact.case_id_hint and artifact.case_id_hint not in scope.cases:
                mismatch = "Dokument ist einem anderen QEC-Fall zugeordnet"
        if mismatch:
            entries.append({
                "beleg_id": f"D{len(entries) + 1:05d}",
                "kategorie": file.category, "datei_im_paket": None,
                "original_aufgenommen": False, "zuordnung": "Nicht passend",
                "auslassungsgrund": mismatch,
            })
        else:
            assigned = "Explizit dem Projekt zugeordnet"
            if artifact is not None and (
                artifact.vin_hint or artifact.case_id_hint
            ):
                assigned += ", Referenzhinweis geprueft"
            else:
                assigned += ", Inhalt nicht automatisch auf Sachnummer geprueft"
            add(file.category, file.sha256, file.source_path, assigned)

    # Original-PDF nur wenn der Parser keine persistierte Version dieses
    # PDFs besitzt. Niemals alle 2345 Originale zusaetzlich duplizieren.
    for pdf in collect_unparsed_quicktest_pdfs(store, scope, parsed_shas):
        if pdf.sha256 in included:
            continue
        add(
            "diagnosis_viewer_fallback", pdf.sha256, pdf.path,
            "FIN-bezogen: " + pdf.reason,
        )
    return entries, originals


def export_tips_filtered(
    archive: ZipFile, store: DuckDBStore, scope: TechnicalScope,
    *, include_fulltext: bool,
) -> dict[str, int]:
    """Nur strukturierte TIPS-Eintraege fuer FINs der Projektkohorte."""
    counters = {"tips_berichte": 0, "tips_eintraege": 0}
    fins = set(scope.fins)
    allowed = {
        "tips_case", "tips_section", "tips_field",
        "tips_table_row", "tips_attachment_reference",
    }
    with archive.open("diagnose/tips_writer.csv", "w") as binary:
        with io.TextIOWrapper(binary, encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(
                stream, fieldnames=(
                    "beleg_id", "fahrzeug_id", "kategorie", "reiter_fundstelle",
                    "beschriftung", "wert_oder_befund", "textfreigabe",
                ), lineterminator="\n",
            )
            writer.writeheader()
            with store.connect() as con:
                if not (_has_table(con, "source_knowledge_rows") and _has_table(
                    con, "source_knowledge_documents"
                )):
                    return counters
                query = (
                    "SELECT r.fin,r.category,r.source_location,r.label,r.payload_json "
                    "FROM source_knowledge_rows r "
                    "JOIN source_knowledge_documents d "
                    "ON d.source_sha256=r.source_sha256 "
                    "WHERE d.source_kind='tips_live_case' "
                    "ORDER BY r.source_sha256,r.record_number"
                )
                cursor = con.execute(query)
                while True:
                    batch = cursor.fetchmany(1000)
                    if not batch:
                        break
                    for fin, category, location, label, data in batch:
                        if _normal_fin(fin) not in fins or category not in allowed:
                            continue
                        counters["tips_eintraege"] += 1
                        if counters["tips_eintraege"] > MAX_TECH_ROWS:
                            raise ValueError("Zu viele TIPS-Eintraege.")
                        try:
                            payload = json.loads(data)
                        except (ValueError, TypeError):
                            payload = {}
                        # Ohne Freitextfreigabe nur Inventar/Fundstelle.
                        readable = json.dumps(payload, ensure_ascii=False) if (
                            include_fulltext and isinstance(payload, dict)
                        ) else ""
                        writer.writerow({
                            "beleg_id": f"TI{counters['tips_eintraege']:07d}",
                            "fahrzeug_id": scope.fins[_normal_fin(fin)],
                            "kategorie": category,
                            "reiter_fundstelle": _redact(location, fins),
                            "beschriftung": _redact(label if include_fulltext else "", fins),
                            "wert_oder_befund": _redact(readable, fins),
                            "textfreigabe": int(include_fulltext),
                        })
    counters["tips_berichte"] = counters["tips_eintraege"]
    return counters
