"""Synthetic regression tests for global product/diagnostic reference sources.

No internal PDFs, FINs, exports or Candela content from the supplied ZIP is
stored in these tests or in the public GitHub repository.
"""
from __future__ import annotations

import io
from datetime import datetime
from zipfile import ZipFile

import pytest
from openpyxl import Workbook
from reportlab.pdfgen import canvas

from ntf_insight.ingestion.artifacts import SourceType
from ntf_insight.ingestion.batch_import import LocalBatchImporter
from ntf_insight.ingestion.reference_source_parsers import (
    AutoExportSummaryParser,
    CandelaParser,
    PartHistoryParser,
    QECDetailsParser,
    SupplierAnalysisDocumentParser,
    iter_autoexport_rows,
)
from ntf_insight.ingestion.service import SourceImportService
from ntf_insight.ingestion.source_detection import detect_source_type
from ntf_insight.storage.source_knowledge_store import SourceKnowledgeStore


FIN = "W1TTEST0000000001"

CDD = b"""<?xml version='1.0' encoding='utf-8'?>
<!DOCTYPE CANDELA SYSTEM 'candela.dtd'>
<CANDELA dtdvers='20.0.5'><ECUDOC>
<DIAGCLASS id='_10'><QUAL>StoredData</QUAL>
<DIAGINST id='_11' req='req'><NAME><TUV xml:lang='en-US'>ReadStatus</TUV></NAME>
<QUAL>ReadStatus</QUAL><DESC><TUV>Read ECU status</TUV></DESC>
<SERVICE><SEMANTIC>STOREDDATAREAD</SEMANTIC></SERVICE></DIAGINST>
<DIAGINST id='_12'><NAME><TUV xml:lang='en-US'>ClearMemory</TUV></NAME>
<QUAL>ClearMemory</QUAL><SERVICE><SEMANTIC>DEFAULT-FAULT-CLEAR</SEMANTIC></SERVICE>
</DIAGINST></DIAGCLASS>
</ECUDOC></CANDELA>"""


def _pdf() -> bytes:
    buffer = io.BytesIO()
    page = canvas.Canvas(buffer)
    lines = [
        "Part History List",
        "Název výrobku: Electric pump",
        "Datum zavedení Index Podrobnosti",
        "8/27/2021    PE-4044089    Q01    PPAP initial release    Line 1",
        "CW10/2026    PE-4480796    Q11    Alternate diode    Line 1 & 2",
        "Only for internal use",
    ]
    for index, text in enumerate(lines):
        page.drawString(40, 760 - 22 * index, text)
    page.save()
    return buffer.getvalue()


def _xlsx() -> bytes:
    book = Workbook()
    sheet = book.active
    sheet.title = "Schadteile QEC"
    sheet.append(["Referenznr.", "FIN", "Rep.-Datum", "Benennung", "Extra", "Extra"])
    sheet.append(["TEST-100", "MBC" + FIN, datetime(2026, 1, 3), "KUEHLMITTELPUMPE", "A", "B"])
    others = book.create_sheet("NTF_Elektrischer Fehler")
    others.append(["Referenznr.", "FIN", "Neue Quelle"])
    others.append(["TEST-100", "MBC" + FIN, "Kommentar"])
    data = io.BytesIO()
    book.save(data)
    return data.getvalue()


def _csv() -> bytes:
    return (
        "Original query: synthetic\nQuery Id: synthetic\n\n"
        "DiagStartDt;EcuFaultNm;EcuNm;Fin;Tag;Tag\n"
        f'2026-01-02;P26F100;CPC3;{FIN};first;second\n'
        '2026-01-03;P01;CPC3;OTHER-VIN;"quoted\nmultiline";another\n'
    ).encode("utf-8")


def _sources(tmp_path):
    return SourceImportService(tmp_path / "raw", tmp_path / "cases.duckdb")


