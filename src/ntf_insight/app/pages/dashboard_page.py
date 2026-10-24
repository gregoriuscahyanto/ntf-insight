"""Projektübersicht für alle registrierten NTF-Workflows.

Die Daten werden in einem separaten Thread aus derselben lokalen DuckDB
ermittelt. Ein QEC-Schadteilfall ist nicht automatisch ein belegter Teiletausch.
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QHeaderView, QLabel, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from ntf_insight.storage.cluster_evidence_store import (
    ClusterEvidenceStore, part_key,
)
from ntf_insight.storage.duckdb_store import DuckDBStore
from ntf_insight.storage.qec_workflow_store import QecWorkflowStore
from ntf_insight.storage.workflow_projects import WorkflowProjectStore
from ntf_insight.storage.workflow_progress import WorkflowProgressStore
from ntf_insight.storage.workflow_source_coverage import get_workflow_coverage


HEADERS = (
    "Projekt", "FINs", "QEC-Fälle", "Tauschfälle", "NTF", "QEC-Berichte",
    "Unterlagen", "Geparst", "Cluster", "Status",
)


def project_overview_rows(store: DuckDBStore) -> list[dict]:
    """Belegte Werte je Projekt; keine globalen Dokumente mehrfach hochzählen."""
    root = Path(store.path).parent
    projects = WorkflowProjectStore(store).list_projects()
    if not projects:
        return []
    all_qec = QecWorkflowStore(store).rows(root / "qec")
    by_part: dict[str, list[dict]] = defaultdict(list)
    for item in all_qec:
        by_part[part_key(str(item.get("part_number") or ""))].append(item)
    evidence = ClusterEvidenceStore(store)
    progress = WorkflowProgressStore(store)
    # Ein Tauschfall erfordert einen tatsächlich gespeicherten Tauscheintrag,
    # nicht nur einen QEC-Schadteilfall.
    confirmed_swaps: dict[tuple[str, str], int] = defaultdict(int)
    for case in store.load_cases():
        part = part_key(str(getattr(case, "qec_part_number", "") or ""))
        if not part or case.investigated_replacement() is None:
            continue
        confirmed_swaps[(case.component_profile_id or "coolant_pump", part)] += 1
    with store.connect() as con:
        tables = {
            name for (name,) in con.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='main'"
            ).fetchall()
        }
        cluster_counts = {}
        if {
            "chatgpt_cluster", "workflow_ai_rounds", "workflow_second_ai_exports"
        }.issubset(tables):
            clusters = con.execute(
                "SELECT e.profile_id,e.part_key,COUNT(DISTINCT c.cluster_id) "
                "FROM chatgpt_cluster c "
                "JOIN workflow_ai_rounds r ON r.analyse_id=c.analyse_id "
                "JOIN workflow_second_ai_exports e "
                "ON e.analyse_id=r.analyse_id AND e.paket_id=r.paket_id "
                "WHERE r.round_number=2 GROUP BY e.profile_id,e.part_key"
            ).fetchall()
            cluster_counts = {(p, k): int(v) for p, k, v in clusters}

    overview = []
    for project in projects:
        cohort = (
            by_part.get(part_key(project.part_number), [])
            if project.profile_id == "coolant_pump" else []
        )
        scoped_evidence = evidence.list_files(
            project.profile_id, project.part_number,
        )
        coverage = get_workflow_coverage(
            store, root, cohort, scoped_evidence,
        )
        categories = ("tp_dashboard", "diagnosis_viewer", "tips_writer", "celonis")
        originals = sum(coverage[key].local_documents for key in categories)
        parsed = sum(coverage[key].parsed_documents for key in categories)
        # Technische Originale haben kein eigenes Downloader-Inventar.
        manual_technical = {
            (item.category, item.sha256)
            for item in scoped_evidence if item.category not in categories
        }
        originals += len(manual_technical)
        parsed += coverage["cdd_smrd"].parsed_documents
        stats = QecWorkflowStore.summarize_rows(cohort)
        state = progress.load(project.profile_id, project.part_number)
        overview.append({
            "title": project.title,
            "profile": project.profile_id,
            "part": project.part_number,
            "fins": stats["fins"],
            "cases": stats["cases"],
            "swaps": confirmed_swaps.get(
                (project.profile_id, part_key(project.part_number)), 0,
            ),
            "ntf": stats["ntf"],
            "reports": stats["downloaded"],
            "documents": originals,
            "parsed": parsed,
            "clusters": cluster_counts.get(
                (project.profile_id, part_key(project.part_number)), 0,
            ),
            "step": state.step + 1,
        })
    return overview


class _OverviewWorker(QThread):
    loaded = Signal(object)
    failed = Signal(str)

    def __init__(self, path: Path) -> None:
        super().__init__()
        self.path = Path(path)

    def run(self) -> None:
        try:
            self.loaded.emit(project_overview_rows(DuckDBStore(self.path)))
        except Exception as exc:
            self.failed.emit(type(exc).__name__)


class DashboardPage(QWidget):
    """Überblick über alle Projekte; Doppelklick öffnet den jeweiligen Workflow."""

    project_selected = Signal(str, str)
    loading_finished = Signal()

    def __init__(self, repository, mode="local", quicktests=None) -> None:
        super().__init__()
        self.store = quicktests.store if quicktests is not None else None
        self._worker: _OverviewWorker | None = None
        self._records: list[dict] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(25, 20, 25, 20)
        layout.setSpacing(12)
        layout.addWidget(QLabel("Projektübersicht", objectName="PageTitle"))
        self.table = QTableWidget(0, len(HEADERS))
        self.table.setHorizontalHeaderLabels(HEADERS)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        for index in range(1, len(HEADERS)):
            self.table.horizontalHeader().setSectionResizeMode(
                index, QHeaderView.ResizeMode.ResizeToContents
            )
        self.table.cellDoubleClicked.connect(self._open_row)
        layout.addWidget(self.table, 1)
        self.status = QLabel("", objectName="PageSubtitle")
        self.status.hide()
        layout.addWidget(self.status)
        self.open_button = QPushButton("Ausgewählten Workflow öffnen")
        self.open_button.clicked.connect(
            lambda: self._open_row(self.table.currentRow(), 0)
        )
        layout.addWidget(self.open_button)
        self.open_button.setEnabled(False)
        self.table.itemSelectionChanged.connect(
            lambda: self.open_button.setEnabled(self.table.currentRow() >= 0)
        )

    def refresh_async(self) -> bool:
        if self.store is None:
            self._loaded([])
            return False
        if self._worker is not None:
            return True
        worker = _OverviewWorker(self.store.path)
        self._worker = worker
        worker.loaded.connect(self._loaded)
        worker.failed.connect(self._failed)
        worker.finished.connect(self._finished)
        worker.start()
        return True

    def _loaded(self, rows: list[dict]) -> None:
        self._records = rows
        self.table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            values = (
                row["title"], row["fins"], row["cases"], row["swaps"],
                row["ntf"], row["reports"], row["documents"], row["parsed"],
                row["clusters"], f"Schritt {row['step']}/5",
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if column:
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignCenter
                    )
                self.table.setItem(index, column, item)
        self.status.setVisible(not bool(rows))
        self.status.setText("Noch keine Projekte angelegt." if not rows else "")
        self.loading_finished.emit()

    def _failed(self, reason: str) -> None:
        self.status.setText("Projektübersicht konnte nicht geladen werden: " + reason)
        self.status.show()
        self.loading_finished.emit()

    def _finished(self) -> None:
        worker, self._worker = self._worker, None
        if worker is not None:
            worker.deleteLater()

    def _open_row(self, row: int, _column: int) -> None:
        if 0 <= row < len(self._records):
            info = self._records[row]
            self.project_selected.emit(info["profile"], info["part"])
