"""Offscreen Qt tests: QEC controls, hyperlink date, and TIPS per case."""

from __future__ import annotations

import json
import os
from datetime import datetime

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from ntf_insight.acquisition.qec_archive import case_folder
from ntf_insight.app.models.case_table_model import CaseRow, CaseTableModel
from ntf_insight.app.pages.case_page import CasePage
from ntf_insight.demo.synthetic_cases import build_demo_cases
from ntf_insight.demo.synthetic_reference import build_demo_reference_repository
from ntf_insight.domain.events import TipsCaseObservation
from ntf_insight.storage.repositories import InMemoryCaseRepository

FIN = "WDD12345678901234"


def test_case_model_exposes_tips_and_underlined_qec_folder():
    app = QApplication.instance() or QApplication([])
    model = CaseTableModel([CaseRow(
        "QEC-A", FIN, "Kühlmittelpumpe", 1, None, "Unbekannt", None,
        tips_status="Ja", qec_date="13.10.2026 18:00",
        qec_folder="C:/test/qec/ref_022301658",
    )])
    assert model.HEADERS[model.TIPS_COLUMN] == "TIPS-Fall"
    assert model.data(model.index(0, model.TIPS_COLUMN), Qt.ItemDataRole.DisplayRole) == "Ja"
    date = model.index(0, model.QEC_COLUMN)
    assert model.data(date, Qt.ItemDataRole.DisplayRole) == "13.10.2026 18:00"
    assert model.data(date, Qt.ItemDataRole.FontRole).underline()
    assert model.qec_folder_at(0) == "C:/test/qec/ref_022301658"
    model.update_qec_archives({"QEC-A": None})
    assert model.data(date, Qt.ItemDataRole.DisplayRole) == "—"
    assert model.qec_folder_at(0) is None


def test_case_page_selects_exact_qec_references_and_marks_linked_tips(tmp_path):
    app = QApplication.instance() or QApplication([])
    first, second = (c.model_copy(deep=True) for c in build_demo_cases()[:2])
    first.vehicle.vin = FIN
    second.vehicle.vin = FIN
    first.case_id = "QEC-CASE-1"
    second.case_id = "QEC-CASE-2"
    first.qec_reference = "022301658"
    second.qec_reference = "022301659"
    first.tips_observations = [
        TipsCaseObservation(
            vin=FIN, occurred_at=datetime(2026, 10, 10),
            tips_case_id="TIPS-0001",
        )
    ]
    second.tips_observations = []

    folder = case_folder(tmp_path / "qec", FIN, "022301658")
    folder.mkdir(parents=True)
    (folder / "qec.json").write_text(json.dumps({
        "fin": FIN, "referenznummer": "022301658",
        "abgerufen_am_utc": "2026-10-13T18:00:00+00:00",
        "abschnitte": [{"bereich": "WE-Daten"}],
    }), encoding="utf-8")
    page = CasePage(
        InMemoryCaseRepository([first, second]),
        build_demo_reference_repository(), data_dir=tmp_path,
    )
    assert page.case_model.rowCount() == 2
    first_index = next(
        i for i in range(2)
        if page.case_model.case_id_at(i) == "QEC-CASE-1"
    )
    assert page.case_model._rows[first_index].tips_status == "Ja"
    assert page.case_model.qec_folder_at(first_index) == str(folder)
    assert page.qec_download.all_button.isEnabled()
    assert page.qec_download.selected_button.isEnabled()
    assert {item.reference for item in page._all_qec_targets()} == {
        "022301658", "022301659",
    }

    # A single selected table row must not download the other reference of the same FIN.
    target_proxy_row = page.case_proxy.mapFromSource(
        page.case_model.index(first_index, 0)
    ).row()
    page.case_table.selectRow(target_proxy_row)
    chosen = page._selected_qec_targets()
    assert len(chosen) == 1 and chosen[0].reference == "022301658"

    page.close()
    app.processEvents()


def test_qec_page_is_removed_from_main_navigation(tmp_path, monkeypatch):
    from ntf_insight.app.windows.main_window import MainWindow

    monkeypatch.setenv("NTF_INSIGHT_DATA_DIR", str(tmp_path))
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    assert "qec_download" not in window.navigation.buttons
    assert "qec_download" not in window.pages
    panel = window.pages["cases"].qec_download
    assert panel.all_button.text() == "Alle QEC-Berichte herunterladen"
    assert panel.selected_button.text() == "Ausgewählte herunterladen"
    window.close()
    app.processEvents()
