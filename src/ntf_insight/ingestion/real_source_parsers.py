"""Concrete parsers for locally stored exports and QuickTest reports.

Parser code may be public; actual source documents, vehicle identifiers, claims,
return-part reports and extracted data MUST stay on the authorized local machine.
"""
from __future__ import annotations

import csv
import re
from itertools import chain
from datetime import date, datetime
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, Field

from ntf_insight.domain.case import NTFCase
from ntf_insight.domain.enums import SupplierFindingResult
from ntf_insight.domain.events import (
    DiagnosticEvent,
    DiagnosticSession,
    ECUStateObservation,
    PartReplacement,
    RepairEvent,
    SupplierFinding,
)
from ntf_insight.domain.vehicle import Vehicle
from ntf_insight.ingestion.artifacts import SourceType


VIN_RE = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$", re.IGNORECASE)
FAULT_LINE = re.compile(r"^\s*(?:FC|EV)\s+([PBUC][0-9A-F]{6})\s*-\s*(.*)", re.I)
ECU_LINE = re.compile(r"^([A-Z0-9_]{2,})(?:-[^\s]+)?\s+-\s+.+")
ODOMETER_RE = re.compile(r"\b(\d+)\s*km", re.I)


def canonical_fin(raw: object) -> str | None:
    """Normalize a known QEC sales prefix but never conflate FIN with US VIN."""
    value = str(raw or "").strip().upper()
    if value.startswith("MBC") and len(value) == 20:
        value = value[3:]
    return value if VIN_RE.fullmatch(value) else None


def _date(value: object) -> tuple[datetime | None, bool]:
    if isinstance(value, datetime):
        # Excel midnight timestamps usually mean only the date is known.
        # Preserve an explicitly non-midnight time when supplied.
        is_midnight = (value.hour, value.minute, value.second, value.microsecond) == (0, 0, 0, 0)
        return value.replace(tzinfo=None), is_midnight
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time()), True
    text = str(value or "").strip()
    if not text:
        return None, False
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        # Desktop records use naive local timestamps. No timezone translation:
        # a source with a timezone retains its UTC clock wall-time explicitly.
        return parsed.replace(tzinfo=None), len(text) <= 10
    except ValueError:
        return None, False


def _date_event(value: object) -> dict:
    occurred_at, day_only = _date(value)
    if occurred_at is None:
        return {}
    if day_only:
        occurred_at = occurred_at.replace(hour=12, minute=0)
    return {
        "occurred_at": occurred_at,
        **({"time_precision": "date"} if day_only else {}),
    }


def _int(value: object) -> int | None:
    text = str(value or "").strip().replace(" ", "")
    try:
        number = int(text)
        return number if number >= 0 else None
    except ValueError:
        return None


