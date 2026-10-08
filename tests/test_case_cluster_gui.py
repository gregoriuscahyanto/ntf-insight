"""Qt smoke tests for case-cluster heatmap and comparable measures."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from ntf_insight.app.widgets.case_cluster_panel import CaseClusterPanel
from ntf_insight.demo.synthetic_cases import build_demo_cases


def test_case_cluster_panel_shows_neighbours_and_heatmap() -> None:
    app = QApplication.instance() or QApplication([])
    panel = CaseClusterPanel(build_demo_cases())

    assert panel.focus.count() == len(build_demo_cases())
    assert panel.result is not None
    assert panel.cluster_model.rowCount() == len(build_demo_cases())
    assert panel.matrix_model.rowCount() >= 2
    assert panel.neighbor_model.rowCount() >= 1

    first = panel.matrix_model.index(0, 1)
    assert panel.matrix_model.data(first, Qt.ItemDataRole.ToolTipRole)
    assert panel.matrix_model.data(first, Qt.ItemDataRole.BackgroundRole)
    assert panel.matrix_model.data(first, Qt.ItemDataRole.ForegroundRole)

    panel.threshold.setValue(0.95)
    assert panel.result.threshold == 0.95

    panel.focus.setCurrentIndex(panel.focus.findData("DEMO-002"))
    assert panel.matrix_model.case_ids[0] == "DEMO-002"

    panel.resize(1100, 750)
    panel.show()
    app.processEvents()
    panel.close()
