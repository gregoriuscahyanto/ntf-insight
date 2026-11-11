"""Untrusted-input boundary for offline Softing-DTS DTC detail JSON.

Native extraction runs in a separate Windows PowerShell process. This module
does not decode proprietary .smr-d binaries.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


class NativeDetailError(ValueError):
    """The native exporter returned malformed or incomplete DTC metadata."""


def _text(value: Any, *, maximum: int = 131072) -> str:
    if value is None:
        return ""
    return str(value)[:maximum]


def _normalize_key(value: Any) -> str:
    return "_".join(_text(value).upper().replace("-", "_").split())


def normalize_sdg_groups(raw_groups: list[dict]) -> tuple[list[dict], dict[str, list[str]]]:
    """Keep all original SDGs while indexing named elements without conflating fields."""
    groups: list[dict] = []
    by_semantic: dict[str, list[str]] = {}
    for raw in raw_groups:
        if not isinstance(raw, dict):
            raise NativeDetailError("SDG-Gruppe muss ein JSON-Objekt sein")
        semantic = _text(raw.get("semantic"))
        caption = _text(raw.get("caption"))
        elements = []
        raw_elements = raw.get("elements", [])
        if not isinstance(raw_elements, list):
            raise NativeDetailError("SDG-Elemente muessen eine Liste sein")
        for elem in raw_elements:
            if not isinstance(elem, dict):
                raise NativeDetailError("SDG-Element muss ein JSON-Objekt sein")
            item = {
                "semantic": _text(elem.get("semantic")),
                "content": _text(elem.get("content")),
                "text_id": _text(elem.get("text_id")),
            }
            elements.append(item)
            content = item["content"]
            if not content.strip():
                continue
            # Element semantic overrides the container semantic. Otherwise a
            # group with multiple named fields would mix possible causes and actions.
            normalized = _normalize_key(item["semantic"] or semantic)
            if normalized:
                values = by_semantic.setdefault(normalized, [])
                if content not in values:
                    values.append(content)
        groups.append({"semantic": semantic, "caption": caption, "elements": elements})
    return groups, by_semantic


def parse_native_details(path: Path, *, maximum_records: int = 250_000) -> tuple[dict, list[dict]]:
    """Parse bounded native-DTS output as ECU reference knowledge, not vehicle events."""
    path = Path(path)
    if not path.is_file() or not 0 < path.stat().st_size <= 160_000_000:
        raise NativeDetailError("Native-DTS-JSON fehlt oder ist zu gross")
    content = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(content, dict) or content.get("format") != "ntf-smrd-native-dtc-v1":
        raise NativeDetailError("Unerwartetes natives Exportformat")
    if content.get("complete") is not True:
        raise NativeDetailError("Unvollstaendiger Export; Import wird verweigert")
    digest = _text(content.get("smrd_sha256")).lower()
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise NativeDetailError("SMR-D-SHA256 fehlt oder ist ungueltig")
    dtcs = content.get("dtcs")
    if not isinstance(dtcs, list) or not 0 < len(dtcs) <= maximum_records:
        raise NativeDetailError("DTC-Liste fehlt, ist leer oder zu gross")
    records = []
    for i, dtc in enumerate(dtcs, 1):
        if not isinstance(dtc, dict):
            raise NativeDetailError(f"DTC #{i} ist kein Objekt")
        code = _text(dtc.get("code"), maximum=100).strip().upper()
        ecu = _text(dtc.get("ecu"), maximum=200).strip()
        variant = _text(dtc.get("variant"), maximum=200).strip()
        if not code or not ecu or not variant:
            raise NativeDetailError(f"DTC #{i} ohne ECU/Variante/Code")
        raw_groups = dtc.get("sdgs") or []
        if not isinstance(raw_groups, list):
            raise NativeDetailError(f"DTC #{i} hat ungueltige SDGs")
        groups, index = normalize_sdg_groups(raw_groups)
        description = _text(dtc.get("dtc_text"))
        details = {
            "ecu": ecu,
            "variant": variant,
            "location": _text(dtc.get("location"), maximum=250),
            "dtc_code": code,
            "dtc_text": description,
            "dtc_numeric": dtc.get("trouble_code"),
            "error_level": dtc.get("level"),
            "repair_action": "\n".join(index.get("REPAIR_ACTION", [])) or None,
            "possible_causes": "\n".join(index.get("POSSIBLE_CAUSES", [])) or None,
            "sdgs": groups,
            "sdg_index": index,
            "db_short_name": _text(dtc.get("short_name")),
            "native_dts": True,
            "source_smrd_sha256": digest,
            "trigger_conditions_validated": False,
            "is_vehicle_observation": False,
        }
        records.append({
            "category": "smrd_native_dtc_detail",
            "source_location": f"native/dtcs/{i}",
            "reference": code,
            "label": f"{code}: {description}"[:4000],
            "fin": None,
            "data": details,
        })
    metadata = {
        "source_kind": "softing_dts_native_dtc",
        "native_format": content["format"],
        "smrd_sha256": digest,
        "dts_version": _text(content.get("dts_version"), maximum=80),
        "records": len(records),
        "complete": True,
        "manufacturer_binary_bundled": False,
    }
    return metadata, records


def knowledge_source_key(smrd_sha256: str) -> str:
    """Stable import identity distinct from the raw SMR-D artifact hash."""
    return hashlib.sha256(
        f"ntf-smrd-native-dtc-v1:{smrd_sha256.lower()}".encode()
    ).hexdigest()


def import_native_details(path: Path, *, data_dir: Path | None = None) -> int:
    from ntf_insight.smrd.library import SmrdLocalLibrary
    from ntf_insight.storage.duckdb_store import DuckDBStore
    from ntf_insight.storage.source_knowledge_store import SourceKnowledgeStore

    metadata, records = parse_native_details(path)
    library = SmrdLocalLibrary(data_dir=data_dir)
    store = SourceKnowledgeStore(DuckDBStore(library.root.parent / "ntf-insight.duckdb"))
    return store.save_records(
        knowledge_source_key(metadata["smrd_sha256"]),
        "softing_dts_native_dtc",
        records,
        metadata=metadata,
    )
