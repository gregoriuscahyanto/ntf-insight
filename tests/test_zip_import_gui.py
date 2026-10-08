"""Offscreen GUI integration for automatic QEC ZIP import."""

from __future__ import annotations

import io
import os
import time
from datetime import datetime
from zipfile import ZipFile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from openpyxl import Workbook
from PySide6.QtWidgets import QApplication

from ntf_insight.app.windows.main_window import MainWindow


def test_zip_drag_drop_import_updates_all_desktop_views(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("NTF_INSIGHT_DATA_DIR", str(tmp_path / "isolated-local"))
    app = QApplication.instance() or QApplication([])

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Schadteile QEC"
    sheet.append(
        ["Referenznr.", "FIN", "Benennung", "Rep.-Datum", "Laufleistung"]
    )
    sheet.append(
        [
            "ZIP-DEMO-001",
            "MBCW1TTEST0000000001",
            "KUEHLMITTELPUMPE",
            datetime(2026, 1, 3),
            12345,
        ]
    )
    binary = io.BytesIO()
    workbook.save(binary)

    source = tmp_path / "synthetic-import.zip"
    with ZipFile(source, "w") as archive:
        archive.writestr("input/cases.xlsx", binary.getvalue())

    window = MainWindow()
    assert window.application_data.mode == "demo"
    page = window.pages["sources"]
    assert page.source_type.currentData() is None

    page._archive_paths([source])
    deadline = time.monotonic() + 15
    while window.application_data.mode == "demo" and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.025)

    assert window.application_data.mode == "local"
    assert window.repository.get_case("QEC-ZIP-DEMO-001") is not None
    assert window.pages["cases"].case_model.rowCount() == 1
    assert "1 neue Fälle" in window.pages["sources"].import_status.text()
    window.close()
    app.processEvents()
