"""Strukturerkennung fuer XENTRY-QuickTest-PDFs (nur lesbare Textebene).

PDF-Originaldaten bleiben lokal. Mehrere QuickTest-Durchlaeufe und nicht
standardisierte ECU-Koepfe werden ohne erfundene Fehlerzeitpunkte aufgeloest.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any


QUICKTEST = re.compile(r"^QuickTest\s+(?P<number>\d+)\s*$", re.I)
ECUS = re.compile(r"^ECUS\s*\((?P<count>\d+)\)\s*$", re.I)
ECU_COUNT = re.compile(r"^ECU Count\s+(?P<count>\d+)\s*$", re.I)
FAULT_COUNT = re.compile(r"^FAULT CODES\s*\((?P<count>\d+)\)\s*$", re.I)
DTC_START = re.compile(
    r"^(?P<kind>FC(?:-DEV)?|EV(?:-DEV)?)\s+"
    r"(?P<code>[PBUC][0-9A-F]{6})\s*-\s*(?P<text>.*)$", re.I,
)
LEGACY_ECU = re.compile(r"^[A-Za-z0-9_]+-\S+\s+-\s+.+$")
PARAMETER_HEADER = re.compile(r"^Name\s+Value\s*\(", re.I)
PARAMETER = re.compile(r"^(?P<name>[a-zA-Z][\w]*)\s+(?P<values>.+)$")
STATUS = re.compile(r"(?:(?<=\s)|(?<=[._]))(?P<status>AS|S|A)\s*$")
META_KEYS = (
    "Diag version", "Diagnostics ID", "ECU variant", "ECU Variant",
    "Boot version", "SW version", "HW partnumber", "HW version",
    "HW Serial ID", "Supplier", "Hardware", "Software", "Boot Version",
)
HEADER_KEYS = (
    "FIN", "VIN", "DISTANCE", "DIAG START", "VERSION", "LANGUAGE",
    "SOURCE", "Sequence", "Duration", "ECU Count", "Status", "Battery",
    "Mileage", "Start Time",
)
FREQUENCY_NAMES = {
    "frequencycounter", "frequency_counter", "frequency_count",
    "dtcextendeddatarecord_frequency_counter",
}
ORIGINAL_ODOMETER_NAMES = {"originalodometervalue", "original_odometer_value"}
RECENT_ODOMETER_NAMES = {"mostrecentodometervalue", "most_recent_odometer_value", "vehicle_odometer_in_low_resolution"}
CYCLE_NAMES = {"ignitioncyclecounter", "operation_cycle_counter", "operation_cycle_count"}


def _value(lines: list[str], key: str) -> str | None:
    rx = re.compile(r"^" + re.escape(key) + r"(?:\s+|$)(.*)$", re.I)
    for line in lines:
        if match := rx.match(line):
            v = match.group(1).strip()
            return v if v and v not in {"-", "---"} else None
    return None


def _int(value: str | None) -> int | None:
    match = re.search(r"\d+", value or "")
    return int(match.group()) if match else None


def _timestamp(text: str | None) -> datetime:
    if not text:
        raise ValueError("QuickTest enthaelt keinen Diagnosezeitpunkt.")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Ungueltiger Diagnosezeitpunkt im QuickTest.") from exc
    # Diagnosezeit im PDF ist Quellzeit; keine unbelegte lokale Zeitzonenkonvertierung.
    return parsed.replace(tzinfo=None)


def _ecu_header(lines: list[tuple[str, int]], index: int) -> dict[str, str] | None:
    line = lines[index][0]
    if " - " not in line:
        return None
    if not (
        (index + 1 < len(lines) and lines[index + 1][0].casefold() == "general information")
        or LEGACY_ECU.fullmatch(line)
    ):
        return None
    head, _, name = line.partition(" - ")
    if "-" not in head:
        return None
    code, location = head.split("-", 1)
    code, location, name = code.strip(), location.strip(), name.strip()
    if not code or not location or not name:
        return None
    return {"ecu": code, "location": location, "name": name}


def _metadata(lines: list[str]) -> dict[str, Any]:
    def lookup(*keys: str) -> str | None:
        for key in keys:
            found = _value(lines, key)
            if found:
                return found
        return None

    diag_id = lookup("Diag version", "Diagnostics ID")
    variant = lookup("ECU variant")
    # Older report layouts place both in one row.
    for line in lines:
        match = re.match(r"^Diagnostics ID\s+(\S+)\s+ECU Variant\s+(\S+)", line, re.I)
        if match:
            diag_id, variant = match.groups()
            break
    if not variant and "ECU Variant" in "\n".join(lines):
        variant = lookup("ECU Variant")

    # Support older split-column PDF text as well as current inline labels.
    raw = "\n".join(lines)
    def legacy(pattern: str) -> str | None:
        m = re.search(pattern, raw, re.I | re.S)
        return m.group(1).strip() if m else None

    return {
        "diagnostics_id": diag_id,
        "ecu_variant": variant,
        "hardware_partnumber": lookup("HW partnumber") or legacy(r"Hardware\s*\nPartnumber\s*\n([^\n]+)"),
        "hardware_version": lookup("HW version") or legacy(r"Hardware\s*\nVersion\s*\n([^\n]+)"),
        "supplier": lookup("Supplier") or legacy(r"Supplier\s+(.+?)\s+Software\s*\nVersion"),
        "software_version": lookup("SW version") or legacy(r"Software\s*\nVersion\s*\n([^\n]+)"),
        "boot_and_serial": lookup("Boot version") or lookup("Boot Version"),
        "software_partnumbers": lookup("Software Partnumbers") or legacy(r"Software\s*\nPartnumbers\s*\n([^\n]+)"),
        "raw_lines": lines,
    }


def _first_last(text: str) -> tuple[str, str | None]:
    value = text.strip()
    if not value:
        return "", None
    if value == "-":
        return "-", None
    if value.startswith("- "):
        return "-", value[2:].strip()
    if value.endswith(" -"):
        return value[:-2].strip(), "-"
    # Snapshot values may be measured in kilometres with fractional units.
    m = re.fullmatch(
        r"(?P<first>-|[\d.,]+\s*km)\s+(?P<last>-|[\d.,]+\s*km)",
        value, re.I,
    )
    if m:
        return m.group("first"), m.group("last")
    if len(value.split()) == 2:
        a, b = value.split()
        return a, b
    return value, None


def _fault(lines: list[tuple[str, int]]) -> dict[str, Any]:
    head = DTC_START.fullmatch(lines[0][0])
    if head is None:
        raise ValueError("Ungueltiger DTC-Blockanfang.")
    pos = 1
    desc = [head.group("text")]
    while pos < len(lines) and not PARAMETER_HEADER.match(lines[pos][0]):
        line = lines[pos][0]
        # Accept legacy PDFs that omit the Name/Value header.
        m = PARAMETER.match(line)
        if m and m.group("name") in {
            "frequencyCounter", "originalOdometerValue", "mostRecentOdometerValue",
            "ignitionCycleCounter", "Operating_Time", "ErrorStrategy_Id_5",
        }:
            break
        desc.append(line)
        pos += 1
    description = " ".join(desc).strip()
    status_match = STATUS.search(description)
    status = status_match.group("status") if status_match else None
    if status_match:
        description = description[:status_match.start()].rstrip(" _.")

    parameters: list[dict[str, Any]] = []
    leftovers: list[str] = []
    pending_name: str | None = None
    for line, page in lines[pos:]:
        if PARAMETER_HEADER.match(line):
            continue
        # Long parameter names can wrap across two lines before the values.
        if pending_name:
            if re.fullmatch(r"[_A-Za-z\d]+", line) and (line.startswith("_") or line[0].isupper()):
                pending_name += line
                continue
            first, last = _first_last(line)
            parameters.append({"name": pending_name, "first_value": first,
                               "last_value": last, "page": page})
            pending_name = None
            continue
        if line.strip().casefold() == "default -" and parameters:
            parameters[-1]["first_value"] += " Default"
            parameters[-1]["last_value"] = "-"
            continue
        m = PARAMETER.match(line)
        if m:
            first, last = _first_last(m.group("values"))
            parameters.append({"name": m.group("name"), "first_value": first,
                               "last_value": last, "page": page})
        elif re.fullmatch(r"[a-zA-Z][\w]+", line) and "_" in line:
            pending_name = line
        elif parameters:
            parameters[-1]["first_value"] += " " + line
        else:
            leftovers.append(line)
    if pending_name:
        leftovers.append(pending_name)

    def number(names: set[str]) -> int | None:
        for p in parameters:
            if p["name"].casefold() not in names:
                continue
            # First value may be unavailable, in which case last is observed.
            for v in (p["first_value"], p["last_value"]):
                if v and v != "-":
                    parsed = _int(v)
                    if parsed is not None:
                        return parsed
        return None

    return {
        "kind": head.group("kind").upper(),
        "code": head.group("code").upper(),
        "description": description,
        "raw_description": " ".join(desc),
        "status": status,
        "frequency_counter": number(FREQUENCY_NAMES),
        "original_odometer_km": number(ORIGINAL_ODOMETER_NAMES),
        "most_recent_odometer_km": number(RECENT_ODOMETER_NAMES),
        "ignition_cycle_counter": number(CYCLE_NAMES),
        "parameters": parameters,
        "unclassified_lines": leftovers,
        "page_start": lines[0][1],
        "page_end": lines[-1][1],
        "raw_block_text": "\n".join(s for s, _ in lines),
    }


def parse_quicktest_structure(page_texts: list[str]) -> dict[str, Any]:
    """Decode a report without silently accepting incomplete ECU/DTC counts.

    The DIAG START timestamp belongs to the PDF, not to an individual DTC
    onset or a later QuickTest pass.
    """
    if not any(page_texts):
        raise ValueError("QuickTest ohne durchsuchbare Textebene; OCR nicht verfuegbar.")
    lines = [
        (line.strip().replace("\x00", ""), page)
        for page, text in enumerate(page_texts, 1)
        for line in text.splitlines()
        if line.strip()
    ]
    # Narrow PDF cells can put FC/EV in one text line and the DTC in the next.
    normalized: list[tuple[str, int]] = []
    pos = 0
    while pos < len(lines):
        text, page = lines[pos]
        if (text in {"FC", "EV", "EV-DEV", "FC-DEV"}
                and pos + 1 < len(lines)
                and re.match(r"^[PBUC][0-9A-F]{6}\s*-", lines[pos+1][0], re.I)):
            normalized.append((text + " " + lines[pos+1][0], page))
            pos += 2
        else:
            normalized.append((text, page))
            pos += 1
    lines = normalized
    headers = [i for i, (line, _) in enumerate(lines) if QUICKTEST.fullmatch(line)]
    if not headers:
        raise ValueError("QuickTest: keine QuickTest-Durchlaeufe erkannt.")
    preamble = [line for line, _ in lines[:headers[0]]]
    fin = _value(preamble, "FIN")
    moment = _timestamp(_value(preamble, "DIAG START"))
    km = _int(_value(preamble, "DISTANCE"))
    ecus: list[dict[str, Any]] = []
    runs: list[dict[str, Any]] = []
    for i, start in enumerate(headers):
        end = headers[i+1] if i+1 < len(headers) else len(lines)
        section = lines[start:end]
        marker = next((j for j, (text, _) in enumerate(section) if ECUS.fullmatch(text)), None)
        if marker is None:
            raise ValueError("QuickTest-Durchlauf ohne ECUS-Anzahl.")
        count = next((int(m.group("count")) for text, _ in section[:marker]
                      if (m := ECU_COUNT.fullmatch(text))), None)
        count_at_section = int(ECUS.fullmatch(section[marker][0]).group("count"))
        if count is None or count != count_at_section:
            raise ValueError("QuickTest: ECU Count und ECUS stimmen nicht ueberein.")
        region = section[marker+1:]
        positions = [(j, parsed) for j in range(len(region))
                     if (parsed := _ecu_header(region, j)) is not None]
        if len(positions) != count:
            raise ValueError(
                f"QuickTest-Durchlauf {QUICKTEST.fullmatch(section[0][0]).group('number')}: "
                f"ECU-Anzahl stimmt nicht ueberein (Bericht={count}, erkannt={len(positions)})."
            )
        run_name = QUICKTEST.fullmatch(section[0][0]).group("number")
        from_index = len(ecus) + 1
        for j, (position, parsed) in enumerate(positions):
            block = region[position:positions[j+1][0] if j+1 < len(positions) else len(region)]
            fcounts = [k for k, (text, _) in enumerate(block) if FAULT_COUNT.fullmatch(text)]
            if len(fcounts) != 1:
                raise ValueError(f"QuickTest: ECU ohne eindeutige DTC-Anzahl ({parsed['ecu']}).")
            count_index = fcounts[0]
            count_faults = int(FAULT_COUNT.fullmatch(block[count_index][0]).group("count"))
            dtc_starts = [k for k, (text, _) in enumerate(block[count_index+1:], count_index+1)
                          if DTC_START.fullmatch(text)]
            if len(dtc_starts) != count_faults:
                raise ValueError(
                    f"QuickTest: {parsed['ecu']} meldet {count_faults} DTCs, "
                    f"aber {len(dtc_starts)} wurden erkannt."
                )
            faults = [_fault(block[k:dtc_starts[t+1] if t+1 < len(dtc_starts) else len(block)])
                      for t, k in enumerate(dtc_starts)]
            ecus.append({
                "ecu_index": len(ecus)+1,
                "quicktest_number": run_name,
                "ecu_code": parsed["ecu"],
                "location": parsed["location"],
                "name": parsed["name"],
                "metadata": _metadata([text for text, _ in block[1:count_index]]),
                "reported_fault_count": count_faults,
                "page_start": block[0][1],
                "page_end": block[-1][1],
                "raw_block_text": "\n".join(text for text, _ in block),
                "faults": faults,
            })
        runs.append({
            "quicktest_number": run_name,
            "ecu_count": count,
            "first_ecu_index": from_index,
            "last_ecu_index": len(ecus),
            "page_start": section[0][1],
            "page_end": section[-1][1],
        })
    return {
        "fin": fin,
        "vin": _value(preamble, "VIN"),
        "diag_start": moment,
        "distance_km": km,
        "preamble": preamble,
        "ecus": ecus,
        "runs": runs,
        "reported_ecu_count": sum(r["ecu_count"] for r in runs),
        "observed_dtc_count": sum(len(e["faults"]) for e in ecus),
        "header": {k: _value(preamble, k) for k in HEADER_KEYS},
    }
