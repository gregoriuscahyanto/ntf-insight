"""Offscreen-Smoketest für Importfortsetzung und lokalen Parser-Diagnoseexport."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from ntf_insight.app.windows.main_window import MainWindow


def test_sources_gui_has_safe_resume_cancel_and_parser_zip(tmp_path, monkeypatch):
    monkeypatch.setenv("NTF_INSIGHT_DATA_DIR", str(tmp_path / "app-data"))
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    page = window.pages["sources"]
    assert page.local_quicktests_button.isEnabled()
    assert page.local_qec_button.isEnabled()
    assert page.problem_zip_button.isEnabled()
    assert not page.cancel_import_button.isEnabled()
    assert not page.resume_import_button.isEnabled()
    assert "ZIP" in page.problem_zip_button.text()
    assert "Original" in page.problem_zip_button.toolTip()
    page._resume_kind = "quicktests"
    page._resume_import()
    assert "Keine lokalen QuickTest-PDFs" in page.import_status.text()
    page._resume_kind = "qec"
    page._resume_import()
    assert "Keine QEC-Berichte" in page.import_status.text()
    window.close()
    app.processEvents()
