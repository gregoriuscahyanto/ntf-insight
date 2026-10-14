"""GUI-Regression für beide FIN-ZIP-Tasten und geteilte Fall-Checkboxen."""

from __future__ import annotations

import json
import os
from pathlib import Path
from zipfile import ZipFile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from ntf_insight.app.pages.case_page import CasePage
from ntf_insight.demo.synthetic_cases import build_demo_cases
from ntf_insight.demo.synthetic_reference import build_demo_reference_repository
from ntf_insight.storage.repositories import InMemoryCaseRepository

FIN_1 = "WDD12345678901234"
FIN_2 = "WDD12345678901235"


def _page(tmp_path, *, different_fin=False):
    app = QApplication.instance() or QApplication([])
    examples = build_demo_cases()
    vins = [FIN_1, FIN_2 if different_fin else FIN_1]
    cases = [
        examples[index].model_copy(
            update={
                "case_id": f"CASE-{index}",
                "vehicle": examples[index].vehicle.model_copy(update={"vin": vins[index]}),
            }
        )
        for index in range(2)
    ]
    page = CasePage(
        InMemoryCaseRepository(cases),
        build_demo_reference_repository(),
        download_root=tmp_path / "quicktests",
    )
    return app, page


def _create_sources(tmp_path: Path, fin: str) -> None:
    q = tmp_path / "quicktests" / fin
    q.mkdir(parents=True, exist_ok=True)
    (q / "diagnose.pdf").write_bytes(b"%PDF-1.7\nSynthetic")
    qec = tmp_path / "qec" / fin / "ref_022301658"
    qec.mkdir(parents=True, exist_ok=True)
    (qec / "qec.json").write_text(json.dumps({
        "fin": fin, "referenznummer": "022301658",
        "abschnitte": [{"bereich": "WE-Daten"}],
    }), encoding="utf-8")
    attachment = qec / "anhaenge"
    attachment.mkdir()
    (attachment / "1603327_Bericht.pdf").write_bytes(b"%PDF-1.7\nBefund")


def _finish_worker(app, panel) -> None:
    worker = panel.worker
    assert worker is not None
    assert worker.wait(5000), "Synthetischer ZIP-Export darf nicht hängen."
    for _ in range(3):
        app.processEvents()


def test_two_zip_buttons_share_case_checkbox_and_ignore_filter(tmp_path):
    app, page = _page(tmp_path)
    panel = page.fin_zip_export
    assert panel is not None
    assert panel.all_button.text() == "Alle FINs als ZIP exportieren"
    assert panel.selected_button.text() == "Ausgewählte FINs als ZIP exportieren"
    assert panel.all_button.isEnabled()
    assert not panel.selected_button.isEnabled()
    assert page.case_model.HEADERS[0] == "Auswahl"
    assert page.qec_download.all_button.isEnabled()
    assert page.quicktest_download_all_button.isEnabled()

    assert page.case_model.setData(
        page.case_model.index(0, page.case_model.CHECK_COLUMN),
        Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole,
    )
    assert panel.selected_button.isEnabled()
    assert panel._selected_count == 1
    assert page.case_model.selected_fins() == [FIN_1]
    page.case_model.setData(
        page.case_model.index(1, page.case_model.CHECK_COLUMN),
        Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole,
    )
    assert panel._selected_count == 1  # Zwei Fälle, nur ein FIN-ZIP.
    page.case_search.setText("nicht-vorhanden")
    assert page.case_proxy.rowCount() == 0
    assert panel.selected_button.isEnabled()
    page.case_search.clear()
    page.case_proxy.sort(2, Qt.SortOrder.DescendingOrder)
    assert page.case_model.selected_fins() == [FIN_1]
    page.close()
    app.processEvents()


def test_selected_button_exports_only_checked_fin(tmp_path, monkeypatch):
    app, page = _page(tmp_path, different_fin=True)
    _create_sources(tmp_path, FIN_1)
    _create_sources(tmp_path, FIN_2)
    output = tmp_path / "ausgabe"
    monkeypatch.setattr(
        "ntf_insight.app.widgets.fin_zip_export.QFileDialog.getExistingDirectory",
        lambda *_a, **_kw: str(output),
    )
    model = page.case_model
    model.setData(model.index(0, model.CHECK_COLUMN),
                  Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole)
    assert page.fin_zip_export.selected_button.isEnabled()
    page.fin_zip_export.selected_button.click()
    _finish_worker(app, page.fin_zip_export)

    one = output / f"{FIN_1}_NTF-Export.zip"
    two = output / f"{FIN_2}_NTF-Export.zip"
    assert one.is_file()
    assert not two.exists()
    with ZipFile(one) as z:
        assert "quicktests/diagnose.pdf" in z.namelist()
        assert "qec/ref_022301658/qec.json" in z.namelist()
        assert "qec/ref_022301658/anhaenge/1603327_Bericht.pdf" in z.namelist()
    assert page.fin_zip_export.selected_button.isEnabled()
    assert "1 ZIP(s)" in page.fin_zip_export.status.text()
    page.close()
    app.processEvents()


def test_all_button_creates_two_separate_fin_zips(tmp_path, monkeypatch):
    app, page = _page(tmp_path, different_fin=True)
    _create_sources(tmp_path, FIN_1)
    _create_sources(tmp_path, FIN_2)
    output = tmp_path / "ausgabe"
    monkeypatch.setattr(
        "ntf_insight.app.widgets.fin_zip_export.QFileDialog.getExistingDirectory",
        lambda *_a, **_kw: str(output),
    )
    page.fin_zip_export.all_button.click()
    _finish_worker(app, page.fin_zip_export)
    assert (output / f"{FIN_1}_NTF-Export.zip").is_file()
    assert (output / f"{FIN_2}_NTF-Export.zip").is_file()
    with ZipFile(output / f"{FIN_1}_NTF-Export.zip") as first, ZipFile(
        output / f"{FIN_2}_NTF-Export.zip"
    ) as second:
        assert json.loads(first.read("export_manifest.json"))["fin"] == FIN_1
        assert json.loads(second.read("export_manifest.json"))["fin"] == FIN_2
    page.close()
    app.processEvents()


def test_destination_dialog_cancel_creates_nothing(tmp_path, monkeypatch):
    app, page = _page(tmp_path)
    monkeypatch.setattr(
        "ntf_insight.app.widgets.fin_zip_export.QFileDialog.getExistingDirectory",
        lambda *_a, **_kw: "",
    )
    page.fin_zip_export.all_button.click()
    assert page.fin_zip_export.worker is None
    assert not (tmp_path / "ausgabe").exists()
    page.close()
    app.processEvents()
