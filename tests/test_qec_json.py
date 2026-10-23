"""Synthetische QEC-Fälle – keine echten FINs, Berichtsdaten oder Anhänge."""
from __future__ import annotations

import json

import pytest

from ntf_insight.ingestion.artifacts import SourceType
from ntf_insight.ingestion.qec_json import (
    QECJsonParser, QEC_SECTIONS, list_downloaded_qec_reports,
)
from ntf_insight.ingestion.source_detection import detect_source_type


FIN = "WDB12345678901234"


def report(*, full=True):
    return {
        "schema_version": 2,
        "fin": FIN,
        "referenznummer": "123456",
        "sachnummer": "A1234567890",
        "bezeichnung": "Kühlmittelpumpe",
        "abgerufen_am_utc": "2026-10-20T12:00:00+00:00",
        "vollstaendige_reiter": full,
        "abschnitte": [
            {
                "bereich": section,
                "fin": FIN,
                "referenznummer": "123456",
                "zeitpunkt_utc": "2026-10-20T12:00:00+00:00",
                "felder": [
                    {"name": "beurteilung", "typ": "text", "wert": "Keine Auffälligkeit", "beschriftung": "Befund"},
                    {"name": "auswahl", "typ": "select-one", "wert": "a", "auswahltext": "Im Labor geprüft"},
                ],
                "tabellen": [
                    {"nummer": 1, "zeilen": [
                        [{"typ": "td", "text": "Prüfstatus", "colspan": 1},
                         {"typ": "td", "text": "Offen", "colspan": 1}]
                    ]}
                ],
                "sichtbarer_text": "Darstellung des ursprünglichen Reiters",
            }
            for section in QEC_SECTIONS
        ],
        "anhaenge": [
            {"anhang_id": "12", "dateiname": "analyse.pdf", "datei": "anhaenge/12_analyse.pdf"},
        ],
        "fehler": [],
    }


