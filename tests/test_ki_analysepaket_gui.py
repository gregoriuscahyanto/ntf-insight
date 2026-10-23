"""GUI-Smoketest für den zusätzlichen leichten Export, ohne Rohdaten."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from ntf_insight.app.windows.main_window import MainWindow


def test_ki_analysepaket_is_separate_from_one_file_backup(tmp_path, monkeypatch):
    monkeypatch.setenv("NTF_INSIGHT_DATA_DIR", str(tmp_path / "app-data"))
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    sources = window.pages["sources"]
    assert sources.portable_backup_panel is not None
    panel = sources.ki_analyse_panel
    assert panel is not None
    assert panel.export_button.isEnabled()
    assert not panel.include_text.isChecked()
    assert "ZIP" in panel.export_button.text()
    assert "Original-PDFs" in panel.layout().itemAt(1).widget().text()
    assert panel._guard is not None
    assert panel._guard()
    window.close()
    app.processEvents()