def test_cdd_parser_extracts_services_and_does_not_assert_trigger_rules(tmp_path) -> None:
    path = tmp_path / "fictional.cdd"
    path.write_bytes(CDD)
    result = CandelaParser().parse(path)
    assert result.kind == "candela_services"
    assert result.metadata["triggers_validated"] is False
    assert result.metadata["service_count"] == 2
    assert result.metadata["class_count"] == 1
    assert result.records[0]["data"]["class"] == "StoredData"
    assert result.records[0]["data"]["semantics"] == ["STOREDDATAREAD"]
    assert result.records[1]["reference"] == "ClearMemory"
    assert all(record["fin"] is None for record in result.records)


def test_cdd_rejects_xml_entity_expansion_and_is_not_an_smr_d_parser(tmp_path) -> None:
    path = tmp_path / "unsafe.cdd"
    path.write_text(
        "<?xml version='1.0'?><!DOCTYPE CANDELA [<!ENTITY x SYSTEM "
        "'file:///etc/passwd'>]><CANDELA><DIAGINST><QUAL>&x;</QUAL>"
        "</DIAGINST></CANDELA>"
    )
    with pytest.raises(ValueError, match="unsicheres"):
        CandelaParser().parse(path)


def test_part_history_preserves_day_and_calendar_week_granularity(tmp_path) -> None:
    path = tmp_path / "part.pdf"
    path.write_bytes(_pdf())
    assert detect_source_type(path) == SourceType.PART_HISTORY
    parsed = PartHistoryParser().parse(path)
    assert len(parsed.records) == 2
    a, b = [row["data"] for row in parsed.records]
    assert a["precision"] == "day"
    assert a["period_start"] == a["period_end"] == "2021-08-27"
    assert b["precision"] == "calendar_week"
    assert b["period_start"] == "2026-03-02"
    assert b["period_end"] == "2026-03-08"
    assert b["revision"] == "Q11"
    assert "Alternate diode" in b["details"]
    assert all(row["fin"] is None for row in parsed.records)


def test_qec_details_persists_all_sheets_and_duplicate_headers(tmp_path) -> None:
    path = tmp_path / "qec.xlsx"
    path.write_bytes(_xlsx())
    details = QECDetailsParser().parse(path)
    assert details.metadata["total_rows"] == 2
    assert len(details.metadata["sheets"]) == 2
    assert details.records[0]["data"]["Extra"] == "A"
    assert details.records[0]["data"]["Extra__2"] == "B"
    assert details.records[1]["source_location"] == "NTF_Elektrischer Fehler!2"


def test_autoexport_rows_keep_all_fins_and_duplicate_columns(tmp_path) -> None:
    path = tmp_path / "auto.csv"
    path.write_bytes(_csv())
    records = list(iter_autoexport_rows(path))
    assert len(records) == 2
    assert records[0]["data"]["Tag"] == "first"
    assert records[0]["data"]["Tag__2"] == "second"
    assert records[1]["fin"] == "OTHER-VIN"
    assert "\n" in records[1]["data"]["Tag"]


def test_autoexport_count_not_used_as_installed_population(tmp_path) -> None:
    path = tmp_path / "aggregate.csv"
    path.write_text("Original query: synthetic\nQuery Id: synthetic\n\nC1\n1234\n")
    assert detect_source_type(path) == SourceType.AUTOEXPORT_SUMMARY
    parsed = AutoExportSummaryParser().parse(path)
    assert parsed.metadata["not_an_installed_population_denominator"] is True
    assert parsed.records[0]["data"]["C1"] == "1234"


