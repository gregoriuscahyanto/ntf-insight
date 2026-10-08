"""Synthetic structural fixtures for local automotive source ZIP import.

No customer/vehicle/claim data from uploaded files is included in the repository.
"""
from __future__ import annotations

import io
import stat
from datetime import datetime
from pathlib import Path
from zipfile import ZipFile, ZipInfo

import pytest
from openpyxl import Workbook
from reportlab.pdfgen import canvas

from ntf_insight.ingestion.artifacts import SourceType
from ntf_insight.ingestion.batch_import import LocalBatchImporter
from ntf_insight.ingestion.real_source_parsers import (
    AutoExportParser,
    QECWorkbookParser,
    QuickTestPdfParser,
    canonical_fin,
)
from ntf_insight.ingestion.service import SourceImportService
from ntf_insight.ingestion.source_detection import detect_source_type


SYNTHETIC_FIN = "W1TTEST0000000001"


def _workbook_bytes() -> bytes:
    book = Workbook()
    sheet = book.active
    sheet.title = "Schadteile QEC"
    sheet.append([
        "Referenznr.", "FIN", "Benennung", "BR", "BM",
        "Prod.-Datum", "Rep.-Datum", "Laufleistung", "Sachnr. Teil",
        "SSL-Endbefund Benennung", "Bef.abschl.datum",
    ])
    sheet.append([
        "EXAMPLE-001", "MBC" + SYNTHETIC_FIN, "KUEHLMITTELPUMPE 100W",
        "214", "099", datetime(2025, 4, 3), datetime(2026, 1, 5),
        12345, "A000TEST", "Elektrischer Fehler - NTF",
        datetime(2026, 1, 17),
    ])
    stream = io.BytesIO()
    book.save(stream)
    return stream.getvalue()


def _autoexport_csv() -> bytes:
    text = (
        "Original query: synthetic fixture\n"
        "Query Id: synthetic\n\n"
        "DiagStartDt;SourceSystemNm;EcuNm;EcuHwPartnumberCd;EcuSuppHwVersionTxt;"
        "EcuSwVersionTxt;KmReadingNum;EcuFaultStateTxt;EcuFaultNm;EcuFaultTxt;"
        "FrequencyCounter;FirstOdometer;Fin\n"
        f"2026-01-02;TD;CPC3;A001;1.0;2.0;12000;S;P26F100;"
        f"Pump performance;3;11995;{SYNTHETIC_FIN}\n"
        f"2026-01-02;TD;CPC3;A001;1.0;2.0;12000;S;P260000;"
        f"Coolant circuit;1;11990;{SYNTHETIC_FIN}\n"
    )
    return text.encode("utf-8")


def _claim_csv() -> bytes:
    text = (
        "Original query: synthetic fixture\n"
        "Query Id: synthetic\n\n"
        "Fin;RepairDt;KmReadingNum;PartLetterCd;ComplDsc;RepairTypeNmGerman;"
        "WorksVisitDsc\n"
        f'{SYNTHETIC_FIN};2026-01-05;12345;A000TEST;'
        '"Pumpe funktioniert nicht";Tausch Pumpe;"Reparatur durchgeführt"\n'
    )
    return text.encode("utf-8")


def _quicktest_bytes(when: str, code: str) -> bytes:
    target = io.BytesIO()
    pdf = canvas.Canvas(target)
    lines = [
        f"FIN {SYNTHETIC_FIN}",
        f"VIN {SYNTHETIC_FIN}",
        "DISTANCE 12345 km",
        f"DIAG START {when}",
        "QuickTest 1",
        "ECU Count 1",
        "ECUS (1)",
        "CPC3-N127 - Control unit Drivetrain",
        "Diagnostics ID 004B35 ECU Variant CPC3_TEST",
        "Hardware",
        "Partnumber",
        "000 901 62 21 Hardware",
        "Version",
        "21/28 001",
        "Supplier Example Software",
        "Version",
        "24/25 000",
        "FAULT CODES (1)",
        f"FC {code} - Coolant pump performance. S",
        "Name Value (first occurence or unknown) Value (last occurence)",
        "frequencyCounter 2 -",
        "originalOdometerValue 12340 km -",
        "mostRecentOdometerValue 12345 km -",
    ]
    for index, line in enumerate(lines):
        # drawString preserves the simple line-wise extraction used by the parser
        pdf.drawString(35, 790 - 19 * index, line)
    pdf.save()
    return target.getvalue()


