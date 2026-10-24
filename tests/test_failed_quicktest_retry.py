"""Gezielter Fehler-Reimport: ausschliesslich synthetische QuickTest-Dateien.

Keine echten Fahrzeugdaten und kein Zugriff auf heruntergeladene Bestands-PDFs.
"""
from __future__ import annotations

import io
from datetime import datetime, timedelta, timezone
from pathlib import Path

from reportlab.pdfgen import canvas

from ntf_insight.ingestion.artifacts import ParseRun, ParseStatus, SourceType
from ntf_insight.ingestion.batch_import import LocalBatchImporter
from ntf_insight.ingestion.failed_quicktests import find_failed_quicktest_artifacts
from ntf_insight.ingestion.real_source_parsers import QuickTestPdfParser
from ntf_insight.ingestion.service import SourceImportService
from ntf_insight.storage.quicktest_store import QuickTestStore


FIN = "W1TTEST0000000001"


def _pdf(*, second: int = 0) -> bytes:
    output = io.BytesIO()
    writer = canvas.Canvas(output)
    rows = [
        f"FIN {FIN}",
        "VIN W1TTEST0000000002",
        "DISTANCE 12345 km",
        f"DIAG START 2026-01-03 10:12:{second:02d}",
        "VERSION 1",
        "LANGUAGE en",
        "SOURCE TD",
        "QuickTest 1",
        "ECU Count 1",
        "ECUS (1)",
        "CPC3-N127 - Controller",
        "Diagnostics ID 00AB13 ECU Variant CPC3_TEST",
        "Hardware", "Partnumber", "001 002 003 Hardware",
        "Version", "23/15 000",
        "Supplier Example Software",
        "Version", "25/04 002",
        "FAULT CODES (0)", "No fault codes",
    ]
    for i, row in enumerate(rows):
        writer.drawString(35, 790 - 20 * i, row)
    writer.save()
    return output.getvalue()


def _source(tmp_path):
    return SourceImportService(tmp_path / "raw", tmp_path / "ntf.duckdb")


def _artifact(sources, tmp_path, name, payload, kind=SourceType.SHORT_TEST):
    path = tmp_path / "quicktests" / FIN / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return sources.import_raw(path, kind)


def _run(sources, artifact, status, *, version="2.0.0", seconds=0, parser="quicktest_pdf"):
    t = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=seconds)
    sources.store.save_parse_run(ParseRun(
        artifact_sha256=artifact.sha256,
        parser_name=parser,
        parser_version=version,
        status=status,
        started_at=t,
        completed_at=t,
    ))


def _persist(sources, artifact):
    parsed = QuickTestPdfParser(artifact.sha256).parse(Path(artifact.archived_path))
    QuickTestStore(sources.store).save_report(parsed.quicktest_report, artifact.sha256)


def test_auswahl_nur_bisherige_fehlversuche_ohne_download_scan(tmp_path, monkeypatch):
    sources = _source(tmp_path)
    good = _artifact(sources, tmp_path, "erfolgreich_v2.pdf", _pdf(second=1))
    _persist(sources, good)
    _run(sources, good, ParseStatus.SUCCESS)

    failed = _artifact(
        sources, tmp_path, "fehlgeschlagen.pdf", _pdf(second=2), SourceType.OTHER
    )
    _run(sources, failed, ParseStatus.FAILED)
    never = _artifact(sources, tmp_path, "niemals_importiert.pdf", _pdf(second=3))
    partial = _artifact(sources, tmp_path, "teilweise.pdf", _pdf(second=4))
    _persist(sources, partial)
    _run(sources, partial, ParseStatus.PARTIAL)
    missing = _artifact(sources, tmp_path, "nicht_gespeichert.pdf", _pdf(second=5))
    _run(sources, missing, ParseStatus.SUCCESS)

    other_source = tmp_path / "fremd.txt"
    other_source.write_text("keine Diagnose")
    unrelated = sources.import_raw(other_source, SourceType.OTHER)
    _run(sources, unrelated, ParseStatus.FAILED)

    def unexpected_scan(*_args, **_kwargs):
        raise AssertionError("Heruntergeladene QuickTests duerfen nicht durchsucht werden")

    monkeypatch.setattr(
        "ntf_insight.ingestion.downloaded_quicktests.list_downloaded_quicktests",
        unexpected_scan,
    )
    selected = find_failed_quicktest_artifacts(sources)
    assert {a.sha256 for a in selected} == {
        failed.sha256, partial.sha256, missing.sha256,
    }
    assert good.sha256 not in {a.sha256 for a in selected}
    assert never.sha256 not in {a.sha256 for a in selected}


