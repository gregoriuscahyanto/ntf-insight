"""Synthetic end-to-end GUI check for HW/SW changes across two QuickTests."""
from __future__ import annotations

import io
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from reportlab.pdfgen import canvas

from ntf_insight.app.windows.main_window import MainWindow
from ntf_insight.domain.case import NTFCase
from ntf_insight.domain.vehicle import Vehicle
from ntf_insight.ingestion.batch_import import LocalBatchImporter
from ntf_insight.ingestion.service import SourceImportService
from ntf_insight.storage.quicktest_store import QuickTestStore


FIN = "W1TTEST0000000001"


def _quicktest_pdf(*, date: str, km: int, hw: str, sw: str) -> bytes:
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer)
    lines = [
        f"FIN {FIN}",
        "VIN W1TTEST0000000002",
        f"DISTANCE {km} km",
        f"DIAG START {date}",
        "VERSION 1",
        "LANGUAGE en",
        "SOURCE TD",
        "QuickTest 1",
        "ECU Count 1",
        "ECUS (1)",
        "CPC3-N127 - Powertrain controller",
        "Diagnostics ID 00AB13 ECU Variant CPC3_SYNTHETIC",
        "Hardware",
        "Partnumber",
        "001 002 003 Hardware",
        "Version",
        hw,
        "Supplier Example Software",
        "Version",
        sw,
        "Software",
        "Partnumbers",
        "000001,000002",
        "FAULT CODES (0)",
        "No fault codes",
    ]
    for index, line in enumerate(lines):
        pdf.drawString(35, 792 - index * 22, line)
    pdf.save()
    return buffer.getvalue()


def test_imported_quicktests_highlight_changed_ecu_hw_sw_and_case_plot(
    tmp_path, monkeypatch,
) -> None:
    data_dir = tmp_path / "appdata"
    monkeypatch.setenv("NTF_INSIGHT_DATA_DIR", str(data_dir))
    service = SourceImportService(
        data_dir / "raw", data_dir / "ntf-insight.duckdb"
    )
    first = tmp_path / "before.pdf"
    second = tmp_path / "after.pdf"
    first.write_bytes(_quicktest_pdf(
        date="2026-01-01 08:00:00", km=12000,
        hw="23/15 000", sw="25/04 001",
    ))
    second.write_bytes(_quicktest_pdf(
        date="2026-01-07 09:30:00", km=12300,
        hw="23/16 000", sw="25/04 002",
    ))
    summary = LocalBatchImporter(service).import_paths([second, first])
    assert summary.quicktests_saved == 2, summary.issues
    qts = QuickTestStore(service.store)
    reports = qts.list_reports(FIN)
    assert len(reports) == 2
    assert qts.list_ecus(reports[0]["report_id"])[0]["metadata"][
        "software_version"
    ] == "25/04 002"

    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        assert window.application_data.mode == "local"
        assert window.repository.list_cases() == []
        page = window.pages["cases"]
        assert page.version_change_model.rowCount() == 2
        assert page.cpc3_panel.version_model.rowCount() == 2
        assert page.cpc3_panel.change_model.rowCount() == 1
        assert "Kein dokumentierter Pumpentauschanker" in (
            page.cpc3_panel.swap_summary.text()
        )
        kinds = [
            page.version_change_model.data(
                page.version_change_model.index(row, 1)
            )
            for row in range(2)
        ]
        assert set(kinds) == {"Hardware", "Software"}
        assert "1 HW-" in page.version_change_summary.text()
        assert "1 SW-" in page.version_change_summary.text()
        assert {entry.kind for entry in page.time_plot._entries} >= {
            "ecu_state", "ecu_hw_change", "ecu_sw_change",
            "diagnostic_session",
        }
        page.time_filter.setText("P26F100")
        assert {entry.kind for entry in page.time_plot._visible_entries()} >= {
            "ecu_state", "ecu_hw_change", "ecu_sw_change",
            "diagnostic_session",
        }
        page.axis_selector.setCurrentIndex(1)
        assert page.time_plot.axis_mode == "mileage"
        assert page.time_plot._odometer_bounds() == (12000, 12300)

        explorer = page.quicktest_browser
        assert explorer is not None
        assert explorer.fin_selector.currentText() == FIN
        assert explorer.ecu_model.rowCount() == 1
        assert explorer.ecu_model.data(explorer.ecu_model.index(0, 5)) == (
            "HW + SW abweichend"
        )
        assert explorer.ecu_model.data(
            explorer.ecu_model.index(0, 3), Qt.ItemDataRole.BackgroundRole
        ) is not None
        assert explorer.ecu_model.data(
            explorer.ecu_model.index(0, 4), Qt.ItemDataRole.BackgroundRole
        ) is not None
        assert explorer.ecu_model.data(
            explorer.ecu_model.index(0, 5), Qt.ItemDataRole.FontRole
        ).bold()
        explorer._select_report(1)
        assert explorer.ecu_model.data(
            explorer.ecu_model.index(0, 5)
        ) == "Keine belegte Abweichung"

        # Reusing the already persisted QuickTest-derived states also works
        # after the real QEC case is created.
    finally:
        window.close()
        app.processEvents()

    projected = [
        qts.case_projection(report["report_id"])
        for report in qts.list_reports(FIN)
    ]
    real = NTFCase(
        case_id="QEC-SYNTHETIC",
        vehicle=Vehicle(vin=FIN),
        component_type="Coolant Pump",
        diagnostic_sessions=[s for sessions, _, _ in projected for s in sessions],
        ecu_states=[s for _, _, states in projected for s in states],
    )
    service.store.save_case(real)
    window = MainWindow()
    try:
        page = window.pages["cases"]
        assert page.version_change_model.rowCount() == 2
        assert {entry.kind for entry in page.time_plot._entries} >= {
            "ecu_hw_change", "ecu_sw_change",
        }
    finally:
        window.close()
        app.processEvents()