def _bundle(path: Path) -> None:
    with ZipFile(path, "w") as z:
        z.writestr("bundle/cases.xlsx", _workbook_bytes())
        z.writestr("bundle/diag.csv", _autoexport_csv())
        z.writestr("bundle/workshop.csv", _claim_csv())
        before = _quicktest_bytes("2026-01-03 12:00:00", "P26F100")
        after = _quicktest_bytes("2026-01-10 12:00:00", "P26F100")
        z.writestr("bundle/report_pre.pdf", before)
        z.writestr("bundle/report_post.pdf", after)
        z.writestr("bundle/report_post_copy.pdf", after)
        z.writestr(
            "bundle/CPC3.cdd",
            "<?xml version='1.0'?><!DOCTYPE CANDELA SYSTEM 'candela.dtd'>"
            "<CANDELA dtdvers='20.0.5'></CANDELA>",
        )


def test_content_detection_and_cdd_not_smr_d(tmp_path) -> None:
    workbook = tmp_path / "random.xlsx"
    workbook.write_bytes(_workbook_bytes())
    diag = tmp_path / "auto.csv"
    diag.write_bytes(_autoexport_csv())
    claim = tmp_path / "claims.csv"
    claim.write_bytes(_claim_csv())
    pdf = tmp_path / "random.pdf"
    pdf.write_bytes(_quicktest_bytes("2026-01-03 12:00:00", "P26F100"))
    cdd = tmp_path / "test.cdd"
    cdd.write_text(
        "<?xml version='1.0'?><!DOCTYPE CANDELA SYSTEM 'candela.dtd'>"
        "<CANDELA></CANDELA>",
        encoding="utf-8",
    )

    assert detect_source_type(workbook) == SourceType.VEHICLE_CASE_LIST
    assert detect_source_type(diag) == SourceType.SHORT_TEST
    assert detect_source_type(claim) == SourceType.WORKSHOP_HISTORY
    assert detect_source_type(pdf) == SourceType.SHORT_TEST
    assert detect_source_type(cdd) == SourceType.DIAGNOSTIC_DESCRIPTION
    assert canonical_fin("MBC" + SYNTHETIC_FIN) == SYNTHETIC_FIN


def test_qec_parser_keeps_case_anchor_and_ntf_as_finding(tmp_path) -> None:
    path = tmp_path / "cases.xlsx"
    path.write_bytes(_workbook_bytes())
    parsed = QECWorkbookParser("a" * 64).parse(path)

    assert len(parsed.cases) == 1
    case = parsed.cases[0]
    assert case.vin == SYNTHETIC_FIN
    assert case.component_profile_id == "coolant_pump"
    assert case.investigated_replacement() is not None
    assert case.investigated_replacement().mileage_km == 12345
    assert case.investigated_replacement().time_precision == "date"
    assert case.supplier_findings[0].result.value == "NTF"


