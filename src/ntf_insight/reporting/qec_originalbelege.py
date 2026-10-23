"""Originale QEC-Befundungsberichte und Anhänge für explizit vertrauliche Exporte.

Keine automatische Anonymisierung! Die echten Inhalte können FINs, Seriennummern,
Kundentext und Lieferantendaten enthalten. Standardexport ruft dies NIE auf.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from dataclasses import dataclass
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from ntf_insight.ingestion.artifacts import SourceArtifact, SourceType, sha256_file

MAX_EVIDENCE_FILES = 5000
MAX_EVIDENCE_BYTES = 1024 * 1024 * 1024  # 1 GiB; no silently incomplete packages.
MAX_SINGLE_FILE_BYTES = 80 * 1024 * 1024
MAX_QEC_JSON_BYTES = 32 * 1024 * 1024
SUFFIXES = frozenset({
    ".pdf", ".xlsx", ".xls", ".csv", ".txt", ".xml", ".png", ".jpg", ".jpeg",
    ".docx", ".doc", ".pptx", ".ppt", ".rtf", ".eml", ".msg", ".zip",
})
_FIN = re.compile(r"[A-HJ-NPR-Z0-9]{17}\Z")
_REF = re.compile(r"[0-9]{1,14}\Z")


@dataclass(frozen=True)
class QECBelegDatei:
    quelle: Path
    datei_im_zip: str
    bericht_id: str
    art: str
    sha256: str
    groesse: int


@dataclass(frozen=True)
class QECBelegPlan:
    dateien: tuple[QECBelegDatei, ...]
    fehlende_berichte: tuple[str, ...]
    fehlende_anhaenge: tuple[str, ...]

    @property
    def anzahl_dateien(self) -> int:
        return len(self.dateien)


def _source_path(path: Path, allowed_root: Path, *, maximum: int) -> Path | None:
    if path.is_symlink() or not path.is_file():
        return None
    root = allowed_root.resolve()
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        return None
    size = resolved.stat().st_size
    if size > maximum or size <= 0:
        return None
    return resolved


def _attachment_name(value: object) -> str | None:
    """The downloader stores a basename or 'anhaenge/<basename>'."""
    if not isinstance(value, str) or not value:
        return None
    normal = value.replace("\\", "/")
    parts = normal.split("/")
    if len(parts) == 2 and parts[0] == "anhaenge":
        name = parts[1]
    elif len(parts) == 1:
        name = parts[0]
    else:
        return None
    if name in {"", ".", ".."} or ".." in name or len(name) > 160:
        return None
    if any(ord(c) < 32 for c in name):
        return None
    if Path(name).suffix.casefold() not in SUFFIXES:
        return None
    return name


def plan_qec_originale(
    data_dir: Path,
    documents: list[dict],
    aliases: dict[str, str],
    artifacts: list[SourceArtifact],
) -> QECBelegPlan:
    """List only QEC sources with matching FIN, reference and source SHA256.

    An old archived qec.json may be included, but its attachments are only
    attached if that EXACT JSON version is the one in the current QEC folder.
    Missing files are listed, never silently substituted with a foreign case.
    """
    root = Path(data_dir).resolve()
    qec_root = root / "qec"
    raw_root = root / "raw"
    raw_by_sha = {
        a.sha256: Path(a.archived_path)
        for a in artifacts
        if a.source_type == SourceType.QEC_REPORT
    }
    results: list[QECBelegDatei] = []
    missing_reports: list[str] = []
    missing_attachments: list[str] = []
    total = 0
    seen: set[str] = set()

    def add(path: Path, arcname: str, alias: str, kind: str) -> bool:
        nonlocal total
        if arcname in seen:
            raise ValueError("Doppelte QEC-Belegadresse im ZIP.")
        size = path.stat().st_size
        if len(results) >= MAX_EVIDENCE_FILES:
            raise ValueError("QEC-Belegpaket überschreitet 5.000 Dateien; bitte Fallauswahl begrenzen.")
        if total + size > MAX_EVIDENCE_BYTES:
            raise ValueError(
                "QEC-Originalbelege überschreiten 1 GiB. "
                "Bitte mit weniger Fällen oder ohne Originale exportieren."
            )
        digest = sha256_file(path)
        results.append(QECBelegDatei(
            quelle=path, datei_im_zip=arcname, bericht_id=alias,
            art=kind, sha256=digest, groesse=size,
        ))
        total += size
        seen.add(arcname)
        return True

    for doc in documents:
        metadata = doc.get("metadata") or {}
        sha = str(doc.get("source_sha256") or "")
        alias = aliases.get(sha)
        fin = str(metadata.get("fin") or "")
        ref = str(metadata.get("reference") or "")
        if not alias or not _FIN.fullmatch(fin) or not _REF.fullmatch(ref):
            continue
        folder = qec_root / fin / ("ref_" + ref)
        current = _source_path(folder / "qec.json", qec_root, maximum=MAX_QEC_JSON_BYTES)
        same_current = current is not None and sha256_file(current) == sha
        report = current if same_current else None
        if report is None:
            report = _source_path(raw_by_sha.get(sha, raw_root / "__missing__"),
                                  raw_root, maximum=MAX_QEC_JSON_BYTES)
            if report is not None and sha256_file(report) != sha:
                report = None
        if report is None:
            missing_reports.append(alias)
            continue
        try:
            payload = json.loads(report.read_text(encoding="utf-8-sig"))
        except (ValueError, UnicodeError, OSError):
            missing_reports.append(alias)
            continue
        if (not isinstance(payload, dict) or payload.get("schema_version") != 2
                or payload.get("fin") != fin
                or str(payload.get("referenznummer") or "") != ref):
            missing_reports.append(alias)
            continue
        add(report, f"qec_originale/{alias}/qec.json", alias, "qec_json_original")
        inventory = payload.get("anhaenge") or []
        if not isinstance(inventory, list):
            missing_attachments.append(alias + "/ungueltige_liste")
            continue
        if not same_current:
            if inventory:
                missing_attachments.append(alias + "/alte_version")
            continue
        for number, item in enumerate(inventory, start=1):
            if not isinstance(item, dict):
                missing_attachments.append(alias + f"/{number}")
                continue
            name = _attachment_name(item.get("datei"))
            if name is None:
                missing_attachments.append(alias + f"/{number}")
                continue
            path = _source_path(folder / "anhaenge" / name, qec_root,
                                maximum=MAX_SINGLE_FILE_BYTES)
            if path is None:
                missing_attachments.append(alias + f"/{number}")
                continue
            suffix = path.suffix.casefold()
            add(path, f"qec_originale/{alias}/anlage_{number:04d}{suffix}",
                alias, "qec_anhang")
    return QECBelegPlan(
        dateien=tuple(results),
        fehlende_berichte=tuple(missing_reports),
        fehlende_anhaenge=tuple(missing_attachments),
    )


def _index_bytes(plan: QECBelegPlan) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(("qec_bericht_id", "art", "datei_im_zip", "sha256", "groesse_bytes"))
    for entry in plan.dateien:
        writer.writerow((
            entry.bericht_id, entry.art, entry.datei_im_zip,
            entry.sha256, entry.groesse,
        ))
    return ("\ufeff" + stream.getvalue()).encode("utf-8")


def write_qec_originale(archive: ZipFile, plan: QECBelegPlan) -> None:
    """Preserve bytes, not original filenames, file timestamps or filesystem paths."""
    archive.writestr(
        ZipInfo("qec_originale/belegindex.csv", (1980, 1, 1, 0, 0, 0)),
        _index_bytes(plan), compress_type=ZIP_DEFLATED,
    )
    archive.writestr(
        ZipInfo("qec_originale/vollstaendigkeit.json", (1980, 1, 1, 0, 0, 0)),
        json.dumps({
            "belegdateien": len(plan.dateien),
            "fehlende_qec_berichte": plan.fehlende_berichte,
            "fehlende_qec_anhaenge": plan.fehlende_anhaenge,
            "hinweis": (
                "Originaldateien enthalten potentiell FINs und vertrauliche Daten. "
                "Nicht automatisch anonymisiert. Fehlende Belege separat prüfen."
            ),
        }, ensure_ascii=False, indent=2).encode("utf-8"),
        compress_type=ZIP_DEFLATED,
    )
    for entry in plan.dateien:
        info = ZipInfo(entry.datei_im_zip, (1980, 1, 1, 0, 0, 0))
        info.compress_type = ZIP_DEFLATED
        info.external_attr = 0o600 << 16
        before = entry.quelle.stat()
        if entry.quelle.is_symlink() or before.st_size != entry.groesse:
            raise ValueError("QEC-Original hat sich seit der Belegprüfung verändert.")
        digest = hashlib.sha256()
        with entry.quelle.open("rb") as source, archive.open(info, "w") as output:
            while True:
                data = source.read(1024 * 1024)
                if not data:
                    break
                digest.update(data)
                output.write(data)
        if digest.hexdigest() != entry.sha256:
            raise ValueError("QEC-Original hat sich während des ZIP-Exports geändert.")
