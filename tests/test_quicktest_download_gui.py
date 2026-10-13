"""GUI-Smoke-Tests für die neue Anmeldung und Abrufhistorie."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLineEdit

from ntf_insight.acquisition.diagnosis_viewer import FinDownloadResult, _write_manifest

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



def test_gui_inventory_survives_a_batch_and_refreshes(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "ntf_insight.app.pages.quicktest_download_page.load_saved_credentials",
        lambda: None,
    )
    fin_one = "WDD12345678901234"
    fin_two = "WDD12345678901235"
    folder = tmp_path / "quicktests"
    for fin in (fin_one, fin_two):
        (folder / fin).mkdir(parents=True)
        (folder / fin / "quicktest.pdf").write_bytes(b"%PDF-1.7\nSynthetic")

    # Only one folder has a current abrufstatus.json; the other is a legacy PDF folder.
    _write_manifest(
        folder / fin_one,
        FinDownloadResult(
            fin=fin_one, status="Erfolgreich",
            last_attempt_at="2026-10-12T10:30:00+00:00",
        ),
    )
    app = QApplication.instance() or QApplication([])
    page = QuickTestDownloadPage(tmp_path)
    assert page.table.rowCount() == 2
    assert page.history_info.text().startswith("Lokaler Bestand: 2 FIN-Ordner")
    rows = {
        page.table.item(row, 0).text(): [
            page.table.item(row, col).text() for col in range(5)
        ]
        for row in range(page.table.rowCount())
    }
    assert rows[fin_one][2] == "Erfolgreich"
    assert rows[fin_two][1] == "Nicht dokumentiert"
    assert rows[fin_two][3] == "1"

    # Completing a download for one FIN must not hide the other FIN.
    page._completed([
        FinDownloadResult(fin=fin_one, status="Erfolgreich", last_attempt_at="2026-10-13T08:00:00+00:00"),
    ])
    assert page.table.rowCount() == 2
    assert {page.table.item(i, 0).text() for i in range(2)} == {fin_one, fin_two}

    third = folder / "WDD12345678901236"
    third.mkdir()
    (third / "quicktest.pdf").write_bytes(b"%PDF-1.7\nSynthetic")
    page.refresh_button.click()
    assert page.table.rowCount() == 3
    assert "3 FIN-Ordner" in page.history_info.text()
    page.close()
    app.processEvents()
