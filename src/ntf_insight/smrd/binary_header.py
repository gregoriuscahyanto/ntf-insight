"""Conservative inspection of observed SMR-D container metadata only.

This is not a proprietary payload decoder or a general Softing format spec.
Unknown headers are rejected; internal build paths/users are never returned.
"""
from __future__ import annotations

import struct
from pathlib import Path

_SIGNATURE = bytes.fromhex("5290d43067147e4781f23c4b73f0f737")
_ALLOWED = {"DATE/TIME", "TRAFO VERSION", "ODX VERSION", "REVISION INFO", "D-SERVER VERSION"}


def inspect_smrd_header(path: Path) -> dict:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    with path.open("rb") as handle:
        header = handle.read(88)
        if len(header) != 88 or header[:16] != _SIGNATURE:
            raise ValueError("Unbekanntes SMR-D-Containerformat.")
        header_size = struct.unpack_from("<I", header, 16)[0]
        payload_offset = struct.unpack_from("<I", header, 24)[0]
        meta_size = struct.unpack_from("<I", header, 84)[0]
        if header_size != 68 or meta_size > 16_000_000:
            raise ValueError("Unbekannte oder unplausible Headerstruktur.")
        metadata_end = 88 + meta_size
        if not metadata_end <= payload_offset <= path.stat().st_size:
            raise ValueError("Ungueltige Nutzdatenposition.")
        if payload_offset - metadata_end > 1_000_000:
            raise ValueError("Unplausible Laenge des Vorbereichs.")
        text = handle.read(meta_size).decode("utf-8", errors="replace")
    fields = {}
    for line in text.splitlines():
        key, separator, value = line.partition(":")
        if separator and key.strip().upper() in _ALLOWED:
            fields[key.strip().upper()] = value.strip()
    return {
        "container_signature": _SIGNATURE.hex(),
        "header_size_bytes": header_size,
        "metadata_length_bytes": meta_size,
        "payload_offset_bytes": payload_offset,
        "additional_preamble_bytes": payload_offset - metadata_end,
        "size_bytes": path.stat().st_size,
        "metadata": fields,
        "payload_decoded": False,
        "dtc_rules_extracted": False,
    }
