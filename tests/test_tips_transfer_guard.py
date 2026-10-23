"""Schutz des Ein-Datei-Transfers gegen laufende TIPS-Downloads.

Synthetischer Windows-Offscreen-Test; keine Live-SSO-Navigation.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from ntf_insight.app.windows.main_window import MainWindow


def test_portable_transfer_is_locked_during_tips_download(tmp_path, monkeypatch):
    monkeypatch.setenv("NTF_INSIGHT_DATA_DIR", str(tmp_path / "app-data"))
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        tips = window.pages["cases"].tips_download
        assert tips is not None
        assert window._portable_transfer_ready()
        # The GUI must refuse an export or restore while TIPS is downloading.
        tips.worker = object()
        assert not window._portable_transfer_ready()
        tips.worker = None
        assert window._portable_transfer_ready()
    finally:
        window.close()
        app.processEvents()
