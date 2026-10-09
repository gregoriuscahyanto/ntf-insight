"""Keep a single PySide6 application alive across all GUI regression tests.

Individual tests previously created/dropped local QApplication Python references
in arbitrary collection order. Qt 6 offscreen on Linux may then destroy shared
QObjects during Python/pytest teardown even after all assertions succeeded.
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_QT_APPLICATION = QApplication.instance() or QApplication([])


@pytest.fixture(scope="session", autouse=True)
def _keep_qt_application_alive():
    yield _QT_APPLICATION
    # Close *all* top-level Qt windows before Python begins destroying
    # module globals. Even closed offscreen widgets are often still alive
    # (QWidget.close() does not necessarily delete the QObject).
    # Defer their deletion through the Qt event queue to preserve QObject
    # parent/child lifetimes, especially QGraphicsScene and shared objects.
    for widget in list(QApplication.topLevelWidgets()):
        widget.close()
        widget.deleteLater()
    QCoreApplication.sendPostedEvents(
        None, QEvent.Type.DeferredDelete
    )
    _QT_APPLICATION.processEvents()
