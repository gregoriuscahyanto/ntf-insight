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


def _atomic_write_with_backup(path: Path, new_bytes: bytes) -> Path | None:
    old = path.read_bytes()
    if old == new_bytes:
        return None
    sha = hashlib.sha256(old).hexdigest()[:16]
    backup = path.with_name(path.name + f".before_smrd_paths_{sha}.bak")
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
