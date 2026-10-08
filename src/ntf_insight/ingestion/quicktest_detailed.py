"""Lossless, FIN-centric extraction of text-layer QuickTest PDF reports.

All supported data, including per-page text, ECU metadata, DTC raw blocks and
every snapshot parameter, stays in the *local* DuckDB. A test's date is the
observation time, never proof of the DTC's original onset time.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime
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
WRAPPED_PARAMETER = re.compile(r"^(?P<name>[a-zA-Z][\\w]*)\\s+(?P<first>.+)$")
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
    """Parse one locally archived PDF, enforcing ECU/DTC count consistency."""
    if path.stat().st_size > 80 * 1024 * 1024:
        raise ValueError("QuickTest-PDF exceeds maximum supported size (80 MB).")
    reader = PdfReader(path, strict=False)
    if reader.is_encrypted or not 1 <= len(reader.pages) <= 250:
        raise ValueError("QuickTest-PDF encrypted or invalid page count.")

    page_texts = [page.extract_text() or "" for page in reader.pages]
    if not any(page_texts):
        raise ValueError("QuickTest ohne durchsuchbare Textebene; OCR nicht verfügbar.")
    lines = [
        (line.strip().replace("\x00", ""), page_number)
        for page_number, page_text in enumerate(page_texts, start=1)
        for line in page_text.splitlines()
        if line.strip()
    ]
    starts = [
        index for index, (line, _) in enumerate(lines)
        if ECU_HEADER.fullmatch(line)
    ]
    if not starts:
        raise ValueError("QuickTest: keine Steuergeräte-Blöcke erkannt.")

    preamble = [line for line, _ in lines[:starts[0]]]
    fin = canonical_fin(_field(preamble, "FIN"))
    reported_vin = canonical_fin(_field(preamble, "VIN"))
    moment = _field(preamble, "DIAG START")
    if not fin or not moment:
        raise ValueError("QuickTest enthält keine eindeutige FIN oder Diagnosezeit.")
    try:
        when = datetime.strptime(moment, "%Y-%m-%d %H:%M:%S")
    except ValueError as exc:
        raise ValueError("Ungültiger Diagnosezeitpunkt im QuickTest.") from exc

    declared_ecus = _int(_field(preamble, "ECU Count"))
    if declared_ecus is None or declared_ecus != len(starts):
        raise ValueError(
            "QuickTest: ECU-Anzahl stimmt nicht überein "
            f"(Bericht={declared_ecus}, erkannt={len(starts)})."
        )

    reported_test = next(
        (text for text in preamble if text.startswith("QuickTest ")), "QuickTest"
    )
    report_id = hashlib.sha256("\f".join(page_texts).encode("utf-8")).hexdigest()
    km = _int(_field(preamble, "DISTANCE"))
    session_id = _identifier(report_id, "session")
    ecus = []
    output = ParsedSource()

    for ecu_index, start in enumerate(starts, start=1):
        end = starts[ecu_index] if ecu_index < len(starts) else len(lines)
        block = lines[start:end]
        header = ECU_HEADER.fullmatch(block[0][0])
        if header is None:
            raise ValueError("QuickTest: ungültiger ECU-Kopf.")
        counts = [
            index for index, (text, _) in enumerate(block)
            if FAULT_COUNT.fullmatch(text)
        ]
        if len(counts) != 1:
            raise ValueError("QuickTest: ECU-Block ohne eindeutige DTC-Anzahl.")
        count_index = counts[0]
        declared_faults = int(FAULT_COUNT.fullmatch(block[count_index][0]).group(1))
        metadata = _ecu_metadata([text for text, _ in block[1:count_index]])
        ecu_name = header.group("ecu")
        starts_dtc = [
            index for index, (text, _) in enumerate(block[count_index+1:], start=count_index+1)
            if DTC_START.match(text)
        ]
        if declared_faults != len(starts_dtc):
            raise ValueError(
                f"QuickTest: {ecu_name} meldet {declared_faults} DTCs, "
                f"aber {len(starts_dtc)} wurden erkannt."
            )
        faults = []
        for dtc_index, dtc_start in enumerate(starts_dtc, start=1):
            dtc_end = starts_dtc[dtc_index] if dtc_index < len(starts_dtc) else len(block)
            fault = _fault_block(block[dtc_start:dtc_end])
            faults.append(fault)
            output.diagnostics.append(DiagnosticEvent(
                event_id=_identifier(report_id, f"ecu:{ecu_index}:dtc:{dtc_index}"),
                vin=fin, occurred_at=when, mileage_km=km,
                session_id=session_id,
                ecu=ecu_name, dtc_code=fault["code"],
                dtc_text=fault["description"], status=fault["status"],
                occurrence_count=fault["frequency_counter"],
                freeze_frame={
                    "kind": fault["kind"],
                    "original_odometer_km": fault["original_odometer_km"],
                    "most_recent_odometer_km": fault["most_recent_odometer_km"],
                    "ignition_cycle_counter": fault["ignition_cycle_counter"],
                    "parameters": fault["parameters"],
                    "observed_at_diagnostic_test": True,
                },
                source_ref=f"raw:{source_sha}#ecu:{ecu_index}:dtc:{dtc_index}",
            ))
        ecus.append({
            "ecu_index": ecu_index,
            "ecu_code": ecu_name,
            "location": header.group("location"),
            "name": header.group("name"),
            "metadata": metadata,
            "reported_fault_count": declared_faults,
            "page_start": block[0][1],
            "page_end": block[-1][1],
            "raw_block_text": "\n".join(text for text, _ in block),
            "faults": faults,
        })
        output.ecu_states.append(ECUStateObservation(
            event_id=_identifier(report_id, f"ecu:{ecu_index}:state"),
            vin=fin, occurred_at=when, mileage_km=km, session_id=session_id,
            ecu=ecu_name, software_version=metadata["software_version"],
            hardware_version=metadata["hardware_version"],
            source_ref=f"raw:{source_sha}#ecu:{ecu_index}",
            hardware_part_number=metadata["hardware_partnumber"],
            supplier=metadata["supplier"],
            ecu_variant=metadata["ecu_variant"],
        ))

    output.sessions.append(DiagnosticSession(
        event_id=_identifier(report_id, "session:event"),
        session_id=session_id, vin=fin, occurred_at=when, mileage_km=km,
        label="QuickTest PDF", ecu_count=len(ecus),
        dtc_count=len(output.diagnostics),
        source_ref=f"raw:{source_sha}#session",
        report_id=report_id,
        report_vin_usa=reported_vin,
        source_is_complete_quicktest=True,
    ))
    output.quicktest_report = {
        "report_id": report_id,
        "fin": fin,
        "vin": reported_vin,
        "diag_start": when.isoformat(),
        "distance_km": km,
        "header": {
            key: _field(preamble, key) for key in HEADER_KEYS
        } | {
            "test_name": reported_test,
            "raw_header_text": "\n".join(preamble),
        },
        "page_texts": page_texts,
        "ecus": ecus,
        "source_sha256": source_sha,
        "reported_ecu_count": declared_ecus,
        "observed_dtc_count": len(output.diagnostics),
    }
    return output