def write_report(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_qec_json_strukturiert_und_anhaenge_nicht_geparst(tmp_path):
    path = write_report(tmp_path / "qec.json", report())
    result = QECJsonParser().parse(path)
    assert result.kind == "qec_live_report"
    assert result.metadata["fresh_complete"]
    assert result.metadata["sections"] == 5
    assert result.metadata["attachments"] == 1
    assert result.metadata["fields"] == 10
    assert result.metadata["table_rows"] == 5
    assert result.metadata["values"] == 15
    assert not result.issues
    assert all(row["fin"] == FIN and row["reference"] == "123456" for row in result.records)
    assert any(row["category"] == "qec_value" and row["data"]["wert"] == "Im Labor geprüft"
               for row in result.records)
    assert any(row["category"] == "qec_table_row" and row["data"]["zellen"][1]["text"] == "Offen"
               for row in result.records)
    attachments = [r for r in result.records if r["category"] == "qec_attachment"]
    assert len(attachments) == 1
    assert attachments[0]["data"]["datei"] == "anhaenge/12_analyse.pdf"
    assert not (tmp_path / "anhaenge").exists()
    assert detect_source_type(path) == SourceType.QEC_REPORT


def test_unvollstaendige_alte_reiter_bleiben_markiert(tmp_path):
    payload = report(full=False)
    payload["abschnitte"][-1]["aus_vorherigem_abruf"] = True
    payload["abschnitte"].pop(0)
    result = QECJsonParser().parse(write_report(tmp_path / "qec.json", payload))
    assert not result.metadata["fresh_complete"]
    assert result.metadata["fresh_sections"] == 3
    assert len(result.metadata["missing_sections"]) == 1
    assert any(r["data"].get("aus_vorherigem_abruf") for r in result.records)


def test_widerspruechliche_fallzuordnung_wird_abgelehnt(tmp_path):
    payload = report()
    payload["abschnitte"][0]["referenznummer"] = "9876"
    with pytest.raises(ValueError, match="FIN/Referenz"):
        QECJsonParser().parse(write_report(tmp_path / "qec.json", payload))


def test_nicht_qec_json_bleibt_sonstiges(tmp_path):
    path = write_report(tmp_path / "other.json", {"version": 1, "value": 5})
    assert detect_source_type(path) == SourceType.OTHER


def test_alte_berichte_offline_suchen_ohne_dateien_zu_lesen(tmp_path):
    path = write_report(tmp_path / "qec" / FIN / "ref_123456" / "qec.json", report())
    other = write_report(tmp_path / "qec" / "INVALID" / "ref_123456" / "qec.json", report())
    assert list_downloaded_qec_reports(tmp_path) == [path]
    assert other.exists()


def test_import_persists_qec_with_source_provenance_and_idempotence(tmp_path):
    from ntf_insight.ingestion.batch_import import LocalBatchImporter
    from ntf_insight.ingestion.service import SourceImportService
    from ntf_insight.storage.source_knowledge_store import SourceKnowledgeStore

    path = write_report(tmp_path / "qec" / FIN / "ref_123456" / "qec.json", report())
    service = SourceImportService(tmp_path / "raw", tmp_path / "local.duckdb")
    importer = LocalBatchImporter(service)
    first = importer.import_paths([path])
    assert first.files_parsed == 1
    assert first.reference_sources == 1
    assert first.cases_created == 0  # No invented QEC case from a report
    store = SourceKnowledgeStore(service.store)
    rows = store.list_rows(category="qec_value", fin=FIN)
    assert len(rows) == 15
    assert {row["reference"] for row in rows} == {"123456"}
    assert all(row["source_sha256"] for row in rows)
    assert store.documents()[0]["metadata"]["fresh_complete"]
    importer.import_paths([path])
    assert len(store.list_rows(category="qec_value", fin=FIN)) == 15


def test_strikte_fin_referenz_teilenummer_und_zeitversion(tmp_path):
    from ntf_insight.ingestion.batch_import import LocalBatchImporter
    from ntf_insight.ingestion.service import SourceImportService
    from ntf_insight.storage.source_knowledge_store import SourceKnowledgeStore

    sources = SourceImportService(tmp_path / "raw", tmp_path / "local.duckdb")
    importer = LocalBatchImporter(sources)
    first = report()
    first["abgerufen_am_utc"] = "2026-10-19T12:00:00+00:00"
    early = write_report(tmp_path / "early.json", first)
    latest = report()
    latest["abschnitte"][0]["felder"][0]["wert"] = "Prüfung abgeschlossen"
    newer = write_report(tmp_path / "newer.json", latest)
    importer.import_paths([early, newer])
    store = SourceKnowledgeStore(sources.store)
    assert store.qec_report_for_case(FIN, "999999") is None
    assert store.qec_report_for_case("WDD12345678901234", "123456") is None
    chosen = store.qec_report_for_case(FIN, "123456", part_number="A 1234567890")
    assert chosen["status"] == "Vollständig"
    assert chosen["versions"] == 2
    assert any(r["data"].get("wert") == "Prüfung abgeschlossen" for r in chosen["records"])
    assert not any(r["data"].get("wert") == "Keine Auffälligkeit"
                   for r in chosen["records"] if r["category"] == "qec_field"
                   and r["data"].get("bereich") == QEC_SECTIONS[0])
    conflict = store.qec_report_for_case(FIN, "123456", part_number="A999")
    assert conflict["status"] == "Prüfbedarf"
    assert not conflict["records"]


def test_mehrere_qec_versionen_mit_gleicher_abrufzeit_werden_nicht_vermischt(tmp_path):
    from ntf_insight.ingestion.batch_import import LocalBatchImporter
    from ntf_insight.ingestion.service import SourceImportService
    from ntf_insight.storage.source_knowledge_store import SourceKnowledgeStore

    sources = SourceImportService(tmp_path / "raw", tmp_path / "local.duckdb")
    importer = LocalBatchImporter(sources)
    one = report()
    two = report()
    two["abschnitte"][0]["felder"][0]["wert"] = "Anderer Befund"
    importer.import_paths([
        write_report(tmp_path / "a.json", one),
        write_report(tmp_path / "b.json", two),
    ])
    chosen = SourceKnowledgeStore(sources.store).qec_report_for_case(FIN, "123456")
    assert chosen["status"] == "Prüfbedarf"
    assert chosen["versions"] == 2
    assert not chosen["records"]


def test_ein_datei_transfer_enthaelt_qec_struktur_und_unveraenderte_anhaenge(tmp_path):
    from ntf_insight.ingestion.batch_import import LocalBatchImporter
    from ntf_insight.ingestion.portable_backup import (
        DATABASE_NAME, export_portable_backup, restore_portable_backup,
    )
    from ntf_insight.ingestion.service import SourceImportService
    from ntf_insight.storage.source_knowledge_store import SourceKnowledgeStore
    from zipfile import ZipFile

    origin = tmp_path / "pc-a"
    origin.mkdir()
    report_path = write_report(
        origin / "qec" / FIN / "ref_123456" / "qec.json", report()
    )
    attachment = report_path.parent / "anhaenge" / "12_analyse.pptx"
    attachment.parent.mkdir()
    attachment.write_bytes(b"SYNTHETISCHE-DATEI-KEIN-PARSER")
    sources = SourceImportService(origin / "raw", origin / DATABASE_NAME)
    LocalBatchImporter(sources).import_paths([report_path])
    package = tmp_path / "ein-datei.ntfbackup"
    export_portable_backup(origin, package)
    with ZipFile(package) as zf:
        assert f"files/qec/{FIN}/ref_123456/qec.json" in zf.namelist()
        assert f"files/qec/{FIN}/ref_123456/anhaenge/12_analyse.pptx" in zf.namelist()
    destination = tmp_path / "pc-b"
    restore_portable_backup(package, destination)
    assert (destination / report_path.relative_to(origin)).read_bytes() == report_path.read_bytes()
    assert (destination / attachment.relative_to(origin)).read_bytes() == attachment.read_bytes()
    from ntf_insight.storage.duckdb_store import DuckDBStore
    store = SourceKnowledgeStore(DuckDBStore(destination / DATABASE_NAME))
    transferred = store.qec_report_for_case(FIN, "123456")
    assert transferred["status"] == "Vollständig"
    assert any(r["category"] == "qec_field" for r in transferred["records"])
