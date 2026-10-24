"""Inspect and explicitly repair filesystem paths in a LOCAL COPY of DTS.

No vendor DLL, license, calibration, or SMR-D payload is modified.
Static checks cannot prove that native DTS initialization will succeed.
"""
from __future__ import annotations

import hashlib
import ntpath
import os
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from ntf_insight.smrd.library import SmrdLocalLibrary

_CONFIGS = (
    ("mvci/SystemConfig.xml", "SystemConfig"),
    ("mvci/config/DtsConfig64.xml", "DtsConfig"),
)
_REQUIRED = (
    "mvci/bin/Softing.Dts.dll", "mvci/bin/csWrap.dll",
    "mvci/bin/cppApi.dll", "mvci/bin/DtsKrnl.dll",
    "mvci/config/license.bin", "globals", "mvciprojects",
)
_TEXT = {"ConfigurationPath", "TracePath", "ProjectPath", "DatabaseCachesPath"}
_ATTR = {"com.softing.GlobalSmrFilePath", "com.softing.StoragePath"}


def _expected(runtime: Path) -> dict[str, str]:
    return {
        "ConfigurationPath": str(runtime / "mvci" / "config"),
        "TracePath": str(runtime / "temp"),
        "ProjectPath": str(runtime / "mvciprojects"),
        "DatabaseCachesPath": str(runtime / "temp"),
        "com.softing.GlobalSmrFilePath": str(runtime / "globals"),
        "com.softing.StoragePath": str(runtime / "temp"),
    }


def _norm(value: str) -> str:
    return ntpath.normcase(ntpath.normpath(value.strip()))


def _read_xml(path: Path, expected_root: str) -> ET.ElementTree:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Konfiguration fehlt oder ist ein Link: {path.name}")
    if not 0 < path.stat().st_size < 2_000_000:
        raise ValueError(f"Ungueltige XML-Dateigroesse: {path.name}")
    raw = path.read_bytes()
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise ValueError(f"DOCTYPE/ENTITY nicht erlaubt: {path.name}")
    root = ET.fromstring(raw)
    if root.tag != expected_root:
        raise ValueError(f"Unerwartetes XML-Format: {path.name}")
    return ET.ElementTree(root)


def _fields(tree: ET.ElementTree) -> dict[str, tuple[ET.Element, str]]:
    result: dict[str, tuple[ET.Element, str]] = {}
    for element in tree.getroot().iter():
        if element.tag in _TEXT:
            key, attribute = element.tag, "text"
        elif element.tag == "SystemProperty" and element.get("ShortName") in _ATTR:
            key, attribute = str(element.get("ShortName")), "Value"
        else:
            continue
        if key in result:
            raise ValueError(f"Doppelter DTS-Konfigurationswert: {key}")
        result[key] = (element, attribute)
    return result


def _current(element: ET.Element, attribute: str) -> str:
    return (element.text or "").strip() if attribute == "text" else (element.get(attribute) or "").strip()


def diagnose_native_runtime(runtime_dir: Path) -> dict:
    """Only read local DTS configuration, never invoke native getSystem()."""
    runtime = Path(runtime_dir).expanduser().resolve()
    expected = _expected(runtime)
    report: dict = {
        "runtime": str(runtime), "ready_for_native_attempt": False,
        "missing": [], "mismatches": [], "errors": [],
        "note": "Statischer Check, kein Funktions-/Lizenznachweis.",
    }
    if not runtime.is_dir():
        report["errors"].append("Runtime-Verzeichnis fehlt")
        return report
    for relative in _REQUIRED:
        if not (runtime / Path(relative)).exists():
            report["missing"].append(relative)
    for relative, root in _CONFIGS:
        try:
            tree = _read_xml(runtime / Path(relative), root)
            fields = _fields(tree)
            keys = {"ConfigurationPath"} if root == "SystemConfig" else set(expected) - {"ConfigurationPath"}
            for name in sorted(keys):
                if name not in fields:
                    report["errors"].append(f"{relative}: Schluessel fehlt: {name}")
                    continue
                element, attribute = fields[name]
                actual = _current(element, attribute)
                if _norm(actual) != _norm(expected[name]):
                    report["mismatches"].append({
                        "config": relative, "key": name,
                        "actual": actual, "expected": expected[name],
                    })
        except (ValueError, ET.ParseError, OSError, UnicodeError) as exc:
            report["errors"].append(f"{relative}: {exc}")
    report["ready_for_native_attempt"] = not any(
        report[k] for k in ("missing", "mismatches", "errors")
    )
    return report


