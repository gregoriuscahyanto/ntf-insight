"""Synthetische QEC-SSL-Endbefunde ohne FIN: lokale Referenzverknüpfung.

Niemals reale Schadteil-, FIN- oder Lieferantendaten in Tests ablegen.
"""
from __future__ import annotations

from datetime import datetime

import pytest
from openpyxl import Workbook

from ntf_insight.analysis.qec_end_finding_filter import finding_counts
from ntf_insight.ingestion.artifacts import SourceType
from ntf_insight.ingestion.batch_import import LocalBatchImporter
from ntf_insight.ingestion.service import SourceImportService
from ntf_insight.ingestion.source_detection import detect_source_type


FIN = "W1TTEST0000000001"
REFERENCE = "SYNTH-REF-42"
PART = "SYNTH-PART-1"
FINDING = "Synthetischer SSL-Endbefund"


def _cases(path):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Schadteile QEC"
    sheet.append((
        "Referenznr.", "FIN", "Rep.-Datum", "Benennung",
        "Sachnr. Teil", "SSL Endbefund", "SSL-Endbefund Benennung",
    ))
    sheet.append((
        REFERENCE, FIN, datetime(2026, 5, 10), "KÜHLMITTELPUMPE",
        PART, None, None,
    ))
    workbook.save(path)
    workbook.close()


def _findings(path, *, reference=REFERENCE, part=PART, finding=FINDING):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Schadteile"
    sheet.append((
        "Referenznr.", "Sachnr. Teil", "SSL Endbefund",
        "SSL-Endbefund Benennung", "Bef.abschl.datum",
    ))
    sheet.append((
        reference, part, "SYNTH-CODE-42", finding, datetime(2026, 5, 20),
    ))
    workbook.save(path)
    workbook.close()


@pytest.mark.parametrize("first", ("cases", "findings", "both"))
def test_qec_ssl_without_fin_links_only_existing_case_by_reference(tmp_path, first):
    case_file = tmp_path / "cases.xlsx"
    finding_file = tmp_path / "ssl.xlsx"
    _cases(case_file)
    _findings(finding_file)
    assert detect_source_type(case_file) == SourceType.VEHICLE_CASE_LIST
    assert detect_source_type(finding_file) == SourceType.VEHICLE_CASE_LIST
    source = SourceImportService(tmp_path / "archive", tmp_path / "store.duckdb")
    importer = LocalBatchImporter(source)
    if first == "both":
        result = importer.import_paths([finding_file, case_file])
        assert result.cases_created == 1
        assert result.qec_findings_linked == 1
    else:
        initial, later = (
            (case_file, finding_file)
            if first == "cases" else (finding_file, case_file)
        )
        earlier = importer.import_paths([initial])
        if first == "findings":
            assert earlier.cases_created == 0
            assert source.store.load_cases() == []
        later_result = importer.import_paths([later])
        assert later_result.qec_findings_linked == 1
    cases = source.store.load_cases()
    assert len(cases) == 1
    assert cases[0].vin == FIN
    assert cases[0].qec_ssl_end_finding == FINDING
    assert cases[0].qec_ssl_end_code == "SYNTH-CODE-42"
    assert cases[0].qec_ssl_end_date == "2026-05-20"
    assert len(cases[0].replacements) == 1
    assert cases[0].investigated_replacement().occurred_at.date().isoformat() == "2026-05-10"
    assert finding_counts(cases) == {FINDING: 1}
    again = importer.import_paths([finding_file])
    assert again.cases_created == 0
    assert again.qec_findings_linked == 0


def test_qec_reference_only_export_must_not_fabricate_fin(tmp_path):
    finding_file = tmp_path / "ssl.xlsx"
    _findings(finding_file)
    source = SourceImportService(tmp_path / "archive", tmp_path / "store.duckdb")
    importer = LocalBatchImporter(source)
    result = importer.import_paths([finding_file])
    assert result.files_parsed == 1
    assert result.reference_rows == 1
    assert result.cases_created == 0
    assert result.events_linked == 0
    assert source.store.load_cases() == []


def test_qec_reference_part_number_mismatch_does_not_link(tmp_path):
    cases = tmp_path / "cases.xlsx"
    findings = tmp_path / "findings.xlsx"
    _cases(cases)
    _findings(findings, part="DIFFERENT-PART")
    source = SourceImportService(tmp_path / "archive", tmp_path / "store.duckdb")
    result = LocalBatchImporter(source).import_paths([cases, findings])
    assert result.qec_findings_linked == 0
    assert result.qec_findings_conflicted == 1
    assert not getattr(source.store.load_cases()[0], "qec_ssl_end_finding", None)


def test_qec_conflicting_reference_findings_are_not_guessed(tmp_path):
    cases = tmp_path / "cases.xlsx"
    a = tmp_path / "one.xlsx"
    b = tmp_path / "two.xlsx"
    _cases(cases)
    _findings(a, finding="Synthetisch A")
    _findings(b, finding="Synthetisch B")
    source = SourceImportService(tmp_path / "archive", tmp_path / "store.duckdb")
    result = LocalBatchImporter(source).import_paths([cases, a, b])
    assert result.qec_findings_linked == 0
    assert result.qec_findings_conflicted == 1
    assert not getattr(source.store.load_cases()[0], "qec_ssl_end_finding", None)
