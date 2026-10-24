"""Lossless, FIN-centric extraction of text-layer QuickTest PDF reports.

All supported data, including per-page text, ECU metadata, DTC raw blocks and
every snapshot parameter, stays in the *local* DuckDB. A test's date is the
observation time, never proof of the DTC's original onset time.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from pypdf import PdfReader

from ntf_insight.domain.events import (
    DiagnosticEvent,
    DiagnosticSession,
    ECUStateObservation,
)
from ntf_insight.ingestion.real_source_parsers import ParsedSource, canonical_fin


ECU_HEADER = re.compile(
    r"^(?P<ecu>[A-Za-z0-9_]+)-(?P<location>\S+)\s+-\s+(?P<name>.+)$"
)
DTC_START = re.compile(
    r"^(?P<kind>FC|EV)\s+(?P<code>[PBUC][0-9A-F]{6})\s*-\s*(?P<text>.*)$",
    re.I,
)
FAULT_COUNT = re.compile(r"^FAULT CODES \((\d+)\)$")
WRAPPED_PARAMETER = re.compile(r"^(?P<name>[a-zA-Z][\w]*)\s+(?P<first>.+)$")
PARAMETER = re.compile(r"^(?P<name>[a-zA-Z][\w]*)\s+(?P<first>.*?)\s+-\s*$")
STATUS = re.compile(r"(?:\s|_)(?P<status>AS|S|A)\s*$")
PARAMETER_HEADER = re.compile(r"^Name\s+Value\s*\(", re.I)

# A technical observation can include these and future unrecognized parameters.
KNOWN_PARAMETERS = {
    "frequencyCounter", "originalOdometerValue", "mostRecentOdometerValue",
    "ignitionCycleCounter", "Operating_Time", "ErrorStrategy_Id_5",
    "Alarmpoint", "BoschId",
}

HEADER_KEYS = (
    "FIN", "VIN", "DISTANCE", "DIAG START", "VERSION", "LANGUAGE",
    "SOURCE", "Sequence", "Duration", "ECU Count", "Status", "Battery",
    "Mileage", "Start Time",
)


def _identifier(source_sha: str, suffix: str) -> str:
    return uuid5(NAMESPACE_URL, f"ntf-insight:quicktest:{source_sha}:{suffix}").hex


def _int(text: str | None) -> int | None:
    match = re.search(r"\d+", text or "")
    return int(match.group()) if match else None


def _field(lines: list[str], key: str) -> str | None:
    pattern = re.compile(r"^" + re.escape(key) + r"(?:\s+|$)(.*)$")
    for line in lines:
        match = pattern.match(line)
        if match:
            value = match.group(1).strip()
            return value if value and value != "-" else None
    return None


def _ecu_metadata(meta_lines: list[str]) -> dict:
    raw = "\n".join(meta_lines)

    def match(pattern: str) -> str | None:
        found = re.search(pattern, raw, flags=re.I | re.S)
        return found.group(1).strip() if found else None

    diag = re.search(
        r"Diagnostics ID\s+([^\s]+)\s+ECU Variant\s+(.+?)(?=\nHardware\s*\nPartnumber|\nFAULT CODES|$)",
        raw, flags=re.I | re.S,
    )
    return {
        "diagnostics_id": diag.group(1).strip() if diag else None,
        "ecu_variant": re.sub(r"\s+", "", diag.group(2)) if diag else None,
        "hardware_partnumber": match(
            r"Hardware\s*\nPartnumber\s*\n(.+?)\s+Hardware\s*\nVersion"
        ),
        "hardware_version": match(
            r"Hardware\s*\nVersion\s*\n([^\n]+)"
        ),
        "supplier": match(
            r"Supplier\s+(.+?)\s+Software\s*\nVersion"
        ),
        "software_version": match(
            r"Software\s*\nVersion\s*\n([^\n]+)"
        ),
        "boot_and_serial": match(
            r"Boot Version\s*(.*?)\s*\nSoftware\s*\nPartnumbers"
        ),
        "software_partnumbers": match(
            r"Software\s*\nPartnumbers\s*\n(.+?)\s*$"
        ),
        "raw_lines": meta_lines,
    }


def _fault_block(lines: list[tuple[str, int]]) -> dict:
    first, page_start = lines[0]
    head = DTC_START.match(first)
    if head is None:
        raise ValueError("Invalid DTC start")
    description_lines = [head.group("text")]
    index = 1
    while index < len(lines):
        line = lines[index][0]
        wrapped = WRAPPED_PARAMETER.match(line)
        if (
            PARAMETER_HEADER.match(line)
            or PARAMETER.match(line)
            or (wrapped and wrapped.group("name") in KNOWN_PARAMETERS)
        ):
            break
        description_lines.append(line)
        index += 1

    description = " ".join(description_lines).strip()
    status_match = STATUS.search(description)
    status = status_match.group("status") if status_match else None
    if status_match:
        description = description[:status_match.start()].rstrip(" _")

    parameters = []
    leftovers = []
    for line, page_number in lines[index:]:
        if PARAMETER_HEADER.match(line):
            continue
        candidate = PARAMETER.match(line)
        wrapped = WRAPPED_PARAMETER.match(line)
        if candidate or (wrapped and wrapped.group("name") in KNOWN_PARAMETERS):
            parameter = candidate or wrapped
            parameters.append({
                "name": parameter.group("name"),
                "first_value": parameter.group("first").strip(),
                "last_value": "-" if candidate else None,
                "page": page_number,
            })
        elif parameters and (
            # Lines may wrap for a long parameter before the next key starts.
            not DTC_START.match(line)
        ):
            parameters[-1]["first_value"] += " " + line.strip()
        else:
            leftovers.append(line)

    def numeric(name: str) -> int | None:
        values = [
            _int(param["first_value"]) for param in parameters
            if param["name"] == name
        ]
        return next((value for value in values if value is not None), None)

    return {
        "kind": head.group("kind").upper(),
        "code": head.group("code").upper(),
        "description": description,
        "raw_description": " ".join(description_lines),
        "status": status,
        "frequency_counter": numeric("frequencyCounter"),
        "original_odometer_km": numeric("originalOdometerValue"),
        "most_recent_odometer_km": numeric("mostRecentOdometerValue"),
        "ignition_cycle_counter": numeric("ignitionCycleCounter"),
        "parameters": parameters,
        "unclassified_lines": leftovers,
        "page_start": page_start,
        "page_end": lines[-1][1],
        "raw_block_text": "\n".join(text for text, _ in lines),
    }


def extract_quicktest(path: Path, source_sha: str) -> ParsedSource:
    """Read every QuickTest pass while preserving one report-level time anchor.

    A PDF may contain several diagnostic passes without distinct timestamps.
    Those passes are retained and labelled, but not assigned invented times.
    """
    from ntf_insight.ingestion.quicktest_structure import parse_quicktest_structure

    if path.stat().st_size > 80 * 1024 * 1024:
        raise ValueError("QuickTest-PDF exceeds maximum supported size (80 MB).")
    reader = PdfReader(path, strict=False)
    if reader.is_encrypted or not 1 <= len(reader.pages) <= 400:
        raise ValueError("QuickTest-PDF encrypted or invalid page count.")
    page_texts = [page.extract_text() or "" for page in reader.pages]
    structure = parse_quicktest_structure(page_texts)
    fin = canonical_fin(structure["fin"])
    if not fin:
        raise ValueError("QuickTest enthaelt keine eindeutige FIN.")
    reported_vin = canonical_fin(structure["vin"])
    when = structure["diag_start"]
    km = structure["distance_km"]
    report_id = hashlib.sha256("\f".join(page_texts).encode("utf-8")).hexdigest()
    session_id = _identifier(report_id, "session")
    output = ParsedSource()
    ecus = []

    for ecu in structure["ecus"]:
        ecu_index = ecu["ecu_index"]
        ecu_code = ecu["ecu_code"]
        metadata = dict(ecu["metadata"])
        metadata["quicktest_number"] = ecu["quicktest_number"]
        faults = ecu["faults"]
        for dtc_index, fault in enumerate(faults, start=1):
            output.diagnostics.append(DiagnosticEvent(
                event_id=_identifier(report_id, f"ecu:{ecu_index}:dtc:{dtc_index}"),
                vin=fin, occurred_at=when, mileage_km=km,
                session_id=session_id, ecu=ecu_code, dtc_code=fault["code"],
                dtc_text=fault["description"], status=fault["status"],
                occurrence_count=fault["frequency_counter"],
                freeze_frame={
                    "kind": fault["kind"],
                    "quicktest_number": ecu["quicktest_number"],
                    "original_odometer_km": fault["original_odometer_km"],
                    "most_recent_odometer_km": fault["most_recent_odometer_km"],
                    "ignition_cycle_counter": fault["ignition_cycle_counter"],
                    "parameters": fault["parameters"],
                    "observed_at_diagnostic_test": True,
                },
                source_ref=f"raw:{source_sha}#ecu:{ecu_index}:dtc:{dtc_index}",
            ))
        ecus.append({**ecu, "metadata": metadata})
        output.ecu_states.append(ECUStateObservation(
            event_id=_identifier(report_id, f"ecu:{ecu_index}:state"),
            vin=fin, occurred_at=when, mileage_km=km, session_id=session_id,
            ecu=ecu_code, software_version=metadata["software_version"],
            hardware_version=metadata["hardware_version"],
            source_ref=f"raw:{source_sha}#ecu:{ecu_index}",
            hardware_part_number=metadata["hardware_partnumber"],
            supplier=metadata["supplier"], ecu_variant=metadata["ecu_variant"],
        ))

    runs = structure["runs"]
    label = "QuickTest PDF" if len(runs) == 1 else f"QuickTest PDF ({len(runs)} Durchlaeufe)"
    output.sessions.append(DiagnosticSession(
        event_id=_identifier(report_id, "session:event"),
        session_id=session_id, vin=fin, occurred_at=when, mileage_km=km,
        label=label, ecu_count=len(ecus), dtc_count=len(output.diagnostics),
        source_ref=f"raw:{source_sha}#session", report_id=report_id,
        report_vin_usa=reported_vin, source_is_complete_quicktest=True,
    ))
    output.quicktest_report = {
        "report_id": report_id,
        "fin": fin,
        "vin": reported_vin,
        "diag_start": when.isoformat(),
        "distance_km": km,
        "header": structure["header"] | {
            "test_name": f"QuickTest {runs[0]['quicktest_number']}",
            "raw_header_text": "\n".join(structure["preamble"]),
            "quicktest_runs": runs,
        },
        "page_texts": page_texts,
        "ecus": ecus,
        "source_sha256": source_sha,
        "reported_ecu_count": structure["reported_ecu_count"],
        "observed_dtc_count": structure["observed_dtc_count"],
    }
    return output
