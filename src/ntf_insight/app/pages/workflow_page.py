"""Kompakter fünfstufiger Arbeitsbereich für die lokale NTF-Prüfung.

Die fünf Workflow-Stationen stehen nebeneinander. Darunter zeigt eine
QStackedWidget genau EINEN Arbeitsschritt; nur Tabellen scrollen intern.
Rohdatenparser, QEC-Downloader und ChatGPT-Vertrag werden nicht dupliziert.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import json
import re
import time
from dataclasses import replace
from datetime import datetime

from PySide6.QtCore import QSortFilterProxyModel, QTimer, Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QGridLayout, QHBoxLayout,
    QFrame, QHeaderView, QLabel, QLayout, QLineEdit, QMenu, QProgressBar,
    QPushButton, QScrollArea, QSizePolicy, QStackedWidget, QTabWidget, QTableView,
    QToolButton, QVBoxLayout, QWidget,
)

from ntf_insight.acquisition.qec_archive import local_qec_archive
from ntf_insight.acquisition.qec_tool import QecTarget, parse_qec_targets
from ntf_insight.ingestion.artifacts import SourceType
from ntf_insight.app.models.simple_table_model import SimpleTableModel
from ntf_insight.app.widgets.workflow_donut import WorkflowDonut
from ntf_insight.components.registry import list_component_profiles
from ntf_insight.reporting.chatgpt_exchange import ChatGPTAnalyseStore
from ntf_insight.storage.cluster_evidence_store import (
    CATEGORY_LABELS, ClusterEvidenceStore, EVIDENCE_CATEGORIES,
)
from ntf_insight.storage.workflow_ai_chain import WorkflowAIChainStore
from ntf_insight.storage.workflow_projects import WorkflowProjectStore
from ntf_insight.storage.workflow_source_activity import WorkflowSourceActivity
from ntf_insight.storage.workflow_ssl_selection import (
    WorkflowSSLSelection, fin_ssl_groups,
)
from ntf_insight.storage.workflow_source_coverage import (
    SourceCoverage, get_workflow_coverage,
)
from ntf_insight.storage.workflow_progress import (
    STEP_COUNT, WorkflowProgressStore, normalize_part_number,
)


def _create_table(headers: tuple[str, ...]) -> tuple[QTableView, SimpleTableModel]:
    """Eine echte FIN-Tabelle statt unscrollbarer Kachelinhalte."""
    model = SimpleTableModel(headers)
    table = QTableView()
    table.setModel(model)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setAlternatingRowColors(True)
    table.verticalHeader().setVisible(False)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    table.setMinimumHeight(140)
    table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    return table, model


# Beide Quellenbereiche nutzen exakt dieselben Spaltenbreiten, Rasterabstände
# und Buttonhöhen. Separate GridLayouts ohne diese Vorgaben würden auseinanderlaufen.
_SOURCE_COLUMNS = (
    ("Quelle", 108),
    ("Portalabruf", 274),
    ("Parser", 230),
    ("Fehleranalyse", 150),
    ("Datei", 120),
    ("Letzter Abruf / Import", 190),
    ("Dokumente / FINs", None),
)
_SOURCE_ACTION_HEIGHT = 36
_SOURCE_ACTION_SPACING = 6
_SOURCE_DOUBLE_HEIGHT = _SOURCE_ACTION_HEIGHT * 2 + _SOURCE_ACTION_SPACING


def _source_grid(frame: QFrame, *, header: bool = False) -> QGridLayout:
    grid = QGridLayout(frame)
    grid.setContentsMargins(9, 0 if header else 8, 9, 0 if header else 8)
    grid.setHorizontalSpacing(8)
    grid.setVerticalSpacing(0)
    for index, (_heading, width) in enumerate(_SOURCE_COLUMNS):
        if width is not None:
            grid.setColumnMinimumWidth(index, width)
    grid.setColumnStretch(len(_SOURCE_COLUMNS) - 1, 1)
    return grid


def _source_header() -> QFrame:
    frame = QFrame(objectName="SourceTableHeader")
    grid = _source_grid(frame, header=True)
    for index, (heading, width) in enumerate(_SOURCE_COLUMNS):
        label = QLabel(heading, objectName="PageSubtitle")
        if width is not None:
            label.setFixedWidth(width)
        grid.addWidget(label, 0, index)
    return frame


def _source_stack(column: int, buttons: list[QPushButton]) -> QWidget:
    """Fixe Buttonhöhe und einheitliche vertikale Abstände ohne Abschneiden."""
    width = _SOURCE_COLUMNS[column][1]
    assert width is not None
    holder = QWidget()
    holder.setFixedWidth(width)
    layout = QVBoxLayout(holder)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(_SOURCE_ACTION_SPACING)
    for button in buttons:
        button.setFixedHeight(_SOURCE_ACTION_HEIGHT)
        layout.addWidget(button)
    return holder


def _source_single(column: int, button: QPushButton) -> QPushButton:
    width = _SOURCE_COLUMNS[column][1]
    assert width is not None
    button.setFixedWidth(width)
    button.setFixedHeight(_SOURCE_DOUBLE_HEIGHT)
    return button


class WorkflowPage(QWidget):
    """Die Startseite bleibt geöffnet; Stationen ändern den lokalen Inhalt."""

    navigate = Signal(str, str)
    action_requested = Signal(str)
    project_selected = Signal(str, str)
    cohort_updated = Signal()
    step_loading = Signal(bool)

    STEPS = (
        ("QEC-FIN-Liste", "QEC-Kohorte", "sources", "qec_list"),
        ("QEC-Befundung", "Berichte", "cases", "qec_reports"),
        ("NTF-Entscheidung", "Prüfung", "sources", "qec_decision"),
        ("Unterlagen", "CPC3 / TP", "workflow", "evidence"),
        ("Clusteranalyse", "Lokal + ChatGPT", "workflow", "cluster"),
    )

    def __init__(
        self, progress_store: WorkflowProgressStore, *, qec_store=None,
        repository=None, quicktests=None, mode="local",
    ) -> None:
        super().__init__(objectName="WorkflowPage")
        self.progress_store = progress_store
        self.qec_store = qec_store
        self.repository = repository
        self.quicktests = quicktests
        self.mode = mode
        self.profile_id, part = progress_store.current_context()
        self._context_part = part
        self.state = replace(
            progress_store.load(self.profile_id, part), paused=False
        )
        self.qec_root = progress_store.store.path.parent / "qec"
        self._all_rows: list[dict] = []
        self._scoped_rows: list[dict] = []
        self._chatgpt_by_case: dict[str, dict] = {}
        self._source_name = ""
        self._data_error = ""
        self._notice = ""
        self._error_step: int | None = None
        self._busy = False
        self._qec_download_scope: str | None = None
        self._qec_stop_requested = False
        self._import_busy = False
        self._import_can_resume = False
        self.analysis_store = ChatGPTAnalyseStore(progress_store.store) if qec_store else None
        self.context_store = ClusterEvidenceStore(progress_store.store)
        self.project_store = WorkflowProjectStore(progress_store.store)
        self.ai_chain = WorkflowAIChainStore(progress_store.store)
        self.ssl_selection = WorkflowSSLSelection(progress_store.store)
        self.source_activity = WorkflowSourceActivity(progress_store.store)
        self._source_coverage: dict[str, SourceCoverage] = {}
        self._project_rows: list[dict] = []
        self._fin_findings: dict[str, str] = {}
        self.context_files = []
        self.first_package = None
        self._context_busy = False
        self._context_scrapers_busy: set[str] = set()
        self._context_scrape_active: dict[str, str] = {}
        self._context_parsers_busy: dict[str, str] = {}
        self._context_stop_requested: set[tuple[str, str]] = set()
        self._context_operation_started: dict[str, float] = {}
        self._transfer_started_at: float | None = None


        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 13, 18, 13)
        outer.setSpacing(7)

        header = QHBoxLayout()
        self.project_title = QLabel(objectName="PageTitle")
        header.addWidget(self.project_title, 1)
        self.project_combo = QComboBox()
        self.project_combo.setAccessibleName("Aktives Sachnummern-Projekt")
        self.project_combo.setMinimumWidth(130)
        self.project_combo.currentIndexChanged.connect(self._project_combo_changed)
        header.addWidget(self.project_combo)
        self.new_project_button = QPushButton("+ Neues Projekt")
        self.new_project_button.clicked.connect(
            lambda: self.action_requested.emit("new_project")
        )
        header.addWidget(self.new_project_button)
        self.adopt_button = QPushButton("Bestehenden QEC-Bestand übernehmen")
        self.adopt_button.clicked.connect(
            lambda: self.action_requested.emit("adopt_legacy")
        )
        self.settings_button = QPushButton("Einstellungen")
        self.settings_button.clicked.connect(
            lambda: self.action_requested.emit("project_settings")
        )
        header.addWidget(self.settings_button)
        self.project_export_button = QPushButton("Projekt-Export")
        self.project_export_button.clicked.connect(
            lambda: self.action_requested.emit("project_export")
        )
        header.addWidget(self.project_export_button)
        self.project_import_button = QPushButton("Projekt-Import")
        self.project_import_button.clicked.connect(
            lambda: self.action_requested.emit("project_import")
        )
        header.addWidget(self.project_import_button)
        outer.addLayout(header)
        self.project_transfer_bar = QProgressBar()
        self.project_transfer_bar.setRange(0, 100)
        self.project_transfer_bar.setFormat("Projekttransfer: %p %")
        self.project_transfer_bar.hide()
        outer.addWidget(self.project_transfer_bar)
        self.project_transfer_eta = QLabel(objectName="PageSubtitle")
        self.project_transfer_eta.hide()
        outer.addWidget(self.project_transfer_eta)
        self.project_ecus_label = QLabel(objectName="PageSubtitle")
        subheader = QHBoxLayout()
        subheader.addWidget(self.project_ecus_label, 1)
        self.adopt_button.setText("Vorhandenen QEC-Bestand übernehmen")
        subheader.addWidget(self.adopt_button)
        outer.addLayout(subheader)

        # API für bestehende Import-/GUI-Funktionen; editierbar ist nur das
        # Projekt auf der Einstellungsseite, nicht die globale Kopfzeile.
        self.profile = QComboBox(self)
        self.profile.hide()
        self.profile.setAccessibleName("Bauteilprofil")
        for item in list_component_profiles():
            label = (
                "Kühlmittelpumpe" if item.profile_id == "coolant_pump"
                else "HV-Batterie" if item.profile_id == "hv_battery"
                else item.display_name
            )
            self.profile.addItem(label, item.profile_id)
        self.profile.setCurrentIndex(max(0, self.profile.findData(self.profile_id)))
        self.profile.currentIndexChanged.connect(self._change_context)
        self.part_number = QLineEdit(part, self)
        self.part_number.hide()
        self.part_number.setPlaceholderText("Sachnummer · alle")
        self.part_number.setMaximumWidth(215)
        self.part_number.setMaxLength(120)
        self.part_number.setAccessibleName("Sachnummer zur QEC-Kohortenfilterung")
        self.part_number.editingFinished.connect(self._change_context)
        self._refresh_project_selector()

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setMaximumHeight(16)
        self.progress.setTextVisible(False)
        outer.addWidget(self.progress)
        self.progress_label = QLabel(objectName="PageSubtitle")
        outer.addWidget(self.progress_label)

        # Ein horizontaler Prozess: keine 2x3-Flächen, kein Seiten-Scrollbereich.
        steps = QHBoxLayout()
        steps.setSpacing(6)
        self.cards: list[QPushButton] = []
        for i, (name, *_rest) in enumerate(self.STEPS):
            button = QPushButton(objectName="WorkflowStep")
            button.setCheckable(True)
            button.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            button.setMinimumHeight(77)
            button.setMaximumHeight(86)
            button.setAccessibleName(f"Schritt {i + 1}: {name} öffnen")
            button.setToolTip(f"{name} auswählen und Inhalte darunter anzeigen")
            button.clicked.connect(lambda _checked=False, index=i: self._open_step(index))
            self.cards.append(button)
            steps.addWidget(button, 1)
            if i + 1 < len(self.STEPS):
                arrow = QLabel("›")
                arrow.setObjectName("WorkflowArrow")
                arrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
                steps.addWidget(arrow)
        outer.addLayout(steps)

        self.current_title = QLabel(objectName="CardTitle")
        outer.addWidget(self.current_title)

        self.workspaces = QStackedWidget()
        self.workspaces.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        outer.addWidget(self.workspaces, 1)
        self._build_step_one()
        self._build_step_two()
        self._build_step_three()
        self._build_step_four()
        self._build_following_steps()

        self.note = QLabel(objectName="PageSubtitle")
        self.note.setWordWrap(True)
        self.note.hide()  # Nur relevante Fehler/konkrete Vorgangsresultate anzeigen.
        outer.addWidget(self.note)
        self.refresh_data()
        self.refresh_ai_chain()
        self._refresh_project_selector()

    def _workspace(self, title: str, subtitle: str = "") -> tuple[QWidget, QVBoxLayout]:
        widget = QWidget()
        body = QVBoxLayout(widget)
        body.setContentsMargins(0, 4, 0, 0)
        body.setSpacing(7)
        heading = QLabel(title, objectName="CardTitle")
        body.addWidget(heading)
        # Hilfetexte werden in Tooltips statt als dauerhafte Fließtexte gezeigt.
        self.workspaces.addWidget(widget)
        return widget, body

    @staticmethod
    def _add_action(row: QHBoxLayout, title: str, signal, *, tooltip: str = "") -> QPushButton:
        button = QPushButton(title, objectName="WorkflowAction")
        button.setToolTip(tooltip)
        button.clicked.connect(signal)
        row.addWidget(button)
        return button

    def _build_step_one(self) -> None:
        _, body = self._workspace(
            "01 · QEC-FIN-Liste",
            "QEC-Excel einlesen, FINs zur Sachnummer anzeigen und als CSV speichern.",
        )
        actions = QHBoxLayout()
        self.qec_import_button = self._add_action(
            actions, "QEC-FIN-Liste importieren",
            lambda: self.action_requested.emit("qec_list_import"),
        )
        self.qec_portal_button = self._add_action(
            actions, "QEC öffnen · FIN-Liste herunterladen",
            lambda: self.action_requested.emit("qec_list_portal"),
            tooltip="Öffnet QEC im Browser. Sachnummern-Filter und Excel-Export "
                    "erfolgen dort manuell; ein automatischer QEC-FIN-Export "
                    "ist noch nicht verifiziert.",
        )
        self.qec_export_button = self._add_action(
            actions, "Gefilterte FIN-Liste als CSV",
            lambda: self.action_requested.emit("qec_list_csv"),
            tooltip="Exportiert die bereits lokal importierte QEC-Liste "
                    "für die eingegebene Sachnummer.",
        )
        actions.addStretch(1)
        body.addLayout(actions)
        import_controls = QHBoxLayout()
        self.cancel_import_button = self._add_action(
            import_controls, "Import abbrechen",
            lambda: self.action_requested.emit("qec_list_cancel"),
        )
        self.resume_import_button = self._add_action(
            import_controls, "Import fortsetzen",
            lambda: self.action_requested.emit("qec_list_resume"),
        )
        import_controls.addStretch(1)
        body.addLayout(import_controls)
        self.source_label = QLabel(objectName="PageSubtitle")
        body.addWidget(self.source_label)
        dashboard = QHBoxLayout()
        self.ssl_donut = WorkflowDonut("SSL-Endbefund · eindeutige FINs")
        dashboard.addWidget(self.ssl_donut, 2)
        selection_box = QVBoxLayout()
        selection_box.addWidget(QLabel("FINs für Schritte 02–05"))
        self.ssl_filter_button = QToolButton()
        self.ssl_filter_button.setText("SSL-Endbefunde auswählen")
        self.ssl_filter_button.setPopupMode(
            QToolButton.ToolButtonPopupMode.InstantPopup
        )
        self.ssl_menu = QMenu(self.ssl_filter_button)
        self.ssl_filter_button.setMenu(self.ssl_menu)
        selection_box.addWidget(self.ssl_filter_button)
        self.ssl_select_all = QPushButton("Alle übernehmen")
        self.ssl_select_all.clicked.connect(lambda: self._select_all_ssl(True))
        selection_box.addWidget(self.ssl_select_all)
        self.ssl_selection_status = QLabel(objectName="PageSubtitle")
        self.ssl_selection_status.setWordWrap(True)
        selection_box.addWidget(self.ssl_selection_status)
        selection_box.addStretch(1)
        dashboard.addLayout(selection_box, 1)
        body.addLayout(dashboard)
        self.fin_search = QLineEdit()
        self.fin_search.setPlaceholderText("FIN, QEC-Fall oder Referenz suchen …")
        body.addWidget(self.fin_search)
        self.fin_table, self.fin_model = _create_table((
            "FIN", "QEC-Fall", "Referenz", "Sachnummer",
            "SSL-Endbefund", "TP", "NTF-Status", "QEC-Bericht",
        ))
        self.fin_proxy = QSortFilterProxyModel(self)
        self.fin_proxy.setSourceModel(self.fin_model)
        self.fin_proxy.setFilterKeyColumn(-1)
        self.fin_proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.fin_table.setModel(self.fin_proxy)
        self.fin_search.textChanged.connect(self.fin_proxy.setFilterFixedString)
        body.addWidget(self.fin_table, 1)

    def _build_step_two(self) -> None:
        _, body = self._workspace(
            "02 · QEC-Befundungsberichte",
            "Abruf ausschließlich für die QEC-FINs und Referenzen der gewählten Sachnummer.",
        )
        actions = QVBoxLayout()
        actions.setSpacing(5)
        self.qec_action_header = _source_header()
        actions.addWidget(self.qec_action_header)

        self.qec_action_row = QFrame(objectName="SourceCoverageRow")
        self.qec_action_row.setProperty("coverageState", "pending")
        self.qec_action_row.setMinimumHeight(138)
        grid = _source_grid(self.qec_action_row)
        name = QLabel("QEC-Befundung")
        name.setFixedWidth(_SOURCE_COLUMNS[0][1])
        name.setWordWrap(True)
        grid.addWidget(name, 0, 0)

        self.download_all_button = QPushButton(
            "Alle QEC-Berichte neu abrufen", objectName="WorkflowAction",
        )
        self.download_all_button.setToolTip(
            "Alle QEC-Berichte der aktuellen Projekt-FINs herunterladen oder "
            "aktualisieren. Bereits vorhandene Berichte werden erneut abgefragt."
        )
        self.download_all_button.clicked.connect(
            lambda: self._trigger_qec_download("all")
        )
        self.download_missing_button = QPushButton(
            "Download fortsetzen", objectName="WorkflowAction",
        )
        self.download_missing_button.clicked.connect(
            lambda: self._trigger_qec_download("missing")
        )
        self.download_selected_button = QPushButton(
            "Markierte herunterladen", objectName="WorkflowAction",
        )
        self.download_selected_button.clicked.connect(
            lambda: self._trigger_qec_download("selected")
        )
        # Kompatible Referenz für vorhandene Aktionen/Tests; kein Stop-Zusatzfeld.
        self.cancel_download_button = QPushButton("Abruf abbrechen", self)
        self.cancel_download_button.hide()
        self.cancel_download_button.clicked.connect(
            lambda: self.action_requested.emit("qec_download_cancel")
        )
        grid.addWidget(_source_stack(1, [
            self.download_all_button, self.download_missing_button,
            self.download_selected_button,
        ]), 0, 1, Qt.AlignmentFlag.AlignTop)

        self.qec_parse_all_button = QPushButton(
            "Alle QEC-Berichte neu parsen", objectName="WorkflowAction",
        )
        self.qec_parse_all_button.clicked.connect(
            lambda: self._trigger_context_parse("qec", "all")
        )
        self.qec_parse_resume_button = QPushButton(
            "Ausstehendes Parsing fortsetzen", objectName="WorkflowAction",
        )
        self.qec_parse_resume_button.clicked.connect(
            lambda: self._trigger_context_parse("qec", "resume")
        )
        grid.addWidget(_source_stack(2, [
            self.qec_parse_all_button, self.qec_parse_resume_button,
        ]), 0, 2, Qt.AlignmentFlag.AlignTop)

        self.qec_problem_zip_button = _source_single(
            3, QPushButton("Fehler-ZIP exportieren", objectName="WorkflowAction"),
        )
        self.qec_problem_zip_button.setToolTip(
            "Nicht parsebare QEC-Dateien als lokales ZIP exportieren. "
            "Standardmäßig ohne Originale; vertrauliche Originaldateien "
            "nur nach gesonderter Bestätigung."
        )
        self.qec_problem_zip_button.clicked.connect(
            lambda: self.action_requested.emit("parser_diagnostics:qec")
        )
        grid.addWidget(self.qec_problem_zip_button, 0, 3, Qt.AlignmentFlag.AlignTop)

        self.local_qec_button = _source_single(
            4, QPushButton("Lokale Berichte", objectName="WorkflowAction"),
        )
        self.local_qec_button.setToolTip("Lokale QEC-Berichte auswählen und einlesen")
        self.local_qec_button.clicked.connect(
            lambda: self.action_requested.emit("qec_import_local")
        )
        grid.addWidget(self.local_qec_button, 0, 4, Qt.AlignmentFlag.AlignTop)

        self.qec_last_fetch = QLabel("—", objectName="PageSubtitle")
        self.qec_last_fetch.setFixedWidth(_SOURCE_COLUMNS[5][1])
        self.qec_last_fetch.setWordWrap(True)
        grid.addWidget(self.qec_last_fetch, 0, 5)

        self.qec_status = QLabel(objectName="PageSubtitle")
        self.qec_status.setWordWrap(True)
        grid.addWidget(self.qec_status, 0, 6)
        actions.addWidget(self.qec_action_row)
        body.addLayout(actions)
        donuts = QHBoxLayout()
        donuts.setSpacing(16)
        self.qec_donut = WorkflowDonut("QEC-Berichte · eindeutige FINs")
        self.qec_parsing_donut = WorkflowDonut("QEC-Parsing · eindeutige FINs")
        donuts.addWidget(self.qec_donut)
        donuts.addWidget(self.qec_parsing_donut)
        body.addLayout(donuts)
        self.qec_coverage = QLabel(objectName="PageSubtitle")
        self.qec_coverage.setWordWrap(True)
        self.qec_coverage.hide()  # Parsing-Donut und Tabellenstatus reichen.
        self.qec_parse_progress = QProgressBar()
        self.qec_parse_progress.setMaximumHeight(9)
        self.qec_parse_progress.setTextVisible(False)
        body.addWidget(self.qec_parse_progress)
        self.qec_table, self.qec_model = _create_table((
            "FIN", "QEC-Fall", "Referenz", "Sachnummer",
            "Letzter Download", "Downloadstatus", "Parsing",
        ))
        self.qec_table.selectionModel().selectionChanged.connect(
            lambda *_: self._refresh_controls()
        )
        body.addWidget(self.qec_table, 1)

    def _build_step_three(self) -> None:
        _, body = self._workspace(
            "03 · NTF-Entscheidung mit ChatGPT",
            "Vorschläge sind zunächst ungeprüft und werden nicht automatisch zu QEC-Fallentscheidungen.",
        )
        actions = QHBoxLayout()
        self.ai_export_button = self._add_action(
            actions, "Für ChatGPT exportieren (ZIP)",
            lambda: self.action_requested.emit("ai_export"),
            tooltip="Versioniertes Analysepaket mit JSON-Ergebnisvorlage und Schema.",
        )
        self.ai_import_button = self._add_action(
            actions, "ChatGPT-Ergebnis importieren (JSON)",
            lambda: self.action_requested.emit("ai_import"),
            tooltip="Prüft Paket-ID, Fallzuordnung und Belege. "
                    "Eine QEC-Entscheidung wird dabei nicht überschrieben.",
        )
        actions.addStretch(1)
        body.addLayout(actions)
        for button in (self.ai_export_button, self.ai_import_button):
            button.setMinimumHeight(52)
            button.setMinimumWidth(250)
            button.setObjectName("ClusterStartButton")
        dashboards = QHBoxLayout()
        self.ntf_donut = WorkflowDonut("NTF-Bewertung · eindeutige FINs")
        self.cause_donut = WorkflowDonut("Verursachungsbereich · ChatGPT-Vorschlag")
        dashboards.addWidget(self.ntf_donut, 1)
        dashboards.addWidget(self.cause_donut, 1)
        body.addLayout(dashboards)
        self.ai_package_status = QLabel(objectName="PageSubtitle")
        self.ai_package_status.setWordWrap(True)
        self.ai_package_status.hide()
        body.addWidget(self.ai_package_status)
        self.ntf_status = QLabel(objectName="PageSubtitle")
        body.addWidget(self.ntf_status)
        self.ntf_table, self.ntf_model = _create_table((
            "FIN", "QEC-Fall", "SSL-Endbefund", "QEC-Entscheidung",
            "ChatGPT-Vorschlag", "Verursachungsbereich", "Prüfstatus",
        ))
        body.addWidget(self.ntf_table, 1)

    def _build_step_four(self) -> None:
        """Unterlagenzentrale: Quellenabrufe und kategorisierte technische Dokumente."""
        _, body = self._workspace(
            "04 · Unterlagen für den zweiten ChatGPT-Durchlauf",
            "Quellen abrufen oder Dateien einsammeln · Unbekannte Scraper werden nicht simuliert.",
        )
        scraper_grid = QVBoxLayout()
        scraper_grid.setSpacing(4)
        self.context_scraper_buttons: dict[str, dict[str, QPushButton]] = {}
        self.context_import_buttons: dict[str, QPushButton] = {}
        self.context_technical_resume: dict[str, QPushButton] = {}
        self.context_technical_parse: dict[str, QPushButton] = {}
        self.context_counts: dict[str, QLabel] = {}
        self.context_source_rows: dict[str, QFrame] = {}
        self.context_technical_rows: dict[str, QFrame] = {}
        self.context_source_dates: dict[str, QLabel] = {}
        self.context_source_names: dict[str, QLabel] = {}
        self.context_coverage_bars: dict[str, QProgressBar] = {}
        self.context_operation_bars: dict[str, QProgressBar] = {}
        self.context_operation_labels: dict[str, QLabel] = {}

        self.context_source_header = _source_header()
        scraper_grid.addWidget(self.context_source_header)

        for category, label in EVIDENCE_CATEGORIES[:4]:
            frame = QFrame(objectName="SourceCoverageRow")
            frame.setProperty("coverageState", "pending")
            frame.setMinimumHeight(94)
            grid = _source_grid(frame)
            self.context_source_rows[category] = frame
            name = QLabel(label)
            name.setFixedWidth(_SOURCE_COLUMNS[0][1])
            name.setWordWrap(True)
            grid.addWidget(name, 0, 0)
            self.context_source_names[category] = name

            buttons: dict[str, QPushButton] = {}
            fetch_buttons: list[QPushButton] = []
            all_fetch = QPushButton("Alle FINs neu abrufen", objectName="WorkflowAction")
            all_fetch.setMinimumHeight(32)
            all_fetch.setToolTip(
                "Erneuter Portalabruf der gesamten FIN-Kohorte; vor dem Start "
                "wird eine Bestätigung abgefragt. Es werden keine Quellen gelöscht."
            )
            all_fetch.clicked.connect(
                lambda _checked=False, c=category:
                self._trigger_context_fetch(c, "all")
            )
            if category not in {"diagnosis_viewer", "tips_writer"}:
                all_fetch.setText("Kein Scraper")
                all_fetch.setEnabled(False)
                all_fetch.setToolTip("Für diese Quelle ist kein Portalscraper verfügbar.")
            buttons["all"] = all_fetch
            fetch_buttons.append(all_fetch)

            missing = QPushButton("Nur fehlende FINs abrufen", objectName="WorkflowAction")
            missing.setMinimumHeight(32)
            missing.setToolTip(
                "Nur FINs ohne vollständigen Abrufstand erneut abfragen."
            )
            missing.clicked.connect(
                lambda _checked=False, c=category:
                self._trigger_context_fetch(c, "missing")
            )
            missing.setVisible(category in {"diagnosis_viewer", "tips_writer"})
            buttons["missing"] = missing
            fetch_buttons.append(missing)
            grid.addWidget(
                _source_stack(1, fetch_buttons), 0, 1, Qt.AlignmentFlag.AlignTop
            )

            parse_all = QPushButton(
                "Alle Dokumente neu parsen", objectName="WorkflowAction"
            )
            parse_all.setToolTip(
                "Alle verifizierten lokalen Dokumente erneut mit dem vorhandenen "
                "Parser verarbeiten. Ohne erneute Portalabfrage."
            )
            parse_all.clicked.connect(
                lambda _checked=False, c=category:
                self._trigger_context_parse(c, "all")
            )
            if category == "celonis":
                parse_all.setText("Kein Parser")
                parse_all.setEnabled(False)
                parse_all.setToolTip(
                    "Celonis-Dateien können lokal archiviert werden, ein "
                    "strukturierter Celonis-Parser ist derzeit nicht vorhanden."
                )
            buttons["parse"] = parse_all
            parse_missing = QPushButton(
                "Ausstehendes Parsing fortsetzen", objectName="WorkflowAction"
            )
            parse_missing.setToolTip(
                "Nur noch nicht erfolgreich geparste lokale Dokumente verarbeiten."
            )
            parse_missing.clicked.connect(
                lambda _checked=False, c=category:
                self._trigger_context_parse(c, "resume")
            )
            if category == "celonis":
                parse_missing.setText("Nicht verfügbar")
                parse_missing.setEnabled(False)
            buttons["resume_parse"] = parse_missing
            grid.addWidget(
                _source_stack(2, [parse_all, parse_missing]),
                0, 2, Qt.AlignmentFlag.AlignTop,
            )
            if category != "celonis":
                problem_zip = _source_single(
                    3, QPushButton(
                        "Fehler-ZIP exportieren", objectName="WorkflowAction",
                    ),
                )
                problem_zip.setToolTip(
                    "Nicht parsebare Dokumente dieser Quelle als lokales ZIP. "
                    "Standardmäßig nur technische Metadaten, Originale nach Bestätigung."
                )
                problem_zip.clicked.connect(
                    lambda _checked=False, c=category:
                    self.action_requested.emit(f"parser_diagnostics:{c}")
                )
                buttons["problem_zip"] = problem_zip
                grid.addWidget(problem_zip, 0, 3, Qt.AlignmentFlag.AlignTop)


            archive = _source_single(
                4, QPushButton("+ Beleg", objectName="WorkflowAction"),
            )
            archive.setToolTip(
                "Lokale Belegdateien in dieser Kategorie archivieren. "
                "Strukturiertes Parsing separat starten."
            )
            archive.clicked.connect(
                lambda _checked=False, c=category:
                self.action_requested.emit(f"context_files:{c}")
            )
            buttons["import"] = archive
            self.context_import_buttons[category] = archive
            grid.addWidget(archive, 0, 4, Qt.AlignmentFlag.AlignTop)

            timestamp = QLabel("Noch kein Abruf", objectName="PageSubtitle")
            timestamp.setFixedWidth(_SOURCE_COLUMNS[5][1])
            timestamp.setWordWrap(True)
            self.context_source_dates[category] = timestamp
            grid.addWidget(timestamp, 0, 5)

            stats = QVBoxLayout()
            stats.setSpacing(3)
            count = QLabel("0 Dokumente", objectName="PageSubtitle")
            count.setWordWrap(True)
            stats.addWidget(count)
            bar = QProgressBar()
            bar.setTextVisible(False)
            bar.setMaximumHeight(8)
            bar.setRange(0, 100)
            bar.setValue(0)
            stats.addWidget(bar)
            operation = QProgressBar()
            operation.setRange(0, 0)
            operation.setMaximumHeight(10)
            operation.hide()
            stats.addWidget(operation)
            operation_label = QLabel(objectName="PageSubtitle")
            operation_label.setWordWrap(True)
            operation_label.hide()
            stats.addWidget(operation_label)
            grid.addLayout(stats, 0, 6)

            self.context_coverage_bars[category] = bar
            self.context_operation_bars[category] = operation
            self.context_operation_labels[category] = operation_label
            self.context_counts[category] = count
            self.context_scraper_buttons[category] = buttons
            scraper_grid.addWidget(frame)

        body.addLayout(scraper_grid)

        middle = QHBoxLayout()
        middle.setSpacing(12)
        left = QVBoxLayout()
        left.addWidget(QLabel("Technische Unterlagen", objectName="CardTitle"))
        tech_grid = QGridLayout()
        tech_grid.setHorizontalSpacing(6)
        tech_grid.setVerticalSpacing(4)
        short_labels = {
            "ecu_messages": "ECU-Nachrichten",
            "trigger_conditions": "Setzbedingungen",
            "network_topology": "Netzwerktopologie",
            "hardware_changes": "HW-Änderungen",
            "software_changes": "SW-Änderungen",
            "additional": "Weitere Dokumente",
        }
        for index, (category, label) in enumerate(EVIDENCE_CATEGORIES[4:]):
            col = 0
            row = index
            tech_frame = QFrame(objectName="TechnicalEvidenceRow")
            tech_frame.setProperty("evidenceState", "pending")
            group = QHBoxLayout(tech_frame)
            group.setContentsMargins(7, 3, 7, 3)
            group.setSpacing(3)
            self.context_technical_rows[category] = tech_frame
            name = QLabel(short_labels.get(category, label))
            name.setToolTip("Dateien werden unverändert lokal und mit SHA-256 archiviert.")
            group.addWidget(name, 1)
            if category == "cdd_smrd":
                parser = QPushButton("Einlesen", objectName="WorkflowAction")
                parser.setToolTip(
                    "CDD strukturiert über den bestehenden Candela-Parser "
                    "einlesen; SMR-D bleibt zunächst Original-Inventar."
                )
                parser.clicked.connect(
                    lambda: self._trigger_context_parse("cdd_smrd", "files")
                )
                self.context_technical_parse[category] = parser
                group.addWidget(parser)
                resume = QPushButton("Parsing fortsetzen", objectName="WorkflowAction")
                resume.setToolTip(
                    "Nur noch nicht strukturiert indexierte CDD-Dateien "
                    "mit dem vorhandenen Candela-Parser lesen. "
                    "SMR-D ist nicht unterstützt."
                )
                resume.clicked.connect(
                    lambda: self._trigger_context_parse("cdd_smrd", "resume")
                )
                self.context_technical_resume[category] = resume
                group.addWidget(resume)
                problem_zip = QPushButton("Fehler-ZIP", objectName="WorkflowAction")
                problem_zip.clicked.connect(
                    lambda: self.action_requested.emit(
                        "parser_diagnostics:cdd_smrd"
                    )
                )
                group.addWidget(problem_zip)
            button = QPushButton("+", objectName="WorkflowAction")
            button.setFixedWidth(30)
            button.setToolTip(f"{label} · eine oder mehrere Dateien auswählen")
            button.clicked.connect(
                lambda _checked=False, c=category:
                self.action_requested.emit(f"context_files:{c}")
            )
            group.addWidget(button)
            self.context_import_buttons[category] = button
            count = QLabel("0", objectName="PageSubtitle")
            count.setMinimumWidth(24)
            group.addWidget(count)
            self.context_counts[category] = count
            tech_grid.addWidget(tech_frame, row, col)
        left.addLayout(tech_grid)
        left.addStretch(1)
        middle.addLayout(left, 3)

        inventory = QVBoxLayout()
        inventory.addWidget(QLabel("Gesammelte Dateien", objectName="CardTitle"))
        self.context_table, self.context_model = _create_table((
            "Quelle", "Datei", "Größe", "SHA-256", "Importiert",
        ))
        self.context_table.setMinimumHeight(126)
        self.context_table.selectionModel().selectionChanged.connect(
            lambda *_: self._refresh_controls()
        )
        inventory.addWidget(self.context_table, 1)
        remove_row = QHBoxLayout()
        self.context_remove_button = QPushButton("Zuordnung entfernen")
        self.context_remove_button.setToolTip(
            "Entfernt nur den Eintrag aus dieser Sachnummern-Sammlung; "
            "Quelldateien und andere Auswertungen bleiben erhalten."
        )
        self.context_remove_button.clicked.connect(
            lambda: self.action_requested.emit("context_remove")
        )
        remove_row.addWidget(self.context_remove_button)
        remove_row.addStretch(1)
        inventory.addLayout(remove_row)
        middle.addLayout(inventory, 4)
        body.addLayout(middle, 1)

        self.context_review_button = QPushButton("Unterlagensammlung geprüft")
        self.context_review_button.clicked.connect(self._review)
        body.addWidget(self.context_review_button)
        self.context_summary = QLabel(objectName="PageSubtitle")
        self.context_summary.hide()  # Keine redundante Gesamtsumme unter Schritt 04.

    def _build_following_steps(self) -> None:
        """Die lokale FIN-Clusterberechnung wird in Schritt 05 eingehängt."""
        _, body = self._workspace(
            "05 · Clusteranalyse",
            "Lokale DTC-Cluster und zweiter ChatGPT-Durchlauf. "
            "Technische Unterlagen dienen der Erklärung und Plausibilisierung.",
        )
        self.cluster_base_status = QLabel(objectName="PageSubtitle")
        self.cluster_base_status.setWordWrap(True)
        self.cluster_base_status.hide()
        body.addWidget(self.cluster_base_status)
        options = QHBoxLayout()
        self.cluster_originals = QCheckBox("Technische Originale beifügen (vertraulich)")
        self.cluster_originals.setChecked(False)
        self.cluster_originals.setToolTip(
            "Originale sind nicht anonymisiert. Auch das importierte erste "
            "ChatGPT-Ergebnis kann vertrauliche Freitexte enthalten."
        )
        options.addWidget(self.cluster_originals)
        self.cluster_export_button = self._add_action(
            options, "2. ChatGPT-Paket exportieren",
            lambda: self.action_requested.emit("cluster_export"),
        )
        self.cluster_import_button = self._add_action(
            options, "Cluster-Ergebnis importieren",
            lambda: self.action_requested.emit("cluster_import"),
        )
        options.addStretch(1)
        body.addLayout(options)
        self.cluster_result_status = QLabel(objectName="PageSubtitle")
        self.cluster_result_status.hide()
        body.addWidget(self.cluster_result_status)
        self.cluster_tabs = QTabWidget()
        self.cluster_tabs.setObjectName("ClusterMethodTabs")
        self.cluster_tabs.setMinimumHeight(250)
        self.cluster_tabs.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        # Genau EIN Scrollbereich fuer den lokalen Clusterinhalt. Der
        # eingebettete AutoExportFinWorkspace gibt seinen alten internen
        # QScrollArea in set_workflow_compact_mode() frei. Ein verschachteltes
        # Scrollen verhindert sonst, dass der untere Teil erreichbar ist.
        self.local_cluster_scroll = QScrollArea()
        self.local_cluster_scroll.setObjectName("WorkflowClusterScroll")
        self.local_cluster_scroll.setWidgetResizable(True)
        self.local_cluster_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOn
        )
        self.local_cluster_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.local_cluster_scroll.setMinimumHeight(230)
        self.local_cluster_holder = QWidget()
        self.local_cluster_holder.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum
        )
        self.local_cluster_layout = QVBoxLayout(self.local_cluster_holder)
        self.local_cluster_layout.setContentsMargins(0, 0, 0, 0)
        self.local_cluster_layout.setSpacing(0)
        self.local_cluster_layout.setSizeConstraint(
            QLayout.SizeConstraint.SetMinimumSize
        )
        self.local_cluster_scroll.setWidget(self.local_cluster_holder)
        self.cluster_tabs.addTab(
            self.local_cluster_scroll, "Lokal · HDBSCAN / Cosinus"
        )
        self.chatgpt_cluster_page = QWidget()
        review_layout = QVBoxLayout(self.chatgpt_cluster_page)
        review_layout.setContentsMargins(5, 5, 5, 5)
        self.chatgpt_cluster_summary = QLabel(objectName="PageSubtitle")
        self.chatgpt_cluster_summary.setWordWrap(True)
        self.chatgpt_cluster_summary.hide()
        review_layout.addWidget(self.chatgpt_cluster_summary)
        self.chatgpt_cluster_table, self.chatgpt_cluster_model = _create_table((
            "Cluster", "Titel", "Fälle", "Sicherheit",
        ))
        self.chatgpt_cluster_table.setMinimumHeight(110)
        self.chatgpt_cluster_table.selectionModel().selectionChanged.connect(
            lambda *_: self._show_chatgpt_cluster_details()
        )
        review_layout.addWidget(self.chatgpt_cluster_table, 1)
        self.chatgpt_cluster_details = QLabel(objectName="PageSubtitle")
        self.chatgpt_cluster_details.setWordWrap(True)
        self.chatgpt_cluster_details.setMaximumHeight(80)
        review_layout.addWidget(self.chatgpt_cluster_details)
        self.chatgpt_case_table, self.chatgpt_case_model = _create_table((
            "FIN", "QEC-Fall", "Cluster", "NTF-Einschätzung",
            "Verursachungsbereich", "Fachstatus",
        ))
        self.chatgpt_case_table.setMinimumHeight(110)
        review_layout.addWidget(self.chatgpt_case_table, 1)
        self.cluster_tabs.addTab(self.chatgpt_cluster_page, "ChatGPT · Ergebnis anzeigen")
        body.addWidget(self.cluster_tabs, 1)
        for button in (self.cluster_export_button, self.cluster_import_button):
            button.setMinimumHeight(52)
            button.setMinimumWidth(245)
            button.setObjectName("ClusterStartButton")
        self.review_buttons = {3: self.context_review_button}
        self.cluster_review_button = QPushButton("Clusteranalyse fachlich geprüft")
        self.cluster_review_button.clicked.connect(self._review)
        body.addWidget(self.cluster_review_button)
        self.review_buttons[4] = self.cluster_review_button
        self.review_button = self.review_buttons[4]

    def mount_local_cluster(self, widget: QWidget) -> None:
        """Ein einziger lokaler Cluster-Workspace, kein zweiter Analysealgorithmus."""
        self.local_cluster_widget = widget
        layout = self.local_cluster_layout
        while layout.count():
            item = layout.takeAt(0)
            if item.widget() is not None:
                item.widget().setParent(None)
        if hasattr(widget, "set_workflow_compact_mode"):
            widget.set_workflow_compact_mode()
        widget.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum
        )
        layout.addWidget(widget)
        widget.show()
        self.local_cluster_scroll.verticalScrollBar().setValue(0)

    def _refresh_project_selector(self) -> None:
        projects = self.project_store.list_projects()
        current = (self.profile_id, self._context_part)
        self.project_combo.blockSignals(True)
        self.project_combo.clear()
        self.project_combo.addItem("Projekt wählen", None)
        for item in projects:
            self.project_combo.addItem(
                item.title, (item.profile_id, item.part_number)
            )
        # Anzeige und intern normalisierte Sachnummer müssen dieselbe
        # Projektidentität abbilden (Leerzeichen/Trennzeichen sind zulässig).
        project = self.project_store.get(*current)
        # Qt kann Python-Tupel im QVariant als Liste zurückgeben: findData()
        # findet in diesem Fall selbst bei derselben Sachnummer keinen Eintrag.
        # Deshalb die stabile Projektidentität explizit vergleichen.
        from ntf_insight.storage.cluster_evidence_store import part_key
        wanted = (self.profile_id, part_key(self._context_part))
        idx = 0
        for number in range(1, self.project_combo.count()):
            item = self.project_combo.itemData(number)
            matches_key = (
                isinstance(item, (tuple, list)) and len(item) == 2
                and item[0] == wanted[0] and part_key(item[1]) == wanted[1]
            )
            matches_title = (
                project is not None
                and self.project_combo.itemText(number) == project.title
            )
            if matches_key or matches_title:
                idx = number
                break
        self.project_combo.setCurrentIndex(idx)
        self.project_combo.blockSignals(False)
        label = project.title if project is not None else (
            f"{'Kühlmittelpumpe' if self.profile_id == 'coolant_pump' else self.profile_id}"
            f" [{self._context_part or 'Sachnummer wählen'}]"
        )
        self.project_title.setText(label)
        self.adopt_button.setVisible(
            project is None and bool(self._all_rows)
            and self.profile_id == "coolant_pump"
        )
        self.project_export_button.setEnabled(project is not None)
        self.project_export_button.setToolTip(
            "Nur das ausgewählte Projekt als .ntfproject exportieren. "
            "Bestehenden Bestand ohne Projekt zuerst übernehmen."
        )
        self.project_ecus_label.setText(
            "Relevante Steuergeräte: " + ", ".join(project.ecu_names)
            if project and project.ecu_names
            else "Relevante Steuergeräte: noch nicht festgelegt"
        )
        self.project_title.setToolTip(
            "Steuergeräte und Projektbeschreibung über Einstellungen konfigurieren."
            + ("\nECUs: " + ", ".join(project.ecu_names) if project and project.ecu_names else "")
        )

    def _project_combo_changed(self) -> None:
        project = self.project_combo.currentData()
        if project is not None:
            self.project_selected.emit(project[0], project[1])

    def activate_project(self, profile: str, part: str) -> None:
        """Auswahl wechselt Kontext und Prüffortschritt, nicht die globalen Rohdaten."""
        from ntf_insight.storage.workflow_progress import normalize_part_number
        part = normalize_part_number(part)
        self.profile_id, self._context_part = profile, part
        idx = self.profile.findData(profile)
        if idx >= 0:
            self.profile.blockSignals(True)
            self.profile.setCurrentIndex(idx)
            self.profile.blockSignals(False)
        self.part_number.setText(part)
        self.progress_store.select_context(profile, part)
        self.state = replace(
            self.progress_store.load(profile, part), paused=False
        )
        self._notice = ""
        self._error_step = None
        self.refresh_context_files()
        self.refresh_ai_chain()
        self._refresh_project_selector()
        self.refresh()

    def refresh_ai_chain(self) -> None:
        self.first_package = self.ai_chain.latest_first_export(
            self.profile_id, self._context_part
        )
        if self.first_package is None:
            self.ai_package_status.setText(
                "Noch keine KI-Analysebasis registriert."
            )
            self.cluster_base_status.setText(
                "Zuerst in Schritt 03 das erste ChatGPT-Paket exportieren "
                "und das erste Ergebnis als JSON importieren."
            )
            self.cluster_result_status.setText("Noch kein zweiter Durchlauf.")
        else:
            package = self.first_package
            self.ai_package_status.setText(
                "1. KI-Paket automatisch gesichert · "
                f"ID {package.paket_id[:12]}…"
            )
            if package.analysis_id is None:
                self.cluster_base_status.setText(
                    "1. KI-Paket vorhanden; die ChatGPT-Ergebnis-JSON aus "
                    "Schritt 03 wurde noch nicht importiert."
                )
            else:
                self.cluster_base_status.setText(
                    f"1. Durchlauf: {package.analysis_id} · "
                    f"{len(self.context_files)} Unterlagen aus Schritt 04 verfügbar."
                )
            prepared, imported = self.ai_chain.second_status(package.paket_id)
            self.cluster_result_status.setText(
                f"2. Durchlauf: {prepared} Clusterpaket(e) erzeugt, "
                f"{imported} Ergebnis(se) validiert importiert."
            )
        self.ai_package_status.setVisible(self.first_package is not None)
        self.cluster_base_status.setVisible(
            self.first_package is not None and self.first_package.analysis_id is not None
        )
        if self.first_package is not None:
            prepared, imported = self.ai_chain.second_status(self.first_package.paket_id)
            self.cluster_result_status.setVisible(bool(prepared or imported))
        else:
            self.cluster_result_status.hide()
        self._refresh_controls()

    def update_project_transfer_progress(self, percent: int, phase: str) -> None:
        """Phasen-Fortschritt; ETA ist eine Schätzung, keine feste Zusage."""
        if self._transfer_started_at is None:
            self._transfer_started_at = time.monotonic()
        self.project_transfer_bar.show()
        self.project_transfer_eta.show()
        if percent < 0:
            self.project_transfer_bar.setRange(0, 0)
            self.project_transfer_eta.setText(phase + " · Dauer derzeit nicht abschätzbar")
            return
        self.project_transfer_bar.setRange(0, 100)
        self.project_transfer_bar.setValue(min(100, max(0, percent)))
        elapsed = max(0., time.monotonic() - self._transfer_started_at)
        if 10 <= percent < 100 and elapsed >= 2:
            remaining = round(elapsed / percent * (100 - percent))
            eta = f" · grob noch {remaining // 60} min {remaining % 60:02d} s"
        else:
            eta = " · Restzeit noch nicht belastbar" if percent < 100 else ""
        self.project_transfer_eta.setText(phase + f" ({percent} %)" + eta)

    def finish_project_transfer_progress(self) -> None:
        self._transfer_started_at = None
        self.project_transfer_bar.hide()
        self.project_transfer_eta.hide()

    def set_context_busy(self, busy: bool) -> None:
        self._context_busy = busy
        self._refresh_controls()

    def set_context_operation(self, category: str, active: bool, message: str = "") -> None:
        """Unbekannte Portal-/Parser-Gesamtmenge als laufende Aktivität zeigen."""
        bar = self.context_operation_bars.get(category)
        label = self.context_operation_labels.get(category)
        if bar is None or label is None:
            return
        bar.setVisible(active)
        label.setVisible(active)
        if active:
            self._context_operation_started.setdefault(category, time.monotonic())
            # Die Quellen melden bearbeitete FINs bzw. lokale Parser-Positionen.
            # Nur bei bekanntem Nenner einen Prozentwert anzeigen.
            match = re.search(r"(?:FIN-Fortschritt:\s*|(?:parsen|einlesen|archivieren|abgleichen)\s*\()(\d+)\s*/\s*(\d+)", message, re.I)
            if match and int(match.group(2)) > 0:
                done, total = map(int, match.groups())
                bar.setRange(0, total)
                bar.setValue(min(done, total))
                elapsed = time.monotonic() - self._context_operation_started[category]
                if done > 0 and done < total and elapsed >= 2:
                    rest = round(elapsed * (total - done) / done)
                    estimate = f" · grob noch {rest // 60} min {rest % 60:02d} s"
                else:
                    estimate = " · Restzeit wird ermittelt" if done < total else ""
                label.setText(message + estimate)
            else:
                bar.setRange(0, 0)
                label.setText(
                    (message or "Verarbeitung läuft")
                    + " · Restzeit nach ersten FINs/Dateien abschätzbar"
                )
        else:
            self._context_operation_started.pop(category, None)
            bar.setRange(0, 100)
            bar.setValue(0)

    def _trigger_context_fetch(self, category: str, scope: str) -> None:
        if category in self._context_scrapers_busy:
            if self._context_scrape_active.get(category) == scope:
                self._context_stop_requested.add(("scrape", category))
                self.action_requested.emit(f"context_scrape:{category}:cancel")
                self._refresh_controls()
            return
        self.action_requested.emit(f"context_scrape:{category}:{scope}")

    def _trigger_context_parse(self, category: str, scope: str) -> None:
        if category in self._context_parsers_busy:
            if self._context_parsers_busy[category] == scope:
                self._context_stop_requested.add(("parse", category))
                self.action_requested.emit(f"context_parse_cancel:{category}")
                self._refresh_controls()
            return
        if scope == "all":
            self.action_requested.emit(f"context_parse_all:{category}")
        elif scope == "files":
            self.action_requested.emit(f"context_parse:{category}")
        else:
            self.action_requested.emit(f"context_parse_resume:{category}")

    def set_context_parser_busy(
        self, category: str, busy: bool, scope: str = "resume",
    ) -> None:
        if busy:
            self._context_parsers_busy[category] = scope
        else:
            self._context_parsers_busy.pop(category, None)
            self._context_stop_requested.discard(("parse", category))
        if category == "qec":
            if busy:
                self.qec_parse_progress.setRange(0, 0)
            else:
                self.qec_parse_progress.setRange(0, 100)
                status = self._source_coverage.get("qec")
                if status is not None:
                    self.qec_parse_progress.setValue(round(
                        100 * (status.parsed_cases or 0)
                        / max(1, status.total_cases or 0)
                    ))
        self._refresh_controls()

    def set_context_scraper_busy(
        self, category: str, busy: bool, scope: str = "all",
    ) -> None:
        self.set_context_operation(
            category, busy, "Portalabruf läuft · Dauer hängt von Portal und SSO ab"
        )
        if busy:
            self._context_scrapers_busy.add(category)
            self._context_scrape_active[category] = scope
        else:
            self._context_scrapers_busy.discard(category)
            self._context_scrape_active.pop(category, None)
            self._context_stop_requested.discard(("scrape", category))
        self._refresh_controls()

    def _historical_portal_downloads(
        self, *, diagnosis: bool, tips: bool,
    ) -> dict[str, tuple[datetime, bool]]:
        """Reale lokale Portal-Manifeste statt geschätzter Download-Daten."""
        if not diagnosis and not tips:
            return {}
        from ntf_insight.acquisition.diagnosis_viewer import read_last_attempt
        from ntf_insight.acquisition.tips_archive import local_tips_cases

        project_rows = self._rows_for_context()
        fins = self.ssl_selection.allowed_fins(
            self.profile_id, self._context_part, project_rows,
        )
        # Kein vollständiger Datumsnachweis aus einer unvollständig gelesenen Kohorte.
        if len(fins) > 2000:
            return {}
        base = self.progress_store.store.path.parent
        result: dict[str, tuple[datetime, bool]] = {}
        if diagnosis:
            for fin in fins:
                state = read_last_attempt(base / "quicktests", fin)
                if state is None or not state.last_attempt_at:
                    continue
                try:
                    timestamp = datetime.fromisoformat(
                        state.last_attempt_at.replace("Z", "+00:00")
                    )
                except ValueError:
                    continue
                last = result.get("diagnosis_viewer")
                if last is None or timestamp > last[0]:
                    result["diagnosis_viewer"] = (timestamp, bool(state.files))
        if tips:
            for fin in fins:
                for path in local_tips_cases(base, fin):
                    try:
                        doc = json.loads(path.read_text(encoding="utf-8-sig"))
                        timestamp = datetime.fromisoformat(
                            str(doc["abgerufen_am_utc"]).replace("Z", "+00:00")
                        )
                    except (OSError, ValueError, KeyError, TypeError):
                        continue
                    if timestamp.tzinfo is None:
                        continue
                    last = result.get("tips_writer")
                    if last is None or timestamp > last[0]:
                        result["tips_writer"] = (timestamp, True)
        return result

    def refresh_context_files(self) -> None:
        """Kontextdaten der aktuellen Sachnummer ohne Dateiinhalt in GUI anzeigen."""
        self.context_files = self.context_store.list_files(
            self.profile_id, self._context_part
        )
        counts = {name: 0 for name in CATEGORY_LABELS}
        for file in self.context_files:
            counts[file.category] += 1
        activities = self.source_activity.get(
            self.profile_id, self._context_part
        )
        source_logs = self.source_activity.get_details(
            self.profile_id, self._context_part
        )
        archived_fetch = self._historical_portal_downloads(
            diagnosis="Abruf" not in source_logs.get("diagnosis_viewer", {}),
            tips="Abruf" not in source_logs.get("tips_writer", {}),
        )
        imported_types = {
            "tp_dashboard": SourceType.TP_DASHBOARD,
            "diagnosis_viewer": SourceType.SHORT_TEST,
            "tips_writer": SourceType.TIPS_CASE,
        }
        all_artifacts = self.progress_store.store.load_artifacts()
        legacy_imports = {}
        for source in all_artifacts:
            for category, source_type in imported_types.items():
                if source.source_type == source_type:
                    last = legacy_imports.get(category)
                    if last is None or source.imported_at > last:
                        legacy_imports[category] = source.imported_at
            if (
                source.source_type == SourceType.OTHER
                and "celonis" in str(source.source_system or "").casefold()
            ):
                last = legacy_imports.get("celonis")
                if last is None or source.imported_at > last:
                    legacy_imports["celonis"] = source.imported_at
        for key, count_label in self.context_counts.items():
            count_label.setText(str(counts[key]))
            if key in self.context_source_dates:
                activity = activities.get(key)
                documents = [f for f in self.context_files if f.category == key]
                log = source_logs.get(key, {})
                descriptions = []
                for event_type in ("Abruf", "Einlesen"):
                    record = log.get(event_type)
                    if record is not None:
                        when, state = record
                        descriptions.append(
                            f"{event_type}: {when:%d.%m.%Y %H:%M} · {state}"
                        )
                if descriptions:
                    self.context_source_dates[key].setText("\n".join(descriptions))
                elif activity:
                    timestamp, state = activity
                    kind = (
                        "Einlesen" if state in {
                            "Einlesen gestartet", "Eingelesen", "Archiviert",
                        } else "Abruf"
                    )
                    self.context_source_dates[key].setText(
                        f"{kind}: {timestamp:%d.%m.%Y %H:%M} · {state}"
                    )
                elif key in archived_fetch:
                    newest, has_files = archived_fetch[key]
                    self.context_source_dates[key].setText(
                        f"Portalarchiv: {newest:%d.%m.%Y %H:%M}"
                        + (" · Dateien vorhanden" if has_files else " · nur Abrufversuch")
                    )
                elif documents:
                    newest = max(f.imported_at for f in documents)
                    self.context_source_dates[key].setText(
                        "Dateiimport: " + newest.strftime("%d.%m.%Y %H:%M")
                    )
                elif key in legacy_imports:
                    newest = legacy_imports[key]
                    self.context_source_dates[key].setText(
                        "Import (projektübergreifend): "
                        + newest.strftime("%d.%m.%Y %H:%M")
                    )
                else:
                    self.context_source_dates[key].setText(
                        "Noch kein Abruf / Import"
                    )
                imported_event = log.get("Einlesen")
                local_parsed = bool(
                    imported_event and imported_event[1] in {"Eingelesen", "Archiviert"}
                    or not imported_event and activity and activity[1] in {
                        "Eingelesen", "Archiviert",
                    }
                )
                available = bool(
                    documents or local_parsed
                    or (key in archived_fetch and archived_fetch[key][1])
                )
                legacy_only = bool(not available and key in legacy_imports)
                count_label.setText(
                    str(counts[key]) if counts[key] else
                    "✓" if local_parsed else "~" if legacy_only else "0"
                )
                self.context_source_names[key].setStyleSheet(
                    "color: #268763; font-weight: 600;" if available
                    else "color: #CA922C;" if legacy_only else ""
                )
                count_label.setStyleSheet(
                    "color: #268763; font-weight: 600;" if available
                    else "color: #CA922C;" if legacy_only else ""
                )
                count_label.setToolTip(
                    "✓ = Datei mit vorhandener Quellenpipeline eingelesen; "
                    "~ = importierte Quelle nur global nachgewiesen. "
                    "Keine automatische FIN-Zuordnung aus Dateinamen."
                )
        self.context_model.set_rows([
            (
                CATEGORY_LABELS[item.category], item.original_name,
                f"{item.size_bytes / (1024**2):.1f} MB",
                item.sha256[:12],
                item.imported_at.strftime("%d.%m.%Y %H:%M"),
            )
            for item in self.context_files
        ], row_states=[
            "success" if item.source_path.is_file() else "error"
            for item in self.context_files
        ])
        automatic = {
            key: value for key, value in self._source_coverage.items()
            if key in {"tp_dashboard", "diagnosis_viewer", "tips_writer", "celonis"}
        }
        automatic_total = sum(item.local_documents for item in automatic.values())
        automatic_parsed = sum(item.parsed_documents for item in automatic.values())
        active_categories = {
            key for key, count in counts.items() if count
        } | {
            key for key, item in automatic.items() if item.local_documents
        }
        self.context_summary.setText(
            f"{automatic_total} Quelldokumente lokal · "
            f"{automatic_parsed} geparst · "
            f"{len(self.context_files)} manuell zugeordnete Unterlagen · "
            f"{len(active_categories)} von {len(counts)} Kategorien mit Bestand. "
            "Quelldokumente und manuelle Zuordnungen sind getrennte Bestände; "
            "Dateien werden nicht automatisch an ChatGPT gesendet."
        )
        if self._source_coverage:
            self._update_coverage_labels()
        self._refresh_controls()

    def _change_context(self) -> None:
        profile_id = self.profile.currentData()
        if not profile_id:
            return
        try:
            part = normalize_part_number(self.part_number.text())
        except ValueError:
            self.part_number.setText(self._context_part)
            self.set_notice("Sachnummer enthält ungültige Zeichen oder ist zu lang.", error=True)
            return
        self.part_number.setText(part)
        if (profile_id, part) != (self.profile_id, self._context_part):
            self.profile_id = profile_id
            self._context_part = part
            self.progress_store.select_context(profile_id, part)
            self.state = replace(
                self.progress_store.load(profile_id, part), paused=False
            )
            self._notice = ""
            self._error_step = None
            self.refresh_ai_chain()
            self._refresh_project_selector()
        self.refresh_context_files()
        self.refresh_ai_chain()
        self._refresh_project_selector()
        self.refresh()

    def _save(self) -> None:
        self.progress_store.save(self.profile_id, self._context_part, self.state)
        self.refresh()

    def _open_step(self, index: int) -> None:
        if not 0 <= index < STEP_COUNT:
            return
        self.step_loading.emit(True)
        try:
            self.state = replace(self.state, step=index)
            self._error_step = None
            self._notice = ""
            self._save()
        finally:
            self.step_loading.emit(False)

    def _review(self) -> None:
        if self.state.step not in (3, 4):
            return
        reviews = set(self.state.reviewed_steps)
        if self.state.step in reviews:
            reviews.remove(self.state.step)
        else:
            reviews.add(self.state.step)
        self.state = replace(self.state, reviewed_steps=tuple(sorted(reviews)))
        self._save()

    @staticmethod
    def _part_key(value: str) -> str:
        return "".join(char for char in normalize_part_number(value) if char.isalnum())

    def _rows_for_context(self) -> list[dict]:
        if self.profile_id != "coolant_pump":
            return []
        part = self._part_key(self._context_part)
        return [
            row for row in self._all_rows
            if not part or self._part_key(row.get("part_number", "")) == part
        ]

    def refresh_data(self) -> None:
        """Teure QEC-Dateien nur bei Quellenwechsel/explicit Refresh neu lesen."""
        self._data_error = ""
        self._all_rows = []
        self._chatgpt_by_case = {}
        try:
            if self.qec_store is not None:
                self._all_rows = self.qec_store.rows(self.qec_root)
                sources = self.qec_store.active_sources()
                self._source_name = (
                    sources[0].original_name if len(sources) == 1
                    else f"{len(sources)} aktive QEC-Listen" if sources else ""
                )
            if self.analysis_store is not None:
                # Schritt 03 zeigt ausschließlich die erste ChatGPT-Auswertung;
                # die zweite Runde wird nur in Schritt 05 angezeigt.
                first = self.ai_chain.latest_first_export(
                    self.profile_id, self._context_part
                )
                first_id = first.analysis_id if first is not None else None
                if first_id:
                    for finding in self.analysis_store.list_case_findings(limit=10000):
                        if finding["analyse_id"] == first_id:
                            self._chatgpt_by_case.setdefault(
                                finding["case_id"], finding
                            )
        except (OSError, ValueError) as exc:
            # Keine rohen Berichtsdetails oder FINs in Logs/Dialoge übertragen.
            self._data_error = (
                "QEC-/ChatGPT-Daten konnten nicht geladen werden: "
                + type(exc).__name__
            )
        self.refresh_context_files()
        self._refresh_project_selector()
        self.refresh()

    def _ssl_categories(self) -> set[str]:
        return set(self._fin_findings.values())

    def _select_all_ssl(self, selected: bool) -> None:
        categories = self._ssl_categories()
        self.ssl_selection.save(
            self.profile_id, self._context_part, categories,
            categories if selected else set(),
        )
        self.cohort_updated.emit()
        self.refresh()

    def _select_ssl_category(self, category: str, checked: bool) -> None:
        categories = self._ssl_categories()
        current = self.ssl_selection.selected(self.profile_id, self._context_part)
        selected = set(categories if current is None else current & categories)
        if checked:
            selected.add(category)
        else:
            selected.discard(category)
        self.ssl_selection.save(
            self.profile_id, self._context_part, categories, selected,
        )
        self.cohort_updated.emit()
        self.refresh()

    def _refresh_ssl_menu(self) -> None:
        categories = self._ssl_categories()
        selected = self.ssl_selection.selected(self.profile_id, self._context_part)
        if selected is None:
            selected = categories
        self.ssl_menu.clear()
        fin_counts = Counter(self._fin_findings.values())
        for category in sorted(categories):
            action = QAction(
                f"{category}  ·  {fin_counts[category]} FINs", self.ssl_menu
            )
            action.setCheckable(True)
            action.setChecked(category in selected)
            action.toggled.connect(
                lambda checked, label=category:
                QTimer.singleShot(
                    0, lambda checked=checked, label=label:
                    self._select_ssl_category(label, checked)
                )
            )
            self.ssl_menu.addAction(action)
        included = sum(
            1 for category in self._fin_findings.values() if category in selected
        )
        self.ssl_filter_button.setText(
            f"Endbefunde wählen · {included}/{len(self._fin_findings)} FINs"
        )
        self.ssl_filter_button.setEnabled(bool(categories))
        self.ssl_select_all.setEnabled(bool(categories))
        self.ssl_selection_status.setText(
            f"{included} FINs in den Schritten 02–05 berücksichtigt. "
            "Die originale QEC-Liste bleibt vollständig erhalten."
        )
        ranked = sorted(
            fin_counts.items(), key=lambda item: (-item[1], item[0])
        )
        chart = dict(ranked[:6])
        if len(ranked) > 6:
            chart["Weitere Endbefunde"] = sum(count for _, count in ranked[6:])
        self.ssl_donut.set_counts(chart)

    @staticmethod
    def _per_fin_distribution(
        rows: list[dict], field,
        *, unknown: str, conflict: str = "Mehrere Bewertungen",
    ) -> dict[str, int]:
        grouped: dict[str, set[str]] = defaultdict(set)
        for row in rows:
            fin = str(row["fin"]).upper()
            grouped[fin].add(str(field(row) or unknown).strip() or unknown)
        counts = Counter(
            next(iter(names)) if len(names) == 1 else conflict
            for names in grouped.values()
        )
        return dict(counts)

    def _update_tables(self) -> None:
        self._project_rows = self._rows_for_context()
        self._fin_findings = fin_ssl_groups(self._project_rows)
        eligible = self.ssl_selection.allowed_fins(
            self.profile_id, self._context_part, self._project_rows,
        )
        self._scoped_rows = [
            row for row in self._project_rows
            if str(row["fin"]).upper() in eligible
        ]
        self.fin_model.set_rows([
            (
                row["fin"], row["case_id"], row["reference"],
                row["part_number"], row["finding"],
                "Ja" if row["tp_dashboard"] else "Fehlt",
                row["decision"], "Ja" if row["report"] else "Nein",
            )
            for row in self._project_rows
        ], row_states=[
            "info" if str(row["fin"]).upper() in eligible else "muted"
            for row in self._project_rows
        ])
        try:
            self._source_coverage = get_workflow_coverage(
                self.progress_store.store,
                self.progress_store.store.path.parent,
                self._scoped_rows, self.context_files,
            )
            self._coverage_error = ""
        except Exception as exc:
            # Kein Qt-Callback darf wegen beschädigter historischer
            # Parserprotokolle abstürzen oder Vollständigkeit vortäuschen.
            self._source_coverage = {}
            self._coverage_error = (
                "Quellenfortschritt nicht ermittelbar: "
                + type(exc).__name__
                + ". Parser- und Archivdaten unter Datenquellen prüfen."
            )
        qec_coverage = self._source_coverage.get(
            "qec", SourceCoverage("qec", None, None, None, 0, 0)
        )
        self.qec_coverage.setText(
            self._coverage_error or qec_coverage.display()
        )
        self._set_traffic_property(
            self.qec_action_row, "coverageState",
            self._source_traffic_state(qec_coverage),
        )
        self.qec_parse_progress.setValue(
            round(100 * (qec_coverage.parsed_cases or 0)
                  / max(1, qec_coverage.total_cases or 0))
        )
        self.qec_parse_progress.setToolTip(qec_coverage.display())
        reports = [
            local_qec_archive(self.qec_root, row["fin"], row["reference"])
            for row in self._scoped_rows
        ]
        latest_report = max(
            (report for report in reports
             if report is not None and getattr(report, "timestamp", None) is not None),
            key=lambda report: report.timestamp,
            default=None,
        )
        self.qec_last_fetch.setText(
            latest_report.date_label if latest_report else "—"
        )
        self.qec_model.set_rows([
            (
                row["fin"], row["case_id"], row["reference"],
                row["part_number"], report.date_label if report else "—",
                "Gespeichert" if report else "Ausstehend",
                (
                    "Mit Hinweisen" if (
                        str(row["fin"]).upper(), str(row["reference"])
                    ) in qec_coverage.partial_qec
                    else "Geparst" if (
                        str(row["fin"]).upper(), str(row["reference"])
                    ) in qec_coverage.parsed_qec
                    else "Ausstehend" if report else "—"
                ),
            )
            for row, report in zip(self._scoped_rows, reports)
        ], row_states=[
            (
                "warning" if (
                    str(row["fin"]).upper(), str(row["reference"])
                ) in qec_coverage.partial_qec
                else "success" if (
                    str(row["fin"]).upper(), str(row["reference"])
                ) in qec_coverage.parsed_qec
                else "warning" if report else "muted"
            )
            for row, report in zip(self._scoped_rows, reports)
        ])
        by_fin: dict[str, list[bool]] = defaultdict(list)
        for row, report in zip(self._scoped_rows, reports):
            by_fin[str(row["fin"]).upper()].append(bool(report))
        qec_counts = {
            "Alle Berichte vorhanden": sum(all(v) for v in by_fin.values()),
            "Teilweise vorhanden": sum(any(v) and not all(v) for v in by_fin.values()),
            "Noch kein Bericht": sum(not any(v) for v in by_fin.values()),
        }
        self.qec_donut.set_counts(qec_counts)
        by_fin_parsing: dict[str, list[str]] = defaultdict(list)
        for row in self._scoped_rows:
            fin = str(row["fin"]).upper()
            key = (fin, str(row["reference"]))
            if key in qec_coverage.partial_qec:
                state = "partial"
            elif key in qec_coverage.parsed_qec:
                state = "done"
            else:
                state = "missing"
            by_fin_parsing[fin].append(state)
        self.qec_parsing_donut.set_counts({
            "Vollständig geparst": sum(
                all(state == "done" for state in states)
                for states in by_fin_parsing.values()
            ),
            "Teilweise / mit Hinweisen": sum(
                any(state != "missing" for state in states)
                and not all(state == "done" for state in states)
                for states in by_fin_parsing.values()
            ),
            "Noch nicht geparst": sum(
                all(state == "missing" for state in states)
                for states in by_fin_parsing.values()
            ),
        })
        def proposal(row: dict) -> dict:
            return self._chatgpt_by_case.get(row["case_id"], {}).get("bewertung", {})
        statuses = {
            "NTF plausibel": "success", "NTF fraglich": "warning",
            "Kein reiner NTF": "error", "Nicht bewertbar": "muted",
        }
        self.ntf_model.set_rows([
            (
                row["fin"], row["case_id"], row["finding"], row["decision"],
                proposal(row).get("ntf_bewertung", "Nicht bewertet"),
                proposal(row).get("verursachungsbereich", "Nicht zuordenbar"),
                self._chatgpt_by_case[row["case_id"]]["review_status"]
                if row["case_id"] in self._chatgpt_by_case else "Offen",
            )
            for row in self._scoped_rows
        ], row_states=[
            statuses.get(proposal(row).get("ntf_bewertung"), "muted")
            for row in self._scoped_rows
        ])
        ratings = self._per_fin_distribution(
            self._scoped_rows,
            lambda row: proposal(row).get("ntf_bewertung", "Nicht bewertet"),
            unknown="Nicht bewertet",
        )
        self.ntf_donut.set_counts({
            key: ratings.get(key, 0) for key in (
                "NTF plausibel", "NTF fraglich", "Kein reiner NTF",
                "Nicht bewertbar", "Nicht bewertet", "Mehrere Bewertungen",
            ) if ratings.get(key, 0)
        })
        causes = self._per_fin_distribution(
            self._scoped_rows,
            lambda row: proposal(row).get("verursachungsbereich", "Nicht zuordenbar"),
            unknown="Nicht zuordenbar",
            conflict="Mehrere Zuordnungen",
        )
        ordered = sorted(causes.items(), key=lambda item: (-item[1], item[0]))
        grouped = dict(ordered[:5])
        if len(ordered) > 5:
            grouped["Weitere"] = sum(value for _, value in ordered[5:])
        self.cause_donut.set_counts(grouped)
        self._refresh_ssl_menu()
        self._update_coverage_labels()

    @staticmethod
    def _source_traffic_state(status: SourceCoverage) -> str:
        """Grün nur bei vollständig belegter FIN- und Parserabdeckung."""
        if not status.local_documents:
            return "pending"
        if status.unsupported_parser or status.partial_documents:
            return "partial"
        if status.local_documents != status.parsed_documents:
            return "partial"
        if status.total_cases is not None and (
            not status.total_cases
            or status.downloaded_cases != status.total_cases
            or status.parsed_cases != status.total_cases
        ):
            return "partial"
        # Bei unbekannter Sollmenge keinen unbelegten Vollständigkeitsstatus.
        if status.total_cases is None:
            return "partial"
        return "done"

    @staticmethod
    def _set_traffic_property(frame: QFrame, property_name: str, value: str) -> None:
        if frame.property(property_name) == value:
            return
        frame.setProperty(property_name, value)
        frame.style().unpolish(frame)
        frame.style().polish(frame)
        frame.update()

    def _update_coverage_labels(self) -> None:
        """Anzeige nur aus verifizierter Dateiliste und gespeicherten Parserläufen."""
        for category, label in self.context_counts.items():
            status = self._source_coverage.get(category)
            if status is None:
                if category in self.context_coverage_bars and getattr(
                    self, "_coverage_error", ""
                ):
                    label.setText(self._coverage_error)
                    self.context_coverage_bars[category].setValue(0)
                continue
            if category not in self.context_coverage_bars:
                label.setText(
                    f"{status.parsed_documents}/{status.local_documents} geparst"
                    if category == "cdd_smrd" else
                    f"{status.local_documents} archiviert"
                )
                label.setToolTip(status.display() + "\n" + status.note)
                if category in self.context_technical_rows:
                    self._set_traffic_property(
                        self.context_technical_rows[category], "evidenceState",
                        "done" if status.local_documents else "pending",
                    )
                label.setStyleSheet(
                    "color: #268763; font-weight: 600;"
                    if status.local_documents else ""
                )
                continue
            label.setText(status.display())
            label.setToolTip(status.note)
            if category in self.context_source_rows:
                self._set_traffic_property(
                    self.context_source_rows[category], "coverageState",
                    self._source_traffic_state(status),
                )
            bar = self.context_coverage_bars[category]
            if status.total_cases is not None:
                ratio = 100 * (status.parsed_cases or 0) / max(1, status.total_cases)
            else:
                ratio = 100 * status.parsed_documents / max(1, status.local_documents)
            bar.setValue(round(ratio))
            bar.setToolTip(status.display() + "\n" + status.note)
            complete = self._source_traffic_state(status) == "done"
            label.setStyleSheet(
                "color: #268763;" if complete
                else "color: #bd8318;" if status.local_documents else ""
            )
        # Die Zusammenfassung muss den zuletzt berechneten lokalen
        # Quellenbestand abbilden, nicht nur manuell verknüpfte Belege.
        if hasattr(self, "context_summary"):
            totals = [
                s for category, s in self._source_coverage.items()
                if category in {"tp_dashboard", "diagnosis_viewer", "tips_writer", "celonis"}
            ]
            documents = sum(s.local_documents for s in totals)
            parsed = sum(s.parsed_documents for s in totals)
            manual_categories = {f.category for f in self.context_files}
            available_categories = manual_categories | {
                s.category for s in totals if s.local_documents
            }
            self.context_summary.setText(
                f"{documents} Quelldokumente lokal · {parsed} geparst · "
                f"{len(self.context_files)} manuell zugeordnete Unterlagen · "
                f"{len(available_categories)} von {len(CATEGORY_LABELS)} Kategorien "
                "mit Bestand. Quelldokumente sind nicht gleich manuelle "
                "Zuordnungen. Keine automatische ChatGPT-Übertragung."
            )

    def _show_chatgpt_cluster_details(self) -> None:
        index = self.chatgpt_cluster_table.currentIndex().row()
        items = getattr(self, "_cluster_entries", [])
        if 0 <= index < len(items):
            entry = items[index]
            self.chatgpt_cluster_details.setText(
                str(entry.get("technische_hypothese") or "Keine technische Hypothese.")
            )
        else:
            self.chatgpt_cluster_details.setText("")

    def _refresh_chatgpt_cluster_view(self) -> None:
        """Nur gespeicherte zweite Runde visualisieren; keine neue KI-Auswertung."""
        self._cluster_entries = []
        package = self.first_package
        if package is None:
            self.chatgpt_cluster_summary.clear()
            self.chatgpt_cluster_summary.hide()
            self.chatgpt_cluster_model.set_rows([])
            self.chatgpt_case_model.set_rows([])
            return
        with self.progress_store.store.connect() as con:
            result = con.execute(
                "SELECT r.analyse_id FROM workflow_ai_rounds r "
                "JOIN chatgpt_imports i ON i.analyse_id=r.analyse_id "
                "WHERE r.paket_id=? AND r.round_number=2 "
                "ORDER BY i.importiert_am DESC,r.analyse_id DESC LIMIT 1",
                [package.paket_id],
            ).fetchone()
            if not result:
                self.chatgpt_cluster_summary.clear()
                self.chatgpt_cluster_summary.hide()
                self.chatgpt_cluster_model.set_rows([])
                self.chatgpt_case_model.set_rows([])
                return
            analysis_id = result[0]
            clusters = con.execute(
                "SELECT payload_json FROM chatgpt_cluster "
                "WHERE analyse_id=? ORDER BY cluster_id",
                [analysis_id],
            ).fetchall()
            findings = con.execute(
                "SELECT case_id,cluster_id,payload_json,review_status "
                "FROM chatgpt_fallanalysen WHERE analyse_id=? ORDER BY case_id",
                [analysis_id],
            ).fetchall()
        current = {str(row["case_id"]): row for row in self._scoped_rows}
        self._cluster_entries = [json.loads(item[0]) for item in clusters]
        self.chatgpt_cluster_model.set_rows([
            (
                entry.get("cluster_id", ""), entry.get("titel", ""),
                len(entry.get("fall_ids") or []),
                entry.get("sicherheit", "Offen"),
            )
            for entry in self._cluster_entries
        ])
        rendered = []
        state = []
        for case_id, cluster_id, payload, review in findings:
            case = current.get(case_id)
            if case is None:
                continue
            finding = json.loads(payload)
            rendered.append((
                case["fin"], case_id, cluster_id or "—",
                finding.get("ntf_bewertung", "Nicht bewertet"),
                finding.get("verursachungsbereich", "Nicht zuordenbar"), review,
            ))
            state.append(
                "success" if review == "Bestätigt" else "info"
                if review != "Abgelehnt" else "error"
            )
        self.chatgpt_case_model.set_rows(rendered, row_states=state)
        self.chatgpt_cluster_summary.show()
        self.chatgpt_cluster_summary.setText(
            f"Analyse {analysis_id} · {len(self._cluster_entries)} ChatGPT-Cluster · "
            f"{len(rendered)} aktuelle QEC-Fälle mit Ergebnissen. "
            "Nur Anzeige – keine erneute KI-Ausführung."
        )
        self._show_chatgpt_cluster_details()

    def qec_targets(self, *, selected_only: bool = False) -> list[QecTarget]:
        """Niemals außerhalb der Sachnummern-Kohorte oder Referenz herunterladen."""
        if self.profile_id != "coolant_pump":
            return []
        if selected_only:
            selected_rows = {
                index.row() for index in self.qec_table.selectionModel().selectedRows()
            }
            rows = [
                row for index, row in enumerate(self._scoped_rows)
                if index in selected_rows
            ]
        else:
            rows = self._scoped_rows
        targets: list[QecTarget] = []
        seen = set()
        for row in rows:
            try:
                parsed = parse_qec_targets(row["fin"])
            except ValueError:
                continue
            reference = str(row["reference"] or "").strip()
            if not reference or not reference.isdigit() or len(reference) > 14:
                continue
            target = QecTarget(
                fin=parsed[0].fin,
                part_number=str(row["part_number"] or ""),
                reference=reference,
            )
            key = target.fin, target.reference, target.part_number
            if key not in seen:
                seen.add(key)
                targets.append(target)
        return targets

    def set_notice(self, message: str, *, error: bool = False) -> None:
        self._notice = message
        self._error_step = self.state.step if error else None
        self.note.setText(message)
        self.note.setVisible(bool(message) and (error or "abgeschlossen" in message.lower()
                             or "gespeichert" in message.lower()))
        self.note.setProperty("isError", error)
        self.note.style().unpolish(self.note)
        self.note.style().polish(self.note)
        if error:
            # Fehlerampel sofort aktualisieren, nicht erst beim nächsten Klick.
            self.refresh()

    def set_import_state(self, busy: bool, *, can_resume: bool = False) -> None:
        self._import_busy = busy
        self._import_can_resume = can_resume
        self._refresh_controls()

    def _trigger_qec_download(self, scope: str) -> None:
        if self._busy:
            if scope == self._qec_download_scope and not self._qec_stop_requested:
                self._qec_stop_requested = True
                self.action_requested.emit("qec_download_cancel")
                self._refresh_controls()
            return
        self.action_requested.emit({
            "all": "qec_download_all",
            "missing": "qec_download_missing",
            "selected": "qec_download_selected",
        }[scope])

    def set_download_busy(
        self, busy: bool, message: str = "", *, scope: str = "all",
    ) -> None:
        self._busy = busy
        self._qec_download_scope = scope if busy else None
        if not busy:
            self._qec_stop_requested = False
        if message:
            self.qec_status.setText(message)
        self._refresh_controls()

    def _refresh_controls(self) -> None:
        paused = False
        has_rows = bool(self._scoped_rows)
        self.qec_import_button.setEnabled(not paused and not self._import_busy)
        for button in self.context_import_buttons.values():
            button.setEnabled(not paused and not self._context_busy)
        for category, buttons in self.context_scraper_buttons.items():
            coverage = self._source_coverage.get(category)
            busy = category in self._context_parsers_busy
            active = self._context_parsers_busy.get(category)
            stop_pending = ("parse", category) in self._context_stop_requested
            blocked = self._context_busy or self._import_busy
            buttons["parse"].setText(
                "Parsing stoppen" if busy and active == "all"
                else "Einlesen stoppen" if busy and active == "files"
                else "Kein Parser" if category == "celonis"
                else "Alle Dokumente neu parsen"
            )
            buttons["resume_parse"].setText(
                "Parsing stoppen" if busy and active == "resume"
                else "Nicht verfügbar" if category == "celonis"
                else "Ausstehendes Parsing fortsetzen"
            )
            buttons["parse"].setEnabled(
                category != "celonis" and (
                    busy and active in {"all", "files"} and not stop_pending
                    or not busy and not blocked and bool(
                        coverage and coverage.local_paths
                    )
                )
            )
            buttons["resume_parse"].setEnabled(
                category != "celonis" and (
                    busy and active == "resume" and not stop_pending
                    or not busy and not blocked and bool(
                        coverage and coverage.can_resume_parsing
                    )
                )
            )
            if "problem_zip" in buttons:
                buttons["problem_zip"].setEnabled(
                    not blocked and bool(coverage and coverage.local_paths)
                )
        for category, button in self.context_technical_resume.items():
            status = self._source_coverage.get(category)
            active = self._context_parsers_busy.get(category)
            stop_pending = ("parse", category) in self._context_stop_requested
            button.setText(
                "Parsing stoppen" if active == "resume" else "Parsing fortsetzen"
            )
            button.setEnabled(
                active == "resume" and not stop_pending
                or active is None and not self._context_busy and not self._import_busy
                and bool(status and status.can_resume_parsing)
            )
            parse_button = self.context_technical_parse.get(category)
            if parse_button is not None:
                parse_button.setText(
                    "Einlesen stoppen" if active == "files" else "Einlesen"
                )
                parse_button.setEnabled(
                    active == "files" and not stop_pending
                    or active is None and not self._context_busy and not self._import_busy
                )
        self.cluster_originals.setEnabled(not paused and not self._context_busy)
        has_first = self.first_package is not None
        has_first_result = bool(has_first and self.first_package.analysis_id)
        self.cluster_export_button.setEnabled(
            not paused and not self._context_busy and has_first_result
        )
        self.cluster_import_button.setEnabled(
            not paused and not self._context_busy and has_first
            and self.ai_chain.second_status(self.first_package.paket_id)[0] > 0
        )
        if hasattr(self, "local_cluster_widget"):
            self.local_cluster_widget.setEnabled(
                not paused and self.profile_id == "coolant_pump"
                and bool(self._context_part)
            )
        self.context_review_button.setEnabled(
            not paused and not self._context_busy and bool(
                self.context_files or any(
                    s.local_documents for category, s in self._source_coverage.items()
                    if category != "qec"
                )
            )
        )
        self.context_review_button.setText(
            "Bestätigung zurücknehmen" if 3 in self.state.reviewed_steps
            else "Unterlagensammlung als geprüft markieren"
        )
        self.context_remove_button.setEnabled(
            not paused and not self._context_busy and bool(
                self.context_table.selectionModel().selectedRows()
            )
        )
        for category in ("diagnosis_viewer", "tips_writer"):
            buttons = self.context_scraper_buttons[category]
            active = self._context_scrape_active.get(category)
            busy = category in self._context_scrapers_busy
            stop_pending = ("scrape", category) in self._context_stop_requested
            status = self._source_coverage.get(category)
            buttons["all"].setText(
                "Abruf stoppen" if active == "all" else "Alle FINs neu abrufen"
            )
            buttons["missing"].setText(
                "Abruf stoppen" if active == "missing"
                else "Nur fehlende FINs abrufen"
            )
            buttons["all"].setEnabled(
                busy and active == "all" and not stop_pending
                or not busy and not self._import_busy and bool(self._scoped_rows)
            )
            buttons["missing"].setEnabled(
                busy and active == "missing" and not stop_pending
                or not busy and not self._import_busy and bool(
                    status is not None and status.missing_fins
                )
            )
        self.cancel_import_button.setEnabled(self._import_busy)
        self.resume_import_button.setEnabled(
            not paused and not self._import_busy and self._import_can_resume
        )
        self.qec_portal_button.setEnabled(not paused and self.profile_id == "coolant_pump")
        self.qec_export_button.setEnabled(not paused and has_rows)
        qec_coverage = self._source_coverage.get("qec")
        choices = {
            "all": (self.download_all_button,
                    "Alle QEC-Berichte neu abrufen", has_rows),
            "missing": (self.download_missing_button,
                        "Download fortsetzen",
                        bool(qec_coverage and qec_coverage.missing_qec)),
            "selected": (self.download_selected_button,
                         "Markierte herunterladen",
                         bool(self.qec_table.selectionModel().selectedRows())),
        }
        for scope, (button, normal_label, available) in choices.items():
            active = self._busy and self._qec_download_scope == scope
            button.setText("Abruf stoppen" if active else normal_label)
            button.setEnabled(
                active and not self._qec_stop_requested
                or not self._busy and not paused and available
            )
        qec_parsing_busy = "qec" in self._context_parsers_busy
        self.qec_parse_all_button.setText(
            "Parsing stoppen" if qec_parsing_busy
            and self._context_parsers_busy.get("qec") == "all"
            else "Alle QEC-Berichte neu parsen"
        )
        self.qec_parse_all_button.setEnabled(
            qec_parsing_busy and self._context_parsers_busy.get("qec") == "all"
            and ("parse", "qec") not in self._context_stop_requested
            or not qec_parsing_busy and not self._busy and not self._import_busy
            and bool(qec_coverage and qec_coverage.local_paths)
        )
        self.qec_parse_resume_button.setText(
            "Parsing stoppen" if qec_parsing_busy
            and self._context_parsers_busy.get("qec") == "resume"
            else "Ausstehendes Parsing fortsetzen"
        )
        self.qec_parse_resume_button.setEnabled(
            qec_parsing_busy and self._context_parsers_busy.get("qec") == "resume"
            and ("parse", "qec") not in self._context_stop_requested
            or not qec_parsing_busy and not paused and not self._busy
            and not self._import_busy and bool(
                qec_coverage is not None and qec_coverage.can_resume_parsing
            )
        )
        self.cancel_download_button.setEnabled(False)
        self.local_qec_button.setEnabled(not paused and not self._busy)
        self.qec_problem_zip_button.setEnabled(
            not self._busy and not self._import_busy
            and bool(qec_coverage and qec_coverage.local_paths)
        )
        self.ai_export_button.setEnabled(not paused and has_rows)
        self.ai_import_button.setEnabled(not paused)
        for button in self.review_buttons.values():
            button.setEnabled(not paused)

    def refresh(self) -> None:
        self._update_tables()
        self._refresh_chatgpt_cluster_view()
        if self.qec_store is not None:
            stats = self.qec_store.summarize_rows(self._scoped_rows)
        else:
            stats = dict.fromkeys(
                ("fins", "cases", "downloaded", "with_tp", "open", "ntf", "not_ntf"), 0
            )
        total, downloaded = stats["fins"], stats["downloaded"]
        reviewed = stats["ntf"] + stats["not_ntf"]
        statuses = [
            "done" if total else "pending",
            "done" if total and downloaded == total else (
                "partial" if downloaded else "pending"
            ),
            "done" if stats["cases"] and not stats["open"] else (
                "partial" if reviewed or self._chatgpt_by_case else "pending"
            ),
            "done" if 3 in self.state.reviewed_steps and (
                self.context_files or any(
                    s.local_documents for category, s in self._source_coverage.items()
                    if category != "qec"
                )
            ) else "partial" if (
                self.context_files or any(
                    s.local_documents for category, s in self._source_coverage.items()
                    if category != "qec"
                )
            ) else "pending",
            "done" if 4 in self.state.reviewed_steps else "pending",
        ]
        fraction = sum(1 if status == "done" else 0.5 if status == "partial" else 0
                       for status in statuses)
        if self._data_error:
            statuses[0] = "error"
        elif self._error_step is not None:
            statuses[self._error_step] = "error"
        self.progress.setValue(round(fraction / STEP_COUNT * 100))
        self.progress_label.setText(
            f"{stats['cases']} QEC-Fälle · {total} FINs · "
            f"{downloaded} FINs mit QEC-Bericht · {reviewed} fachlich entschieden "
            f"· {self.progress.value()} % Bearbeitungsstand"
        )
        if self._source_name:
            self.source_label.setText(f"QEC-Quelle: {self._source_name}")
        else:
            self.source_label.setText(
                "Noch keine aktive QEC-FIN-Liste. Bitte Original-Excel importieren."
            )
        qec_coverage = self._source_coverage.get("qec")
        self.qec_status.setText(
            self.qec_status.text() if self._busy else
            f"{downloaded}/{total} FINs mit Bericht\n"
            f"{qec_coverage.parsed_cases or 0}/{total} FINs geparst"
            if qec_coverage is not None else
            f"{downloaded}/{total} FINs mit Bericht"
        )
        self.ntf_status.setText(
            f"NTF: {stats['ntf']} · Kein NTF: {stats['not_ntf']} · "
            f"Offen: {stats['open']} · ChatGPT-Vorschläge getrennt von QEC-Entscheidungen"
        )
        source_documents = sum(
            s.local_documents for category, s in self._source_coverage.items()
            if category in {"tp_dashboard", "diagnosis_viewer", "tips_writer", "celonis"}
        )
        names = (
            f"{total} FINs", f"{downloaded}/{total} Berichte",
            f"{reviewed}/{stats['cases']} geprüft",
            f"{source_documents} Quelldokumente",
            "Geprüft" if statuses[4] == "done" else "Offen",
        )
        lamps = {"done": "●", "partial": "●", "pending": "○", "error": "!"}
        for i, button in enumerate(self.cards):
            status = statuses[i]
            button.setProperty("workflowState", status)
            button.setProperty("isCurrent", i == self.state.step)
            button.setChecked(i == self.state.step)
            button.setText(
                f"{i + 1:02d}  {self.STEPS[i][0]}\n"
                f"{lamps[status]}  {names[i]}"
            )
            button.setEnabled(True)
            button.style().unpolish(button)
            button.style().polish(button)
        self.workspaces.setCurrentIndex(self.state.step)
        self.current_title.setText(
            f"{self.STEPS[self.state.step][0]} · Schritt {self.state.step + 1}/{STEP_COUNT}"
        )
        if self.state.step in self.review_buttons:
            button = self.review_buttons[self.state.step]
            button.setText(
                "Bestätigung zurücknehmen"
                if self.state.step in self.state.reviewed_steps
                else "Als fachlich geprüft markieren"
            )
        if self._data_error:
            self.note.setText(self._data_error)
        elif self._notice:
            self.note.setText(self._notice)
        else:
            self.note.clear()
            self.note.hide()
        self._refresh_controls()
