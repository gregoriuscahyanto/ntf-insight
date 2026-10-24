"""Status-Donuts, FIN-Auswahl und KI-Datenbegrenzung – nur synthetische Daten."""
from __future__ import annotations

import csv
import io
import json
import os
from types import SimpleNamespace
from zipfile import ZipFile

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QScrollArea

from ntf_insight.app.windows.main_window import MainWindow
from ntf_insight.domain.case import NTFCase
from ntf_insight.domain.vehicle import Vehicle
from ntf_insight.reporting.ki_analysepaket import export_ki_analysepaket
from ntf_insight.storage.duckdb_store import DuckDBStore
from ntf_insight.storage.workflow_source_activity import WorkflowSourceActivity
from ntf_insight.storage.workflow_ssl_selection import (
    MISSING, MULTIPLE, WorkflowSSLSelection, fin_ssl_groups,
)
from test_chatgpt_rueckimport import FIN, make_data


FIN_B = "WDD12345678901235"
FIN_C = "WDD12345678901236"


def _synthetic_rows():
    return [
        {
            "fin": FIN, "case_id": "QA-1", "reference": "11111",
            "part_number": "A 111 222", "finding": "D: Elektrischer Fehler - NTF",
            "tp_dashboard": True, "decision": "Offen", "reason": "",
            "report": False,
        },
        {
            "fin": FIN_B, "case_id": "QB-2", "reference": "22222",
            "part_number": "A 111 222", "finding": "Wassereintritt",
            "tp_dashboard": False, "decision": "Offen", "reason": "",
            "report": False,
        },
        {
            "fin": FIN_C, "case_id": "QC-3", "reference": "33333",
            "part_number": "A 111 222", "finding": "",
            "tp_dashboard": False, "decision": "Offen", "reason": "",
            "report": False,
        },
    ]


def test_ssl_selection_persists_and_handles_multiple_findings(tmp_path):
    store = DuckDBStore(tmp_path / "scope.duckdb")
    selection = WorkflowSSLSelection(store)
    rows = _synthetic_rows() + [{
        **_synthetic_rows()[1], "case_id": "QB-4", "finding": "Korrosion",
    }]
    categories = fin_ssl_groups(rows)
    assert categories[FIN_B] == MULTIPLE
    assert categories[FIN_C] == MISSING
    assert selection.selected("coolant_pump", "A111222") is None
    assert selection.allowed_fins("coolant_pump", "A111222", rows) == {
        FIN, FIN_B, FIN_C,
    }
    selection.save(
        "coolant_pump", "A 111-222",
        set(categories.values()), {"D: Elektrischer Fehler - NTF"},
    )
    reopened = WorkflowSSLSelection(store)
    assert reopened.allowed_fins("coolant_pump", "A111222", rows) == {FIN}
    assert reopened.selected("coolant_pump", "B333444") is None
    reopened.save("coolant_pump", "A111222", set(categories.values()), set())
    assert reopened.allowed_fins("coolant_pump", "A111222", rows) == set()


def test_donuts_and_stage_one_filter_only_selected_fins_downstream(
    tmp_path, monkeypatch,
):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("NTF_INSIGHT_DATA_DIR", str(tmp_path / "app-data"))
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    page = window.pages["workflow"]
    monkeypatch.setattr(page.qec_store, "rows", lambda _root: _synthetic_rows())
    monkeypatch.setattr(page.qec_store, "active_sources", lambda: [])
    page.part_number.setText("A 111 222")
    page._change_context()
    page.refresh_data()
    assert page.fin_model.rowCount() == 3
    assert page.qec_model.rowCount() == 3
    assert sum(count for _, count in page.ssl_donut.ring.values) == 3
    assert page.ssl_filter_button.menu().actions()
    assert page.cards[0].property("workflowState") == "done"
    page._select_ssl_category("Wassereintritt", False)
    page._select_ssl_category(MISSING, False)
    assert page.fin_model.rowCount() == 3  # Quelle bleibt vollständig.
    assert page.qec_model.rowCount() == 1
    assert page.ntf_model.rowCount() == 1
    assert [target.fin for target in page.qec_targets()] == [FIN]
    assert page.ssl_filter_button.text().endswith("1/3 FINs")
    assert window.pages["cases"].cluster_workspace._workflow_allowed_fins == {FIN}
    assert page.fin_model._row_states == ["info", "muted", "muted"]
    assert not hasattr(page, "previous_button")
    assert not hasattr(page, "pause_button")
    assert not hasattr(page, "next_button")
    window.close()
    app.processEvents()


