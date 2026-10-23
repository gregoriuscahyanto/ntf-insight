"""Smoke tests for the standalone air-gapped PySide6 workspace."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from ntf_insight.app.pages.smrd_offline_page import SmrdOfflinePage
from ntf_insight.smrd.offline_gui import _OfflineWindow


def test_offline_page_can_open_without_dts_or_internet(tmp_path):
    application = QApplication.instance() or QApplication([])
    page = SmrdOfflinePage(tmp_path)
    assert "SMR-D" in page.findChildren(type(page.status))[0].text() or page.status.text()
    assert page.convert_button.isEnabled()
    assert not page.import_button.isEnabled()
    assert page._worker is None
    assert page._bundle is None
    page.close()
    application.processEvents()


def test_offline_page_recognizes_user_originals_folder(tmp_path):
    application = QApplication.instance() or QApplication([])
    root = tmp_path / "smrd" / "originale"
    root.mkdir(parents=True)
    source = root / "Another_ECU.smr-d"
    source.write_bytes(b"synthetic content used only for listing")
    page = SmrdOfflinePage(tmp_path)
    assert page.smrd_path.text() == str(source)
    assert "1 Original-SMR-D" in page.status.text()
    page.close()
    application.processEvents()


def test_standalone_window_does_not_use_main_app_navigation(tmp_path):
    application = QApplication.instance() or QApplication([])
    window = _OfflineWindow()
    page = SmrdOfflinePage(tmp_path)
    window.setCentralWidget(page)
    assert window.centralWidget() is page
    assert not hasattr(page, "navigation")
    window.close()
    application.processEvents()


def test_vendor_converter_controls_are_opt_in_and_explain_license(tmp_path):
    application = QApplication.instance() or QApplication([])
    page = SmrdOfflinePage(tmp_path)
    assert page.vendor_button.isEnabled()
    assert page.export_ecu.isChecked()
    assert page.export_dtcs.isChecked()
    assert not page.export_compar.isChecked()
    assert not page.export_canmodel.isChecked()
    assert "Lizenz" in page.vendor_note.text()
    assert page.vendor_runtime.text().endswith(
        str(tmp_path / "smrd" / "runtime" / "SMRxView")
    )
    page.close()
    application.processEvents()


def test_vendor_button_requires_real_external_executable(tmp_path):
    application = QApplication.instance() or QApplication([])
    root = tmp_path / "smrd" / "originale"
    root.mkdir(parents=True)
    (root / "CPC3_24.01.00.smr-d").write_bytes(b"synthetic file")
    page = SmrdOfflinePage(tmp_path)
    assert page.ecu_name.text() == "CPC3"
    page.vendor_button.click()
    assert "Smrd2Xml.exe fehlt" in page.status.text()
    assert page._worker is None
    assert page._bundle is None
    page.close()
    application.processEvents()