def _atomic_write_with_backup(
    path: Path, new_bytes: bytes, *, reason: str = "paths"
) -> Path | None:
    old = path.read_bytes()
    if old == new_bytes:
        return None
    sha = hashlib.sha256(old).hexdigest()[:16]
    backup = path.with_name(path.name + f".before_smrd_{reason}_{sha}.bak")
    if backup.exists():
        if backup.read_bytes() != old:
            raise FileExistsError(f"Backup-Kollision: {backup}")
    else:
        with backup.open("xb") as handle:
            handle.write(old)
            handle.flush()
            os.fsync(handle.fileno())
    staged: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=path.name + ".", suffix=".tmp", delete=False
        ) as handle:
            staged = Path(handle.name)
            handle.write(new_bytes)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(staged, path)
    finally:
        if staged is not None:
            staged.unlink(missing_ok=True)
    return backup


def prepare_native_runtime(
    runtime_dir: Path, *, data_dir: Path | None = None, apply: bool = False
) -> dict:
    """Repoint XML paths only in a user-local runtime COPY, with backups."""
    library = SmrdLocalLibrary(data_dir=data_dir)
    given = Path(runtime_dir).expanduser()
    if given.is_symlink():
        raise ValueError("Symbolischer Runtime-Link nicht erlaubt")
    runtime = given.resolve()
    allowed = (library.root / "runtime").resolve()
    if runtime == allowed or not runtime.is_relative_to(allowed):
        raise ValueError("Nur lokale Kopie unter .ntf-insight/smrd/runtime darf geaendert werden")
    report = diagnose_native_runtime(runtime)
    if report["missing"] or report["errors"]:
        raise ValueError(f"Runtime unvollstaendig: {report['missing']} {report['errors']}")
    report["applied"] = False
    report["backups"] = []
    if not report["mismatches"]:
        return report
    wanted = _expected(runtime)
    replacements: list[tuple[Path, bytes]] = []
    for relative, root in _CONFIGS:
        path = runtime / Path(relative)
        tree = _read_xml(path, root)
        entries = _fields(tree)
        names = {"ConfigurationPath"} if root == "SystemConfig" else set(wanted) - {"ConfigurationPath"}
        for name in names:
            element, attribute = entries[name]
            if attribute == "text":
                element.text = wanted[name]
            else:
                element.set(attribute, wanted[name])
        serialized = ET.tostring(tree.getroot(), encoding="utf-8", xml_declaration=True)
        ET.fromstring(serialized)
        replacements.append((path, serialized))
    if not apply:
        return report
    (runtime / "temp").mkdir(parents=True, exist_ok=True)
    # Validate backup collisions before touching either config file.
    for path, _ in replacements:
        old = path.read_bytes()
        backup = path.with_name(
            path.name + f".before_smrd_paths_{hashlib.sha256(old).hexdigest()[:16]}.bak"
        )
        if backup.exists() and backup.read_bytes() != old:
            raise FileExistsError(f"Backup-Kollision: {backup}")
    for path, content in replacements:
        saved = _atomic_write_with_backup(path, content)
        if saved is not None:
            report["backups"].append(str(saved))
    final = diagnose_native_runtime(runtime)
    if not final["ready_for_native_attempt"]:
        raise ValueError("Nachkontrolle fehlgeschlagen. Originale als .bak gesichert.")
    final["applied"] = True
    final["backups"] = report["backups"]
    return final


def _archive_member(
    archive: zipfile.ZipFile, suffix: str, *, maximum_bytes: int
) -> zipfile.ZipInfo:
    """Find one fixed member name without extracting the zip or following paths."""
    suffix = "/" + suffix.lower().replace("\\", "/")
    found: list[zipfile.ZipInfo] = []
    for info in archive.infolist():
        name = info.filename.replace("\\", "/")
        parts = name.split("/")
        if name.startswith("/") or ".." in parts or "." in parts:
            raise ValueError("Unsicherer Pfad im Originalarchiv")
        if not info.is_dir() and ("/" + name.lower()).endswith(suffix):
            found.append(info)
    if len(found) != 1:
        raise ValueError(
            f"Originalarchiv enthaelt nicht exakt eine Datei {suffix}: {len(found)}"
        )
    info = found[0]
    if not 0 < info.file_size <= maximum_bytes:
        raise ValueError(f"Unplausible Dateigroesse in Originalarchiv: {suffix}")
    if info.flag_bits & 0x1:
        raise ValueError("Verschluesselte ZIP-Eintraege nicht unterstuetzt")
    return info


def _zip_bytes(
    archive: zipfile.ZipFile, member: zipfile.ZipInfo, maximum_bytes: int
) -> bytes:
    with archive.open(member, "r") as handle:
        data = handle.read(maximum_bytes + 1)
    if len(data) > maximum_bytes or len(data) != member.file_size:
        raise ValueError(f"ZIP-Eintrag ausserhalb der Groessengrenze: {member.filename}")
    return data