def test_qec_download_donut_and_semantic_row_highlights(tmp_path, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("NTF_INSIGHT_DATA_DIR", str(tmp_path / "app-data"))
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    page = window.pages["workflow"]
    monkeypatch.setattr(page.qec_store, "rows", lambda _root: _synthetic_rows())
    monkeypatch.setattr(page.qec_store, "active_sources", lambda: [])
    from ntf_insight.app.pages import workflow_page as page_module
    monkeypatch.setattr(
        page_module, "local_qec_archive",
        lambda _root, fin, _ref:
        SimpleNamespace(date_label="20.10.2026") if fin == FIN else None,
    )
    page.part_number.setText("A111222")
    page._change_context()
    page.refresh_data()
    assert dict(page.qec_donut.ring.values) == {
        "Alle Berichte vorhanden": 1,
        "Teilweise vorhanden": 0,
        "Noch kein Bericht": 2,
    }
    from PySide6.QtGui import QBrush
    for row in range(3):
        brush = page.qec_model.data(
            page.qec_model.index(row, 0),
            Qt.ItemDataRole.BackgroundRole,
        )
        assert isinstance(brush, QBrush)
    assert page.qec_model._row_states == ["warning", "muted", "muted"]
    assert page.qec_model.rows[0][-1] == "Ausstehend"
    page._chatgpt_by_case = {
        "QA-1": {"bewertung": {
            "ntf_bewertung": "NTF plausibel",
            "verursachungsbereich": "Steuergerät",
        }, "review_status": "Offen"},
        "QB-2": {"bewertung": {
            "ntf_bewertung": "NTF fraglich",
            "verursachungsbereich": "Lieferant? (nicht belegt)",
        }, "review_status": "Offen"},
        "QC-3": {"bewertung": {
            "ntf_bewertung": "Kein reiner NTF",
            "verursachungsbereich": "Nicht zuordenbar",
        }, "review_status": "Offen"},
    }
    page.refresh()
    assert dict(page.ntf_donut.ring.values)["NTF plausibel"] == 1
    assert dict(page.ntf_donut.ring.values)["NTF fraglich"] == 1
    assert dict(page.ntf_donut.ring.values)["Kein reiner NTF"] == 1
    assert page.ntf_model._row_states == ["success", "warning", "error"]
    assert len(page.ntf_model.rows[0]) == 7  # Ursache als eigene Spalte.
    window.close()
    app.processEvents()


def test_source_activity_distinguishes_download_from_manual_import(tmp_path, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("NTF_INSIGHT_DATA_DIR", str(tmp_path / "app-data"))
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    page = window.pages["workflow"]
    store = WorkflowSourceActivity(page.progress_store.store)
    store.record("coolant_pump", "A111222", "diagnosis_viewer", "Abgeschlossen")
    store.record("coolant_pump", "A111222", "tp_dashboard", "Eingelesen")
    page.part_number.setText("A111222")
    page._change_context()
    assert "Abruf:" in page.context_source_dates["diagnosis_viewer"].text()
    assert "Einlesen:" in page.context_source_dates["tp_dashboard"].text()
    assert "CSV-Dateien" in page.context_counts["tp_dashboard"].text()
    assert "Einlesen:" in page.context_source_dates["tp_dashboard"].text()
    assert "selected" not in page.context_scraper_buttons["diagnosis_viewer"]
    assert page.context_scraper_buttons["tp_dashboard"]["parse"].text() == "Einlesen …"
    assert page.context_scraper_buttons["celonis"]["parse"].text() == "Einlesen (Archiv)"
    assert not hasattr(page, "context_self_import_button")
    assert page.cluster_tabs.count() == 2
    assert page.cluster_tabs.tabText(1).startswith("ChatGPT")
    assert isinstance(page.local_cluster_scroll, QScrollArea)
    assert window.pages["cases"].cluster_workspace._embedded_scroll is None
    assert window.pages["cases"].cluster_workspace._embedded_content is not None
    assert page.ai_export_button.minimumHeight() >= 52
    assert page.cluster_export_button.minimumHeight() >= 52
    window.close()
    app.processEvents()


def test_first_chatgpt_package_is_restricted_to_selected_fins(tmp_path):
    data_root = tmp_path / "data"
    data_root.mkdir()
    source = make_data(data_root, qec=False)
    source.store.save_case(NTFCase(
        case_id="EXCLUDED-CASE-002",
        vehicle=Vehicle(vin=FIN_B, model_series="214"),
        component_type="Kühlmittelpumpe",
        component_profile_id="coolant_pump",
        qec_reference="22222",
        qec_part_number="B-OTHER",
    ))
    zipped = export_ki_analysepaket(
        source, tmp_path / "only-picked.zip", selected_fins={FIN},
    )
    with ZipFile(zipped.pfad) as archive:
        cases = list(csv.DictReader(io.StringIO(
            archive.read("faelle.csv").decode("utf-8-sig")
        )))
        manifest = json.loads(archive.read("manifest.json"))
        assert len(cases) == 1
        assert manifest["ssl_fin_filter_aktiv"] is True
        assert manifest["fin_filter_anzahl"] == 1
    mapping = zipped.private_zuordnung.read_text(encoding="utf-8-sig")
    assert FIN in mapping
    assert FIN_B not in mapping
    with pytest.raises(ValueError, match="Keine FINs"):
        export_ki_analysepaket(
            source, tmp_path / "empty.zip", selected_fins=set(),
        )



def test_ssl_filtered_opt_in_qec_originals_keep_only_chosen_fin(tmp_path):
    root = tmp_path / "evidence"
    root.mkdir()
    source = make_data(root, qec=True)
    source.store.save_case(NTFCase(
        case_id="OTHER-QEC-FALL-2",
        vehicle=Vehicle(vin=FIN_B, model_series="214"),
        component_type="Kühlmittelpumpe",
        component_profile_id="coolant_pump",
        qec_reference="22222",
        qec_part_number="B-OTHER",
    ))
    result = export_ki_analysepaket(
        source, tmp_path / "selected_with_originals.zip",
        mit_qec_originalen=True, selected_fins={FIN},
    )
    with ZipFile(result.pfad) as archive:
        names = archive.namelist()
        reports = [item for item in names if item.endswith("/qec.json")]
        assert len(reports) == 1
        assert FIN.encode("ascii") in archive.read(reports[0])
        assert FIN_B.encode("ascii") not in archive.read(reports[0])
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["ssl_fin_filter_aktiv"] is True
