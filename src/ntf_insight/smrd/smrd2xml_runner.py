"""Optional offline Windows adapter for the USER'S OWN Smrd2Xml.exe.

"Offline" means no Internet is used by this adapter. It does NOT mean the
proprietary executable has no DTS/BaseSystem licensing requirements. Never
bundle, alter, patch, emulate or bypass the vendor program or its license.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from xml.etree import ElementTree as ET

from ntf_insight.smrd.library import SmrdLocalLibrary, digest
from ntf_insight.smrd.offline_convert import offline_convert
from ntf_insight.smrd.xml_reference import parse_xml


MODES = ("ECU", "DTCSXML", "COMPAR", "CANMODEL")
DEFAULT_MODES = ("ECU", "DTCSXML")
MAX_XML_BYTES = 160_000_000


class Smrd2XmlError(RuntimeError):
    """Vendor tool failed or produced no useful XML."""


class Smrd2XmlLicenseError(Smrd2XmlError):
    """The external vendor program needs a license not available locally."""


def guess_ecu_name(smrd: Path) -> str:
    """Suggest an ECU name from a filename, never claim it is authenticated."""
    stem = Path(smrd).stem
    match = re.match(r"^(.+?)_\d{2}\.\d{2}\.\d{2}(?:_|$)", stem)
    name = match.group(1) if match else stem.split(".")[0]
    if not re.fullmatch(r"[A-Za-z0-9_]+(?:\.\d+\.\d+\.\d+)?", name):
        raise ValueError(
            "ECU-Name aus Dateiname nicht erkennbar. --ecu explizit angeben."
        )
    return name


def _xml_snapshots(folders: list[Path]) -> dict[Path, tuple[int, int]]:
    snapshots = {}
    for folder in folders:
        if not folder.is_dir():
            continue
        for item in folder.glob("*.xml"):
            if item.is_file() and not item.is_symlink():
                stat = item.stat()
                snapshots[item.resolve()] = (stat.st_size, stat.st_mtime_ns)
    return snapshots


def _checked_xml(path: Path) -> tuple[str, bool]:
    """Accept safe XML documents and identify the formats NTF can index."""
    size = path.stat().st_size
    if not 0 < size <= MAX_XML_BYTES:
        raise ValueError("XML-Leerdatei oder Groessengrenze ueberschritten")
    raw = path.read_bytes()
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise ValueError("XML-DTD/ENTITY nicht erlaubt")
    root = ET.fromstring(raw)
    tag = root.tag.rsplit("}", 1)[-1]
    return tag, tag.casefold() in ("ecus", "smrd2xml")


def _error_from_vendor(result: subprocess.CompletedProcess, mode: str) -> Smrd2XmlError:
    message = ((result.stderr or "") + "\n" + (result.stdout or ""))[-5000:]
    if any(
        term in message.casefold()
        for term in (
            "esystem_license_error",
            "no basesystem license was found",
            "basesystem license",
        )
    ):
        return Smrd2XmlLicenseError(
            f"Smrd2Xml ({mode}) meldet eine fehlende DTS-BaseSystem-Lizenz. "
            "Das Programm ist lokal/offline, aber nicht nachweislich lizenzfrei. "
            "Bitte Berechtigung im offiziellen Softing-System-Configurator "
            "pruefen; NTF Insight umgeht keine Lizenzkontrolle.\n" + message
        )
    return Smrd2XmlError(
        f"Smrd2Xml ({mode}) fehlgeschlagen, Exit-Code {result.returncode}. "
        "Keine DTC-Daten erfunden oder importiert.\n" + message
    )


def run_smrd2xml(
    smrd: Path,
    *,
    runtime_dir: Path | None = None,
    data_dir: Path | None = None,
    ecu: str | None = None,
    modes: tuple[str, ...] = DEFAULT_MODES,
    timeout: int = 180,
    remember: bool = False,
    dry_run: bool = False,
) -> dict:
    """Invoke the local vendor executable and catalogue only genuine XML output.

    The original SMR-D is read-only: the executable receives a local staged
    COPY. Vendor outputs, logs and the optional JSON bundle remain under the
    user's .ntf-insight/smrd/exporte directory. No DB import is performed.
    """
    library = SmrdLocalLibrary(data_dir=data_dir)
    original = Path(smrd).expanduser()
    if original.is_symlink() or not original.is_file() or original.suffix.lower() != ".smr-d":
        raise ValueError("Eine regulaere lokale .smr-d-Datei ist erforderlich")
    source = original.resolve()
    runtime = (
        Path(runtime_dir).expanduser().resolve()
        if runtime_dir is not None
        else (library.root / "runtime" / "SMRxView").resolve()
    )
    executable = runtime / "Smrd2Xml.exe"
    if executable.is_symlink() or not executable.is_file():
        raise FileNotFoundError(
            "Smrd2Xml.exe fehlt. Das eigene, rechtmaessig bereitgestellte "
            f"Originalprogramm unter {runtime} verwenden; niemals ins Git kopieren."
        )
    if not modes or any(mode not in MODES for mode in modes):
        raise ValueError(f"Zulaessige Smrd2Xml-Modi: {', '.join(MODES)}")
    modes = tuple(dict.fromkeys(modes))
    ecu_name = (ecu or guess_ecu_name(source)).strip()
    if "ECU" in modes and not re.fullmatch(
        r"[A-Za-z0-9_]+(?:\.\d+\.\d+\.\d+)?", ecu_name
    ):
        raise ValueError("Ungueltiger ECU-Bezeichner")
    if timeout < 5 or timeout > 1800:
        raise ValueError("Timeout muss zwischen 5 und 1800 Sekunden liegen")
    checksum = digest(source)
    export_root = library.exports / "smrd2xml" / checksum
    plan = {
        "source_smrd_sha256": checksum,
        "runtime_dir": str(runtime),
        "executable": str(executable),
        "ecu_name_guess": ecu_name,
        "selected_modes": list(modes),
        "license_free_guaranteed": False,
        "network_used_by_adapter": False,
        "executed": not dry_run,
    }
    if dry_run:
        return plan
    if sys.platform != "win32":
        raise Smrd2XmlError("Smrd2Xml.exe kann nur auf Windows ausgefuehrt werden")
    library._ensure()
    export_root.mkdir(parents=True, exist_ok=True)
    if export_root.is_symlink():
        raise ValueError("Symlink als Exportordner verboten")

    xml_sources: list[Path] = []
    raw_only: list[dict] = []
    runs: list[dict] = []
    warnings: list[str] = []
    # No modification of the original .smr-d is possible through the input path.
    with tempfile.TemporaryDirectory(dir=library.exports, prefix=".smrd2xml-work-") as tmp:
        working = Path(tmp)
        staged_source = working / source.name
        shutil.copyfile(source, staged_source)
        if digest(staged_source) != checksum:
            raise ValueError("Kopie der SMR-D hat eine abweichende Pruefsumme")
        for mode in modes:
            mode_dir = export_root / mode
            mode_dir.mkdir(parents=True, exist_ok=True)
            folders = [working, runtime, mode_dir]
            before = _xml_snapshots(folders)
            if mode == "ECU":
                command = [
                    str(executable), ecu_name, str(staged_source),
                    str(mode_dir), "",
                ]
            else:
                # These positional forms are embedded in the supplied EXE.
                command = [str(executable), mode, str(staged_source)]
            try:
                result = subprocess.run(
                    command, cwd=runtime, capture_output=True, text=True,
                    encoding="utf-8", errors="replace", timeout=timeout, check=False,
                )
            except subprocess.TimeoutExpired as exc:
                raise Smrd2XmlError(
                    f"Smrd2Xml ({mode}) hat nach {timeout}s das Zeitlimit "
                    "erreicht. Keine unvollstaendige Ausgabe importieren."
                ) from exc
            run_report = {
                "mode": mode,
                "exit_code": result.returncode,
                "xml_files": [],
                "unindexed_xml": [],
            }
            # Logs remain on this PC and can include vendor diagnostics.
            log = mode_dir / "converter.log"
            log.write_text(
                f"Mode: {mode}\nExit: {result.returncode}\n"
                f"Source SHA256: {checksum}\n"
                f"\n--- stdout (first 60000 chars) ---\n{(result.stdout or '')[:60000]}"
                f"\n--- stderr (first 60000 chars) ---\n{(result.stderr or '')[:60000]}\n",
                encoding="utf-8",
            )
            run_report["log_file"] = str(log)
            if result.returncode:
                raise _error_from_vendor(result, mode)
            # Some versions write XML to stdout, others into the output
            # folder, the input folder or the converter working directory.
            if (result.stdout or "").lstrip().startswith("<?xml"):
                (mode_dir / "stdout.xml").write_text(result.stdout, encoding="utf-8")
            after = _xml_snapshots(folders)
            candidates = [
                path for path, state in after.items()
                if path not in before or before[path] != state
            ]
            # Skip XML files not produced or changed by this invocation.
            for path in sorted(candidates):
                try:
                    root_tag, can_index = _checked_xml(path)
                except (OSError, ValueError, ET.ParseError) as exc:
                    warnings.append(
                        f"{mode}: Ausgabe {path.name} ist kein sicheres XML: {exc}"
                    )
                    continue
                if path.parent != mode_dir.resolve():
                    destination = mode_dir / path.name
                    if destination.exists():
                        destination = mode_dir / (
                            path.stem + "-" + hashlib.sha256(str(path).encode()).hexdigest()[:8]
                            + ".xml"
                        )
                    shutil.copy2(path, destination)
                else:
                    destination = path
                item = {
                    "file": str(destination),
                    "xml_root": root_tag,
                    "sha256": digest(destination),
                }
                if can_index:
                    # A recognized schema may still be invalid. Do not add it
                    # until the strict reference parser accepts it.
                    try:
                        parse_xml(destination)
                    except (ValueError, ET.ParseError) as exc:
                        warnings.append(
                            f"{mode}: XML {destination.name} nicht indexierbar: {exc}"
                        )
                        raw_only.append(item)
                    else:
                        xml_sources.append(destination)
                        run_report["xml_files"].append(item)
                else:
                    raw_only.append(item)
                    run_report["unindexed_xml"].append(item)
            if not run_report["xml_files"] and not run_report["unindexed_xml"]:
                warnings.append(
                    f"{mode}: Kein neues XML gefunden; Details in {log}."
                )
            runs.append(run_report)
    xml_sources = list(dict.fromkeys(xml_sources))
    summary = {
        **plan,
        "tool_sha256": digest(executable),
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "mode_runs": runs,
        "generated_xml": [str(path) for path in xml_sources],
        "additional_xml": raw_only,
        "warnings": warnings,
        "xml_catalogue_generated": bool(xml_sources),
    }
    if xml_sources:
        report = offline_convert(
            source, xml_files=xml_sources, data_dir=data_dir, remember=remember,
            xml_origin="smrd2xml_local_vendor_export",
        )
        summary["bundle"] = report["bundle"]
        summary["counts"] = report["counts"]
        summary["total_references"] = report["total_references"]
        summary["provenance_note"] = (
            "Referenzen sind durch das vom Benutzer lokal ausgefuehrte "
            "Smrd2Xml.exe erzeugte XML-Daten; der NTF-Python-Parser "
            "entschluesselt den binaeren SMR-D-Payload nicht."
        )
    else:
        summary["counts"] = {}
        summary["total_references"] = 0
    manifest = export_root / "smrd2xml-run.json"
    manifest.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    summary["manifest"] = str(manifest)
    return summary
