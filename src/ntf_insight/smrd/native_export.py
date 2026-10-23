"""Windows-only offline Softing.Dts.dll backend for DTC metadata.

No proprietary binaries, licenses or ECU data are bundled. No license bypass,
no vehicle connection and no diagnostic service execution is attempted.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from importlib.resources import files
from pathlib import Path

from ntf_insight.smrd.library import SmrdLocalLibrary, digest
from ntf_insight.smrd.native_details import NativeDetailError, parse_native_details


class NativeRuntimeError(RuntimeError):
    """Native Softing runtime is missing, incompatible or returned an error."""


def resolve_runtime_dir(runtime_dir: Path | None, library: SmrdLocalLibrary) -> tuple[Path, Path]:
    """Find the user's locally installed licensed runtime, never repo binaries."""
    base = (
        Path(runtime_dir).expanduser()
        if runtime_dir
        else (
            Path(os.environ["NTF_SOFTING_RUNTIME_DIR"]).expanduser()
            if os.environ.get("NTF_SOFTING_RUNTIME_DIR")
            else library.root / "runtime" / "SMRxView"
        )
    ).resolve()
    candidates = (base / "mvci" / "bin", base / "bin", base)
    for binary_dir in candidates:
        if (binary_dir / "Softing.Dts.dll").is_file() and (
            binary_dir / "csWrap.dll"
        ).is_file():
            return base, binary_dir
    raise NativeRuntimeError(
        "Kompatible lokale Softing-Laufzeit fehlt (Softing.Dts.dll/csWrap.dll). "
        f"Pruefe {base}; installiere/kopiere eine selbst lizenzierte Laufzeit "
        "ausserhalb des Git-Repositories."
    )


def _run_script(
    script: Path,
    *,
    source: Path | None,
    runtime: Path,
    output: Path | None,
    timeout: int,
    probe_only: bool,
) -> subprocess.CompletedProcess:
    if sys.platform != "win32":
        raise NativeRuntimeError("Der native DTS-Exporter erfordert Windows x64.")
    if sys.maxsize <= 2**32:
        raise NativeRuntimeError("Der native DTS-Exporter erfordert 64-Bit-Python.")
    executable = shutil.which("powershell.exe")
    if executable is None:
        raise NativeRuntimeError("Windows PowerShell 5.1 wurde nicht gefunden.")
    args = [
        executable,
        "-NoProfile", "-NonInteractive", "-File", str(script),
        "-RuntimeDir", str(runtime),
    ]
    if probe_only:
        args.append("-ProbeOnly")
    else:
        assert source is not None and output is not None
        args.extend(["-SmrdFile", str(source), "-OutputJson", str(output)])
    try:
        return subprocess.run(
            args, cwd=runtime, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout, check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise NativeRuntimeError(
            "Die Softing-DTS-Konvertierung hat das Zeitlimit ueberschritten."
        ) from exc


def native_probe(
    *,
    runtime_dir: Path | None = None,
    data_dir: Path | None = None,
    timeout: int = 40,
) -> str:
    library = SmrdLocalLibrary(data_dir=data_dir)
    runtime, _ = resolve_runtime_dir(runtime_dir, library)
    script = Path(str(files("ntf_insight.smrd").joinpath("softing_native_export.ps1")))
    result = _run_script(
        script, source=None, output=None, runtime=runtime,
        timeout=timeout, probe_only=True,
    )
    if result.returncode:
        raise NativeRuntimeError(
            (result.stderr or result.stdout or "DTS-Probe fehlgeschlagen")[-4000:]
        )
    return result.stdout.strip()


def export_native_dtcs(
    smrd: Path,
    *,
    runtime_dir: Path | None = None,
    data_dir: Path | None = None,
    output_path: Path | None = None,
    timeout: int = 240,
) -> tuple[Path, int]:
    """Extract offline native DTS DTC details; reject incomplete and empty output."""
    smrd = Path(smrd).expanduser().resolve()
    if not smrd.is_file() or smrd.suffix.casefold() != ".smr-d":
        raise FileNotFoundError(f"SMR-D-Datei fehlt: {smrd}")
    library = SmrdLocalLibrary(data_dir=data_dir)
    runtime, _ = resolve_runtime_dir(runtime_dir, library)
    from ntf_insight.smrd.runtime_config import diagnose_native_runtime

    health = diagnose_native_runtime(runtime)
    if not health["ready_for_native_attempt"]:
        missing = ", ".join(health["missing"])
        differences = ", ".join(item["key"] for item in health["mismatches"])
        errors = "; ".join(health["errors"])
        raise NativeRuntimeError(
            "Softing-Laufzeit vor dem nativen Aufruf nicht bereit. "
            "Abbruch, um einen erneuten CSNIDTS_getSystem-Absturz zu vermeiden. "
            f"Fehlend: {missing or '-'}; falsche Pfade: {differences or '-'}; "
            f"Konfigurationsfehler: {errors or '-'}. "
            "Bitte erst 'python -m ntf_insight.smrd native-doctor' ausfuehren."
        )
    library.exports.mkdir(parents=True, exist_ok=True)
    output = (
        Path(output_path).expanduser().resolve()
        if output_path
        else library.exports / f"{digest(smrd)}.native-dtc.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    script = Path(str(files("ntf_insight.smrd").joinpath("softing_native_export.ps1")))
    with tempfile.TemporaryDirectory(dir=library.exports, prefix=".native-") as workdir:
        intermediate = Path(workdir) / "details.json"
        result = _run_script(
            script, source=smrd, runtime=runtime, output=intermediate,
            timeout=timeout, probe_only=False,
        )
        if result.returncode:
            raise NativeRuntimeError(
                "Softing-DTS-Exporter fehlgeschlagen. Keine Datenbank veraendert.\n"
                + (result.stderr or result.stdout or "DTS gab keine Details zurueck")[-6000:]
            )
        try:
            metadata, rows = parse_native_details(intermediate)
        except (NativeDetailError, ValueError) as exc:
            raise NativeRuntimeError(f"Native-DTS-JSON unvollstaendig: {exc}") from exc
        if metadata["smrd_sha256"] != digest(smrd):
            raise NativeRuntimeError(
                "Die SMR-D-Pruefsumme stimmt mit dem Export nicht ueberein."
            )
        os.replace(intermediate, output)
    return output, len(rows)
