"""Standalone, completely local Qt window for SMR-D offline conversion.

Launch with: python -m ntf_insight.smrd.offline_gui
The main app's navigation and sensitive dataset workflows remain untouched.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMainWindow, QMessageBox

from ntf_insight.app.pages.smrd_offline_page import SmrdOfflinePage
from ntf_insight.smrd.library import data_root


class _OfflineWindow(QMainWindow):
    def closeEvent(self, event) -> None:
        page = self.centralWidget()
        worker = getattr(page, "_worker", None)
        if worker is not None and worker.isRunning():
            QMessageBox.information(
                self, "Offline-Verarbeitung aktiv",
                "Der lokale Konvertierungsprozess läuft noch. "
                "Das Fenster kann nach dem Abschluss geschlossen werden.",
            )
            event.ignore()
            return
        super().closeEvent(event)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="SMR-D Offline-Workspace (no DTS license or Internet)"
    )
    parser.add_argument("--data-dir", type=Path, default=None)
    args = parser.parse_args(argv)
    application = QApplication.instance()
    owns_application = application is None
    if application is None:
        application = QApplication(sys.argv[:1])
    window = _OfflineWindow()
    window.setWindowTitle("NTF Insight · SMR-D Offline")
    window.resize(1000, 700)
    window.setCentralWidget(SmrdOfflinePage(data_root(args.data_dir)))
    window.show()
    if not owns_application:
        return 0
    return int(application.exec())


if __name__ == "__main__":
    raise SystemExit(main())
