"""GUI regression for source-specific swap dates and audited human confirmation."""
from __future__ import annotations

import os
from datetime import datetime

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox

from ntf_insight.app.windows.main_window import MainWindow
from ntf_insight.domain.case import NTFCase
from ntf_insight.domain.events import PartReplacement
from ntf_insight.domain.manual import ManualAction
from ntf_insight.domain.vehicle import Vehicle
from ntf_insight.storage.duckdb_store import DuckDBStore
from ntf_insight.storage.source_knowledge_store import SourceKnowledgeStore


FIN = "W1TTEST0000000001"


def test_gui_displays_both_dates_km_axis_and_audited_confirmation(tmp_path, monkeypatch):
    data_dir = tmp_path / "ntf"
    monkeypatch.setenv("NTF_INSIGHT_DATA_DIR", str(data_dir))
    app = QApplication.instance() or QApplication([])
    store = DuckDBStore(data_dir / "ntf-insight.duckdb")
    replacement = PartReplacement(
        vin=FIN, component_type="Coolant Pump",
        occurred_at=datetime(2026, 1, 12, 12),
        time_precision="date", mileage_km=12000,
        old_part_number="A 000 123",
        source_ref="raw:" + "a" * 64 + "#Schadteile QEC!2",
    )
    case = NTFCase(
        case_id="QEC-TEST",
        vehicle=Vehicle(vin=FIN),
        component_type="Coolant Pump",
        replacements=[replacement],
        investigated_replacement_id=replacement.event_id,
        qec_part_number="A000123",
    )
    store.save_case(case)
    knowledge = SourceKnowledgeStore(store)
    knowledge.save_records(
        "b" * 64,
        "autoexport_rows",
        [{
            "category": "autoexport_repair",
            "source_location": "csv:row:10",
            "fin": FIN,
            "data": {
                "Fin": FIN, "RepairDt": "2026-01-17",
                "KmReadingNum": "12000",
                "PartLetterCd": "A000123",
                "RepairTypeNmGerman": "Rep. mit Teilen",
            },
        }],
    )

    window = MainWindow()
    page = window.pages["cases"]
    assert page.replacement_value.text() == "12.01.2026"
    assert "17.01.2026" in page.autoexport_date_value.text()
    assert "5 Tage" in page.date_match_value.text()
    assert "QEC" in page.effective_swap_value.text()
    assert page.confirm_swap_button.isEnabled()
    kinds = {event.kind for event in page.time_plot._entries}
    assert "replacement" in kinds
    assert "replacement_candidate" in kinds
    assert page.axis_selector.currentData() == "date"
    page.axis_selector.setCurrentIndex(1)
    assert page.time_plot.axis_mode == "mileage"
    page.time_filter.setText("CPC3")
    assert any(
        event.kind == "replacement_candidate"
        for event in page.time_plot._visible_entries()
    )

    monkeypatch.setattr(
        QMessageBox, "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )
    page._confirm_autoexport_swap()
    app.processEvents()

    checked = store.get_case("QEC-TEST")
    assert checked is not None
    assert len(checked.replacements) == 2
    assert checked.investigated_replacement().occurred_at.date().isoformat() == "2026-01-17"
    assert checked.investigated_replacement().confirmed_from_autoexport
    assert any(
        event.occurred_at.date().isoformat() == "2026-01-12"
        for event in checked.replacements
    )
    assert store.load_manual_changes("QEC-TEST")[-1].action == ManualAction.ADD_EVENT

    page = window.pages["cases"]
    assert page.replacement_value.text() == "12.01.2026"
    assert "17.01.2026" in page.autoexport_date_value.text()
    assert "17.01.2026" in page.effective_swap_value.text()
    assert not page.confirm_swap_button.isEnabled()
    window.close()
    app.processEvents()
