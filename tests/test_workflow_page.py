"""Regressionen für den schlanken Workflow, nur synthetische Fallwerte."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QScrollArea

from ntf_insight.analysis.workflow_progress import (
    WorkflowProgress, filter_part_rows, norm_sachnummer,
)
from ntf_insight.app.windows.main_window import MainWindow


def _rows():
    return [
        dict(fin="FIN-1", part_number="A 000 500 12 34",
             decision="NTF", report=True, tp_dashboard=True),
        dict(fin="FIN-2", part_number="A-000-500-12-34",
             decision="Offen", report=False, tp_dashboard=False),
        dict(fin="FIN-3", part_number="B111", decision="Kein NTF",
             report=True, tp_dashboard=True),
    ]


def test_sachnummer_is_not_hardcoded():
    assert norm_sachnummer("A 000 500 12 34") == norm_sachnummer("a-000.500-12-34")
    assert len(filter_part_rows(_rows(), "A0005001234")) == 2
    assert len(filter_part_rows(_rows(), "B111")) == 1
    assert len(filter_part_rows(_rows(), "")) == 3
    assert filter_part_rows(_rows(), "andere") == []


def test_workflow_progress_uses_real_coverage_not_ntf_guesswork():
    progress = WorkflowProgress.from_rows(
        _rows(), ["FIN-1"], ["FIN-1"], sachnummer="A0005001234",
    )
    assert progress.cases == 2
    assert progress.fins == 2
    assert progress.downloaded == 1
    assert progress.ntf == 1
    assert progress.open == 1
    assert progress.handed_off == 1
    assert progress.completion == 60
    assert progress.next_step == "befund"
    assert progress.statuses()["cluster"] == "progress"
    assert WorkflowProgress.from_rows([]).completion == 0


def test_new_workflow_page_actions_and_no_scroll(tmp_path, monkeypatch):
    monkeypatch.setenv("NTF_INSIGHT_DATA_DIR", str(tmp_path / "app-data"))
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    workflow = window.pages["workflow"]
    sources = window.pages["sources"]

    assert window.navigation.buttons["workflow"].isChecked()
    assert not workflow.findChildren(QScrollArea)
    assert workflow.part_number.isEnabled()
    assert workflow.self_import.isEnabled()
    assert workflow.pc_import.isEnabled()
    assert workflow.pc_export.isEnabled()
    assert workflow.ai_import.isEnabled()
    assert workflow.ai_export.isEnabled()
    assert workflow.parser_retry.isEnabled()
    assert not workflow.cancel.isEnabled()
    assert not workflow.resume.isEnabled()
    assert workflow._last_progress.cases == 0

    workflow.part_number.setText("SYNTH-123")
    workflow.refresh()
    assert workflow.part_number.text() == "SYNTH-123"
    workflow.canvas.stage_selected.emit("cluster")
    assert workflow._selected == "cluster"
    workflow._open_selected()
    assert window.navigation.buttons["cases"].isChecked()
    assert sources.portable_backup_panel is not None

    window.close()
    app.processEvents()
