"""Offscreen-Smoketest für Importfortsetzung und lokalen Parser-Diagnoseexport."""
from __future__ import annotations

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from ntf_insight.app.windows.main_window import MainWindow


def test_sources_gui_has_safe_resume_cancel_and_parser_zip(tmp_path, monkeypatch):
    monkeypatch.setenv("NTF_INSIGHT_DATA_DIR", str(tmp_path / "app-data"))
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    page = window.pages["sources"]
    assert page.local_quicktests_button.isEnabled()
    assert page.failed_quicktests_button.isEnabled()
    assert "Nur fehlerhafte QuickTests" in page.failed_quicktests_button.text()
    assert "v2" in page.failed_quicktests_button.toolTip()
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



def test_gezielter_quicktest_button_scannt_nicht_den_gesamten_altbestand(tmp_path, monkeypatch):
    monkeypatch.setenv("NTF_INSIGHT_DATA_DIR", str(tmp_path / "app-data"))
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    page = window.pages["sources"]

    def no_full_scan(*_args, **_kwargs):
        raise AssertionError("Der gezielte Fehlerreimport darf keinen PDF-Verzeichnisscan starten")

    monkeypatch.setattr(
        "ntf_insight.app.pages.sources_page.list_downloaded_quicktests",
        no_full_scan,
    )
    page.failed_quicktests_button.click()
    assert page._resume_kind == "quicktest_errors"
    assert page._worker is not None
    assert page._worker.retry_failed_quicktests
    assert not page.failed_quicktests_button.isEnabled()
    deadline = time.monotonic() + 20
    while page._worker is not None and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.02)
    app.processEvents()
    assert page._worker is None
    assert "Keine bereits protokollierten fehlerhaften QuickTest-PDFs" in page.import_status.text()
    assert page.failed_quicktests_button.isEnabled()
    assert page.resume_import_button.isEnabled()
    window.close()
    app.processEvents()
