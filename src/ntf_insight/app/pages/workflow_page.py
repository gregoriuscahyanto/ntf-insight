"""Neue zentrale Workflow-Seite; nutzt ausschließlich bestehende Import-/Export-Dienste."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings, Signal, QTimer
from PySide6.QtWidgets import (
    QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QProgressBar, QVBoxLayout, QWidget,
)

from ntf_insight.analysis.workflow_progress import WorkflowProgress
from ntf_insight.app.widgets.workflow_canvas import WorkflowCanvas
from ntf_insight.storage.qec_workflow_store import QecWorkflowStore
from ntf_insight.storage.quicktest_store import QuickTestStore


class WorkflowPage(QWidget):
    """Nicht scrollbar; primäre Bedienaktionen bleiben im vorhandenen Backend."""

    open_page = Signal(str)

    STAGE_PAGES = {
        "qec": "sources",
        "befund": "sources",
        "entscheidung": "sources",
        "kein_ntf": "sources",
        "ntf": "sources",
        "diagnose": "cases",
        "cluster": "cases",
    }
    TITLES = {
        "qec": "QEC-FIN-Liste",
        "befund": "Befundungsberichte",
        "entscheidung": "NTF-Entscheidung",
        "kein_ntf": "Kein NTF · Lieferantenprüfung",
        "ntf": "NTF · Übergabe",
        "diagnose": "CPC/SAM · Diagnose",
        "cluster": "Clusteranalyse",
    }

    def __init__(self, source_page: QWidget, database_path: Path,
                 data_dir: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("WorkflowPage")
        self.source_page = source_page
        self.workflow = QecWorkflowStore(source_page.import_service.store)
        self.quicktests = QuickTestStore(source_page.import_service.store)
        self.qec_root = Path(data_dir) / "qec"
        self._selected = "qec"
        self._last_progress: WorkflowProgress | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(26, 20, 26, 18)
        root.setSpacing(12)

        top = QHBoxLayout()
        heading = QVBoxLayout()
        heading.setSpacing(2)
        heading.addWidget(QLabel("Analyse-Workflow", objectName="PageTitle"))
        heading.addWidget(QLabel("QEC  ·  Diagnose  ·  NTF  ·  Cluster",
                                 objectName="PageSubtitle"))
        top.addLayout(heading, 1)
        self.refresh_button = QPushButton("↻  Aktualisieren")
        self.refresh_button.clicked.connect(self.refresh)
        top.addWidget(self.refresh_button)
        root.addLayout(top)

        selectors = QHBoxLayout()
        selectors.addWidget(QLabel("Bauteil"))
        self.component = QLineEdit()
        self.component.setPlaceholderText("z. B. Kühlmittelpumpe")
        self.component.setText(str(QSettings().value(
            "workflow/bauteil", "Kühlmittelpumpe",
        )))
        self.component.setMaximumWidth(255)
        selectors.addWidget(self.component, 2)
        selectors.addWidget(QLabel("Sachnummer"))
        self.part_number = QLineEdit()
        self.part_number.setPlaceholderText("Alle Sachnummern")
        self.part_number.setClearButtonEnabled(True)
        self.part_number.setText(str(QSettings().value("workflow/sachnummer", "")))
        selectors.addWidget(self.part_number, 2)
        self.part_number.editingFinished.connect(self.refresh)
        self.component.editingFinished.connect(self._save_component)
        root.addLayout(selectors)

        progress_row = QHBoxLayout()
        self.summary = QLabel("QEC-Daten prüfen", objectName="CardTitle")
        progress_row.addWidget(self.summary, 1)
        self.percent = QLabel("0 %")
        progress_row.addWidget(self.percent)
        root.addLayout(progress_row)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(7)
        root.addWidget(self.progress_bar)

        self.canvas = WorkflowCanvas()
        self.canvas.stage_selected.connect(self.select_stage)
        root.addWidget(self.canvas, 1)

        details = QFrame(objectName="WorkflowDetails")
        info = QVBoxLayout(details)
        info.setContentsMargins(16, 10, 16, 10)
        info.setSpacing(7)
        info_head = QHBoxLayout()
        self.stage_title = QLabel("QEC-FIN-Liste", objectName="CardTitle")
        info_head.addWidget(self.stage_title, 1)
        self.stage_state = QLabel("Offen", objectName="PageSubtitle")
        info_head.addWidget(self.stage_state)
        info.addLayout(info_head)
        self.stage_info = QLabel("Keine Liste geladen", objectName="PageSubtitle")
        info.addWidget(self.stage_info)
        row = QHBoxLayout()
        self.open_button = QPushButton("Schritt öffnen")
        self.open_button.clicked.connect(self._open_selected)
        row.addWidget(self.open_button)
        self.quicktest_button = QPushButton("QuickTests einlesen")
        self.quicktest_button.clicked.connect(source_page._import_existing_quicktests)
        row.addWidget(self.quicktest_button)
        self.qec_button = QPushButton("QEC einlesen")
        self.qec_button.clicked.connect(source_page._import_existing_qec)
        row.addWidget(self.qec_button)
        info.addLayout(row)
        root.addWidget(details)

        commands = QGridLayout()
        commands.setHorizontalSpacing(8)
        commands.setVerticalSpacing(8)
        self.self_import = QPushButton("Dateien selbst importieren")
        self.self_import.clicked.connect(self._self_import)
        commands.addWidget(self.self_import, 0, 0)
        self.cancel = QPushButton("Abbrechen")
        self.cancel.clicked.connect(source_page._cancel_import)
        commands.addWidget(self.cancel, 0, 1)
        self.resume = QPushButton("Fortsetzen")
        self.resume.clicked.connect(source_page._resume_import)
        commands.addWidget(self.resume, 0, 2)

        self.pc_export = QPushButton("PC-Export")
        self.pc_export.clicked.connect(source_page.portable_backup_panel._export)
        commands.addWidget(self.pc_export, 1, 0)
        self.pc_import = QPushButton("PC-Import")
        self.pc_import.clicked.connect(source_page.portable_backup_panel._restore)
        commands.addWidget(self.pc_import, 1, 1)
        self.ai_export = QPushButton("ChatGPT-Export")
        self.ai_export.clicked.connect(source_page.ki_analyse_panel._export)
        commands.addWidget(self.ai_export, 2, 0)
        self.ai_import = QPushButton("ChatGPT-Import")
        self.ai_import.clicked.connect(source_page.ki_analyse_panel._import_result)
        commands.addWidget(self.ai_import, 2, 1)
        self.parser_retry = QPushButton("Fehlerhafte QuickTests")
        self.parser_retry.clicked.connect(source_page._import_failed_quicktests)
        commands.addWidget(self.parser_retry, 1, 2)
        self.parser_export = QPushButton("Parser-Diagnose")
        self.parser_export.clicked.connect(source_page._export_parser_problems)
        commands.addWidget(self.parser_export, 2, 2)
        root.addLayout(commands)

        self.import_status = QLabel("", objectName="PageSubtitle")
        self.import_status.setMaximumHeight(42)
        self.import_status.setWordWrap(True)
        root.addWidget(self.import_status)
        self._last_running = False
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(600)
        self._poll_timer.timeout.connect(self._poll)
        self._poll_timer.start()
        self.refresh()

    def _poll(self) -> None:
        running = self.source_page._worker is not None
        message = self.source_page.import_status.text()
        if message != self.import_status.text():
            self._status_changed(message)
        if self._last_running and not running:
            self.refresh()
        self._last_running = running
        self._sync_controls()

    def _save_component(self) -> None:
        QSettings().setValue("workflow/bauteil", self.component.text().strip())

    def _self_import(self) -> None:
        if self.source_page._worker is not None:
            return
        filenames, _ = QFileDialog.getOpenFileNames(
            self, "Quelldateien importieren", "",
            "Quelldateien (*.pdf *.zip *.json *.xlsx *.xls *.csv *.xml *.pptx);;Alle Dateien (*)",
        )
        if filenames:
            self.source_page.source_type.setCurrentIndex(0)
            self.source_page._archive_paths([Path(name) for name in filenames])
            self._sync_controls()

    def _status_changed(self, message: str) -> None:
        # Never log FINs or file paths; this label is local to the running GUI.
        self.import_status.setText(message)
        self._sync_controls()

    def _sync_controls(self) -> None:
        source = self.source_page
        running = source._worker is not None
        transferring = (
            source.portable_backup_panel.worker is not None
            or source.ki_analyse_panel.worker is not None
            or source.ki_analyse_panel.import_worker is not None
        )
        self.cancel.setEnabled(running and source.cancel_import_button.isEnabled())
        self.resume.setEnabled(
            not running and not transferring and source.resume_import_button.isEnabled()
        )
        self.self_import.setEnabled(not running and not transferring)
        self.quicktest_button.setEnabled(not running and not transferring)
        self.qec_button.setEnabled(not running and not transferring)
        self.parser_retry.setEnabled(not running and not transferring)
        self.parser_export.setEnabled(not running and not transferring)

    def refresh(self) -> None:
        part = self.part_number.text().strip()
        QSettings().setValue("workflow/sachnummer", part)
        rows = self.workflow.rows(self.qec_root)
        current = WorkflowProgress.from_rows(
            rows, self.quicktests.list_fins(), self.workflow.handed_off_fins(),
            sachnummer=part,
        )
        self._last_progress = current
        labels = {
            "qec": f"{current.fins} FIN · {current.cases} Fälle",
            "befund": f"{current.downloaded}/{current.fins} Berichte",
            "entscheidung": f"{current.ntf + current.not_ntf}/{current.cases} bewertet",
            "kein_ntf": f"{current.not_ntf} Fälle",
            "ntf": f"{current.ntf} bestätigt",
            "diagnose": f"{current.quicktest_fins} QT · {current.with_tp} TP",
            "cluster": f"{current.handed_off} FIN freigegeben",
        }
        self.canvas.set_data(current.statuses(), labels, self._selected, current.next_step)
        self.summary.setText(
            f"{current.cases} Fälle · {current.fins} FIN · {current.open} offen"
        )
        self.percent.setText(f"{current.completion} % Datenabdeckung")
        self.progress_bar.setValue(current.completion)
        self.select_stage(self._selected)
        self._sync_controls()

    def select_stage(self, key: str) -> None:
        if key not in self.TITLES or self._last_progress is None:
            return
        self._selected = key
        self.canvas.selected = key
        self.canvas.update()
        self.stage_title.setText(self.TITLES[key])
        statuses = {"ready": "Erfasst", "progress": "In Bearbeitung", "off": "Offen"}
        self.stage_state.setText(statuses.get(self._last_progress.statuses()[key], "Offen"))
        self.stage_info.setText(self.canvas.labels.get(key, ""))
        self.open_button.setText(
            "Clusteranalyse öffnen" if key == "cluster" else "Schritt öffnen"
        )

    def _open_selected(self) -> None:
        self.open_page.emit(self.STAGE_PAGES[self._selected])
