"""Read native DLL export names without loading code into the process."""
from __future__ import annotations

import struct
from pathlib import Path


class NativeSymbolError(ValueError):
    """Malformed, unsupported or inaccessible PE export table."""


def _u16(data: bytes, offset: int) -> int:
    if not 0 <= offset <= len(data) - 2:
        raise NativeSymbolError("PE: 16-Bit-Feld ausserhalb der Datei")
    return struct.unpack_from("<H", data, offset)[0]


def _u32(data: bytes, offset: int) -> int:
    if not 0 <= offset <= len(data) - 4:
        raise NativeSymbolError("PE: 32-Bit-Feld ausserhalb der Datei")
    return struct.unpack_from("<I", data, offset)[0]


def dll_exports(path: Path, *, max_size: int = 64_000_000) -> frozenset[str]:
    """Statically list named exports of a 32/64-bit Windows PE DLL."""
    path = Path(path)
    if not path.is_file() or not 0 < path.stat().st_size <= max_size:
        raise NativeSymbolError("Native DLL fehlt oder ist zu gross")
    raw = path.read_bytes()
    if raw[:2] != b"MZ":
        raise NativeSymbolError("Kein PE/DLL-Header")
    pe = _u32(raw, 0x3C)
    if pe < 0x40 or pe > len(raw) - 24 or raw[pe:pe + 4] != b"PE\0\0":
        raise NativeSymbolError("Ungueltiger PE-Header")
    num_sections = _u16(raw, pe + 6)
    optional_size = _u16(raw, pe + 20)
    optional = pe + 24
    magic = _u16(raw, optional)
    directory_delta = {0x10B: 96, 0x20B: 112}.get(magic)
    if directory_delta is None or optional_size < directory_delta + 8:
        raise NativeSymbolError("PE-Optionen ohne Export-Verzeichnis")
    exports_rva = _u32(raw, optional + directory_delta)
    exports_size = _u32(raw, optional + directory_delta + 4)
    if not exports_rva or not exports_size:
        return frozenset()
    if not 0 < num_sections <= 96:
        raise NativeSymbolError("Ungueltige PE-Sektionszahl")
    section_start = optional + optional_size
    if section_start + 40 * num_sections > len(raw):
        raise NativeSymbolError("PE-Sektionstabelle unvollstaendig")
    sections = []
    for i in range(num_sections):
        hdr = section_start + i * 40
        virtual_size = _u32(raw, hdr + 8)
        virtual_rva = _u32(raw, hdr + 12)
        raw_size = _u32(raw, hdr + 16)
        raw_offset = _u32(raw, hdr + 20)
        if raw_offset > len(raw) or raw_size > len(raw) - raw_offset:
            raise NativeSymbolError("PE-Sektionsdaten ausserhalb der Datei")
        sections.append((virtual_rva, max(virtual_size, raw_size), raw_offset, raw_size))

    def to_offset(rva: int, bytes_needed: int = 1) -> int:
        for virtual_rva, virtual_size, raw_offset, raw_size in sections:
            if rva >= virtual_rva and rva - virtual_rva <= virtual_size:
                local = rva - virtual_rva
                if local <= raw_size and bytes_needed <= raw_size - local:
                    return raw_offset + local
        raise NativeSymbolError("PE-RVA liegt ausserhalb der Datei")

    directory = to_offset(exports_rva, 40)
    count = _u32(raw, directory + 24)
    names_rva = _u32(raw, directory + 32)
    if count > 50000:
        raise NativeSymbolError("Unplausible Anzahl an DLL-Exportnamen")
    names_offset = to_offset(names_rva, count * 4)
    result = set()
    for i in range(count):
        name_rva = _u32(raw, names_offset + i * 4)
        name_at = to_offset(name_rva)
        end = raw.find(b"\x00", name_at, min(name_at + 1025, len(raw)))
        if end < 0:
            raise NativeSymbolError("PE-Exportname ist nicht abgeschlossen")
        try:
            name = raw[name_at:end].decode("ascii")
        except UnicodeDecodeError as exc:
            raise NativeSymbolError("PE-Exportname ist nicht ASCII") from exc
        result.add(name)
    return frozenset(result)


REQUIRED_OFFLINE_EXPORTS: tuple[str, ...] = (
    "CSNIDTS_getSystem",
    "CSNIDTS_DtsSystem_initialize",
    "CSNIDTS_DtsSystem_selectDynamicProject",
    "CSNIDTS_DtsSystem_deselectProject",
    "CSNIDTS_DtsSystem_uninitialize",
    "CSNIDTS_DtsProject_getDbProject",
    "CSNIDTS_DtsDbProject_getDbEcuMems",
    "CSNIDTS_DtsDbLocation_getDbDTCs",
    "CSNIDTS_DtsDbDiagTroubleCode_getLevel",
    "CSNIDTS_DtsDbDiagTroubleCode_getDbSDGs",
    "CSNIDTS_DtsDbSpecialDataElement_getContent",
    "CSNIDTS_DtsDbSpecialData_getSemanticInformation",
)


def diagnose_native_symbols(binary: Path) -> dict:
    """Report actual exported functions; managed method existence is insufficient."""
    available = dll_exports(binary)
    return {
        "dll": str(binary),
        "native_api_ready": all(item in available for item in REQUIRED_OFFLINE_EXPORTS),
        "missing_required_exports": [
            item for item in REQUIRED_OFFLINE_EXPORTS if item not in available
        ],
        "managed_only_viewer_api": "CSNIDTS_DtsSystem_loadViewerProject" not in available,
        "has_dynamic_project_api": "CSNIDTS_DtsSystem_selectDynamicProject" in available,
        "has_project_database_api": "CSNIDTS_DtsProject_getDbProject" in available,
        "named_export_count": len(available),
    }
