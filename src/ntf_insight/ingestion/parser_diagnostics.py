"""Lokales Parser-Fehlerpaket für QuickTest-PDFs und QEC-JSON.

Standardmäßig nur neutrale technische Metadaten. Die optionalen Originaldateien
sind vertraulich und dürfen ausschließlich nach gesonderter Freigabe geteilt
werden. Kein Netzwerkzugriff, keine automatische Anonymisierung.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from zipfile import ZIP_DEFLATED, ZipFile

from ntf_insight.ingestion.artifacts import ParseRun, ParseStatus, SourceType, sha256_file
from ntf_insight.ingestion.downloaded_quicktests import list_downloaded_quicktests
from ntf_insight.ingestion.qec_json import QECJsonParser, list_downloaded_qec_reports
from ntf_insight.ingestion.real_source_parsers import AutoExportParser, QuickTestPdfParser
from ntf_insight.ingestion.reference_source_parsers import CandelaParser
from ntf_insight.ingestion.tips_json import TipsJsonParser
from ntf_insight.ingestion.service import SourceImportService
from ntf_insight.storage.source_knowledge_store import SourceKnowledgeStore

MAX_PROBLEM_FILES = 30
MAX_FILE_BYTES = 35 * 1024 * 1024
MAX_PACKAGE_BYTES = 150 * 1024 * 1024


@dataclass(frozen=True)
class ParserProblem:
    artifact_sha256: str
    kind: str
    archived_path: Path
    status: str
    parser_name: str
    parser_version: str
    size_bytes: int


@dataclass(frozen=True)
class ParserDiagnosticsResult:
    path: Path
    problems_found: int
    entries_documented: int
    original_files: int
    originals_omitted: int


def find_parser_problems(
    service: SourceImportService,
    data_dir: Path,
    *,
    progress: Callable[[str], None] | None = None,
    category: str | None = None,
    scope_paths: tuple[Path, ...] | None = None,
) -> list[ParserProblem]:
    """Identify failed, incomplete or unrecognized downloaded sources.

    A file is only a parser problem after its SHA is already archived; an
    unimported download is not automatically classified as a parse failure.
    """
    artifacts = {item.sha256: item for item in service.list_artifacts()}
    if not artifacts:
        return []
    scope_shas: set[str] | None = None
    if scope_paths is not None:
        scope_shas = set()
        for number, path in enumerate(scope_paths, 1):
            path = Path(path)
            if path.is_symlink() or not path.is_file():
                continue
            if path.stat().st_size > MAX_PACKAGE_BYTES * 16:
                continue
            scope_shas.add(sha256_file(path))
            if progress and number % 25 == 0:
                progress(f"Projektbezogene Quellen prüfen: {number}/{len(scope_paths)}")

    from ntf_insight.storage.quicktest_store import QuickTestStore
    QuickTestStore(service.store)  # Bei einem frischen Roharchiv noch nicht angelegt.
    with service.store.connect() as con:
        quicktest_done = {
            row[0] for row in con.execute(
                "SELECT artifact_sha256 FROM quicktest_sources"
            ).fetchall()
        }
    documents = {
        doc["source_sha256"]: doc["source_kind"]
        for doc in SourceKnowledgeStore(service.store).documents()
    }
    qec_docs = {
        sha for sha, kind in documents.items() if kind == "qec_live_report"
    }
    recent: dict[tuple[str, str], ParseRun] = {}
    for run in service.store.load_parse_runs():
        key = (run.artifact_sha256, run.parser_name)
        old = recent.get(key)
        if old is None or (run.completed_at or run.started_at) >= (
            old.completed_at or old.started_at
        ):
            recent[key] = run

    # SourceType.OTHER includes invalid PDFs / JSON captured by automatic
    # detection. Attribute these only when their SHA matches a *real* local
    # downloaded QuickTest/QEC path, not an arbitrary other archive file.
    downloaded: dict[str, str] = {}
    quicktests = list_downloaded_quicktests(data_dir)
    qecs = list_downloaded_qec_reports(data_dir)
    for index, (path, kind) in enumerate(
        [(p, "quicktests") for p in quicktests] + [(p, "qec") for p in qecs],
        start=1,
    ):
        if index % 100 == 0 and progress:
            progress(f"Parser-Problemdateien abgleichen: {index}/{len(quicktests) + len(qecs)}")
        digest = sha256_file(path)
        if digest in artifacts:
            downloaded[digest] = kind

    found: list[ParserProblem] = []
    root = service.archive.root.resolve()
    parser_kinds = {
        "quicktests": (QuickTestPdfParser, ".pdf", "quicktest"),
        "qec": (QECJsonParser, ".json", "qec_live_report"),
        "tp_dashboard": (AutoExportParser, ".csv", "autoexport_rows"),
        "tips_writer": (TipsJsonParser, ".json", "tips_live_case"),
        "cdd_smrd": (CandelaParser, ".cdd", "candela_services"),
    }
    for sha, artifact in artifacts.items():
        if scope_shas is not None and sha not in scope_shas:
            continue
        suffix = artifact.original_name.lower()
        kind = (
            "quicktests" if artifact.source_type == SourceType.SHORT_TEST
            and suffix.endswith(".pdf")
            else "qec" if artifact.source_type == SourceType.QEC_REPORT
            and suffix.endswith(".json")
            else "tp_dashboard" if artifact.source_type == SourceType.TP_DASHBOARD
            and suffix.endswith(".csv")
            else "tips_writer" if artifact.source_type == SourceType.TIPS_CASE
            and suffix.endswith(".json")
            else "cdd_smrd" if artifact.source_type == SourceType.DIAGNOSTIC_DESCRIPTION
            and suffix.endswith(".cdd")
            else downloaded.get(sha)
        )
        if category is None and kind not in {"quicktests", "qec"}:
            continue  # Bestehender globaler Diagnostikexport unverändert.
        if category is not None and kind != {
            "diagnosis_viewer": "quicktests",
            "tp_dashboard": "tp_dashboard",
            "tips_writer": "tips_writer",
            "cdd_smrd": "cdd_smrd",
            "qec": "qec",
        }.get(category):
            continue
        if kind not in parser_kinds:
            continue
        parser, suffix, stored_kind = parser_kinds[kind]
        run = recent.get((sha, parser.name))
        persisted = (
            sha in quicktest_done if kind == "quicktests"
            else sha in qec_docs if kind == "qec"
            else documents.get(sha) == stored_kind
        )
        if run is not None and run.status == ParseStatus.FAILED:
            status = "fehlgeschlagen"
        elif run is not None and run.status == ParseStatus.PARTIAL:
            status = "teilweise"
        elif run is not None and run.parser_version != parser.version:
            status = "parser_version_veraltet"
        elif not persisted:
            status = "nicht_erkannt_oder_nicht_gespeichert"
        else:
            continue
        path = Path(artifact.archived_path).absolute()
        if path.is_symlink() or not path.resolve().is_relative_to(root) or not path.is_file():
            continue
        if path.suffix.lower() != suffix:
            continue
        found.append(ParserProblem(
            artifact_sha256=sha, kind=kind, archived_path=path,
            status=status, parser_name=run.parser_name if run else parser.name,
            parser_version=run.parser_version if run else parser.version,
            size_bytes=artifact.size_bytes,
        ))
    return sorted(
        found,
        key=lambda item: (
            0 if item.status == "fehlgeschlagen" else 1,
            item.kind,
            item.artifact_sha256,
        ),
    )


def export_parser_diagnostics(
    service: SourceImportService,
    data_dir: Path,
    destination: Path,
    *,
    include_originals: bool = False,
    progress: Callable[[str], None] | None = None,
    category: str | None = None,
    scope_paths: tuple[Path, ...] | None = None,
) -> ParserDiagnosticsResult:
    """Write one atomic, bounded ZIP, without exporting source names or FINs.

    The manifest intentionally excludes error_message, the source directory
    and original filename: those can include personally identifying data.
    If original files are requested, their *content* stays unmodified and
    confidential; no claim of automatic anonymization is made.
    """
    destination = Path(destination).absolute()
    if destination.exists():
        raise FileExistsError("Das Fehlerpaket existiert bereits; bitte anderen Dateinamen wählen.")
    if destination.suffix.lower() != ".zip":
        raise ValueError("Parser-Diagnosepaket muss die Endung .zip verwenden.")
    if progress:
        progress("Bereits archivierte Parser-Problemdateien ermitteln …")
    problems = find_parser_problems(
        service, data_dir, progress=progress,
        category=category, scope_paths=scope_paths,
    )
    if not problems:
        raise ValueError("Keine problematischen importierten Dateien dieser Quelle gefunden.")

    selected = problems[:MAX_PROBLEM_FILES]
    manifest: list[dict[str, object]] = []
    written = 0
    omitted = 0
    total = 0
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=".ntf-parser-diagnose-", suffix=".zip", dir=destination.parent,
    )
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        with ZipFile(tmp, "w", compression=ZIP_DEFLATED) as archive:
            archive.writestr("HINWEISE.txt", (
                "NTF Insight Parser-Diagnosepaket\n\n"
                "Dieses Paket wurde lokal und ohne Netzwerkübertragung erzeugt.\n"
                "diagnose.json enthält keine Originaldateinamen, FINs oder Fehlertexte.\n"
                "Bei enthaltenen 'originale/'-Dateien sind die Dateiinhalte "
                "UNVERÄNDERT und können FINs, Personendaten oder vertrauliche "
                "Mercedes-Benz-Informationen enthalten.\n"
                "Nicht ungeprüft an ChatGPT, GitHub oder externe Dienste hochladen.\n"
                "Vor Weitergabe Originale anonymisieren und interne Freigabe einholen.\n"
                "Die ZIP-Datei ist NICHT verschlüsselt.\n"
            ))
            for number, item in enumerate(selected, start=1):
                suffix = {
                    "quicktests": ".pdf", "qec": ".json",
                    "tips_writer": ".json", "tp_dashboard": ".csv",
                    "cdd_smrd": ".cdd",
                }[item.kind]
                entry_name = f"originale/{number:03d}{suffix}"
                inclusion = False
                if include_originals and item.size_bytes <= MAX_FILE_BYTES and (
                    total + item.size_bytes <= MAX_PACKAGE_BYTES
                ):
                    # Protect against mismatched/out-of-date archive contents.
                    if sha256_file(item.archived_path) != item.artifact_sha256:
                        raise ValueError("Archivprüfsumme einer Problemdatei stimmt nicht.")
                    if item.archived_path.is_symlink():
                        raise ValueError("Symbolische Quelldatei wird nicht exportiert.")
                    archive.write(item.archived_path, arcname=entry_name)
                    written += 1
                    total += item.size_bytes
                    inclusion = True
                else:
                    omitted += 1
                manifest.append({
                    "nummer": number,
                    "format": {
                        "quicktests": "quicktest_pdf",
                        "qec": "qec_json",
                        "tips_writer": "tips_json",
                        "tp_dashboard": "tp_dashboard_csv",
                        "cdd_smrd": "candela_cdd",
                    }[item.kind],
                    "sha256": item.artifact_sha256,
                    "dateigroesse_bytes": item.size_bytes,
                    "parser": item.parser_name,
                    "parser_version": item.parser_version,
                    "erfassungsstatus": item.status,
                    "originaldatei_enthalten": inclusion,
                    "datei_im_paket": entry_name if inclusion else None,
                })
                if progress and number % 5 == 0:
                    progress(f"Diagnosepaket: {number}/{len(selected)} Fälle dokumentiert …")
            archive.writestr(
                "diagnose.json",
                json.dumps({
                    "schema_version": 1,
                    "dateien_gesamt_problematisch": len(problems),
                    "dateien_dokumentiert": len(selected),
                    "originale_beigefuegt": written,
                    "dateien": manifest,
                }, ensure_ascii=False, indent=2),
            )
        if destination.exists():
            raise FileExistsError("Das Ziel ist zwischenzeitlich bereits vorhanden.")
        os.replace(tmp, destination)
    finally:
        tmp.unlink(missing_ok=True)
    return ParserDiagnosticsResult(
        destination, len(problems), len(selected), written, omitted,
    )
