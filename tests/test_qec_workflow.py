"""Synthetische Regressionstests für die QEC-FIN-Kohorte und den Workflow."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from openpyxl import Workbook

from ntf_insight.ingestion.batch_import import LocalBatchImporter
from ntf_insight.ingestion.service import SourceImportService
from ntf_insight.storage.qec_workflow_store import QecWorkflowStore


def _primary(
    path: Path, ref: str, fin: str = "W1TTEST0000000001",
    part: str = "SYNTH-PART",
) -> None:
    workbook = Workbook()
    ws = workbook.active
    ws.title = "Schadteile QEC"
    ws.append(["Referenznr.", "FIN", "Rep.-Datum", "Benennung", "Sachnr. Teil"])
    ws.append([ref, fin, datetime(2026, 5, 10), "KÜHLMITTELPUMPE", part])
    workbook.save(path)
    workbook.close()


def _ssl(path: Path, ref: str) -> None:
    workbook = Workbook()
    ws = workbook.active
    ws.title = "Schadteile"
    ws.append(["Referenznr.", "Sachnr. Teil", "SSL Endbefund", "SSL-Endbefund Benennung"])
    ws.append([ref, "SYNTH-PART", "SYNTH-CODE", "Synthetisch NTF"])
    workbook.save(path)
    workbook.close()


def _env(tmp_path: Path):
    source = SourceImportService(tmp_path / "archive", tmp_path / "qec.duckdb")
    return source, LocalBatchImporter(source), QecWorkflowStore(source.store)


def test_only_one_primary_qec_list_and_idempotent_reimport(tmp_path: Path):
    source, importer, workflow = _env(tmp_path)
    first = tmp_path / "first.xlsx"
    second = tmp_path / "second.xlsx"
    finding = tmp_path / "ssl.xlsx"
    _primary(first, "1001")
    _primary(second, "1002")
    _ssl(finding, "1001")
    importer.import_paths([first])
    importer.import_paths([first])
    importer.import_paths([finding])
    assert workflow.active_source().original_name == "first.xlsx"
    assert len(source.store.load_cases()) == 1
    with pytest.raises(ValueError, match="nur eine QEC"):
        importer.import_paths([second])
    assert workflow.active_source().original_name == "first.xlsx"
    assert len(source.store.load_cases()) == 1


def test_ntf_manual_decision_csv_handoff_and_change_invalidates(tmp_path: Path):
    source, importer, workflow = _env(tmp_path)
    first = tmp_path / "first.xlsx"
    _primary(first, "12345")
    importer.import_paths([first])
    artifact = workflow.active_source()
    assert artifact is not None
    stats = workflow.overview(tmp_path / "qec")
    assert stats["cases"] == stats["fins"] == stats["open"] == 1
    assert stats["downloaded"] == stats["ntf"] == 0
    assert workflow.handoff_ntf(tmp_path / "qec") == 0
    workflow.set_decision(artifact.sha256, "QEC-12345", "NTF", "Synthetischer Prüfbericht")
    assert workflow.handoff_ntf(tmp_path / "qec") == 1
    assert workflow.handed_off_fins() == ("W1TTEST0000000001",)
    output = tmp_path / "export.csv"
    assert workflow.export_csv(output, tmp_path / "qec") == 1
    assert "Synthetischer Prüfbericht" in output.read_text(encoding="utf-8-sig")
    workflow.set_decision(artifact.sha256, "QEC-12345", "Kein NTF", "Bauteildefekt")
    assert workflow.handed_off_fins() == ()


def test_delete_primary_removes_cohort_and_allows_next(tmp_path: Path):
    source, importer, workflow = _env(tmp_path)
    first = tmp_path / "first.xlsx"
    second = tmp_path / "second.xlsx"
    _primary(first, "1001")
    _primary(second, "1002")
    importer.import_paths([first])
    artifact = workflow.active_source()
    workflow.set_decision(artifact.sha256, "QEC-1001", "NTF", "")
    source.delete_artifact(artifact.sha256)
    assert workflow.active_source() is None
    assert source.store.load_cases() == []
    assert workflow.handed_off_fins() == ()
    importer.import_paths([second])
    assert workflow.active_source().original_name == "second.xlsx"
    assert len(source.store.load_cases()) == 1


def test_no_automatic_classification_from_ssl(tmp_path: Path):
    source, importer, workflow = _env(tmp_path)
    first = tmp_path / "first.xlsx"
    finding = tmp_path / "ssl.xlsx"
    _primary(first, "1001")
    _ssl(finding, "1001")
    importer.import_paths([first, finding])
    rows = workflow.rows(tmp_path / "qec")
    assert rows[0]["decision"] == "Offen"
    assert "NTF" in rows[0]["finding"]



def test_two_independent_qec_part_projects_can_coexist(tmp_path: Path):
    """Different parts may have different source lists without losing earlier cases."""
    source, importer, workflow = _env(tmp_path)
    first = tmp_path / "pumpe-a.xlsx"
    second = tmp_path / "pumpe-b.xlsx"
    _primary(first, "12345", part="A-PART")
    _primary(
        second, "98765", fin="W1TTEST0000000002", part="B-PART",
    )
    importer.import_paths([first])
    importer.import_paths([second])
    assert workflow.active_source() is None
    assert len(workflow.active_sources()) == 2
    cases = workflow.rows(tmp_path / "qec")
    assert len(cases) == 2
    assert {r["part_number"] for r in cases} == {"A-PART", "B-PART"}
    assert {r["source_sha256"] for r in cases} == {
        source.sha256 for source in workflow.active_sources()
    }
    b = next(row for row in cases if row["part_number"] == "B-PART")
    workflow.set_decision(
        b["source_sha256"], b["case_id"], "NTF", "Synthetisch geprüft",
    )
    assert workflow.handoff_ntf(tmp_path / "qec") == 1
    assert workflow.handed_off_fins() == ("W1TTEST0000000002",)
    assert len(source.store.load_cases()) == 2
