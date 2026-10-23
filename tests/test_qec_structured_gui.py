"""GUI-Prüfung der strukturierten QEC-Originalanzeige (nur Synthetikdaten)."""
from __future__ import annotations

import json
import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from ntf_insight.app.widgets.qec_structured_panel import QECStructuredPanel
from ntf_insight.ingestion.batch_import import LocalBatchImporter
from ntf_insight.ingestion.service import SourceImportService
from ntf_insight.storage.source_knowledge_store import SourceKnowledgeStore


FIN = "WDD12345678901234"
REF = "022301658"


def test_qec_panel_shows_only_matching_report_and_source_values(tmp_path):
    app = QApplication.instance() or QApplication([])
    payload = {
        "schema_version": 2,
        "fin": FIN,
        "referenznummer": REF,
        "sachnummer": "A001",
        "abgerufen_am_utc": "2026-10-21T08:00:00+00:00",
        "vollstaendige_reiter": False,
        "abschnitte": [{
            "bereich": "Stellungnahme Lieferant",
            "fin": FIN,
            "referenznummer": REF,
            "felder": [
                {"name": "befund", "typ": "text", "wert": "Unverändert geprüft", "beschriftung": "Originalbefund"},
            ],
            "tabellen": [{"nummer": 1, "zeilen": [
                [{"typ": "td", "text": "Schadteil"}, {"typ": "td", "text": "Kein Schaden nachgewiesen"}]
            ]}],
            "sichtbarer_text": "Synthetische Quellansicht; kein Lieferantenurteil.",
        }],
        "anhaenge": [{"anhang_id": "3", "dateiname": "anlage.pdf", "datei": "anhaenge/3_anlage.pdf"}],
    }
    path = tmp_path / "qec" / FIN / ("ref_" + REF) / "qec.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    sources = SourceImportService(tmp_path / "raw", tmp_path / "local.duckdb")
    LocalBatchImporter(sources).import_paths([path])
    panel = QECStructuredPanel(SourceKnowledgeStore(sources.store), data_dir=tmp_path)
    case = SimpleNamespace(
        vin=FIN, qec_reference=REF, qec_part_number="A001",
        diagnostics=[], investigated_replacement=lambda: None,
    )
    panel.show_case(case)
    assert "Teilweise" in panel.status.text()
    assert "Original-SHA-256" in panel.metadata.text()
    assert panel.table_model.rowCount() == 3  # field + table row + file reference
    assert any("Unverändert geprüft" in str(row) for row in panel.table_model.rows)
    assert any("3_anlage.pdf" in str(row) for row in panel.table_model.rows)

    section = panel.section_filter.findData("Stellungnahme Lieferant")
    panel.section_filter.setCurrentIndex(section)
    assert "Synthetische Quellansicht" in panel.original_text.toPlainText()
    assert panel.table_model.rowCount() == 2
    panel.text_filter.setText("Originalbefund")
    assert panel.table_model.rowCount() == 1
    panel.text_filter.clear()

    wrong = SimpleNamespace(
        vin=FIN, qec_reference="999999", qec_part_number="A001",
        diagnostics=[], investigated_replacement=lambda: None,
    )
    panel.show_case(wrong)
    assert "Nicht erfasst" in panel.status.text()
    assert panel.table_model.rowCount() == 0
    panel.close()
    app.processEvents()


def test_qec_panel_blocks_inconsistent_part_number(tmp_path):
    app = QApplication.instance() or QApplication([])
    payload = {
        "schema_version": 2, "fin": FIN, "referenznummer": REF,
        "sachnummer": "A001", "abgerufen_am_utc": "2026-10-21T08:00:00+00:00",
        "vollstaendige_reiter": False, "abschnitte": [],
    }
    path = tmp_path / "qec" / FIN / ("ref_" + REF) / "qec.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    sources = SourceImportService(tmp_path / "raw", tmp_path / "local.duckdb")
    LocalBatchImporter(sources).import_paths([path])
    panel = QECStructuredPanel(SourceKnowledgeStore(sources.store))
    case = SimpleNamespace(
        vin=FIN, qec_reference=REF, qec_part_number="A099",
        diagnostics=[], investigated_replacement=lambda: None,
    )
    panel.show_case(case)
    assert "Prüfbedarf" in panel.status.text()
    assert "Sachnummer" in panel.metadata.text()
    assert panel.table_model.rowCount() == 0
    panel.close()
    app.processEvents()
