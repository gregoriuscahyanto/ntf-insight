"""Projektlöschung als separater Worker (kein blockierender GUI-Vorgang)."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal

from ntf_insight.storage.duckdb_store import DuckDBStore
from ntf_insight.storage.workflow_project_deletion import (
    fully_delete_project, remove_project_assignment,
)


class ProjectDeleteWorker(QThread):
    completed = Signal(object)
    failed = Signal(str)

    def __init__(
        self, data_dir: Path, profile: str, part: str, *,
        complete: bool,
    ) -> None:
        super().__init__()
        self.data_dir = Path(data_dir)
        self.profile = profile
        self.part = part
        self.complete = complete

    def run(self) -> None:
        try:
            store = DuckDBStore(self.data_dir / "ntf-insight.duckdb")
            if self.complete:
                result = fully_delete_project(
                    store, self.data_dir, self.profile, self.part,
                )
            else:
                result = remove_project_assignment(
                    store, self.profile, self.part,
                )
        except Exception as exc:
            self.failed.emit(
                "Projekt konnte nicht sicher gelöscht werden: "
                f"{type(exc).__name__}: {exc}"
            )
        else:
            self.completed.emit(result)
