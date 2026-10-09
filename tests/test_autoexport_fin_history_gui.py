"""Offscreen regression: full VIN/FIN AutoExport history needs no QEC case."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from ntf_insight.app.windows.main_window import MainWindow
from ntf_insight.storage.duckdb_store import DuckDBStore
from ntf_insight.storage.source_knowledge_store import SourceKnowledgeStore

FIN = "W1TTEST0000000002"


def test_fin_history_is_searchable_without_qec_case_and_is_paged(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setenv("NTF_INSIGHT_DATA_DIR", str(tmp_path))
    source = SourceKnowledgeStore(DuckDBStore(tmp_path / "ntf-insight.duckdb"))

    records = [
        {
            "category": "autoexport_dtc",
            "fin": FIN,
            "reference": "P26F100",
            "label": f"2026-01-02T12:{index % 60:02d}:00Z",
            "source_location": f"csv:row:{index + 1}",
            "data": {
                "Fin": FIN,
                "DiagStartTs": f"2026-01-02T12:{index % 60:02d}:00Z",
                "EcuNm": "CPC3", "EcuFaultNm": "P26F100",
                "EcuFaultTxt": "Synthetic coolant pump DTC",
                "KmReadingNum": "12345",
            },
        } for index in range(203)
    ]
    records += [
        {
            "category": "autoexport_tips", "fin": FIN,
            "reference": "TIPS-001", "label": "2026-01-03",
            "source_location": "csv:row:204",
            "data": {
                "Fin": FIN, "CaseId": "TIPS-001", "CreationDate": "2026-01-03",
                "InitialWorkshopMessageCustomerComplaint": "Synthetic complaint",
            },
        },
        {
            "category": "autoexport_repair", "fin": FIN,
            "reference": None, "label": "2026-01-04",
            "source_location": "csv:row:205",
            "data": {
                "Fin": FIN, "RepairDt": "2026-01-04",
                "RepairTypeNmGerman": "Synthetic workshop repair",
            },
        },
    ]
    assert source.save_records(
        "c" * 64, "autoexport_rows", records
    ) == 205

    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    cases = window.pages["cases"]
    assert cases.selector.count() == 0
    assert cases.autoexport_history_model.rowCount() == 0
    cases.autoexport_fin_lookup.setText(FIN)
    cases.autoexport_history_button.click()

    assert cases.autoexport_history_model.rowCount() == 200
    assert "203 historische DTC-Rohzeilen" in cases.autoexport_history_note.text()
    assert "1 TIPS-Vorgänge" in cases.autoexport_history_note.text()
    assert cases.autoexport_history_more.isEnabled()

    cases.autoexport_history_more.click()
    assert cases.autoexport_history_model.rowCount() == 205
    assert not cases.autoexport_history_more.isEnabled()
    assert "205 / 205 Rohzeilen" in cases.autoexport_history_count.text()
    assert window.pages["cases"].real_cases == []  # no fabricated NTF cases

    cases.autoexport_fin_lookup.setText("invalid FIN")
    cases.autoexport_history_button.click()
    assert cases.autoexport_history_model.rowCount() == 0
    assert "gültige 17-stellige FIN" in cases.autoexport_history_note.text()

    window.close()
    app.processEvents()
