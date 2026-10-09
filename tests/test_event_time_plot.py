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


def test_event_time_plot_filters_specific_dtc() -> None:
    app = QApplication.instance() or QApplication([])
    case = build_demo_cases()[0]
    plot = EventTimePlot()
    plot.set_entries(build_timeline(case))

    plot.set_filter_text("P26F100")
    visible = plot._visible_entries()

    assert visible
    assert any(
        entry.kind == "diagnostic" and "P26F100" in entry.title
        for entry in visible
    )
    assert all(
        "P26F100" in entry.title
        for entry in visible if entry.kind == "diagnostic"
    )
    assert any(entry.kind == "diagnostic_session" for entry in visible)
    assert any(entry.kind == "replacement" for entry in visible)
    app.processEvents()
