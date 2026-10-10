"""Synthetic-only PySide6 tests of the FIN-wide 2D/3D scatter."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from ntf_insight.analysis.autoexport_fin_patterns import cluster_autoexport_fins
from ntf_insight.app.widgets.fin_cluster_projection_plot import (
    FinClusterProjectionPlot,
)
from test_autoexport_fin_patterns import _synthetic_population


def test_scatter_plots_all_dtc_fins_with_real_groups_and_pickable_points():
    app = QApplication.instance() or QApplication([])
    fins, codes, *_ = _synthetic_population()
    result = cluster_autoexport_fins(fins, codes)
    plot = FinClusterProjectionPlot()
    picked = []
    plot.fin_picked.connect(picked.append)
    plot.resize(800, 480)
    plot.show()
    plot.set_result(result)
    app.processEvents()

    assert len(plot._fins) == result.dtc_fins == 21
    assert plot._result is result
    assert plot.mode == "2d"
    assert not plot.grab().isNull()
    x, y = plot._screen[0]
    point = QPoint(round(x), round(y))
    actual_hit = plot._fin_at(QPointF(point))
    assert actual_hit is not None
    QTest.mouseClick(plot, Qt.MouseButton.LeftButton, pos=point)
    assert picked == [actual_hit]
    plot.set_highlight(result.groups[0].group_id)
    plot.grab()
    plot.close()
    app.processEvents()


def test_left_drag_rotates_3d_but_is_not_a_fin_selection():
    app = QApplication.instance() or QApplication([])
    fins, codes, *_ = _synthetic_population()
    result = cluster_autoexport_fins(fins, codes)
    plot = FinClusterProjectionPlot()
    plot.resize(800, 480)
    plot.set_result(result)
    plot.set_mode("3d")
    plot.show()
    app.processEvents()
    selected = []
    plot.fin_picked.connect(selected.append)
    initial = (plot.yaw, plot.elevation)
    start = QPoint(220, 180)
    QTest.mousePress(plot, Qt.MouseButton.LeftButton, pos=start)
    for moved in (start + QPoint(21, -12), start + QPoint(51, -24)):
        event = QMouseEvent(
            QEvent.Type.MouseMove, QPointF(moved),
            Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        QApplication.sendEvent(plot, event)
    QTest.mouseRelease(
        plot, Qt.MouseButton.LeftButton,
        pos=start + QPoint(51, -24),
    )
    assert plot.yaw != initial[0]
    assert plot.elevation != initial[1]
    assert not selected
    assert plot._result is result
    plot.reset_view()
    assert (plot.yaw, plot.elevation) == (32, 24)
    plot.close()
    app.processEvents()
