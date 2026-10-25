"""Nicht blockierende lokale Unterlagenimporte und Clusterkontext-Exporte."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal

from ntf_insight.reporting.cluster_context_package import export_cluster_context
from ntf_insight.storage.cluster_evidence_store import ClusterEvidenceStore


class ClusterEvidenceImportWorker(QThread):
    completed = Signal(int)
    failed = Signal(str)
    progress = Signal(str)

    def __init__(
        self, store: ClusterEvidenceStore, profile: str, part_number: str,
        category: str, paths: list[Path],
    ) -> None:
        super().__init__()
        self.store = store
        self.profile = profile
        self.part_number = part_number
        self.category = category
        self.paths = [Path(p) for p in paths]

    def run(self) -> None:
        try:
            count = self.store.add_files(
                self.profile, self.part_number, self.category, self.paths,
                progress=self.progress.emit,
            )
        except Exception as exc:  # Worker-Grenze: kein Qt-Thread-Absturz
            self.failed.emit(f"{type(exc).__name__}: {exc}")
            return
        self.completed.emit(count)


class ClusterContextExportWorker(QThread):
    completed = Signal(object)
    failed = Signal(str)
    progress = Signal(str)

    def __init__(
        self, store: ClusterEvidenceStore, profile: str, part_number: str,
        first_package: Path, destination: Path, *, include_originals: bool,
        include_confidential_basis: bool = False,
        first_result: dict | None = None,
    ) -> None:
        super().__init__()
        self.store = store
        self.profile = profile
        self.part_number = part_number
        self.first_package = Path(first_package)
        self.destination = Path(destination)
        self.include_originals = include_originals
        self.include_confidential_basis = include_confidential_basis
        self.first_result = first_result

    def run(self) -> None:
        try:
            result = export_cluster_context(
                self.store, self.profile, self.part_number,
                self.first_package, self.destination,
                include_originals=self.include_originals,
                include_confidential_basis=self.include_confidential_basis,
                first_result=self.first_result,
                progress=self.progress.emit,
            )
        except Exception as exc:  # Worker-Grenze: kein Qt-Thread-Absturz
            self.failed.emit(f"{type(exc).__name__}: {exc}")
            return
        self.completed.emit(result)
