"""Synthetische FIN-Verteilung als Donut, ohne Fahrzeugdaten."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from ntf_insight.app.widgets.fin_status_donut import FinStatusDonut


def test_donut_displays_exact_unique_fin_partition():
    app = QApplication.instance() or QApplication([])
    widget = FinStatusDonut()
    assert widget.values is None
    widget.set_values((5702, 5136, 900))
    assert widget.values == (5702, 5136, 900)
    assert "5.702 von 11.738" in widget.toolTip()
    assert "5.136 von 11.738" in widget.toolTip()
    assert "900 von 11.738" in widget.toolTip()
    widget.show()
    app.processEvents()
    assert not widget.grab().isNull()
    widget.set_values((0, 0, 0))
    assert not widget.grab().isNull()
    widget.set_values(None)
    assert "Noch keine" in widget.toolTip()
    widget.close()
    app.processEvents()


@pytest.mark.parametrize("values", [(-1, 0, 2), (1, 2), (1.5, 2, 3), (True, 2, 3)])
def test_donut_rejects_wrong_status_counts(values):
    widget = FinStatusDonut()
    with pytest.raises(ValueError, match="nichtnegative"):
        widget.set_values(values)
