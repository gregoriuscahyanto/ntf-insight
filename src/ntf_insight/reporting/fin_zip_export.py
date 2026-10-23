"""Datensparsamer, lokaler FIN-ZIP-Export aus QuickTest, QEC und optional TIPS.

Quelle ist ausschliesslich das lokale NTF-Insight-Datenverzeichnis.
ZIP-Dateien werden weder hochgeladen noch mit Benutzerkonten verknuepft.
"""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


_FIN = re.compile(r"[A-HJ-NPR-Z0-9]{17}\Z")
_REFERENCE = re.compile(r"ref_([0-9]{1,14})\Z")
_TIPS_EXTENSIONS = frozenset({
    ".json", ".pdf", ".jpg", ".jpeg", ".png", ".tif", ".tiff",
    ".bmp", ".gif", ".webp", ".doc", ".docx", ".xls", ".xlsx",
    ".csv", ".txt", ".eml", ".msg",
})
_CATEGORIES = ("quicktests", "qec_json", "qec_pdfs", "tips_json", "tips_dateien")


@dataclass(frozen=True, slots=True)
class FinZipResult:
    fin: str
    zip_path: Path | None
    counts: dict[str, int] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()

    @property
    def file_count(self) -> int:
        return sum(self.counts.values())


@dataclass(frozen=True, slots=True)
class _Entry:
    source: Path
    destination: str
    category: str


def _safe_directory(folder: Path, *, base: Path | None = None) -> bool:
    if folder.is_symlink() or not folder.is_dir():
        return False
    if base is not None and not folder.resolve().is_relative_to(base.resolve()):
        return False
    return True


def _safe_files(folder: Path):
    """Never follow links (even a link in a parent directory)."""
    if not _safe_directory(folder):
        return
    for source in sorted(folder.rglob("*")):
        if not source.is_file() or source.is_symlink():
            continue
        relative = source.relative_to(folder)
        if any(parent.is_symlink() for parent in (folder / Path(*relative.parts[:i])
                                                 for i in range(1, len(relative.parts)))):
            continue
        try:
            if not source.resolve().is_relative_to(folder.resolve()):
                continue
        except OSError:
            continue
        yield source, relative


def _archive_name(prefix: str, relative: Path) -> str:
    name = PurePosixPath(prefix, *relative.parts)
    if (name.is_absolute() or not name.parts
            or any(part in (".", "..") or "\\" in part for part in name.parts)
            or any(":" in part for part in name.parts)):
        raise ValueError("Unsicherer ZIP-Dateiname.")
    return name.as_posix()


def _add_entry(entries: list[_Entry], seen: set[str], warnings: list[str],
               path: Path, archive_name: str, category: str) -> None:
    key = archive_name.casefold()
    if key in seen:
        warnings.append(f"Doppelter ZIP-Pfad ausgelassen: {archive_name}")
        return
    seen.add(key)
    entries.append(_Entry(path, archive_name, category))


def _qec_entries(data_dir: Path, fin: str, entries: list[_Entry],
                 seen: set[str], warnings: list[str]) -> None:
    base = data_dir / "qec"
    root = base / fin
    if not _safe_directory(base) or not _safe_directory(root, base=base):
        return
    for ref in sorted(root.iterdir()):
        if not _safe_directory(ref, base=root) or not _REFERENCE.fullmatch(ref.name):
            continue
        report = ref / "qec.json"
        if not report.is_file() or report.is_symlink():
            warnings.append(f"{ref.name}: qec.json fehlt; Anhänge nicht eindeutig verifizierbar.")
            continue
        try:
            value = json.loads(report.read_text(encoding="utf-8"))
            if (not isinstance(value, dict) or value.get("fin") != fin
                    or str(value.get("referenznummer", "")) != ref.name[4:]):
                raise ValueError("FIN oder Referenznummer stimmt nicht überein.")
        except (OSError, UnicodeError, ValueError, TypeError) as exc:
            warnings.append(f"{ref.name}: QEC-JSON nicht verwendbar ({type(exc).__name__}); ausgelassen.")
            continue
        _add_entry(
            entries, seen, warnings, report,
            _archive_name("qec", Path(ref.name) / "qec.json"), "qec_json",
        )
        attachments = ref / "anhaenge"
        if not _safe_directory(attachments, base=ref):
            continue
        for path, relative in _safe_files(attachments):
            if path.suffix.lower() == ".pdf":
                _add_entry(
                    entries, seen, warnings, path,
                    _archive_name("qec", Path(ref.name) / "anhaenge" / relative),
                    "qec_pdfs",
                )