def _str(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def _key(source_sha: str, reference: str) -> str:
    return uuid5(NAMESPACE_URL, f"ntf-insight:{source_sha}:{reference}").hex


def _ref(source_sha: str, record: str) -> str:
    return f"raw:{source_sha}#{record}"


class ParsedSource(BaseModel):
    cases: list[NTFCase] = Field(default_factory=list)
    diagnostics: list[DiagnosticEvent] = Field(default_factory=list)
    sessions: list[DiagnosticSession] = Field(default_factory=list)
    ecu_states: list[ECUStateObservation] = Field(default_factory=list)
    repairs: list[RepairEvent] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    skipped_rows: int = 0
    source_summary_count: int | None = None
    quicktest_report: dict | None = None


def _csv_rows(path: Path):
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for line in handle:
            if line.startswith(("Original query:", "Query Id:")) or not line.strip():
                continue
            # Header and body are semicolon-delimited; quoted free text may
            # contain newlines. Do not split the data on newlines manually.
            reader = csv.DictReader(
                chain([line], handle), delimiter=";", quotechar='"'
            )
            for index, row in enumerate(reader, start=2):
                yield index, row
            return


class QECWorkbookParser:
    name = "qec_workbook"
    version = "1.0.0"

    def __init__(self, source_sha: str) -> None:
        self.source_sha = source_sha

    def parse(self, path: Path) -> ParsedSource:
        from openpyxl import load_workbook

        output = ParsedSource()
        workbook = load_workbook(
            path, read_only=True, data_only=True, keep_links=False
        )
        try:
            if "Schadteile QEC" not in workbook.sheetnames:
                raise ValueError("QEC workbook has no primary 'Schadteile QEC' sheet.")
            sheet = workbook["Schadteile QEC"]
            rows = sheet.iter_rows(values_only=True)
            headers = next(rows)
            if not {"Referenznr.", "FIN", "Rep.-Datum"} <= set(headers):
                raise ValueError("QEC primary sheet is missing required columns.")

            for row_number, values in enumerate(rows, start=2):
                record = dict(zip(headers, values))
                reference = _str(record.get("Referenznr."))
                fin = canonical_fin(record.get("FIN"))
                if not reference or not fin:
                    output.skipped_rows += 1
                    continue
                raw_desc = _str(record.get("Benennung")) or ""
                if "KUEHLMITTELPUMPE" in raw_desc.upper() or "KÜHLMITTELPUMPE" in raw_desc.upper():
                    component, profile = "Coolant Pump", "coolant_pump"
                elif raw_desc:
                    component, profile = raw_desc, None
                else:
                    output.skipped_rows += 1
                    continue

                production, _ = _date(record.get("Prod.-Datum"))
                vehicle = Vehicle(
                    vin=fin,
                    model_series=_str(record.get("BR")),
                    variant=_str(record.get("BM")),
                    production_date=production.date() if production else None,
                    original_qec_fin=_str(record.get("FIN")),
                )
                finding = _str(record.get("SSL-Endbefund Benennung"))
                end_dt = _date_event(record.get("Bef.abschl.datum"))
                case = NTFCase(
                    case_id=f"QEC-{reference}",
                    vehicle=vehicle,
                    component_type=component,
                    component_profile_id=profile,
                    qec_reference=reference,
                    qec_status=_str(record.get("Status")),
                    qec_part_number=_str(record.get("Sachnr. Teil")),
                    qec_ssl_end_finding=finding,
                    qec_ssl_end_date=(
                        end_dt["occurred_at"].date().isoformat() if end_dt else None
                    ),
                    source_ref=_ref(self.source_sha, f"Schadteile QEC!{row_number}"),
                )

                replacement_dt = _date_event(record.get("Rep.-Datum"))
                if replacement_dt:
                    replacement = PartReplacement(
                        event_id=_key(self.source_sha, f"QEC:{row_number}:replacement"),
                        vin=fin,
                        mileage_km=_int(record.get("Laufleistung")),
                        component_type=component,
                        old_part_number=_str(record.get("Sachnr. Teil")),
                        serial_number=_str(record.get("Lief. Seriennr.")),
                        source_ref=_ref(self.source_sha, f"Schadteile QEC!{row_number}"),
                        **replacement_dt,
                    )
                    case.replacements.append(replacement)
                    case.investigated_replacement_id = replacement.event_id
                if finding:
                    # An undated SSL result belongs to the case, but is NOT an
                    # event at the replacement date. Keep original wording in
                    # qec_ssl_end_finding without fabricating a timestamp.
                    if end_dt:
                        upper = finding.upper()
                        if "NTF" in upper or "OHNE FEHLER" in upper:
                            result = SupplierFindingResult.NTF
                        else:
                            result = SupplierFindingResult.OTHER
                        case.supplier_findings.append(
                            SupplierFinding(
                                event_id=_key(self.source_sha, f"QEC:{row_number}:finding"),
                                vin=fin,
                                result=result,
                                failure_mode=finding,
                                source_ref=_ref(self.source_sha, f"Schadteile QEC!{row_number}"),
                                **end_dt,
                            )
                        )
                output.cases.append(case)
        finally:
            workbook.close()
        if output.skipped_rows:
            output.issues.append(f"QEC: {output.skipped_rows} rows without valid reference/FIN/component.")
        if not output.cases:
            output.issues.append("QEC: no valid case rows.")
        return output


class AutoExportParser:
    name = "autoexport"
    version = "1.0.0"

    def __init__(
        self,
        source_sha: str,
        source_type: SourceType,
        allowed_fins: set[str] | None = None,
    ) -> None:
        self.source_sha = source_sha
        self.source_type = source_type
        self.allowed_fins = allowed_fins

    def parse(self, path: Path) -> ParsedSource:
        output = ParsedSource()
        seen_ecu_states: set[tuple] = set()
        total = 0
        invalid = 0
        for row_number, row in _csv_rows(path):
            total += 1
            if "C1" in row and "Fin" not in row and "EcuFaultNm" not in row:
                output.source_summary_count = _int(row.get("C1"))
                continue

            fin = canonical_fin(row.get("Fin"))
            if not fin:
                output.skipped_rows += 1
                invalid += 1
                continue
            if self.allowed_fins is not None and fin not in self.allowed_fins:
                output.skipped_rows += 1
                continue

            when = _date_event(row.get("DiagStartDt" if self.source_type == SourceType.SHORT_TEST else "RepairDt"))
            if not when:
                output.skipped_rows += 1
                invalid += 1
                continue

            source_ref = _ref(self.source_sha, f"csv:{row_number}")
            if self.source_type == SourceType.SHORT_TEST:
                ecu = _str(row.get("EcuNm"))
                dtc = _str(row.get("EcuFaultNm"))
                if not ecu or not dtc:
                    output.skipped_rows += 1
                    invalid += 1
                    continue
                km = _int(row.get("KmReadingNum"))
                output.diagnostics.append(
                    DiagnosticEvent(
                        event_id=_key(self.source_sha, f"csv:{row_number}:dtc"),
                        vin=fin,
                        ecu=ecu,
                        dtc_code=dtc,
                        dtc_text=_str(row.get("EcuFaultTxt")),
                        status=_str(row.get("EcuFaultStateTxt")),
                        occurrence_count=_int(row.get("FrequencyCounter")),
                        mileage_km=km,
                        freeze_frame={
                            key: str(row[key])
                            for key in ("FirstOdometer", "EcuFootPrintTxt")
                            if row.get(key)
                        },
                        source_ref=source_ref,
                        **when,
                    )
                )
                hw = _str(row.get("EcuSuppHwVersionTxt"))
                sw = _str(row.get("EcuSwVersionTxt"))
                part = _str(row.get("EcuHwPartnumberCd"))
                identity = (fin, when["occurred_at"], ecu, hw, sw, part)
                if identity not in seen_ecu_states and (hw or sw):
                    seen_ecu_states.add(identity)
                    output.ecu_states.append(
                        ECUStateObservation(
                            event_id=_key(self.source_sha, f"csv:state:{row_number}"),
                            vin=fin, ecu=ecu,
                            software_version=sw,
                            hardware_version=hw,
                            hardware_part_number=part,
                            mileage_km=km,
                            source_ref=source_ref,
                            **when,
                        )
                    )
            elif self.source_type == SourceType.WORKSHOP_HISTORY:
                output.repairs.append(
                    RepairEvent(
                        event_id=_key(self.source_sha, f"csv:{row_number}:repair"),
                        vin=fin,
                        mileage_km=_int(row.get("KmReadingNum")),
                        complaint=_str(row.get("ComplDsc")),
                        action=_str(row.get("RepairTypeNmGerman")),
                        notes=_str(row.get("WorksVisitDsc")),
                        damaged_part_number=_str(row.get("PartLetterCd")),
                        damage_type=_str(row.get("DamageTypeNmDeu")),
                        source_ref=source_ref,
                        **when,
                    )
                )
        if invalid:
            output.issues.append(
                f"AutoExport: {invalid} invalid rows of {total}; "
                f"{output.skipped_rows - invalid} rows excluded by FIN filter."
            )
        return output


def _field(text: str, label: str) -> str | None:
    match = re.search(r"(?m)^\s*" + re.escape(label) + r"\s+([^\n]+)", text)
    return match.group(1).strip() if match else None


class QuickTestPdfParser:
    """Complete QuickTest parser, including ECU and DTC snapshot details."""

    name = "quicktest_pdf"
    version = "2.0.0"

    def __init__(self, source_sha: str) -> None:
        self.source_sha = source_sha

    def parse(self, path: Path) -> ParsedSource:
        from ntf_insight.ingestion.quicktest_detailed import extract_quicktest

        return extract_quicktest(path, self.source_sha)
