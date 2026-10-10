"""Purely synthetic, offline Qt smoke for the QEC status pie."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from ntf_insight.app.widgets.cluster_case_pie import ClusterCasePie


def test_pie_values_and_accessible_local_status_counts():
    app = QApplication.instance() or QApplication([])
    chart = ClusterCasePie()
    assert chart.values is None
    chart.set_values((74, 96, 166))
    assert chart.values == (74, 96, 166)
    assert "74 von 336" in chart.toolTip()
    assert "96 von 336" in chart.toolTip()
    assert "166 von 336" in chart.toolTip()
    chart.show()
    app.processEvents()
    assert not chart.grab().isNull()
    chart.set_values((0, 0, 0))
    chart.grab()
    chart.set_values(None)
    assert "Noch keine" in chart.toolTip()
    chart.close()
    app.processEvents()


@pytest.mark.parametrize("values", [(-1, 2, 3), (1, 2), (1.5, 2, 3)])
def test_pie_rejects_invalid_partition(values):
    pie = ClusterCasePie()
    with pytest.raises(ValueError, match="nichtnegative"):
        pie.set_values(values)
