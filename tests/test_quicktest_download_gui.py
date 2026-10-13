"""GUI-Smoke-Tests für die neue Anmeldung und Abrufhistorie."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLineEdit

from ntf_insight.app.pages.quicktest_download_page import QuickTestDownloadPage


def test_login_fields_and_last_download_date_column(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "ntf_insight.app.pages.quicktest_download_page.load_saved_credentials",
        lambda: None,
    )
    app = QApplication.instance() or QApplication([])
    page = QuickTestDownloadPage(tmp_path)
    assert page.table.columnCount() == 5
    assert page.table.horizontalHeaderItem(1).text() == "Letzter Abruf"
    assert page.password.echoMode() == QLineEdit.EchoMode.Password
    assert page.remember_login.isChecked()
    assert not page.retry_recent.isChecked()
    assert page.worker is None
    page.close()
    app.processEvents()
