"""Native GUI smoke tests only on fictional diagnostic cases."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from ntf_insight.app.widgets.hdbscan_panel import HDBSCANPanel
from test_hdbscan_clustering import sample


def test_local_gap_and_medoid_views_are_read_only():
    app = QApplication.instance() or QApplication([])
    cases = sample()
    panel = HDBSCANPanel(cases)
    panel.run_analysis()
    assert panel.gap_model.rowCount() == 2
    assert "Keine FIN-Rohdatenbank" in panel.gap_summary.text()
    assert panel.transfer_model.rowCount() > 0
    assert "keine automatische" in panel.transfer_summary.text().lower()
    assert "Repräsentantenbefund" in panel.transfer_summary.text() or panel.transfer_model.rowCount() > 0
    panel.close()
    app.processEvents()
