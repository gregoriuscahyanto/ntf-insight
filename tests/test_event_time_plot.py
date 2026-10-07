import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from ntf_insight.analysis.timeline import build_timeline
from ntf_insight.app.widgets.event_time_plot import EventTimePlot
from ntf_insight.demo.synthetic_cases import build_demo_cases


def test_event_time_plot_accepts_case_timeline() -> None:
    app = QApplication.instance() or QApplication([])
    case = build_demo_cases()[0]
    plot = EventTimePlot()

    plot.set_entries(build_timeline(case))

    assert plot.minimumHeight() >= 270
    plot.resize(900, plot.minimumHeight())
    plot.show()
    app.processEvents()
    plot.close()