def test_nur_fehlerhafte_wiederholen_erhaelt_v2_erfolge(tmp_path, monkeypatch):
    sources = _source(tmp_path)
    ok = _artifact(sources, tmp_path, "ok_v2.pdf", _pdf(second=1))
    failed = _artifact(
        sources, tmp_path, "fehlgeschlagen_v2.pdf", _pdf(second=2), SourceType.OTHER
    )
    _persist(sources, ok)
    _run(sources, ok, ParseStatus.SUCCESS)
    _run(sources, failed, ParseStatus.FAILED)
    seen = []
    original_parse = QuickTestPdfParser.parse

    def recording_parser(self, path):
        seen.append(Path(path))
        return original_parse(self, path)

    monkeypatch.setattr(QuickTestPdfParser, "parse", recording_parser)
    result = LocalBatchImporter(sources).retry_failed_quicktests()

    assert result.selected_failed_quicktests == 1
    assert result.files_parsed == 1
    assert result.files_failed == 0
    assert result.quicktests_saved == 1
    assert seen == [Path(failed.archived_path)]
    assert {run.parser_version for run in sources.store.load_parse_runs(ok.sha256)} == {
        "2.0.0"
    }
    assert not find_failed_quicktest_artifacts(sources)

    again = LocalBatchImporter(sources).retry_failed_quicktests()
    assert again.selected_failed_quicktests == 0
    assert again.files_parsed == 0
    assert len(seen) == 1
    assert len(QuickTestStore(sources.store).list_reports(FIN)) == 2


def test_bekannt_fehlerhafte_koennen_mit_gleicher_version_nochmal_versucht_werden(tmp_path):
    sources = _source(tmp_path)
    bad = _artifact(sources, tmp_path, "kaputt.pdf", b"KEINE PDF")
    _run(sources, bad, ParseStatus.FAILED)
    importer = LocalBatchImporter(sources)

    first = importer.retry_failed_quicktests()
    assert first.selected_failed_quicktests == 1
    assert first.files_failed == 1
    assert first.files_parsed == 0
    second = importer.retry_failed_quicktests()
    assert second.selected_failed_quicktests == 1
    assert second.files_failed == 1
    assert len(sources.store.load_parse_runs(bad.sha256)) == 3
    assert all(run.status == ParseStatus.FAILED
               for run in sources.store.load_parse_runs(bad.sha256))


def test_bereits_persistierte_erfolge_werden_nicht_wegen_neuer_version_reparsed(tmp_path):
    sources = _source(tmp_path)
    ok = _artifact(sources, tmp_path, "v2_erfolg.pdf", _pdf(second=1))
    _persist(sources, ok)
    _run(sources, ok, ParseStatus.SUCCESS, version="2.0.0")
    # Even a later broken attempt must not discard the proven v2 import.
    _run(sources, ok, ParseStatus.FAILED, version="3.0.0", seconds=1)
    assert find_failed_quicktest_artifacts(sources) == []


def test_abweichende_archivpruefsumme_wird_abgewiesen(tmp_path):
    sources = _source(tmp_path)
    bad = _artifact(sources, tmp_path, "manipuliert.pdf", _pdf(second=1))
    _run(sources, bad, ParseStatus.FAILED)
    Path(bad.archived_path).write_bytes(_pdf(second=2))
    result = LocalBatchImporter(sources).retry_failed_quicktests()
    assert result.selected_failed_quicktests == 1
    assert result.files_failed == 1
    assert result.files_parsed == 0
    assert not QuickTestStore(sources.store).list_reports()
    assert len(sources.store.load_parse_runs(bad.sha256)) == 1
    assert "SHA-256" in result.issues[0]


def test_fehler_reimport_abbruch_und_fortsetzung(tmp_path):
    sources = _source(tmp_path)
    for ix in (1, 2, 3):
        bad = _artifact(sources, tmp_path, f"fehler_{ix}.pdf", _pdf(second=ix))
        _run(sources, bad, ParseStatus.FAILED)
    cancelled = LocalBatchImporter(sources).retry_failed_quicktests(
        should_cancel=lambda: True,
    )
    assert cancelled.cancelled
    assert cancelled.files_parsed == 0
    assert len(find_failed_quicktest_artifacts(sources)) == 3
    finished = LocalBatchImporter(sources).retry_failed_quicktests()
    assert finished.selected_failed_quicktests == 3
    assert finished.files_parsed == 3
    assert not find_failed_quicktest_artifacts(sources)