def test_end_to_end_zip_archives_parses_and_avoids_fin_fabrication(tmp_path) -> None:
    archive = tmp_path / "fixtures.zip"
    with ZipFile(archive, "w") as package:
        package.writestr("input/diag.cdd", CDD)
        package.writestr("input/history.pdf", _pdf())
        package.writestr("input/qec.xlsx", _xlsx())
        package.writestr("input/auto.csv", _csv())
        package.writestr("input/summary.csv", b"C1\n1234\n")
    service = _sources(tmp_path)
    importer = LocalBatchImporter(service)
    first = importer.import_paths([archive])
    knowledge = SourceKnowledgeStore(service.store)
    counts = knowledge.summary()

    assert first.reference_sources == 5
    assert counts["candela_services"] == 2
    assert counts["part_history"] == 2
    assert counts["qec_details"] == 2
    assert counts["autoexport_rows"] == 2
    assert counts["autoexport_summary"] == 1
    assert knowledge.count_rows("cdd_service") == 2
    assert len(knowledge.list_rows(category="part_change")) == 2
    assert knowledge.list_rows(category="autoexport_dtc", fin="OTHER-VIN")
    # QEC details must not manufacture extra NTF cases from sub-sheets.
    assert len(service.store.load_cases()) == 1  # sub-sheets never create duplicate NTF cases
    assert first.files_parsed >= 4

    again = importer.import_paths([archive])
    assert again.reference_sources == 5
    assert knowledge.summary() == counts
    assert len(service.store.load_artifacts()) == 6


def test_source_knowledge_transaction_rolls_back_on_invalid_row(tmp_path) -> None:
    store = SourceKnowledgeStore(_sources(tmp_path).store)
    store.save_records("x" * 64, "custom", [
        {"category": "a", "reference": "one", "data": {"ok": True}},
    ])
    with pytest.raises(ValueError, match="mehr"):
        store.save_records("x" * 64, "custom", [
            {"category": "a", "data": {}},
            {"category": "a", "data": {}},
        ], maximum_rows=1)
    assert store.count_rows("a") == 1


def _supplier_pdf() -> bytes:
    out = io.BytesIO()
    report = canvas.Canvas(out)
    report.drawString(25, 760, "ANALYSIS REPORT")
    report.drawString(25, 730, "Complaint: synthetic coolant pump observation")
    report.drawString(25, 700, "Evaluation: inspect component, no confirmed result")
    report.showPage()
    report.drawString(25, 760, "Further analysis notes, no conclusive claim")
    report.save()
    return out.getvalue()


def test_supplier_pdf_is_extracted_without_claiming_ntf(tmp_path) -> None:
    path = tmp_path / "supplier.pdf"
    path.write_bytes(_supplier_pdf())
    assert detect_source_type(path) == SourceType.SUPPLIER_FINDING
    parsed = SupplierAnalysisDocumentParser().parse(path)
    assert len(parsed.records) == 2
    assert parsed.metadata["ntf_result_automatically_inferred"] is False
    assert parsed.metadata["requires_manual_qec_match"] is True
    assert all(row["fin"] is None for row in parsed.records)
    service = _sources(tmp_path)
    summary = LocalBatchImporter(service).import_paths([path])
    assert summary.reference_sources == 1
    assert len(service.store.load_cases()) == 0
    assert SourceKnowledgeStore(service.store).summary()["supplier_analysis_document"] == 2


def test_knowledge_only_import_opens_local_mode_and_gui_explorer(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("NTF_INSIGHT_DATA_DIR", str(tmp_path / "local-data"))
    from PySide6.QtWidgets import QApplication

    from ntf_insight.app.windows.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    assert window.application_data.mode == "demo"

    cdd_path = tmp_path / "example.cdd"
    cdd_path.write_bytes(CDD)
    import_result = LocalBatchImporter(
        window.pages["sources"].import_service
    ).import_paths([cdd_path])
    assert import_result.reference_sources == 1
    window._reload_data()

    assert window.application_data.mode == "local"
    assert window.repository.list_cases() == []
    assert "knowledge" in window.navigation.buttons
    page = window.pages["knowledge"]
    assert page.table_model.rowCount() == 2
    page.category.setCurrentIndex(page.category.findData("cdd_service"))
    assert page.table_model.rowCount() == 2
    page.search.setText("ClearMemory")
    assert page.table_model.rowCount() == 1
    page._show_detail(page.table_model.index(0, 0))
    assert "DEFAULT-FAULT-CLEAR" in page.detail.toPlainText()
    page.search.clear()
    assert page.table_model.rowCount() == 2

    window.close()
    app.processEvents()