def test_csv_exports_preserve_source_row_and_datetime_precision(tmp_path) -> None:
    path = tmp_path / "diagnostics.csv"
    path.write_bytes(_autoexport_csv())
    parsed = AutoExportParser(
        "b" * 64, SourceType.SHORT_TEST, {SYNTHETIC_FIN}
    ).parse(path)
    assert len(parsed.diagnostics) == 2
    assert len(parsed.sessions) == 0  # Filtered fault export is NOT a full short test.
    assert len(parsed.ecu_states) == 1
    assert parsed.diagnostics[0].time_precision == "date"
    assert parsed.diagnostics[0].occurrence_count == 3
    assert parsed.diagnostics[0].source_ref.startswith("raw:")

    claim = tmp_path / "claims.csv"
    claim.write_bytes(_claim_csv())
    claims = AutoExportParser(
        "c" * 64, SourceType.WORKSHOP_HISTORY, {SYNTHETIC_FIN}
    ).parse(claim)
    assert len(claims.repairs) == 1
    assert "Tausch" in claims.repairs[0].action


def test_quicktest_pdf_extracts_full_session_and_dtc(tmp_path) -> None:
    path = tmp_path / "report.pdf"
    path.write_bytes(_quicktest_bytes("2026-01-03 12:00:00", "P26F100"))
    parsed = QuickTestPdfParser("d" * 64).parse(path)

    assert len(parsed.sessions) == 1
    assert len(parsed.diagnostics) == 1
    assert len(parsed.ecu_states) == 1
    assert parsed.sessions[0].dtc_count == 1
    assert parsed.diagnostics[0].ecu == "CPC3"
    assert parsed.diagnostics[0].dtc_code == "P26F100"
    assert parsed.diagnostics[0].occurrence_count == 2
    assert parsed.ecu_states[0].software_version == "24/25 000"


def test_zip_import_is_local_linked_and_idempotent(tmp_path) -> None:
    archive = tmp_path / "synthetic-sources.zip"
    _bundle(archive)
    source = SourceImportService(tmp_path / "raw", tmp_path / "cases.duckdb")
    importer = LocalBatchImporter(source)

    first = importer.import_paths([archive])
    saved = source.store.load_cases()
    assert first.cases_created == 1
    assert len(saved) == 1
    assert first.files_parsed == 5
    assert first.duplicates == 1
    assert len(saved[0].diagnostic_sessions) == 2
    assert len(saved[0].diagnostics) == 4
    assert len(saved[0].replacements) == 1
    assert len(saved[0].repairs) == 1
    assert saved[0].investigated_replacement() is not None
    assert source.store.load_artifacts()

    second = importer.import_paths([archive])
    repeated = source.store.load_cases()
    assert second.cases_created == 0
    assert len(repeated[0].diagnostics) == len(saved[0].diagnostics)
    assert len(repeated[0].diagnostic_sessions) == 2


def test_zip_rejects_path_traversal_without_extracting(tmp_path) -> None:
    path = tmp_path / "unsafe.zip"
    with ZipFile(path, "w") as z:
        z.writestr("../outside.csv", b"not a valid path")
    source = SourceImportService(tmp_path / "raw", tmp_path / "cases.duckdb")
    with pytest.raises(ValueError, match="ZIP-Pfad"):
        LocalBatchImporter(source).import_paths([path])
    assert not (tmp_path / "outside.csv").exists()


def test_zip_rejects_symlinks(tmp_path) -> None:
    path = tmp_path / "symlink.zip"
    with ZipFile(path, "w") as z:
        info = ZipInfo("bundle/link.csv")
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        z.writestr(info, "../../secret")
    source = SourceImportService(tmp_path / "raw", tmp_path / "cases.duckdb")
    with pytest.raises(ValueError, match="symbolische Links"):
        LocalBatchImporter(source).import_paths([path])


@pytest.mark.parametrize("member_name", ["bundle/file:stream.csv", "bundle/CON.csv"])
def test_zip_rejects_windows_unsafe_member_names(tmp_path, member_name) -> None:
    path = tmp_path / "unsafe-name.zip"
    with ZipFile(path, "w") as z:
        z.writestr(member_name, b"synthetic")
    source = SourceImportService(tmp_path / "raw", tmp_path / "cases.duckdb")
    with pytest.raises(ValueError, match="ZIP"):
        LocalBatchImporter(source).import_paths([path])