def _tips_entries(data_dir: Path, fin: str, entries: list[_Entry],
                  seen: set[str], warnings: list[str]) -> None:
    """Future TIPS downloads can be placed in tips/<FIN>/ without code changes."""
    base = data_dir / "tips"
    folder = base / fin
    if not _safe_directory(base) or not _safe_directory(folder, base=base):
        return
    for path, relative in _safe_files(folder):
        suffix = path.suffix.lower()
        if suffix not in _TIPS_EXTENSIONS:
            continue
        if suffix == ".json":
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(payload, dict) and payload.get("fin", fin) != fin:
                    warnings.append(f"TIPS-Datei mit abweichender FIN ausgelassen: {relative.as_posix()}")
                    continue
            except (OSError, UnicodeError, ValueError):
                warnings.append(f"Ungültige TIPS-JSON ausgelassen: {relative.as_posix()}")
                continue
        category = "tips_json" if suffix == ".json" else "tips_dateien"
        _add_entry(
            entries, seen, warnings, path,
            _archive_name("tips", relative), category,
        )


def _collect_entries(data_dir: Path, fin: str) -> tuple[list[_Entry], list[str]]:
    entries: list[_Entry] = []
    warnings: list[str] = []
    seen: set[str] = set()
    base = data_dir / "quicktests"
    folder = base / fin
    if _safe_directory(base) and _safe_directory(folder, base=base):
        for path, relative in _safe_files(folder):
            if path.suffix.lower() == ".pdf":
                _add_entry(
                    entries, seen, warnings, path,
                    _archive_name("quicktests", relative), "quicktests",
                )
    _qec_entries(data_dir, fin, entries, seen, warnings)
    _tips_entries(data_dir, fin, entries, seen, warnings)
    return entries, warnings


def _available_zip_name(directory: Path, fin: str) -> Path:
    stem = f"{fin}_NTF-Export"
    target = directory / f"{stem}.zip"
    index = 2
    while target.exists():
        target = directory / f"{stem}_{index}.zip"
        index += 1
    return target


def export_fin_zip(fin: str, data_dir: Path, destination: Path) -> FinZipResult:
    """Create exactly one ZIP for a FIN, or report no local sources.

    New files are atomically published only after closing a valid archive.
    Never copy manifests of downloads, browser profiles, credentials or other FINs.
    """
    if not isinstance(fin, str) or not _FIN.fullmatch(fin):
        raise ValueError("Eine gültige 17-stellige FIN ist erforderlich.")
    data_dir = Path(data_dir)
    destination = Path(destination)
    entries, warnings = _collect_entries(data_dir, fin)
    if not entries:
        return FinZipResult(fin, None, {category: 0 for category in _CATEGORIES},
                            tuple([*warnings, "Keine lokalen Quelldateien gefunden."]))
    destination.mkdir(parents=True, exist_ok=True)
    counts: Counter[str] = Counter()
    manifest_files: list[dict] = []
    target = _available_zip_name(destination, fin)

    with tempfile.NamedTemporaryFile(
        prefix=f".{fin}_", suffix=".partial", dir=destination, delete=False,
    ) as handle:
        temporary = Path(handle.name)
    try:
        with ZipFile(temporary, mode="w", compression=ZIP_DEFLATED,
                     compresslevel=6, allowZip64=True) as archive:
            for entry in entries:
                if entry.source.is_symlink() or not entry.source.is_file():
                    warnings.append(f"Während des Exports nicht mehr verfügbar: {entry.destination}")
                    continue
                try:
                    stat = entry.source.stat()
                    modified = time.localtime(stat.st_mtime)[:6]
                    if modified[0] < 1980:
                        modified = (1980, 1, 1, 0, 0, 0)
                    info = ZipInfo(entry.destination, modified)
                    info.compress_type = ZIP_DEFLATED
                    checksum = hashlib.sha256()
                    size = 0
                    with entry.source.open("rb") as original, archive.open(info, "w") as zipped:
                        while chunk := original.read(1024 * 1024):
                            zipped.write(chunk)
                            checksum.update(chunk)
                            size += len(chunk)
                    counts[entry.category] += 1
                    manifest_files.append({
                        "pfad": entry.destination,
                        "typ": entry.category,
                        "bytes": size,
                        "sha256": checksum.hexdigest(),
                    })
                except OSError as exc:
                    # Do not conceal data corruption or return a partial archive.
                    raise RuntimeError(
                        f"FIN {fin}: Quelldatei {entry.destination} nicht lesbar."
                    ) from exc
            manifest = {
                "schema_version": 1,
                "fin": fin,
                "export_utc": datetime.now(timezone.utc).isoformat(),
                "dateien": manifest_files,
                "anzahl": {category: counts[category] for category in _CATEGORIES},
                "fehlende_quellen": [category for category in _CATEGORIES
                                    if counts[category] == 0],
                "hinweise": warnings,
            }
            archive.writestr("export_manifest.json",
                             json.dumps(manifest, ensure_ascii=False, indent=2))
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return FinZipResult(
        fin, target, {category: counts[category] for category in _CATEGORIES},
        tuple(warnings),
    )
