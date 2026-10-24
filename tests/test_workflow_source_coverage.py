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
    with store.connect() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS quicktest_reports (
                report_id VARCHAR PRIMARY KEY, fin VARCHAR NOT NULL
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS quicktest_sources (
                artifact_sha256 VARCHAR PRIMARY KEY,report_id VARCHAR NOT NULL
            )
        """)
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
        con.execute("INSERT INTO quicktest_reports VALUES (?,?)", ["QT1", FIN_1])
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
    assert coverage["tp_dashboard"].downloaded_cases is None

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
