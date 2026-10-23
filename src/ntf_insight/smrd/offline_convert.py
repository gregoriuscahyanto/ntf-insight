"""Portable, license-free SMR-D container analysis and offline reference bundling.

This module deliberately NEVER decrypts protected SMR-D payloads and never
loads or invokes Softing libraries. Structured diagnostic reference rows can
come ONLY from explicitly supplied or previously linked local XML exports.
A standalone SMR-D produces metadata-only output, not invented DTCs.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import tempfile

from ntf_insight.smrd.binary_header import inspect_smrd_header
from ntf_insight.smrd.library import SmrdLocalLibrary, digest
from ntf_insight.smrd.xml_reference import parse_xml

OFFLINE_FORMAT = "ntf-smrd-offline-bundle-v1"
BINDING_FORMAT = "ntf-smrd-offline-xml-links-v1"
MAX_REFERENCES = 250_000
MAX_BUNDLE_BYTES = 160_000_000
RELEVANT_CATEGORIES = {
    "smrd_xml_ecu", "smrd_xml_variant", "smrd_xml_dtc",
    "smrd_xml_service", "smrd_xml_parameter", "smrd_xml_sdg",
}


def _sections(smrd: Path, *, payload_offset: int) -> list[dict]:
    """List validated opaque data regions without reading protected payloads."""
    with smrd.open("rb") as handle:
        header = handle.read(88)
    if len(header) != 88:
        raise ValueError("SMR-D-Header ist unvollstaendig")
    words = struct.unpack_from("<17I", header, 16)
    end = smrd.stat().st_size
    offset = payload_offset
    regions = [{"name": "hash_block", "offset": offset, "size_bytes": 32}]
    offset += 32
    for i, name in enumerate(("database_index", "database_binary", "database_strings")):
        size, flags = words[8 + i * 2], words[9 + i * 2]
        if size > end - offset:
            raise ValueError(f"SMR-D-Sektion ist groesser als die Datei: {name}")
        regions.append({
            "name": name,
            "offset": offset,
            "size_bytes": size,
            "attributes_hex": f"0x{flags:08x}",
            "compression_bit_set": bool(flags & 0x100),
            "decode_status": "opaque_not_decoded",
        })
        offset += size
    if offset != end:
        regions.append({
            "name": "unknown_trailing_bytes",
            "offset": offset,
            "size_bytes": end - offset,
            "decode_status": "unknown_not_decoded",
        })
    return regions


def _version_parts(value: str | None) -> tuple[int, ...] | None:
    if not value or not re.fullmatch(r"\d+(?:\.\d+)+", value.strip()):
        return None
    return tuple(int(part) for part in value.strip().split("."))


def _ecu_matches_filename(filename: str, ecu: str) -> bool:
    # The filename has no standard that guarantees ECU identity; this is a
    # warning only and cannot establish an authentic binary-to-XML link.
    stem = filename.casefold().removesuffix(".smr-d")
    key = ecu.casefold().strip()
    return stem == key or stem.startswith(key + "_") or stem.startswith(key + "-")


def _unique_reference_key(row: dict) -> tuple | None:
    category = str(row.get("category", ""))
    if category not in {"smrd_xml_ecu", "smrd_xml_variant", "smrd_xml_dtc"}:
        return None
    data = row["data"]
    return (
        category,
        str(data.get("ecu") or "").casefold(),
        str(data.get("variant") or "").casefold(),
        str(row.get("reference") or "").casefold(),
    )


def _write_json_atomic(destination: Path, document: dict) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_symlink() or destination.parent.is_symlink():
        raise ValueError("Symlinks sind fuer Offline-Exportziele nicht erlaubt")
    staged: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=destination.parent,
            prefix=".smrd-offline-", suffix=".json.tmp", delete=False,
        ) as stream:
            staged = Path(stream.name)
            json.dump(document, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if staged.stat().st_size > MAX_BUNDLE_BYTES:
            raise ValueError("Offline-Paket ist zu gross")
        os.replace(staged, destination)
    finally:
        if staged is not None:
            staged.unlink(missing_ok=True)


def _binding_path(library: SmrdLocalLibrary, smrd_sha: str) -> Path:
    return library.manifests / "offline-links" / f"{smrd_sha}.json"


def _saved_xml_files(library: SmrdLocalLibrary, smrd_sha: str) -> list[Path]:
    manifest = _binding_path(library, smrd_sha)
    if not manifest.exists():
        return []
    if manifest.is_symlink() or manifest.stat().st_size > 64_000:
        raise ValueError("Unsichere Offline-Referenzzuordnung")
    data = json.loads(manifest.read_text(encoding="utf-8"))
    if data.get("format") != BINDING_FORMAT or data.get("smrd_sha256") != smrd_sha:
        raise ValueError("Offline-Referenzzuordnung passt nicht zu SMR-D")
    sources = data.get("sources")
    if not isinstance(sources, list) or len(sources) > 20:
        raise ValueError("Offline-Referenzzuordnung enthaelt ungueltige Quellen")
    paths = []
    for source in sources:
        if not isinstance(source, dict) or not isinstance(source.get("path"), str):
            raise ValueError("Ungueltige Offline-XML-Quellenzuordnung")
        path = Path(source["path"])
        if not path.is_file() or path.is_symlink() or digest(path) != source.get("sha256"):
            raise ValueError(
                "Lokal zugeordnete XML fehlt oder wurde veraendert; "
                "erneut mit --xml und --remember verknuepfen"
            )
        paths.append(path)
    return paths


def offline_convert(
    smrd: Path,
    *,
    xml_files: list[Path] | None = None,
    data_dir: Path | None = None,
    output: Path | None = None,
    remember: bool = False,
) -> dict:
    """Create a transparent offline JSON bundle from SMR-D and LOCAL XML references.

    The library is standard-library-only. No DTS process, network, keys,
    customer data upload, protected payload decoding or vehicle communication.
    """
    source = Path(smrd).expanduser().resolve()
    if source.suffix.casefold() != ".smr-d" or not source.is_file():
        raise ValueError("Es wird eine vorhandene .smr-d-Datei benoetigt")
    if Path(smrd).is_symlink():
        raise ValueError("SMR-D-Symlink nicht erlaubt")
    library = SmrdLocalLibrary(data_dir=data_dir)
    sha = digest(source)
    header = inspect_smrd_header(source)
    sections = _sections(source, payload_offset=header["payload_offset_bytes"])
    if xml_files is not None:
        for path in xml_files:
            if Path(path).expanduser().is_symlink():
                raise ValueError("Lokale XML-Symlinks sind nicht erlaubt")
        xml_paths = [Path(p).expanduser().resolve() for p in xml_files]
    else:
        xml_paths = _saved_xml_files(library, sha)
    if len(xml_paths) > 20:
        raise ValueError("Maximal 20 lokale XML-Dateien pro Offline-Paket")
    if remember and not xml_paths:
        raise ValueError("--remember benoetigt mindestens eine XML-Quelle")

    references: list[dict] = []
    unique: dict[tuple, int] = {}
    sources: list[dict] = []
    warnings: list[str] = []
    seen_sources: set[str] = set()
    for xml in xml_paths:
        if xml.is_symlink() or not xml.is_file():
            raise ValueError(f"Lokale XML fehlt oder ist ein Symlink: {xml.name}")
        source_hash = digest(xml)
        if source_hash in seen_sources:
            continue
        seen_sources.add(source_hash)
        metadata, parsed = parse_xml(
            xml, include_dtcs=True, max_records=MAX_REFERENCES
        )
        names = {str(item["data"].get("ecu") or "") for item in parsed
                 if item.get("category") == "smrd_xml_ecu"}
        if not names or not all(names):
            raise ValueError(f"XML ohne nachweisbaren ECU-Namen: {xml.name}")
        for ecu in sorted(names):
            if not _ecu_matches_filename(source.name, ecu):
                warnings.append(
                    f"ECU {ecu} ist nicht eindeutig am SMR-D-Dateinamen "
                    f"{source.name} erkennbar. Nur explizite XML-Zuordnung, "
                    "keine Verifikation aus verschluesseltem Inhalt."
                )
        expected_version = _version_parts(header["metadata"].get("REVISION INFO"))
        versions = {
            _version_parts(str(item["data"].get("ecu_version") or ""))
            for item in parsed if item.get("category") == "smrd_xml_ecu"
        } - {None}
        if expected_version and versions and expected_version not in versions:
            warnings.append(
                f"XML-Versionsangabe {sorted(versions)} weicht von "
                "SMR-D-Revision ab; Zuordnung nicht cryptographisch belegt."
            )
        sources.append({
            "kind": "preexisting_local_xml",
            "filename": xml.name,
            "sha256": source_hash,
            "xml_format": metadata.get("format"),
            "source_counts": metadata.get("counts", {}),
            "ecu_names": sorted(names),
            "native_smrd_payload_source": False,
        })
        for row in parsed:
            if len(references) >= MAX_REFERENCES:
                raise ValueError("Zu viele aggregierte Offline-Referenzeintraege")
            if row.get("category") not in RELEVANT_CATEGORIES:
                raise ValueError("Unbekannte XML-Referenzkategorie")
            normalized = {
                **row,
                "data": dict(row["data"]),
                "source_provenance": [{
                    "xml_sha256": source_hash,
                    "location": row.get("source_location"),
                }],
            }
            normalized["data"]["from_native_smrd_payload"] = False
            normalized["data"]["is_vehicle_observation"] = False
            normalized["data"]["trigger_conditions_validated"] = False
            unique_key = _unique_reference_key(normalized)
            if unique_key is not None and unique_key in unique:
                current = references[unique[unique_key]]
                current["source_provenance"].extend(normalized["source_provenance"])
                # Never infer an agreement where two exporters disagree.
                if current.get("label") != normalized.get("label"):
                    labels = current["data"].setdefault("alternate_xml_labels", [])
                    if normalized["label"] not in labels:
                        labels.append(normalized["label"])
                for field in ("repair_action", "possible_causes", "error_level"):
                    value = normalized["data"].get(field)
                    existing = current["data"].get(field)
                    if value and not existing:
                        current["data"][field] = value
                    elif value and existing and value != existing:
                        values = current["data"].setdefault("conflicting_xml_fields", {})
                        alternatives = values.setdefault(field, [])
                        if value not in alternatives:
                            alternatives.append(value)
                continue
            if unique_key is not None:
                unique[unique_key] = len(references)
            references.append(normalized)

    counts = dict(sorted(Counter(x["category"] for x in references).items()))
    has_xml = bool(sources)
    document = {
        "format": OFFLINE_FORMAT,
        "offline": True,
        "vendor_runtime_used": False,
        "network_used": False,
        "source_smrd": {
            "filename": source.name,
            "sha256": sha,
            "container": header,
            "opaque_sections": sections,
        },
        "coverage": {
            "status": "metadata_and_local_xml_references" if has_xml else "metadata_only",
            "smrd_header_inspected": True,
            "native_binary_dtc_decoded": False,
            "dtc_reference_catalogue_from_xml": counts.get("smrd_xml_dtc", 0) > 0,
            "smrd_payload_encryption_not_bypassed": True,
            "error_level_from_xml_only": True,
            "repair_action_from_xml_only": True,
            "possible_causes_from_xml_only": True,
            "trigger_conditions_validated": False,
        },
        "xml_sources": sources,
        "counts": counts,
        "reference_records": references,
        "warnings": warnings,
    }
    export = (
        Path(output).expanduser().resolve()
        if output is not None else library.exports / f"{sha}.offline.json"
    )
    if output is not None and Path(output).expanduser().is_symlink():
        raise ValueError("Exportziel darf kein Symlink sein")
    library._ensure()
    _write_json_atomic(export, document)
    if remember:
        link = _binding_path(library, sha)
        _write_json_atomic(link, {
            "format": BINDING_FORMAT,
            "smrd_sha256": sha,
            "sources": [{"path": str(xml), "sha256": digest(xml)}
                        for xml in xml_paths],
        })
    return {
        "bundle": str(export),
        "smrd_sha256": sha,
        "status": document["coverage"]["status"],
        "counts": counts,
        "total_references": len(references),
        "xml_sources": len(sources),
        "native_binary_dtc_decoded": False,
        "warnings": warnings,
    }


def import_offline_bundle(path: Path, *, data_dir: Path | None = None) -> int:
    """Import only verified reference records; never vehicle DTC observations."""
    path = Path(path).expanduser()
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= MAX_BUNDLE_BYTES:
        raise ValueError("Offline-Paket fehlt oder ist zu gross")
    doc = json.loads(path.read_text(encoding="utf-8"))
    if doc.get("format") != OFFLINE_FORMAT or doc.get("vendor_runtime_used") is not False:
        raise ValueError("Unbekanntes oder natives Offline-Paket")
    smrd = doc.get("source_smrd", {})
    sha = smrd.get("sha256")
    if not isinstance(sha, str) or not re.fullmatch("[0-9a-f]{64}", sha):
        raise ValueError("Ungueltige SMR-D-Quellenidentitaet")
    rows = doc.get("reference_records")
    if not isinstance(rows, list) or not 0 < len(rows) <= MAX_REFERENCES:
        raise ValueError("Offline-Paket enthaelt keine importierbaren XML-Referenzen")
    for row in rows:
        if not isinstance(row, dict) or row.get("category") not in RELEVANT_CATEGORIES:
            raise ValueError("Ungültiger Referenzdatensatz im Offline-Paket")
        data = row.get("data")
        if not isinstance(data, dict) or data.get("is_vehicle_observation") is not False:
            raise ValueError("Fahrzeugereignisse duerfen nicht aus dem Katalog importiert werden")
        if data.get("from_native_smrd_payload") is not False:
            raise ValueError("Unbelegte native SMR-D-Daten im Offline-Paket")
    xml_hashes = [str(item["sha256"]) for item in doc.get("xml_sources", [])]
    identity = hashlib.sha256(
        (OFFLINE_FORMAT + ":" + sha + ":" + ":".join(sorted(xml_hashes))).encode()
    ).hexdigest()
    from ntf_insight.storage.duckdb_store import DuckDBStore
    from ntf_insight.storage.source_knowledge_store import SourceKnowledgeStore

    library = SmrdLocalLibrary(data_dir=data_dir)
    store = SourceKnowledgeStore(
        DuckDBStore(library.root.parent / "ntf-insight.duckdb")
    )
    return store.save_records(identity, "smrd_offline_reference", rows, metadata={
        "source_kind": OFFLINE_FORMAT,
        "source_smrd_sha256": sha,
        "xml_sources": doc["xml_sources"],
        "counts": doc["counts"],
        "native_binary_dtc_decoded": False,
        "is_vehicle_event": False,
        "trigger_conditions_validated": False,
    })
