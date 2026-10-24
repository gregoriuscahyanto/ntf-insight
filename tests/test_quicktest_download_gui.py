"""GUI-Regression: QuickTest-Abruf ist Teil von Fälle / FIN → FIN / Fallanalyse."""

from __future__ import annotations

import os
from pathlib import Path
from threading import Event

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from ntf_insight.acquisition.diagnosis_viewer import FinDownloadResult, _write_manifest
from ntf_insight.app.pages.case_page import CasePage
from ntf_insight.demo.synthetic_cases import build_demo_cases
from ntf_insight.demo.synthetic_reference import build_demo_reference_repository
from ntf_insight.storage.repositories import InMemoryCaseRepository


FIN = "WDD12345678901234"


def _case_page(tmp_path, monkeypatch, *, two_cases=False):
    monkeypatch.setattr(
        "ntf_insight.app.pages.case_page.load_saved_credentials", lambda: None
    )
    cases = []
    for i in range(2 if two_cases else 1):
        original = build_demo_cases()[i]
        cases.append(original.model_copy(update={
            "case_id": f"SYN-CASE-{i}",
            "vehicle": original.vehicle.model_copy(update={"vin": FIN}),
        }))
    app = QApplication.instance() or QApplication([])
    page = CasePage(
        InMemoryCaseRepository(cases), build_demo_reference_repository(),
        download_root=tmp_path / "quicktests",
    )
    return app, page


def test_checkbox_is_interactive_and_selection_button_only_activates_when_checked(
    tmp_path, monkeypatch,
):
    app, page = _case_page(tmp_path, monkeypatch, two_cases=True)
    assert page.case_model.HEADERS[0] == "Auswahl"
    assert page.case_model.HEADERS[-1] == "QuickTest-Abruf-Datum"
    assert page.detail_tabs.tabText(0) == "FIN / Fallanalyse"
    assert page.quicktest_download_all_button.isEnabled()
    assert not page.quicktest_download_selected_button.isEnabled()
    page.show()
    page.detail_tabs.setCurrentWidget(page.analysis_tab)
    app.processEvents()
    proxy_index = page.case_proxy.index(0, 0)
    rect = page.case_table.visualRect(proxy_index)
    assert rect.isValid()
    QTest.mouseClick(
        page.case_table.viewport(), Qt.MouseButton.LeftButton, pos=rect.center()
    )
    app.processEvents()
    assert len(page.case_model.checked_case_ids()) == 1
    assert page.quicktest_download_selected_button.isEnabled()
    assert page.case_model.selected_fins() == [FIN]
    # Filtering and sorting do not accidentally change the checked case ID.
    previous = page.case_model.checked_case_ids()
    page.case_search.setText("nonexistent")
    assert page.case_proxy.rowCount() == 0
    assert page.case_model.checked_case_ids() == previous
    page.case_search.clear()
    page.case_proxy.sort(2, Qt.SortOrder.DescendingOrder)
    assert page.case_model.checked_case_ids() == previous
    page.close()
    app.processEvents()


def test_date_link_opens_real_local_fin_folder_and_na_is_inert(tmp_path, monkeypatch):
    app, page = _case_page(tmp_path, monkeypatch)
    assert page.case_model.data(
        page.case_model.index(0, page.case_model.QUICKTEST_DATE_COLUMN),
        Qt.ItemDataRole.DisplayRole,
    ) == "n.a."
    folder = tmp_path / "quicktests" / FIN
    folder.mkdir(parents=True)
    (folder / "test.pdf").write_bytes(b"%PDF-1.7\nsynthetic")
    _write_manifest(folder, FinDownloadResult(
        fin=FIN, status="Erfolgreich", last_attempt_at="2026-10-13T10:35:00+00:00",
    ))
    page._refresh_quicktest_download_dates()
    source = page.case_model.index(0, page.case_model.QUICKTEST_DATE_COLUMN)
    proxy = page.case_proxy.mapFromSource(source)
    assert page.case_model.folder_at(0) == folder
    assert page.case_model.data(source, Qt.ItemDataRole.FontRole).underline()
    opened = []
    monkeypatch.setattr(
        "ntf_insight.app.pages.case_page.QDesktopServices.openUrl",
        lambda url: opened.append(url.toLocalFile()) or True,
    )
    page._case_table_quicktest_link_clicked(proxy)
    assert [Path(value) for value in opened] == [folder]
    page.close()
    app.processEvents()


class FakeDownloadWorker(QObject):
    progress = Signal(str)
    completed = Signal(object)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, fins, folder, profile, login=None, retry_recent=False):
        super().__init__()
        self.fins = fins
        self.folder = folder
        self.profile = profile
        self.login = login
        self.retry_recent = retry_recent
        self.cancel = Event()
        self.started = False

    def start(self):
        self.started = True


def test_only_chosen_fins_sent_to_worker_with_stored_credentials(tmp_path, monkeypatch):
    app, page = _case_page(tmp_path, monkeypatch, two_cases=True)
    monkeypatch.setattr(
        "ntf_insight.app.pages.case_page.DownloadWorker", FakeDownloadWorker
    )
    saved = []
    monkeypatch.setattr(
        "ntf_insight.app.pages.case_page.save_credentials",
        lambda uid, password: saved.append((uid, password)),
    )
    page.quicktest_user_id.setText("user-123")
    page.quicktest_password.setText("test-passwort")
    page.case_model.setData(
        page.case_model.index(0, 0), Qt.CheckState.Checked,
        Qt.ItemDataRole.CheckStateRole,
    )
    assert page.quicktest_download_selected_button.isEnabled()
    page._start_quicktest_download(selected_only=True)
    worker = page._quicktest_worker
    assert worker.started
    assert worker.fins == [FIN]  # Two cases with same FIN -> one request.
    assert worker.login.user_id == "user-123"
    assert worker.login.password == "test-passwort"
    assert saved == [("user-123", "test-passwort")]
    assert page.quicktest_password.text() == ""
    assert not page.quicktest_download_selected_button.isEnabled()
    worker.completed.emit([FinDownloadResult(fin=FIN, status="Keine Quicktests")])
    worker.finished.emit()
    assert page._quicktest_worker is None
    assert page.quicktest_download_selected_button.isEnabled()
    page.close()
    app.processEvents()



def test_s3_without_quicktest_shows_separate_skipped_counter(tmp_path, monkeypatch):
    app, page = _case_page(tmp_path, monkeypatch)
    page._quicktest_download_completed([
        FinDownloadResult(
            fin=FIN, status="Keine Quicktests",
            no_quicktest_sessions=["Sitzung 1 (2026-10-13 09:00:00)"],
        )
    ])
    text = page.quicktest_download_status.text()
    assert "1 S3-Sitzung(en) ohne QuickTest übersprungen" in text
    assert "0 Fehler" in text
    page.close()
    app.processEvents()
