"""Einzeldatei-Transfer eines bereits ausgewerteten NTF-Insight-Datenbestands.

Ein .ntfbackup ist ein geschlossenes ZIP mit einer nativen DuckDB-Kopie
und den lokal referenzierten Originaldateien. Wiederherstellen erfordert
keinen erneuten Parserlauf. Nur für genehmigte Unternehmensspeicherorte:
das Paket ist NICHT verschlüsselt oder kryptographisch signiert.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Callable
from zipfile import ZIP_DEFLATED, ZipFile

import duckdb

from ntf_insight.ingestion.artifacts import SourceArtifact


BACKUP_EXTENSION = ".ntfbackup"
FORMAT_NAME = "ntf-insight-portable"
FORMAT_VERSION = 1
DATABASE_NAME = "ntf-insight.duckdb"
DATABASE_ENTRY = "database/" + DATABASE_NAME
MANIFEST_ENTRY = "manifest.json"
DATA_FOLDERS = ("raw", "quicktests", "qec", "tips")
MAX_ENTRIES = 100_000
MAX_TOTAL_BYTES = 80 * 1024**3
MAX_MEMBER_BYTES = 40 * 1024**3
MAX_MANIFEST_BYTES = 16 * 1024**2
_CHUNK = 1024 * 1024
_SHA = re.compile(r"[a-f0-9]{64}\Z")
_RESERVED = re.compile(r"(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\..*)?\Z", re.I)
_ALLOWED_LOCAL_SUFFIXES = {
    "quicktests": {".pdf", ".json"},
    "qec": {".pdf", ".json", ".html", ".htm", ".txt", ".csv", ".xml",
            ".jpg", ".jpeg", ".png", ".xlsx", ".docx", ".zip"},
    "tips": {
        ".pdf", ".json", ".jpg", ".jpeg", ".png", ".bmp", ".tif",
        ".tiff", ".webp", ".gif", ".csv", ".xlsx", ".xls", ".doc",
        ".docx", ".pptx", ".ppt", ".txt", ".zip", ".eml", ".msg",
        ".xml",
    },
}
Progress = Callable[[str], None]


@dataclass(frozen=True)
class PortableBackupResult:
    path: Path
    file_count: int
    database_bytes: int


@dataclass(frozen=True)
class PortableRestoreResult:
    file_count: int
    case_count: int
    quicktest_count: int


def _message(progress: Progress | None, value: str) -> None:
    if progress is not None:
        progress(value)


def _relative(name: str) -> PurePosixPath:
    """Reject path traversal, Windows device names, ADS and ambiguous names."""
    if not isinstance(name, str) or not name or "\\" in name or name.startswith("/"):
        raise ValueError("Unsicherer Paketpfad.")
    parts = name.split("/")
    for part in parts:
        if (
            not part or part in {".", ".."} or part.rstrip(" .") != part
            or any(ord(char) < 32 or char in '<>:"|?*' for char in part)
            or _RESERVED.fullmatch(part)
        ):
            raise ValueError("Unsicherer Paketpfad.")
    return PurePosixPath(*parts)


def _safe_file(root: Path, path: Path) -> Path:
    """Only files beneath the real data root, never symlinks or junction escapes."""
    root = root.absolute()
    path = path.absolute()
    if root.is_symlink() or not path.is_relative_to(root):
        raise ValueError("Datei liegt außerhalb des lokalen Datenverzeichnisses.")
    current = path
    while current != root:
        if current.is_symlink():
            raise ValueError("Symbolischer Link im Datenverzeichnis ist nicht erlaubt.")
        current = current.parent
    if not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("Lokale Quelldatei fehlt oder liegt außerhalb des Datenverzeichnisses.")
    return path


def _sql_path(path: Path) -> str:
    return str(path).replace("'", "''")


def _snapshot_database(database: Path, destination: Path) -> None:
    """Logical DuckDB-to-DuckDB copy including all persisted derived tables."""
    if not database.is_file():
        raise ValueError("Keine lokale NTF-Insight-Datenbank vorhanden.")
    if destination.exists():
        raise ValueError("Datenbank-Snapshot darf nicht überschrieben werden.")
    # Do not copy a live .duckdb file byte-by-byte (WAL/in-flight transactions).
    # ATTACH/COPY copies a consistent set of tables, indices and saved records.
    with duckdb.connect(":memory:") as con:
        con.execute(f"ATTACH '{_sql_path(database)}' AS quelle (READ_ONLY)")
        con.execute(f"ATTACH '{_sql_path(destination)}' AS snapshot")
        con.execute("COPY FROM DATABASE quelle TO snapshot")
        con.execute("DETACH snapshot")
        con.execute("DETACH quelle")


def _artifacts(database: Path) -> list[SourceArtifact]:
    with duckdb.connect(str(database), read_only=True) as con:
        rows = con.execute("SELECT payload_json FROM source_artifacts").fetchall()
    return [SourceArtifact.model_validate_json(payload) for (payload,) in rows]


def _export_sources(root: Path, snapshot: Path) -> tuple[dict[str, Path], dict[str, str]]:
    """Return all selected on-disk files and SHA-to-raw-path mapping."""
    files: dict[str, Path] = {}
    artifact_files: dict[str, str] = {}
    for artifact in _artifacts(snapshot):
        if not _SHA.fullmatch(artifact.sha256):
            raise ValueError("Ungültiger Quell-Prüfsummenwert in der Datenbank.")
        path = _safe_file(root, Path(artifact.archived_path))
        relative = path.relative_to(root).as_posix()
        if not relative.startswith("raw/") or len(PurePosixPath(relative).parts) < 3:
            raise ValueError("Quellarchiv liegt nicht im erwarteten raw/-Ordner.")
        _relative(relative)
        if artifact.sha256 in artifact_files and artifact_files[artifact.sha256] != relative:
            raise ValueError("Widersprüchliche Rohdateipfade für denselben Quellhash.")
        artifact_files[artifact.sha256] = relative
        files["files/" + relative] = path

    for folder_name, suffixes in _ALLOWED_LOCAL_SUFFIXES.items():
        base = root / folder_name
        if not base.exists():
            continue
        if base.is_symlink() or not base.is_dir():
            raise ValueError("Berichtsordner ist kein regulärer lokaler Ordner.")
        for path in base.rglob("*"):
            if path.is_symlink():
                raise ValueError("Symbolischer Link im Berichtsordner ist nicht erlaubt.")
            if not path.is_file():
                continue
            relative = path.relative_to(root).as_posix()
            _relative(relative)
            if path.suffix.lower() not in suffixes:
                raise ValueError(
                    "Unbekannter Anhangstyp im Berichtsordner. "
                    "Bitte diesen vor dem vollständigen Export prüfen: " + path.suffix.lower()
                )
            files["files/" + relative] = _safe_file(root, path)
    return files, artifact_files


def _write_member(archive: ZipFile, entry: str, path: Path) -> dict[str, object]:
    digest = hashlib.sha256()
    count = 0
    with path.open("rb") as source, archive.open(entry, "w", force_zip64=True) as output:
        while block := source.read(_CHUNK):
            digest.update(block)
            count += len(block)
            if count > MAX_MEMBER_BYTES:
                raise ValueError("Eine Datei überschreitet die maximale Sicherungsgröße.")
            output.write(block)
    return {"name": entry, "bytes": count, "sha256": digest.hexdigest()}


def export_portable_backup(
    data_dir: Path, destination: Path, *, progress: Progress | None = None,
) -> PortableBackupResult:
    """Write a single .ntfbackup atomically, without passwords or browser profiles."""
    root = Path(data_dir).absolute()
    destination = Path(destination).absolute()
    if not destination.name.lower().endswith(BACKUP_EXTENSION):
        raise ValueError("Bitte eine Datei mit Endung .ntfbackup wählen.")
    if destination.is_relative_to(root) or destination.is_symlink():
        raise ValueError("Sicherung außerhalb des NTF-Insight-Datenordners speichern.")
    if destination.exists():
        raise FileExistsError("Zieldatei existiert bereits; nichts wurde überschrieben.")
    destination.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="ntf-snapshot-") as temp:
        snapshot = Path(temp) / DATABASE_NAME
        _message(progress, "Ausgewertete DuckDB-Datenbank konsistent kopieren …")
        _snapshot_database(_safe_file(root, root / DATABASE_NAME), snapshot)
        sources, artifact_files = _export_sources(root, snapshot)
        if len(sources) + 1 > MAX_ENTRIES:
            raise ValueError("Zu viele lokale Dateien für ein Transferpaket.")
        raw_shas = {"files/" + relative: sha for sha, relative in artifact_files.items()}

        fd, temp_name = tempfile.mkstemp(prefix=".ntf-export-", suffix=".partial",
                                         dir=destination.parent)
        os.close(fd)
        partial = Path(temp_name)
        try:
            entries = []
            with ZipFile(partial, "w", compression=ZIP_DEFLATED,
                         compresslevel=1, allowZip64=True) as archive:
                entries.append(_write_member(archive, DATABASE_ENTRY, snapshot))
                total_size = entries[0]["bytes"]
                for index, (name, path) in enumerate(sorted(sources.items()), 1):
                    item = _write_member(archive, name, path)
                    if name in raw_shas and item["sha256"] != raw_shas[name]:
                        raise ValueError("Rohdatei weicht von ihrer Datenbank-Prüfsumme ab.")
                    entries.append(item)
                    total_size += item["bytes"]
                    if total_size > MAX_TOTAL_BYTES:
                        raise ValueError("Das vollständige Paket überschreitet das Größenlimit.")
                    if index % 50 == 0:
                        _message(progress, f"{index}/{len(sources)} Dateien gesichert …")
                manifest = {
                    "format": FORMAT_NAME,
                    "version": FORMAT_VERSION,
                    "erstellt_am_utc": datetime.now(timezone.utc).isoformat(),
                    "duckdb_version": duckdb.__version__,
                    "files": entries,
                    "artifact_files": artifact_files,
                }
                data = json.dumps(manifest, ensure_ascii=False, sort_keys=True).encode("utf-8")
                if len(data) > MAX_MANIFEST_BYTES:
                    raise ValueError("Das Transfermanifest ist zu groß.")
                archive.writestr(MANIFEST_ENTRY, data)
            if destination.exists():
                raise FileExistsError("Zieldatei wurde inzwischen angelegt.")
            os.replace(partial, destination)
        finally:
            partial.unlink(missing_ok=True)
    _message(progress, "Gesamtdatenstand vollständig in einer Datei gesichert.")
    return PortableBackupResult(destination, len(entries), int(entries[0]["bytes"]))


def _inspect_backup(archive: ZipFile) -> tuple[list[dict], dict[str, str]]:
    infos = archive.infolist()
    if len(infos) > MAX_ENTRIES + 2 or any(info.is_dir() for info in infos):
        raise ValueError("Ungültige Anzahl oder Art von ZIP-Einträgen.")
    names = [info.filename for info in infos]
    if (
        len(set(names)) != len(names)
        or len(set(name.casefold() for name in names)) != len(names)
        or MANIFEST_ENTRY not in names
    ):
        raise ValueError("Doppelte ZIP-Pfade oder fehlendes Transfermanifest.")
    for info in infos:
        _relative(info.filename)
        if stat.S_IFMT(info.external_attr >> 16) == stat.S_IFLNK:
            raise ValueError("Symbolische Links sind im Transferpaket verboten.")
        if info.file_size > MAX_MEMBER_BYTES:
            raise ValueError("Eine Datei im Transferpaket ist zu groß.")
        if info.file_size / max(info.compress_size, 1) > 10000:
            raise ValueError("Verdächtige ZIP-Kompressionsrate.")
    if sum(info.file_size for info in infos) > MAX_TOTAL_BYTES + MAX_MANIFEST_BYTES:
        raise ValueError("Das Transferpaket überschreitet das Größenlimit.")
    manifest_info = archive.getinfo(MANIFEST_ENTRY)
    if manifest_info.file_size > MAX_MANIFEST_BYTES:
        raise ValueError("Transfermanifest ist zu groß.")
    try:
        manifest = json.loads(archive.read(MANIFEST_ENTRY))
    except (UnicodeError, ValueError) as exc:
        raise ValueError("Transfermanifest ist kein gültiges JSON.") from exc
    if (
        not isinstance(manifest, dict)
        or manifest.get("format") != FORMAT_NAME
        or manifest.get("version") != FORMAT_VERSION
    ):
        raise ValueError("Unbekanntes oder inkompatibles NTF-Insight-Paket.")
    entries = manifest.get("files")
    mappings = manifest.get("artifact_files")
    if not isinstance(entries, list) or not isinstance(mappings, dict):
        raise ValueError("Unvollständiges Transfermanifest.")
    indexed: dict[str, dict] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("Ungültiger Manifest-Dateieintrag.")
        name, size, sha = entry.get("name"), entry.get("bytes"), entry.get("sha256")
        if (
            not isinstance(name, str) or name in indexed
            or type(size) is not int or size < 0 or size > MAX_MEMBER_BYTES
            or not isinstance(sha, str) or not _SHA.fullmatch(sha)
        ):
            raise ValueError("Ungültiger Manifest-Dateieintrag.")
        _relative(name)
        if (
            name != DATABASE_ENTRY
            and not any(name.startswith("files/" + folder + "/") for folder in DATA_FOLDERS)
        ):
            raise ValueError("Nicht erlaubter Dateityp im Transferpaket.")
        indexed[name] = entry
        if archive.getinfo(name).file_size != size:
            raise ValueError("Transfermanifest und Dateigrößen stimmen nicht überein.")
    if DATABASE_ENTRY not in indexed or set(indexed) | {MANIFEST_ENTRY} != set(names):
        raise ValueError("Transferpaket enthält fehlende oder unbekannte Dateien.")
    for sha, relative in mappings.items():
        if (
            not isinstance(sha, str) or not _SHA.fullmatch(sha)
            or not isinstance(relative, str)
        ):
            raise ValueError("Ungültige Rohdateireferenz im Transfermanifest.")
        _relative(relative)
        if not relative.startswith("raw/") or "files/" + relative not in indexed:
            raise ValueError("Eine Rohdateireferenz fehlt im Transferpaket.")
        if indexed["files/" + relative]["sha256"] != sha:
            raise ValueError("Rohdateireferenz hat einen widersprüchlichen Hash.")
    return entries, mappings


def _validate_and_rebase_database(
    database: Path, mappings: dict[str, str], target_root: Path,
) -> tuple[int, int]:
    """Repoint just the archived-file paths; leave every parsed row untouched."""
    with duckdb.connect(str(database)) as con:
        tables = {
            row[0] for row in con.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'main'"
            ).fetchall()
        }
        if not {"source_artifacts", "case_snapshots", "manual_changes"} <= tables:
            raise ValueError("Die Sicherung enthält keine kompatible NTF-Insight-Datenbank.")
        artifacts = con.execute(
            "SELECT sha256, payload_json FROM source_artifacts"
        ).fetchall()
        if {sha for sha, _ in artifacts} != set(mappings):
            raise ValueError("Datenbank und Rohdateiinventar widersprechen sich.")
        con.execute("BEGIN TRANSACTION")
        try:
            for sha, payload in artifacts:
                artifact = SourceArtifact.model_validate_json(payload)
                if artifact.sha256 != sha:
                    raise ValueError("Quellidentität der Datenbank ist widersprüchlich.")
                relative = _relative(mappings[sha])
                new_path = target_root.joinpath(*relative.parts)
                changed = artifact.model_copy(update={"archived_path": str(new_path)})
                con.execute(
                    "UPDATE source_artifacts SET payload_json = ? WHERE sha256 = ?",
                    [changed.model_dump_json(), sha],
                )
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
        case_count = con.execute("SELECT COUNT(*) FROM case_snapshots").fetchone()[0]
        quicktests = (
            con.execute("SELECT COUNT(*) FROM quicktest_reports").fetchone()[0]
            if "quicktest_reports" in tables else 0
        )
        # Ensure new machine can use the single database file without a WAL sidecar.
        con.execute("CHECKPOINT")
    return int(case_count), int(quicktests)


def has_local_dataset(data_dir: Path) -> bool:
    """Recognize substantive pre-existing data; a new app creates an empty DB."""
    root = Path(data_dir).absolute()
    for folder_name in DATA_FOLDERS:
        folder = root / folder_name
        if folder.is_symlink():
            raise ValueError("Symbolischer Link im lokalen Datenverzeichnis.")
        if folder.is_file():
            raise ValueError("Ein erwarteter Datenordner ist eine Datei.")
        if folder.is_dir() and any(folder.iterdir()):
            return True
    database = root / DATABASE_NAME
    if not database.exists():
        return False
    if database.is_symlink():
        raise ValueError("Datenbankdatei ist ein symbolischer Link.")
    with duckdb.connect(str(database), read_only=True) as con:
        tables = [
            row[0] for row in con.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'main' AND table_type = 'BASE TABLE'"
            ).fetchall()
        ]
        return any(
            con.execute(
                'SELECT EXISTS(SELECT 1 FROM "' + table.replace('"', '""') + '" LIMIT 1)'
            ).fetchone()[0]
            for table in tables
        )


class _IncompleteRollback(RuntimeError):
    """The staging directory must remain available for manual recovery."""


def _replace_dataset(stage: Path, root: Path) -> None:
    """Same-filesystem install with rollback on rename/permission failure."""
    before = stage / "_vorher"
    before.mkdir()
    names = [*DATA_FOLDERS, DATABASE_NAME, DATABASE_NAME + ".wal"]
    moved_old: list[str] = []
    installed: list[str] = []
    try:
        for name in names:
            target = root / name
            if target.is_symlink():
                raise ValueError("Symbolischer Link im Ziel-Datenverzeichnis.")
            if target.exists():
                os.replace(target, before / name)
                moved_old.append(name)
        for folder in DATA_FOLDERS:
            source = stage / "files" / folder
            source.mkdir(parents=True, exist_ok=True)
            os.replace(source, root / folder)
            installed.append(folder)
        os.replace(stage / DATABASE_ENTRY, root / DATABASE_NAME)
        installed.append(DATABASE_NAME)
    except Exception as original:
        errors = []
        for name in reversed(installed):
            path = root / name
            try:
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink(missing_ok=True)
            except OSError as exc:
                errors.append(f"{name}: {type(exc).__name__}")
        for name in reversed(moved_old):
            try:
                os.replace(before / name, root / name)
            except OSError as exc:
                errors.append(f"{name}: {type(exc).__name__}")
        if errors:
            raise _IncompleteRollback(
                "Rücksetzung nicht vollständig; alte Daten zur manuellen "
                f"Wiederherstellung erhalten unter {before}."
            ) from original
        raise


def restore_portable_backup(
    package: Path, data_dir: Path, *,
    replace_existing: bool = False,
    progress: Progress | None = None,
) -> PortableRestoreResult:
    """Validate all bytes before replacing data. Never run source parsers."""
    root = Path(data_dir).absolute()
    package = Path(package).absolute()
    if root.is_symlink() or package.is_symlink():
        raise ValueError("Symbolische Links dürfen nicht als Transferpfad verwendet werden.")
    if package.is_relative_to(root):
        raise ValueError("Paket bitte außerhalb des NTF-Insight-Datenordners ablegen.")
    if not package.is_file():
        raise FileNotFoundError(package)
    root.mkdir(parents=True, exist_ok=True)
    if has_local_dataset(root) and not replace_existing:
        raise ValueError(
            "Auf diesem PC existieren bereits Daten. "
            "Vor dem Ersetzen bitte deren vollständiges Paket exportieren."
        )
    stage = Path(tempfile.mkdtemp(prefix=".ntf-restore-", dir=root.parent))
    preserve_stage = False
    try:
        with ZipFile(package) as archive:
            entries, artifact_files = _inspect_backup(archive)
            _message(progress, "Paket und alle Prüfsummen überprüfen …")
            for index, entry in enumerate(entries, start=1):
                name = entry["name"]
                relative = _relative(name)
                staged = stage.joinpath(*relative.parts)
                staged.parent.mkdir(parents=True, exist_ok=True)
                digest = hashlib.sha256()
                count = 0
                with archive.open(name) as source, staged.open("wb") as target:
                    while block := source.read(_CHUNK):
                        digest.update(block)
                        count += len(block)
                        if count > entry["bytes"]:
                            raise ValueError("Entpackte Datei ist größer als im Manifest.")
                        target.write(block)
                if count != entry["bytes"] or digest.hexdigest() != entry["sha256"]:
                    raise ValueError("Paket beschädigt: Prüfsumme oder Dateigröße falsch.")
                if index % 50 == 0:
                    _message(progress, f"{index}/{len(entries)} Dateien überprüft …")
        # Validate the entire database and rewrite absolute raw archive paths
        # while the destination is still completely untouched.
        _message(progress, "Datenbank prüfen und lokale Quellpfade anpassen …")
        case_count, quicktests = _validate_and_rebase_database(
            stage / DATABASE_ENTRY, artifact_files, root,
        )
        if has_local_dataset(root) and not replace_existing:
            raise ValueError("Zieldaten wurden zwischenzeitlich verändert.")
        _message(progress, "Geprüften Gesamtdatenstand ohne Neuparsen wiederherstellen …")
        _replace_dataset(stage, root)
    except _IncompleteRollback:
        # Never delete original files that could not be moved back.
        preserve_stage = True
        raise
    finally:
        if not preserve_stage:
            shutil.rmtree(stage, ignore_errors=True)
    return PortableRestoreResult(
        file_count=len(entries), case_count=case_count, quicktest_count=quicktests,
    )
