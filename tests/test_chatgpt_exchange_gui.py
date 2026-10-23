"""GUI-Smoketest: QEC-Originale sind Opt-in, ChatGPT-Vorschläge bleiben separat."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from ntf_insight.app.windows.main_window import MainWindow


def test_chatgpt_return_and_qec_document_checkbox_are_visible(tmp_path, monkeypatch):
    monkeypatch.setenv("NTF_INSIGHT_DATA_DIR", str(tmp_path / "app-data"))
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    sources = window.pages["sources"]
    panel = sources.ki_analyse_panel
    assert panel is not None
    assert panel.export_button.isEnabled()
    assert panel.import_button.isEnabled()
    assert not panel.include_text.isChecked()
    assert not panel.include_qec_originale.isChecked()
    assert "Befundungsdokumente" in panel.include_qec_originale.text()
    assert "nicht" in panel.review_note.text().casefold()
    assert panel.review_model.rowCount() == 0
    assert not panel.review_confirm.isEnabled()
    assert not panel.review_reject.isEnabled()
    assert panel._guard is not None and panel._guard()

    case_page = window.pages["cases"]
    assert case_page.chatgpt_analysen is not None
    assert "Keine ChatGPT-Analyse" in case_page.chatgpt_result_text.text() or (
        "Noch keine" in case_page.chatgpt_result_text.text()
    )
    window.close()
    app.processEvents()