def recover_native_runtime_configs(
    runtime_dir: Path,
    source_zip: Path,
    *,
    data_dir: Path | None = None,
    apply: bool = False,
) -> dict:
    """Restore ONLY malformed XML config files from the user's matching vendor ZIP.

    The archive's native DLL hashes must match the local runtime. Only
    non-well-formed configs are eligible; valid user customization is preserved.
    Dry-run by default. Explicit apply produces byte-exact, SHA-named backups.
    """
    library = SmrdLocalLibrary(data_dir=data_dir)
    given = Path(runtime_dir).expanduser()
    allowed = (library.root / "runtime").resolve()
    runtime = given.resolve()
    if runtime == allowed or not runtime.is_relative_to(allowed):
        raise ValueError("Wiederherstellung nur unter .ntf-insight/smrd/runtime erlaubt")
    for candidate in (
        library.root, library.root / "runtime", given,
        given / "mvci", given / "mvci" / "bin", given / "mvci" / "config",
    ):
        if candidate.is_symlink():
            raise ValueError("Symbolischer Link in Runtime-Kopie nicht erlaubt")
    zip_path = Path(source_zip).expanduser().resolve()
    if not zip_path.is_file() or zip_path.suffix.lower() != ".zip":
        raise ValueError("Original-SMRxView-ZIP fehlt")
    report: dict = {
        "runtime": str(runtime),
        "source_archive": str(zip_path),
        "dll_hashes_match": False,
        "malformed_configurations": [],
        "preserved_valid_configurations": [],
        "restorable_count": 0,
        "applied": False,
        "backups": [],
        "note": "Keine Hersteller-Binaries, Lizenzen oder SMR-D-Dateien werden veraendert.",
    }
    updates: list[tuple[Path, bytes]] = []
    with zipfile.ZipFile(zip_path, "r") as archive:
        if len(archive.infolist()) > 5000:
            raise ValueError("Originalarchiv enthaelt zu viele ZIP-Eintraege")
        # Check the provenance of the original archive against all four
        # native components so we cannot mix different DTS distributions.
        for binary in ("Softing.Dts.dll", "csWrap.dll", "cppApi.dll", "DtsKrnl.dll"):
            member = _archive_member(
                archive, f"mvci/bin/{binary}", maximum_bytes=64_000_000
            )
            old_bytes = _zip_bytes(archive, member, 64_000_000)
            installed = runtime / "mvci" / "bin" / binary
            if not installed.is_file() or installed.is_symlink():
                raise ValueError(f"Lokale Softing-Binaerdatei fehlt: {binary}")
            actual = hashlib.sha256(installed.read_bytes()).digest()
            expected = hashlib.sha256(old_bytes).digest()
            if actual != expected:
                raise ValueError(
                    f"ZIP gehoert nicht zur lokalen Softing-Runtime ({binary} abweichend)."
                )
        report["dll_hashes_match"] = True
        for relative, root in _CONFIGS:
            path = runtime / Path(relative)
            vendor_member = _archive_member(
                archive, relative, maximum_bytes=2_000_000
            )
            known_good = _zip_bytes(archive, vendor_member, 2_000_000)
            # Verify the archived config before permitting any local changes.
            upper = known_good.upper()
            if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
                raise ValueError(f"Originalarchiv enthaelt DTD/ENTITY: {relative}")
            if ET.fromstring(known_good).tag != root:
                raise ValueError(f"Originalarchiv enthaelt falsches XML: {relative}")
            if not path.is_file() or path.is_symlink():
                raise ValueError(f"Lokale Runtime-Konfiguration fehlt: {relative}")
            try:
                _read_xml(path, root)
            except (ValueError, ET.ParseError, UnicodeError) as exc:
                report["malformed_configurations"].append({
                    "file": relative,
                    "parser_error": str(exc)[:240],
                    "zip_member": vendor_member.filename,
                })
                updates.append((path, known_good))
            else:
                report["preserved_valid_configurations"].append(relative)
        report["restorable_count"] = len(updates)
    if not apply or not updates:
        return report
    # Preflight ALL backups before overwriting any XML file.
    for path, _ in updates:
        previous = path.read_bytes()
        short_sha = hashlib.sha256(previous).hexdigest()[:16]
        backup = path.with_name(path.name + f".before_smrd_restore_{short_sha}.bak")
        if backup.exists() and backup.read_bytes() != previous:
            raise FileExistsError(f"Backup-Kollision: {backup}")
    for path, known_good in updates:
        original = _atomic_write_with_backup(path, known_good, reason="restore")
        if original is not None:
            report["backups"].append(str(original))
    # Do not claim runtime readiness: the XML now contains its original
    # installation paths and still needs a separate checked relocation.
    report["applied"] = True
    report["doctor_after_restore"] = diagnose_native_runtime(runtime)
    return report
