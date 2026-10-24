"""Inkrementeller, nach einem Abbruch fortsetzbarer QuickTest-/QEC-Import.

Die Test-Fixtures sind ausschließlich synthetisch. Keine echten Fahrzeugdaten.
"""
from __future__ import annotations

import io
import json
from threading import Event

from reportlab.pdfgen import canvas

from ntf_insight.ingestion.artifacts import ParseStatus
from ntf_insight.ingestion.batch_import import LocalBatchImporter
from ntf_insight.ingestion.qec_json import QEC_SECTIONS
from ntf_insight.ingestion.service import SourceImportService
from ntf_insight.storage.quicktest_store import QuickTestStore
from ntf_insight.storage.source_knowledge_store import SourceKnowledgeStore


FIN = "W1TTEST0000000001"


def service_for(tmp_path):
    return SourceImportService(tmp_path / "raw", tmp_path / "data.duckdb")


def qec_file(tmp_path, reference="123456", *, value="A"):
    path = tmp_path / "qec" / FIN / ("ref_" + reference) / "qec.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 2,
        "fin": FIN,
        "referenznummer": reference,
        "sachnummer": "A000TEST",
        "abgerufen_am_utc": "2026-10-21T12:00:00+00:00",
        "vollstaendige_reiter": True,
        "abschnitte": [
            {"bereich": name, "fin": FIN, "referenznummer": reference,
             "sichtbarer_text": "Synthetischer QEC-Reiter",
             "felder": [{"name": "probe", "typ": "text", "wert": value}],
             "tabellen": []}
            for name in QEC_SECTIONS
        ],
        "anhaenge": [],
        "fehler": [],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def valid_quicktest_pdf() -> bytes:
    stream = io.BytesIO()
    pdf = canvas.Canvas(stream)
    lines = [
        f"FIN {FIN}",
        "VIN W1TTEST0000000002",
        "DISTANCE 11980 km",
        "DIAG START 2026-01-03 10:12:45",
        "VERSION 1",
        "LANGUAGE en",
        "SOURCE TD",
        "QuickTest 1",
        "ECU Count 1",
        "ECUS (1)",
        "CPC3-N127 - Controller",
        "Diagnostics ID 00AB13 ECU Variant CPC3_TEST",
        "Hardware", "Partnumber",
        "001 002 003 Hardware", "Version", "23/15 000",
        "Supplier Example Software", "Version", "25/04 002",
        "Software", "Partnumbers", "000001,000002",
        "FAULT CODES (0)", "No fault codes",
    ]
    for index, line in enumerate(lines):
        pdf.drawString(35, 792 - 20 * index, line)
    pdf.save()
    return stream.getvalue()


def test_qec_only_new_skips_completed_and_detects_updated_json(tmp_path):
    source = service_for(tmp_path)
    importer = LocalBatchImporter(source)
    path = qec_file(tmp_path)
    one = importer.import_paths([path], only_new=True, local_kind="qec")
    assert one.files_parsed == 1
    assert not one.cancelled
    two = importer.import_paths([path], only_new=True, local_kind="qec")
    assert two.files_parsed == 0
    assert two.files_unchanged == 1
    assert two.files_archived == 0
    assert len(source.list_artifacts()) == 1
    path = qec_file(tmp_path, value="B")
    three = importer.import_paths([path], only_new=True, local_kind="qec")
    assert three.files_parsed == 1
    assert three.files_unchanged == 0
    assert len(source.list_artifacts()) == 2
    assert len([
        document for document in SourceKnowledgeStore(source.store).documents()
        if document["source_kind"] == "qec_live_report"
    ]) == 2


def test_quicktest_only_new_skips_known_report_without_parser_run(tmp_path, monkeypatch):
    source = service_for(tmp_path)
    importer = LocalBatchImporter(source)
    path = tmp_path / "quicktests" / FIN / "bericht.pdf"
    path.parent.mkdir(parents=True)
    path.write_bytes(valid_quicktest_pdf())
    first = importer.import_paths([path], only_new=True, local_kind="quicktests")
    assert first.quicktests_saved == 1
    assert len(QuickTestStore(source.store).list_reports(FIN)) == 1

    def cannot_parse(*_args, **_kwargs):
        raise AssertionError("Unveränderter QuickTest darf nicht nochmals geparst werden")

    monkeypatch.setattr("ntf_insight.ingestion.real_source_parsers.QuickTestPdfParser.parse", cannot_parse)
    second = importer.import_paths([path], only_new=True, local_kind="quicktests")
    assert second.files_parsed == 0
    assert second.files_unchanged == 1
    assert second.files_archived == 0


def test_qec_cancel_after_some_reports_and_resume_from_db(tmp_path):
    source = service_for(tmp_path)
    importer = LocalBatchImporter(source)
    paths = [qec_file(tmp_path, str(ref)) for ref in (123450, 123451, 123452, 123453)]
    cancel = Event()
    parsed = {"count": 0}

    def progress(text):
        if text.startswith("Referenzquelle einlesen"):
            parsed["count"] += 1
            if parsed["count"] == 2:
                cancel.set()

    first = importer.import_paths(
        paths, only_new=True, local_kind="qec",
        should_cancel=cancel.is_set, on_progress=progress,
    )
    assert first.cancelled
    assert first.files_parsed == 2
    assert not first.files_unchanged
    assert len([
        doc for doc in SourceKnowledgeStore(source.store).documents()
        if doc["source_kind"] == "qec_live_report"
    ]) == 2

    # New importer simulates closing and reopening the application.
    restarted = LocalBatchImporter(source)
    second = restarted.import_paths(paths, only_new=True, local_kind="qec")
    assert second.files_unchanged == 2
    assert second.files_parsed == 2
    assert not second.cancelled
    third = restarted.import_paths(paths, only_new=True, local_kind="qec")
    assert third.files_unchanged == 4
    assert third.files_parsed == 0


def test_cancel_during_archive_leaves_raw_files_and_no_incomplete_case(tmp_path):
    source = service_for(tmp_path)
    paths = [qec_file(tmp_path, str(ref)) for ref in (11111, 11112, 11113)]
    calls = {"n": 0}

    def cancel():
        calls["n"] += 1
        return calls["n"] > 1

    first = LocalBatchImporter(source).import_paths(
        paths, only_new=True, local_kind="qec", should_cancel=cancel,
    )
    assert first.cancelled
    assert first.files_archived == 1
    assert first.files_parsed == 0
    assert len(source.list_artifacts()) == 1
    next_run = LocalBatchImporter(source).import_paths(
        paths, only_new=True, local_kind="qec",
    )
    assert next_run.files_parsed == 3
    assert not next_run.cancelled


def test_unrecognized_qec_keeps_failed_parser_checkpoint_for_resume(tmp_path):
    source = service_for(tmp_path)
    path = tmp_path / "qec" / FIN / "ref_123456" / "qec.json"
    path.parent.mkdir(parents=True)
    path.write_text('{"schema_version": 999}', encoding="utf-8")
    first = LocalBatchImporter(source).import_paths(
        [path], only_new=True, local_kind="qec",
    )
    assert first.files_failed == 1
    artifact = source.list_artifacts()[0]
    runs = source.store.load_parse_runs(artifact.sha256)
    assert runs[-1].status == ParseStatus.FAILED
    second = LocalBatchImporter(source).import_paths(
        [path], only_new=True, local_kind="qec",
    )
    assert second.files_unchanged == 1
    assert second.files_failed == 0
