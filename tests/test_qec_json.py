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
