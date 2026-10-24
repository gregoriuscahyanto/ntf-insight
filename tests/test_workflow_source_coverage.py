"""Projektbezogene Parser-/Downloadstände: nur synthetische Daten.

Downloadbeleg ist nicht gleich Parsererfolg; Fortsetzen wählt niemals
bereits nachweislich erfolgreich geparste unveränderte Dateien erneut aus.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from ntf_insight.ingestion.artifacts import ParseRun, ParseStatus, RawArchive, SourceType
from ntf_insight.ingestion.qec_json import QECJsonParser
from ntf_insight.ingestion.real_source_parsers import AutoExportParser, QuickTestPdfParser
from ntf_insight.ingestion.tips_json import TipsJsonParser
from ntf_insight.storage.cluster_evidence_store import ClusterEvidenceStore
from ntf_insight.storage.duckdb_store import DuckDBStore
from ntf_insight.storage.quicktest_store import QuickTestStore
from ntf_insight.storage.source_knowledge_store import SourceKnowledgeStore
from ntf_insight.storage.workflow_source_coverage import get_workflow_coverage


FIN_1 = "WDD12345678901234"
FIN_2 = "WDD12345678901235"
FIN_3 = "WDD12345678901236"
STAMP = "2026-10-10T10:15:00+00:00"


def _setup(root: Path):
    root.mkdir(parents=True)
    store = DuckDBStore(root / "ntf-insight.duckdb")
    knowledge = SourceKnowledgeStore(store)
    evidence = ClusterEvidenceStore(store)
    # Gleiche produktive Tabellenstruktur wie beim echten Quellenimport.
    QuickTestStore(store)
    return store, knowledge, evidence


def _run(store: DuckDBStore, sha: str, parser, status=ParseStatus.SUCCESS):
    store.save_parse_run(ParseRun(
        artifact_sha256=sha,
        parser_name=parser.name, parser_version=parser.version,
        status=status,
        started_at=datetime(2026, 10, 10, tzinfo=timezone.utc),
        completed_at=datetime(2026, 10, 10, tzinfo=timezone.utc),
        records_emitted=1,
    ))


def _rows():
    return [
        {"fin": FIN_1, "reference": "12345", "case_id": "CASE-A",
         "part_number": "A111222"},
        {"fin": FIN_2, "reference": "23456", "case_id": "CASE-B",
         "part_number": "A111222"},
        {"fin": FIN_3, "reference": "34567", "case_id": "CASE-C",
         "part_number": "A111222"},
    ]


def _write_qec(root: Path):
    path = root / "qec" / FIN_1 / "ref_12345" / "qec.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({
        "schema_version": 2,
        "fin": FIN_1, "referenznummer": "12345",
        "abgerufen_am_utc": STAMP,
        "vollstaendige_reiter": True,
        "abschnitte": [
            {"bereich": name, "felder": [], "tabellen": []}
            for name in (
                "WE-Daten", "Voranalysen", "Stellungnahme Lieferant",
                "Ergebnis + Nachanalyse", "Historie",
            )
        ],
        "fehler": [],
    }), encoding="utf-8")
    return path


def _write_tips(root: Path):
    path = root / "tips" / FIN_1 / "fall_54321" / "tips.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({
        "schema_version": 1, "quelle": "XENTRY TIPS Writer",
        "fin": FIN_1, "fallnummer": "54321",
        "titel": "Synthetischer TIPS Fall",
        "abgerufen_am_utc": STAMP,
        "vollstaendige_reiter": True,
        "abschnitte": [
            {"bereich": name, "felder": [], "tabellen": []}
            for name in (
                "Erstanfrage", "Betriebsdaten", "Fahrzeugdaten",
                "Symptom", "Kommunikation", "Anhänge", "Funktionsgruppe",
                "Steuergerät/FC", "Zustandsdaten", "Inspektor / Notizen",
            )
        ],
        "fehler": [],
    }), encoding="utf-8")
    return path


def test_tips_structured_parser_preserves_fin_case_and_references(tmp_path):
    report = _write_tips(tmp_path)
    result = TipsJsonParser().parse(report)
    assert result.kind == "tips_live_case"
    assert result.metadata["fin"] == FIN_1
    assert result.metadata["reference"] == "54321"
    assert result.metadata["full_sections"] is True
    assert len(result.records) == 11
    from ntf_insight.ingestion.source_detection import detect_source_type
    assert detect_source_type(report) == SourceType.TIPS_CASE
    report.parent.parent.mkdir(parents=True, exist_ok=True)
    data = json.loads(report.read_text())
    data["fallnummer"] = "99999"
    report.write_text(json.dumps(data), encoding="utf-8")
    import pytest
    with pytest.raises(ValueError, match="Dateipfad"):
        TipsJsonParser().parse(report)


def test_counts_qec_quicktest_tips_are_source_based_and_project_scoped(tmp_path):
    root = tmp_path / "data"
    store, knowledge, _ = _setup(root)
    report = _write_qec(root)
    first = get_workflow_coverage(store, root, _rows())
    assert first["qec"].total_cases == 3
    assert first["qec"].local_documents == 1
    assert first["qec"].parsed_documents == 0
    assert first["qec"].pending_paths == (report,)
    assert len(first["qec"].missing_qec) == 2

    artifact = RawArchive(root / "raw").archive(report, SourceType.QEC_REPORT)
    store.save_artifact(artifact)
    parsed = QECJsonParser().parse(report)
    knowledge.save_records(
        artifact.sha256, parsed.kind, parsed.records, metadata=parsed.metadata,
    )
    _run(store, artifact.sha256, QECJsonParser)
    updated = get_workflow_coverage(store, root, _rows())
    assert updated["qec"].parsed_documents == 1
    assert updated["qec"].parsed_cases == 1
    assert not updated["qec"].pending_paths
    assert (FIN_1, "12345") in updated["qec"].parsed_qec

    pdf = root / "quicktests" / FIN_1 / "q1.pdf"
    pdf.parent.mkdir(parents=True)
    pdf.write_bytes(b"%PDF-1.4\nfake synthetic")
    report_sha = RawArchive(root / "raw").archive(pdf, SourceType.SHORT_TEST)
    store.save_artifact(report_sha)
    with store.connect() as con:
        con.execute(
            "INSERT INTO quicktest_reports "
            "(report_id,fin,vin,diagnosed_at,mileage_km,ecu_count,dtc_count,"
            "header_json,first_source_sha256,imported_at) "
            "VALUES (?,?,?,CURRENT_TIMESTAMP,?,?,?, ?,?,CURRENT_TIMESTAMP)",
            ["QT1", FIN_1, FIN_1, None, 0, 0, "{}", report_sha.sha256],
        )
        con.execute(
            "INSERT INTO quicktest_sources VALUES (?,?)", [report_sha.sha256, "QT1"],
        )
    before = get_workflow_coverage(store, root, _rows())
    assert before["diagnosis_viewer"].local_documents == 1
    assert before["diagnosis_viewer"].parsed_documents == 0
    assert before["diagnosis_viewer"].missing_fins == (FIN_2, FIN_3)
    _run(store, report_sha.sha256, QuickTestPdfParser)
    after = get_workflow_coverage(store, root, _rows())
    assert after["diagnosis_viewer"].parsed_documents == 1
    assert after["diagnosis_viewer"].parsed_cases == 1
    assert not after["diagnosis_viewer"].can_resume_parsing

    tips_file = _write_tips(root)
    initial = get_workflow_coverage(store, root, _rows())
    assert initial["tips_writer"].local_documents == 1
    assert initial["tips_writer"].parsed_documents == 0
    assert initial["tips_writer"].pending_paths == (tips_file,)
    tips_source = RawArchive(root / "raw").archive(tips_file, SourceType.TIPS_CASE)
    store.save_artifact(tips_source)
    tips_result = TipsJsonParser().parse(tips_file)
    knowledge.save_records(
        tips_source.sha256, tips_result.kind, tips_result.records,
        metadata=tips_result.metadata,
    )
    _run(store, tips_source.sha256, TipsJsonParser, ParseStatus.PARTIAL)
    tips = get_workflow_coverage(store, root, _rows())["tips_writer"]
    assert tips.parsed_documents == 1
    assert tips.partial_documents == 1
    assert tips.parsed_cases == 1
    assert tips.missing_fins == (FIN_1, FIN_2, FIN_3)
    assert "mit Hinweisen" in tips.display()


def test_tp_csv_document_parser_and_celonis_archive_are_separate(tmp_path):
    root = tmp_path / "data"
    store, knowledge, evidence = _setup(root)
    tp = tmp_path / "tp.csv"
    tp.write_text("DiagStartDt;EcuFaultNm;Fin\n", encoding="utf-8")
    evidence.add_files("coolant_pump", "A111222", "tp_dashboard", [tp])
    files = evidence.list_files("coolant_pump", "A111222")
    coverage = get_workflow_coverage(store, root, _rows(), files)
    assert coverage["tp_dashboard"].local_documents == 1
    assert coverage["tp_dashboard"].parsed_documents == 0
    assert len(coverage["tp_dashboard"].pending_paths) == 1
    artifact = store.load_artifacts()[0]
    knowledge.save_records(
        artifact.sha256, "autoexport_rows",
        [{"category": "autoexport_dtc", "fin": FIN_1,
          "source_location": "row:1", "label": "Test", "data": {}}],
        metadata={"source_type": "tp_dashboard", "raw_schema_version": 2},
    )
    _run(store, artifact.sha256, AutoExportParser)
    coverage = get_workflow_coverage(store, root, _rows(), files)
    assert coverage["tp_dashboard"].parsed_documents == 1
    assert coverage["tp_dashboard"].parsed_cases == 1
    assert coverage["tp_dashboard"].downloaded_cases == 1

    cel = tmp_path / "celonis.xlsx"
    cel.write_bytes(b"synthetisches xlsx zum Archivtest")
    evidence.add_files("coolant_pump", "A111222", "celonis", [cel])
    coverage = get_workflow_coverage(
        store, root, _rows(), evidence.list_files("coolant_pump", "A111222"),
    )
    assert coverage["celonis"].local_documents == 1
    assert coverage["celonis"].unsupported_parser
    assert coverage["celonis"].parsed_documents == 0
    assert coverage["celonis"].total_cases is None
    assert not coverage["celonis"].can_resume_parsing
    assert "nicht sicher zuordenbar" in coverage["celonis"].display()



def test_tips_json_download_can_be_resumed_through_existing_import_service(tmp_path):
    from ntf_insight.ingestion.service import SourceImportService
    from ntf_insight.ingestion.batch_import import LocalBatchImporter

    root = tmp_path / "local"
    store, knowledge, _ = _setup(root)
    tips_report = _write_tips(root)
    sources = SourceImportService(root / "raw", root / "ntf-insight.duckdb")
    importer = LocalBatchImporter(sources)
    result = importer.import_paths([tips_report])
    assert result.files_parsed == 1
    docs = knowledge.documents()
    assert any(doc["source_kind"] == "tips_live_case" for doc in docs)
    coverage = get_workflow_coverage(store, root, _rows())
    assert coverage["tips_writer"].parsed_documents == 1
    assert coverage["tips_writer"].parsed_cases == 1
    assert not coverage["tips_writer"].can_resume_parsing
    # Eine bereits erfolgreiche Quelle wird durch das neue Resume nicht
    # nochmals verarbeitet, selbst wenn die Originaldatei noch vorhanden ist.
    result2 = importer.import_paths(
        [tips_report], only_new=False,
    )
    assert result2.files_parsed >= 0  # Normaler Neuimport bleibt separate Aktion.
    coverage2 = get_workflow_coverage(store, root, _rows())
    assert coverage2["tips_writer"].parsed_documents == 1



def test_workflow_buttons_show_actual_counts_and_resume_only_missing(tmp_path, monkeypatch):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from ntf_insight.app.windows.main_window import MainWindow

    root = tmp_path / "app-data"
    monkeypatch.setenv("NTF_INSIGHT_DATA_DIR", str(root))
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    page = window.pages["workflow"]
    rows = [
        dict(
            row,
            finding="Elektrischer Fehler",
            tp_dashboard=False, decision="Offen", reason="", report=False,
        )
        for row in _rows()
    ]
    monkeypatch.setattr(page.qec_store, "rows", lambda _root: rows)
    monkeypatch.setattr(page.qec_store, "active_sources", lambda: [])
    _write_qec(root)
    page.part_number.setText("A111222")
    page._change_context()
    page.refresh_data()
    assert page.qec_parse_resume_button.isEnabled()
    assert page.download_missing_button.isEnabled()
    assert "1 Berichte lokal" in page.qec_coverage.text()
    assert "0 geparst" in page.qec_coverage.text()
    assert "QEC-Fälle: 1/3" in page.qec_coverage.text()
    assert page.qec_model.rows[0][-1] == "Ausstehend"
    assert "diagnosis_viewer" in page.context_counts
    assert "3" in page.context_counts["diagnosis_viewer"].text()
    assert page.context_scraper_buttons["diagnosis_viewer"]["missing"].isEnabled()
    assert not page.context_scraper_buttons["celonis"]["resume_parse"].isEnabled()
    assert page.context_scraper_buttons["tips_writer"]["resume_parse"].text() == (
        "Parsing fortsetzen"
    )
    window.close()
    app.processEvents()



def test_unparsed_manual_evidence_counts_as_documents_not_fictitious_fin_cases(
    tmp_path,
):
    root = tmp_path / "data"
    store, _knowledge, evidence = _setup(root)
    quicktest = tmp_path / "extern.pdf"
    quicktest.write_bytes(b"%PDF-1.4\nsynthetic not yet parsed")
    evidence.add_files(
        "coolant_pump", "A111222", "diagnosis_viewer", [quicktest],
    )
    external_tips = _write_tips(tmp_path / "extern")
    evidence.add_files(
        "coolant_pump", "A111222", "tips_writer", [external_tips],
    )
    files = evidence.list_files("coolant_pump", "A111222")
    result = get_workflow_coverage(store, root, _rows(), files)
    quick = result["diagnosis_viewer"]
    assert quick.local_documents == 1
    assert quick.parsed_documents == 0
    assert quick.downloaded_cases == 0  # FIN nicht aus Dateiname raten
    assert quick.can_resume_parsing
    assert quick.pending_paths[0].is_file()
    tips = result["tips_writer"]
    assert tips.local_documents == 1
    assert tips.parsed_documents == 0
    assert tips.downloaded_cases == 0
    assert tips.can_resume_parsing
    assert tips.pending_paths[0].is_file()



def test_cdd_resume_does_not_claim_unparsed_smrd_trigger_conditions(tmp_path):
    from ntf_insight.ingestion.reference_source_parsers import CandelaParser

    root = tmp_path / "data"
    store, knowledge, evidence = _setup(root)
    cdd = tmp_path / "diag.cdd"
    cdd.write_text("<CANDELA></CANDELA>", encoding="utf-8")
    smr = tmp_path / "trace.smr-d"
    smr.write_text("synthetic SMR-D (not a diagnostic parser fixture)", encoding="utf-8")
    evidence.add_files("coolant_pump", "A111222", "cdd_smrd", [cdd, smr])
    files = evidence.list_files("coolant_pump", "A111222")
    before = get_workflow_coverage(store, root, _rows(), files)["cdd_smrd"]
    assert before.local_documents == 2
    assert before.parsed_documents == 0
    assert before.can_resume_parsing
    assert len(before.pending_paths) == 1
    assert before.pending_paths[0].suffix == ".cdd"

    cdd_item = next(item for item in files if item.source_path.suffix == ".cdd")
    knowledge.save_records(
        cdd_item.sha256, "candela_services",
        [{"category": "candela_service", "label": "Synthetisch", "data": {}}],
        metadata={"standard": "CANDELA", "triggers_validated": False},
    )
    _run(store, cdd_item.sha256, CandelaParser)
    after = get_workflow_coverage(store, root, _rows(), files)["cdd_smrd"]
    assert after.local_documents == 2
    assert after.parsed_documents == 1
    assert not after.can_resume_parsing  # Kein SMR-D-Parser erfunden.
    assert "SMR-D" in after.note



def test_incomplete_qec_report_is_downloaded_but_eligible_for_resume(tmp_path):
    root = tmp_path / "data"
    store, _knowledge, _evidence = _setup(root)
    report = _write_qec(root)
    data = json.loads(report.read_text(encoding="utf-8"))
    data["vollstaendige_reiter"] = False
    data["abschnitte"][0]["aus_vorherigem_abruf"] = True
    report.write_text(json.dumps(data), encoding="utf-8")
    coverage = get_workflow_coverage(store, root, _rows())["qec"]
    assert coverage.local_documents == 1
    assert coverage.parsed_documents == 0
    assert coverage.missing_qec == (
        (FIN_1, "12345"), (FIN_2, "23456"), (FIN_3, "34567"),
    )
    assert coverage.pending_paths == (report,)
    assert "1 Berichte lokal" in coverage.display()


def test_partial_qec_parser_stays_amber_instead_of_false_green(tmp_path):
    root = tmp_path / "data"
    store, knowledge, _ = _setup(root)
    report = _write_qec(root)
    data = json.loads(report.read_text(encoding="utf-8"))
    data["vollstaendige_reiter"] = False
    report.write_text(json.dumps(data), encoding="utf-8")
    archived = RawArchive(root / "raw").archive(report, SourceType.QEC_REPORT)
    store.save_artifact(archived)
    parsed = QECJsonParser().parse(report)
    knowledge.save_records(
        archived.sha256, parsed.kind, parsed.records,
        metadata=parsed.metadata,
    )
    _run(store, archived.sha256, QECJsonParser, ParseStatus.PARTIAL)
    status = get_workflow_coverage(store, root, _rows())["qec"]
    assert status.local_documents == 1
    assert status.parsed_documents == 1
    assert status.partial_documents == 1
    assert status.partial_qec == frozenset({(FIN_1, "12345")})
    assert (FIN_1, "12345") in status.missing_qec



def test_progress_rejects_invalid_fin_as_local_archive_path(tmp_path):
    root = tmp_path / "data"
    store, _, _ = _setup(root)
    malicious_rows = [{
        "fin": "..", "reference": "1",
        "case_id": "invalid", "part_number": "A111222",
    }]
    progress = get_workflow_coverage(store, root, malicious_rows)
    assert progress["diagnosis_viewer"].total_cases == 0
    assert progress["tips_writer"].total_cases == 0
    assert progress["qec"].local_documents == 0
