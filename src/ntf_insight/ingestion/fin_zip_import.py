"""Validated import of FIN ZIPs exported by NTF Insight on another PC.

A manifest is not trusted merely because a ZIP has one: every entry is
validated before a single file is installed. Import never transfers browser
profiles, credentials or a local database and never overwrites changed files.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from zipfile import ZipFile
from pypdf.errors import PdfReadError

from ntf_insight.ingestion.quicktest_detailed import extract_quicktest


_FIN = re.compile(r"[A-HJ-NPR-Z0-9]{17}\Z")
_REF = re.compile(r"ref_[0-9]{1,14}\Z")
_SHA = re.compile(r"[a-f0-9]{64}\Z")
_TIPS_SUFFIXES = frozenset({
    ".json", ".pdf", ".jpg", ".jpeg", ".png", ".tif", ".tiff",
    ".bmp", ".gif", ".webp", ".doc", ".docx", ".xls", ".xlsx",
    ".csv", ".txt", ".eml", ".msg",
})
_TYPES = frozenset({"quicktests", "qec_json", "qec_pdfs", "tips_json", "tips_dateien"})


@dataclass(frozen=True)
class PreparedFinFile:
    staged_path: Path
    relative_path: Path
    category: str
    checksum: str


@dataclass(frozen=True)
class FinZipPlan:
    fin: str
    files: tuple[PreparedFinFile, ...]


@dataclass(frozen=True)
class FinZipInstallResult:
    quicktest_paths: tuple[Path, ...]
    attachments: tuple[Path, ...]
    counts: dict[str, int]
    conflicts: tuple[str, ...]


def is_fin_export(path: Path) -> bool:
    """Recognize this format without guessing based on its filename."""
    with ZipFile(path) as archive:
        return "export_manifest.json" in archive.namelist()


def _location(fin: str, relative: PurePosixPath, category: str) -> Path:
    parts = relative.parts
    if (
        not parts or relative.is_absolute()
        or any(part in ("", ".", "..") or ":" in part or "\\" in part for part in parts)
        or relative.as_posix() != str(relative)
    ):
        raise ValueError("Unsicherer Dateipfad im FIN-ZIP.")
    if category == "quicktests":
        if parts[0] != "quicktests" or len(parts) < 2 or relative.suffix.lower() != ".pdf":
            raise ValueError("Ungültiger QuickTest-Pfad im FIN-ZIP.")
        return Path("quicktests", fin, *parts[1:])
    if category in {"qec_json", "qec_pdfs"}:
        if len(parts) < 3 or parts[0] != "qec" or not _REF.fullmatch(parts[1]):
            raise ValueError("Ungültige QEC-Referenz im FIN-ZIP.")
        if category == "qec_json":
            if len(parts) != 3 or parts[2] != "qec.json":
                raise ValueError("Ungültiger QEC-JSON-Pfad.")
        elif (
            len(parts) < 4 or parts[2] != "anhaenge"
            or relative.suffix.lower() != ".pdf"
        ):
            raise ValueError("Ungültiger QEC-Anhangspfad.")
        return Path("qec", fin, *parts[1:])
    if category in {"tips_json", "tips_dateien"}:
        if len(parts) < 2 or parts[0] != "tips" or relative.suffix.lower() not in _TIPS_SUFFIXES:
            raise ValueError("Ungültiger TIPS-Pfad.")
        if (category == "tips_json") != (relative.suffix.lower() == ".json"):
            raise ValueError("TIPS-Kategorie und Dateiendung widersprechen sich.")
        return Path("tips", fin, *parts[1:])
    raise ValueError("Unbekannte Kategorie im FIN-ZIP.")


def prepare_fin_export(path: Path, temp_root: Path) -> FinZipPlan:
    """Stage and check all members and PDF FINs before changing the destination."""
    with ZipFile(path) as archive:
        infos = [info for info in archive.infolist() if not info.is_dir()]
        names = [info.filename for info in infos]
        if len(names) != len(set(names)) or len(names) != len({name.casefold() for name in names}):
            raise ValueError("FIN-ZIP enthält mehrfach verwendete Dateipfade.")
        if names.count("export_manifest.json") != 1:
            raise ValueError("FIN-ZIP benötigt genau ein Exportmanifest.")
        manifest_info = archive.getinfo("export_manifest.json")
        if manifest_info.file_size > 1024 * 1024:
            raise ValueError("Exportmanifest ist zu groß.")
        try:
            manifest = json.loads(archive.read(manifest_info))
        except (UnicodeError, ValueError) as exc:
            raise ValueError("Exportmanifest ist kein gültiges JSON.") from exc
        if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
            raise ValueError("Nicht unterstützte FIN-Exportversion.")
        fin = manifest.get("fin")
        if not isinstance(fin, str) or not _FIN.fullmatch(fin):
            raise ValueError("FIN im Exportmanifest ist ungültig.")
        entries = manifest.get("dateien")
        if not isinstance(entries, list) or not entries:
            raise ValueError("Exportmanifest enthält keine Quelldateien.")
        listed: set[str] = set()
        prepared: list[PreparedFinFile] = []
        counts: Counter[str] = Counter()
        qec_references: set[str] = set()
        qec_attachments: set[str] = set()
        temp_root.mkdir(parents=True, exist_ok=True)
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                raise ValueError("Ungültiger Dateieintrag im Exportmanifest.")
            name, category = entry.get("pfad"), entry.get("typ")
            expected_size, expected_sha = entry.get("bytes"), entry.get("sha256")
            if (
                not isinstance(name, str) or not name or name == "export_manifest.json"
                or "\\" in name or name.startswith("/")
                or name in listed or category not in _TYPES
                or type(expected_size) is not int or expected_size < 0
                or not isinstance(expected_sha, str) or not _SHA.fullmatch(expected_sha)
            ):
                raise ValueError("Ungültiger oder doppelter FIN-ZIP-Dateieintrag.")
            posix = PurePosixPath(name)
            if posix.as_posix() != name:
                raise ValueError("Uneindeutiger Pfad im FIN-ZIP.")
            relative = _location(fin, posix, category)
            listed.add(name)
            counts[category] += 1
            if category == "qec_json":
                qec_references.add(posix.parts[1])
            elif category == "qec_pdfs":
                qec_attachments.add(posix.parts[1])
            try:
                info = archive.getinfo(name)
            except KeyError as exc:
                raise ValueError("Exportmanifest nennt eine fehlende Datei.") from exc
            if info.file_size != expected_size:
                raise ValueError("FIN-ZIP-Dateigröße stimmt nicht mit Manifest überein.")
            staged = temp_root / str(index)
            digest = hashlib.sha256()
            with archive.open(info) as source, staged.open("wb") as dest:
                while chunk := source.read(1024 * 1024):
                    digest.update(chunk)
                    dest.write(chunk)
            if digest.hexdigest() != expected_sha:
                raise ValueError("FIN-ZIP-Prüfsumme stimmt nicht überein.")
            if category in {"quicktests", "qec_pdfs"}:
                with staged.open("rb") as source:
                    if not source.read(5).startswith(b"%PDF-"):
                        raise ValueError("Ein PDF-Anhang ist keine PDF-Datei.")
            if category == "quicktests":
                # Unsupported layouts remain importable as originals; an
                # *explicitly contradictory* parsed FIN must be rejected.
                try:
                    parsed = extract_quicktest(staged, expected_sha)
                except (OSError, ValueError, PdfReadError):
                    parsed = None
                if parsed is not None and parsed.quicktest_report["fin"] != fin:
                    raise ValueError("QuickTest-FIN weicht vom Exportmanifest ab.")
            elif category == "qec_json":
                try:
                    payload = json.loads(staged.read_text(encoding="utf-8"))
                except (UnicodeError, ValueError) as exc:
                    raise ValueError("QEC-Bericht enthält ungültiges JSON.") from exc
                if (
                    not isinstance(payload, dict)
                    or payload.get("fin") != fin
                    or str(payload.get("referenznummer", "")) != posix.parts[1][4:]
                ):
                    raise ValueError("QEC-FIN oder QEC-Referenz stimmt nicht überein.")
            elif category == "tips_json":
                try:
                    payload = json.loads(staged.read_text(encoding="utf-8"))
                except (UnicodeError, ValueError) as exc:
                    raise ValueError("TIPS-JSON ist ungültig.") from exc
                if not isinstance(payload, dict) or payload.get("fin", fin) != fin:
                    raise ValueError("TIPS-JSON enthält eine abweichende FIN.")
            prepared.append(PreparedFinFile(staged, relative, category, expected_sha))
        if listed != set(names) - {"export_manifest.json"}:
            raise ValueError("FIN-ZIP enthält Dateien außerhalb des Exportmanifests.")
        if qec_attachments - qec_references:
            raise ValueError("QEC-Anhänge ohne passenden QEC-Referenzbericht.")
        declared_counts = manifest.get("anzahl", {})
        if not isinstance(declared_counts, dict) or any(
            declared_counts.get(category, 0) != counts[category] for category in _TYPES
        ):
            raise ValueError("FIN-ZIP-Kategoriezähler stimmen nicht überein.")
        return FinZipPlan(fin, tuple(prepared))


def _safe_parent(data_dir: Path, target: Path) -> None:
    """Refuse symlinks inside a data root, including final existing paths."""
    root = data_dir.absolute()
    if root.is_symlink():
        raise ValueError("Der Datenordner ist ein symbolischer Link.")
    if not target.absolute().is_relative_to(root):
        raise ValueError("FIN-ZIP-Ziel liegt außerhalb des Datenverzeichnisses.")
    current = root
    for part in target.relative_to(root).parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("Ein Datenpfad enthält einen symbolischen Link.")


def install_fin_export(plan: FinZipPlan, data_dir: Path) -> FinZipInstallResult:
    """Merge only missing files. Preserve conflicting QEC originals for review."""
    data_dir = Path(data_dir).absolute()
    counts: Counter[str] = Counter()
    quicktests: list[Path] = []
    attachments: list[Path] = []
    conflicts: list[str] = []
    # Never combine new attachments with a different local QEC finding.
    rejected_refs: set[str] = set()
    for item in plan.files:
        if item.category != "qec_json":
            continue
        target = data_dir / item.relative_path
        _safe_parent(data_dir, target)
        if target.is_file():
            with target.open("rb") as existing:
                if hashlib.file_digest(existing, "sha256").hexdigest() != item.checksum:
                    rejected_refs.add(item.relative_path.parts[2])
    for item in plan.files:
        if (
            item.category in {"qec_json", "qec_pdfs"}
            and item.relative_path.parts[2] in rejected_refs
        ):
            conflicts.append(str(item.relative_path))
            continue
        target = data_dir / item.relative_path
        _safe_parent(data_dir, target)
        if target.exists() and target.is_dir():
            raise ValueError("Ein Zieldateiname wird bereits als Verzeichnis verwendet.")
        if target.exists():
            with target.open("rb") as existing:
                digest = hashlib.file_digest(existing, "sha256").hexdigest()
            if digest != item.checksum:
                if item.category == "quicktests":
                    # A filename collision must not discard a different session.
                    serial = 2
                    while True:
                        candidate = target.with_name(
                            f"{target.stem}_import_{serial}{target.suffix}"
                        )
                        _safe_parent(data_dir, candidate)
                        if not candidate.exists():
                            target = candidate
                            break
                        with candidate.open("rb") as existing:
                            if hashlib.file_digest(existing, "sha256").hexdigest() == item.checksum:
                                target = candidate
                                break
                        serial += 1
                else:
                    conflicts.append(str(item.relative_path))
                    continue
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            _safe_parent(data_dir, target)
            fd, tmp_name = tempfile.mkstemp(prefix=".ntf-import-", dir=target.parent)
            try:
                with os.fdopen(fd, "wb") as dest, item.staged_path.open("rb") as source:
                    shutil.copyfileobj(source, dest, length=1024 * 1024)
                os.replace(tmp_name, target)
            finally:
                Path(tmp_name).unlink(missing_ok=True)
            counts[item.category] += 1
        if item.category == "quicktests":
            quicktests.append(target)
        elif item.category == "qec_pdfs":
            attachments.append(target)
    return FinZipInstallResult(
        tuple(quicktests), tuple(attachments), dict(counts), tuple(conflicts),
    )
