"""Regressionen: ECU-Unterlagen während Parsing und DuckDB-Dateisperre.

Synthetische lokale Tests ohne echte FINs, Portale oder Downloads.
"""
from __future__ import annotations

import os

import duckdb
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QFileDialog

from ntf_insight.app.windows.main_window import MainWindow


def _window(tmp_path, monkeypatch):
    monkeypatch.setenv("NTF_INSIGHT_DATA_DIR", str(tmp_path / "data"))
    app = QApplication.instance() or QApplication([])
    return app, MainWindow()


def test_ecu_documents_queued_while_parsing_and_imported_afterward(
    tmp_path, monkeypatch,
):
    app, window = _window(tmp_path, monkeypatch)
    source = window.pages["sources"]
    workflow = window.pages["workflow"]
    fake_worker = object()
    try:
        source._worker = fake_worker
        workflow.set_context_parser_busy("qec", True, "all")
        document = tmp_path / "ecu-messages.xlsx"
        document.write_bytes(b"synthetic")
        monkeypatch.setattr(
            QFileDialog, "getOpenFileNames",
            lambda *args, **kwargs: ([str(document)], ""),
        )
        # Tests behandeln die aktuell aktive Parser-Verbindung als freigegeben
        # für die *Dateiauswahl*, nicht als Freigabe für DB-Schreibzugriffe.
        monkeypatch.setattr(
            window, "_portable_transfer_ready",
            lambda *, allow_source_parser=False, allow_context_import=False:
            allow_source_parser or source._worker is None,
        )
        started = []
        monkeypatch.setattr(
            window, "_start_context_evidence_import",
            lambda *args: started.append(args),
        )
        window._context_import("ecu_messages")
        assert len(window._pending_context_imports) == 1
        assert not started
        assert "vorgemerkt" in workflow._notice
        source._worker = None
        workflow.set_context_parser_busy("qec", False)
        window._drain_pending_context_imports()
        assert len(started) == 1
        assert started[0][2] == "ecu_messages"
        assert started[0][3] == (document,)
        assert not window._pending_context_imports
    finally:
        source._worker = None
        window.close()
        app.processEvents()


def test_database_lock_during_refresh_does_not_escape_qt_callback(
    tmp_path, monkeypatch,
):
    app, window = _window(tmp_path, monkeypatch)
    workflow = window.pages["workflow"]
    try:
        def locked():
            raise duckdb.IOException("database is locked by another Python process")

        monkeypatch.setattr(workflow, "_update_tables", locked)
        workflow.refresh()
        assert workflow.note.isVisibleTo(workflow) or workflow.note.isVisible()
        assert "Datenbank derzeit gesperrt" in workflow.note.text()
        # Eine Statusmeldung darf keinen zweiten Datenbankversuch auslösen.
        workflow.set_notice("Ein Download läuft bereits.", error=True)
        assert "Ein Download läuft bereits." in workflow.note.text()
    finally:
        window.close()
        app.processEvents()


def test_requested_parse_stop_remains_visible_during_late_progress(
    tmp_path, monkeypatch,
):
    app, window = _window(tmp_path, monkeypatch)
    workflow = window.pages["workflow"]
    try:
        workflow.set_context_parser_busy("tp_dashboard", True, "all")
        workflow._context_stop_requested.add(("parse", "tp_dashboard"))
        workflow.set_context_operation(
            "tp_dashboard", True, "Abbruch angefordert",
        )
        label = workflow.context_operation_labels["tp_dashboard"]
        assert "Abbruch angefordert" in label.text()
        # Auch spätere Worker-Signale ohne Dateizähler dürfen den
        # Stopphinweis nicht durch "Dauer unbekannt" überschreiben.
        workflow.set_context_operation(
            "tp_dashboard", True, "Verknüpfte Fälle dauerhaft speichern …",
        )
        assert "Abbruch angefordert" in label.text()
        workflow.set_context_operation("tp_dashboard", False)
        workflow.set_context_parser_busy("tp_dashboard", False)
        assert not label.text()
    finally:
        window.close()
        app.processEvents()
