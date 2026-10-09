"""Qt smoke test for the explicit, read-only pilot inspection list."""
from __future__ import annotations

from PySide6.QtWidgets import QApplication
from ntf_insight.app.widgets.hdbscan_panel import HDBSCANPanel
from test_hdbscan_clustering import sample


def test_pilot_view_has_one_medoid_per_group_and_independent_targets():
    app = QApplication.instance() or QApplication([])
    panel = HDBSCANPanel(sample())
    panel.run_analysis()
    assert panel.result is not None
    assert panel.pilot_model.rowCount() == len(panel.result.clusters)
    assert panel.latest_pilot_plan.representative_count == len(panel.result.clusters)
    assert panel.pilot_inspection_model.rowCount() <= 3*len(panel.result.clusters)
    assert "keine technischen Ursachenchancen" in panel.pilot_summary.text()
    assert sum("Repräsentant" in row[2] for row in panel.pilot_inspection_model.rows) >= 2
    panel.close()
    app.processEvents()
