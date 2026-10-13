"""QEC und QuickTest benutzen dieselben Fall-Checkboxen und SSO-Felder."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from ntf_insight.acquisition.credentials import LoginCredentials
from ntf_insight.acquisition.qec_archive import case_folder
from ntf_insight.app.models.case_table_model import CaseRow, CaseTableModel
from ntf_insight.app.pages.case_page import CasePage
from ntf_insight.demo.synthetic_cases import build_demo_cases
from ntf_insight.demo.synthetic_reference import build_demo_reference_repository
from ntf_insight.domain.events import TipsCaseObservation
from ntf_insight.storage.repositories import InMemoryCaseRepository

FIN = "WDD12345678901234"


def _make_page(tmp_path: Path):
    app = QApplication.instance() or QApplication([])
    original = build_demo_cases()
    first = original[0].model_copy(
        deep=True,
        update={"case_id": "QEC-CASE-1", "qec_reference": "022301658"},
    )
    second = original[1].model_copy(
        deep=True,
        update={"case_id": "QEC-CASE-2", "qec_reference": "022301659"},
    )
    first.vehicle = first.vehicle.model_copy(update={"vin": FIN})
    second.vehicle = second.vehicle.model_copy(update={"vin": FIN})
    first.tips_observations = [
        TipsCaseObservation(
            vin=FIN, occurred_at=datetime(2026, 10, 10),
            tips_case_id="TIPS-0001",
        )
    ]
    second.tips_observations = []
    page = CasePage(
        InMemoryCaseRepository([first, second]),
        build_demo_reference_repository(),
        download_root=tmp_path / "quicktests",
    )
    return app, page


def test_qec_model_reuses_main_checkbox_and_keeps_quicktest_last_column(tmp_path):
    QApplication.instance() or QApplication([])
    folder = tmp_path / "ref_022301658"
    folder.mkdir()
    model = CaseTableModel([CaseRow(
        "QEC-A", FIN, "Kühlmittelpumpe", 1, None, "Unbekannt", None,
        tips_status="Ja",
    )])
    assert model.HEADERS[0] == "Auswahl"
    assert model.HEADERS[-1] == "QuickTest-Abruf-Datum"
    assert model.HEADERS[model.TIPS_COLUMN] == "TIPS-Fall"
    assert model.HEADERS[model.QEC_DATE_COLUMN] == "QEC-Abrufdatum"
    assert model.data(
        model.index(0, model.TIPS_COLUMN), Qt.ItemDataRole.DisplayRole,
    ) == "Ja"
    index = model.index(0, model.QEC_DATE_COLUMN)
    model.set_qec_history({"QEC-A": ("13.10.2026 18:00", folder)})
    assert model.data(index, Qt.ItemDataRole.DisplayRole) == "13.10.2026 18:00"
    assert model.data(index, Qt.ItemDataRole.FontRole).underline()
    assert model.qec_folder_at(0) == folder
    model.setData(
        model.index(0, model.CHECK_COLUMN), Qt.CheckState.Checked,
        Qt.ItemDataRole.CheckStateRole,
    )
    model.set_qec_history({})
    assert model.checked_case_ids() == {"QEC-A"}
    assert model.qec_folder_at(0) is None


def test_qec_and_quicktest_use_identical_checked_cases(tmp_path):
    app, page = _make_page(tmp_path)
    assert page.case_model.rowCount() == 2
    assert page.case_model._rows[0].tips_status == "Ja"
    assert page.quicktest_download_all_button.isEnabled()
    assert page.qec_download.all_button.isEnabled()
    assert not page.quicktest_download_selected_button.isEnabled()
    assert not page.qec_download.selected_button.isEnabled()

    page.case_model.setData(
        page.case_model.index(0, page.case_model.CHECK_COLUMN),
        Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole,
    )
    assert page.quicktest_download_selected_button.isEnabled()
    assert page.qec_download.selected_button.isEnabled()
    assert page.case_model.selected_fins() == [FIN]
    chosen = page._selected_qec_targets()
    assert len(chosen) == 1
    assert chosen[0].reference == "022301658"

    page.case_search.setText("not-present")
    assert page.case_proxy.rowCount() == 0
    assert page._selected_qec_targets()[0].reference == "022301658"
    page.case_search.clear()
    page.case_proxy.sort(2, Qt.SortOrder.DescendingOrder)
    assert page._selected_qec_targets()[0].reference == "022301658"
    page.close()
    app.processEvents()


def test_qec_date_link_matches_reference_and_opens_local_folder(tmp_path, monkeypatch):
    app, page = _make_page(tmp_path)
    folder = case_folder(tmp_path / "qec", FIN, "022301658")
    folder.mkdir(parents=True)
    (folder / "qec.json").write_text(json.dumps({
        "fin": FIN,
        "referenznummer": "022301658",
        "abgerufen_am_utc": "2026-10-13T18:00:00+00:00",
        "abschnitte": [{"bereich": "WE-Daten"}],
    }), encoding="utf-8")
    page._refresh_qec_download_dates()

    assert page.case_model.qec_folder_at(0) == folder
    assert page.case_model.qec_folder_at(1) is None
    opened = []
    monkeypatch.setattr(
        "ntf_insight.app.pages.case_page.QDesktopServices.openUrl",
        lambda url: opened.append(url.toLocalFile()) or True,
    )
    index = page.case_proxy.mapFromSource(
        page.case_model.index(0, page.case_model.QEC_DATE_COLUMN)
    )
    page._case_table_qec_link_clicked(index)
    assert [Path(value) for value in opened] == [folder]
    second = page.case_proxy.mapFromSource(
        page.case_model.index(1, page.case_model.QEC_DATE_COLUMN)
    )
    page._case_table_qec_link_clicked(second)
    assert len(opened) == 1
    page.close()
    app.processEvents()


def test_qec_reuses_quicktest_password_and_green_vault_marker(tmp_path, monkeypatch):
    from ntf_insight.app.pages import case_page as case_module

    vault = {}
    monkeypatch.setattr(
        case_module, "load_saved_credentials",
        lambda: vault.get("login"),
    )
    monkeypatch.setattr(
        case_module, "save_credentials",
        lambda user_id, password: vault.__setitem__(
            "login", LoginCredentials(user_id, password)
        ),
    )
    app, page = _make_page(tmp_path)
    assert "Keine" in page.shared_credentials_status.text() or "Noch keine" in (
        page.shared_credentials_status.text()
    )
    page.quicktest_user_id.setText("test-user")
    page.quicktest_password.setText("test-secret")
    login = page._resolve_qec_credentials()
    assert login == LoginCredentials("test-user", "test-secret")
    assert page.quicktest_password.text() == ""
    assert vault["login"].password == "test-secret"
    assert "#268b52" in page.shared_credentials_status.styleSheet()
    page.close()
    app.processEvents()


def test_navigation_contains_no_separate_qec_page(tmp_path, monkeypatch):
    from ntf_insight.app.windows.main_window import MainWindow

    monkeypatch.setenv("NTF_INSIGHT_DATA_DIR", str(tmp_path))
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    assert "qec_download" not in window.navigation.buttons
    assert "qec_download" not in window.pages
    page = window.pages["cases"]
    assert page.qec_download is not None
    assert page.qec_download.all_button.text() == (
        "Alle QEC-Berichte herunterladen/aktualisieren"
    )
    assert page.qec_download.selected_button.text() == (
        "QEC-Berichte für ausgewählte Fälle herunterladen/aktualisieren"
    )
    window.close()
    app.processEvents()
