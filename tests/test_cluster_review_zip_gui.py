"""Qt integration of one-click pseudonymized cluster review export."""
from __future__ import annotations

import json
from zipfile import ZipFile

from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from ntf_insight.app.widgets.hdbscan_panel import HDBSCANPanel
from test_hdbscan_clustering import sample


def test_zip_button_exports_safe_package_not_internal_qec_or_fin(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    cases = sample()
    cases[0].qec_ssl_end_finding = "PRIVATE-SSL-DO-NOT-SHARE"
    panel = HDBSCANPanel(cases)
    assert not panel.chat_zip_button.isEnabled()
    panel.run_analysis()
    assert panel.chat_zip_button.isEnabled()
    destination = tmp_path / "chat.zip"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName",
        lambda *args, **kwargs: (str(destination), "ZIP-Dateien (*.zip)"),
    )
    shown = []
    monkeypatch.setattr(
        QMessageBox, "information",
        lambda _parent, title, description: shown.append((title, description)),
    )
    panel.chat_zip_button.click()
    assert destination.exists()
    assert len(shown) == 1
    assert "NICHT_HOCHLADEN" in shown[0][1]
    with ZipFile(destination) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["faelle"] == len(cases)
        assert manifest["repraesentanten"] == len(panel.result.clusters)
        assert "PRIVATE-SSL-DO-NOT-SHARE" not in str(archive.read("README.txt"))
    panel.close()
    app.processEvents()
