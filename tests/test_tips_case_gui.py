"""Qt-Regression: TIPS teilt sich FIN-Checkboxen und SSO mit QEC/QuickTest."""

from __future__ import annotations

import json
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from ntf_insight.app.pages.case_page import CasePage
from ntf_insight.demo.synthetic_cases import build_demo_cases
from ntf_insight.demo.synthetic_reference import build_demo_reference_repository
from ntf_insight.reporting.fin_zip_export import export_fin_zip
from ntf_insight.storage.repositories import InMemoryCaseRepository

FIN = "WDD12345678901234"
OTHER_FIN = "WDD12345678901235"


def _page(tmp_path, *, two_fins=False):
    app = QApplication.instance() or QApplication([])
    originals = build_demo_cases()
    vins = [FIN, OTHER_FIN if two_fins else FIN]
    cases = []
    for i in range(2):
        initial = originals[i]
        case = initial.model_copy(deep=True)
        case.case_id = f"SYN-TIPS-{i}"
        case.vehicle = case.vehicle.model_copy(update={"vin": vins[i]})
        case.tips_observations = []
        cases.append(case)
    page = CasePage(
        InMemoryCaseRepository(cases), build_demo_reference_repository(),
        download_root=tmp_path / "quicktests",
    )
    return app, page


def test_tips_buttons_reuse_existing_checkbox_selection_even_when_filtered(tmp_path):
    app, page = _page(tmp_path, two_fins=True)
    assert page.tips_download is not None
    assert page.tips_download.all_button.isEnabled()
    assert not page.tips_download.selected_button.isEnabled()
    assert "TIPS-Fälle" in page.tips_download.all_button.text()
    assert page.quicktest_download_all_button.isEnabled()
    assert page.qec_download.all_button.isEnabled()
    assert page.fin_zip_export.all_button.isEnabled()

    model = page.case_model
    assert model.setData(
        model.index(0, model.CHECK_COLUMN), Qt.CheckState.Checked,
        Qt.ItemDataRole.CheckStateRole,
    )
    assert page.tips_download.selected_button.isEnabled()
    assert page.tips_download._selected_count == 1
    assert page.case_model.selected_fins() == [FIN]
    assert page.qec_download.selected_button.isEnabled()
    assert page.fin_zip_export.selected_button.isEnabled()
    page.case_search.setText("absolut-nicht-vorhanden")
    assert page.case_proxy.rowCount() == 0
    assert page.tips_download.selected_button.isEnabled()
    assert page.tips_download.selected_fins() == [FIN]
    page.close()
    app.processEvents()


def test_multiple_cases_same_fin_have_one_tips_download_target(tmp_path):
    app, page = _page(tmp_path)
    for index in (0, 1):
        page.case_model.setData(
            page.case_model.index(index, page.case_model.CHECK_COLUMN),
            Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole,
        )
    assert page.tips_download._selected_count == 1
    assert page.tips_download.selected_fins() == [FIN]
    assert page.tips_download.all_fins() == [FIN]
    page.close()
    app.processEvents()


def test_verified_local_tips_json_sets_fin_hint_not_confirmed_case_match(tmp_path):
    app, page = _page(tmp_path, two_fins=True)
    expected = tmp_path / "tips" / FIN / "fall_01234567" / "tips.json"
    expected.parent.mkdir(parents=True)
    expected.write_text(json.dumps({
        "fin": FIN, "fallnummer": "01234567",
        "abschnitte": [{"bereich": "Erstanfrage"}],
    }), encoding="utf-8")
    page._refresh_local_tips_status()
    rows = page.case_model._rows
    assert rows[0].tips_status == "FIN-Hinweis"
    assert rows[1].tips_status == "—"
    package = export_fin_zip(FIN, tmp_path, tmp_path / "export")
    assert package.zip_path is not None
    from zipfile import ZipFile
    with ZipFile(package.zip_path) as z:
        assert "tips/fall_01234567/tips.json" in z.namelist()
    page.close()
    app.processEvents()


def test_tips_uses_exact_same_ssso_credentials_callback_as_qec(tmp_path):
    app, page = _page(tmp_path)
    assert page.tips_download.login_resolver.__self__ is page
    assert page.tips_download.login_resolver.__func__ is (
        page.qec_download.login_resolver.__func__
    )
    page.close()
    app.processEvents()


def test_tips_only_in_case_analysis_not_in_navigation(tmp_path, monkeypatch):
    from ntf_insight.app.windows.main_window import MainWindow

    monkeypatch.setenv("NTF_INSIGHT_DATA_DIR", str(tmp_path))
    app = QApplication.instance() or QApplication([])
    main = MainWindow()
    assert "tips_download" not in main.navigation.buttons
    assert "tips_download" not in main.pages
    assert main.pages["cases"].tips_download is not None
    main.close()
    app.processEvents()
