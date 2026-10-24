"""Kompakter sechsstufiger Arbeitsbereich für die lokale NTF-Prüfung.

Die sechs Workflow-Stationen stehen nebeneinander. Darunter zeigt eine
QStackedWidget genau EINEN Arbeitsschritt; nur Tabellen scrollen intern.
Rohdatenparser, QEC-Downloader und ChatGPT-Vertrag werden nicht dupliziert.
"""
from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import QSortFilterProxyModel, Qt, Signal
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QGridLayout, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QProgressBar, QPushButton,
    QSizePolicy, QStackedWidget, QTableView, QVBoxLayout, QWidget,
)

from ntf_insight.acquisition.qec_archive import local_qec_archive
from ntf_insight.acquisition.qec_tool import QecTarget, parse_qec_targets
from ntf_insight.app.models.simple_table_model import SimpleTableModel
from ntf_insight.components.registry import list_component_profiles
from ntf_insight.reporting.chatgpt_exchange import ChatGPTAnalyseStore
from ntf_insight.storage.cluster_evidence_store import (
    CATEGORY_LABELS, ClusterEvidenceStore, EVIDENCE_CATEGORIES,
)
from ntf_insight.storage.workflow_ai_chain import WorkflowAIChainStore
from ntf_insight.storage.workflow_projects import WorkflowProjectStore
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


class WorkflowPage(QWidget):
    """Die Startseite bleibt geöffnet; Stationen ändern den lokalen Inhalt."""

    navigate = Signal(str, str)
    action_requested = Signal(str)
    project_selected = Signal(str, str)

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
        self.state = progress_store.load(self.profile_id, part)
        self.qec_root = progress_store.store.path.parent / "qec"
        self._all_rows: list[dict] = []
        self._scoped_rows: list[dict] = []
        self._chatgpt_by_case: dict[str, dict] = {}
        self._source_name = ""
        self._data_error = ""
        self._notice = ""
        self._error_step: int | None = None
        self._busy = False
        self._import_busy = False
        self._import_can_resume = False
        self.analysis_store = ChatGPTAnalyseStore(progress_store.store) if qec_store else None
        self.context_store = ClusterEvidenceStore(progress_store.store)
        self.project_store = WorkflowProjectStore(progress_store.store)
        self.ai_chain = WorkflowAIChainStore(progress_store.store)
        self.context_files = []
        self.first_package = None
        self._context_busy = False
        self._context_scrapers_busy: set[str] = set()


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
        header.addWidget(self.adopt_button)
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
        self.project_ecus_label = QLabel(objectName="PageSubtitle")
        outer.addWidget(self.project_ecus_label)

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

        controls = QHBoxLayout()
        self.previous_button = QPushButton("← Zurück")
        self.previous_button.clicked.connect(lambda: self._move(-1))
        controls.addWidget(self.previous_button)
        self.current_title = QLabel(objectName="CardTitle")
        controls.addWidget(self.current_title, 1)
        self.pause_button = QPushButton("Pausieren")
        self.pause_button.clicked.connect(self._toggle_pause)
        controls.addWidget(self.pause_button)
        self.next_button = QPushButton("Weiter →")
        self.next_button.clicked.connect(lambda: self._move(1))
        controls.addWidget(self.next_button)
        outer.addLayout(controls)

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
        if subtitle:
            label = QLabel(subtitle, objectName="PageSubtitle")
            label.setWordWrap(True)
            body.addWidget(label)
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
        actions = QHBoxLayout()
        self.download_all_button = self._add_action(
            actions, "Alle QEC-Berichte herunterladen / aktualisieren",
            lambda: self.action_requested.emit("qec_download_all"),
        )
        self.download_selected_button = self._add_action(
            actions, "Markierte herunterladen",
            lambda: self.action_requested.emit("qec_download_selected"),
        )
        self.cancel_download_button = self._add_action(
            actions, "Abruf abbrechen",
            lambda: self.action_requested.emit("qec_download_cancel"),
        )
        self.local_qec_button = self._add_action(
            actions, "Lokale Berichte einlesen",
            lambda: self.action_requested.emit("qec_import_local"),
        )
        actions.addStretch(1)
        body.addLayout(actions)
        self.qec_status = QLabel(objectName="PageSubtitle")
        self.qec_status.setWordWrap(True)
        body.addWidget(self.qec_status)
        self.qec_table, self.qec_model = _create_table((
            "FIN", "QEC-Fall", "Referenz", "Sachnummer",
            "Letzter Download", "Downloadstatus",
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
        self.ai_package_status = QLabel(objectName="PageSubtitle")
        self.ai_package_status.setWordWrap(True)
        body.addWidget(self.ai_package_status)
        self.ntf_status = QLabel(objectName="PageSubtitle")
        body.addWidget(self.ntf_status)
        self.ntf_table, self.ntf_model = _create_table((
            "FIN", "QEC-Fall", "SSL-Endbefund", "QEC-Entscheidung",
            "ChatGPT-Vorschlag", "Prüfstatus",
        ))
        body.addWidget(self.ntf_table, 1)

    def _build_step_four(self) -> None:
        """Unterlagenzentrale: Quellenabrufe und kategorisierte technische Dokumente."""
        _, body = self._workspace(
            "04 · Unterlagen für den zweiten ChatGPT-Durchlauf",
            "Quellen abrufen oder Dateien einsammeln · Unbekannte Scraper werden nicht simuliert.",
        )
        scraper_grid = QGridLayout()
        scraper_grid.setHorizontalSpacing(8)
        scraper_grid.setVerticalSpacing(3)
        self.context_scraper_buttons: dict[str, dict[str, QPushButton]] = {}
        self.context_import_buttons: dict[str, QPushButton] = {}
        self.context_counts: dict[str, QLabel] = {}
        for index, (category, label) in enumerate(EVIDENCE_CATEGORIES[:4]):
            scraper_grid.addWidget(QLabel(label), index, 0)
            buttons: dict[str, QPushButton] = {}
            for j, (key, caption) in enumerate((
                ("all", "Alle abrufen"),
                ("selected", "Markierte"),
                ("cancel", "Stop"),
            ), start=1):
                button = QPushButton(caption, objectName="WorkflowAction")
                if category in ("diagnosis_viewer", "tips_writer"):
                    button.clicked.connect(
                        lambda _checked=False, c=category, k=key:
                        self.action_requested.emit(f"context_scrape:{c}:{k}")
                    )
                else:
                    button.setEnabled(False)
                    button.setToolTip(
                        "Ein automatisierter Scraper ist für diese Quelle "
                        "im Repository noch nicht implementiert."
                    )
                    if key == "all":
                        button.setText("Scraper offen")
                    else:
                        button.setVisible(False)
                buttons[key] = button
                scraper_grid.addWidget(button, index, j)
            buttons["import"] = QPushButton("Dateien wählen …", objectName="WorkflowAction")
            buttons["import"].clicked.connect(
                lambda _checked=False, c=category:
                self.action_requested.emit(f"context_files:{c}")
            )
            self.context_import_buttons[category] = buttons["import"]
            scraper_grid.addWidget(buttons["import"], index, 4)
            count = QLabel("0", objectName="PageSubtitle")
            scraper_grid.addWidget(count, index, 5)
            self.context_counts[category] = count
            self.context_scraper_buttons[category] = buttons
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
            group = QHBoxLayout()
            group.setSpacing(3)
            name = QLabel(short_labels.get(category, label))
            name.setToolTip("Dateien werden unverändert lokal und mit SHA-256 archiviert.")
            group.addWidget(name, 1)
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
            tech_grid.addLayout(group, row, col)
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
        self.context_self_import_button = QPushButton("Sonstige Dateien importieren …")
        self.context_self_import_button.setToolTip(
            "Vorhandenen manuellen Quellenimport öffnen, ohne eine "
            "zweite Importlogik zu erzeugen."
        )
        self.context_self_import_button.clicked.connect(
            lambda: self.action_requested.emit("self_import")
        )
        body.addWidget(self.context_self_import_button)
        self.context_summary = QLabel(objectName="PageSubtitle")
        self.context_summary.setWordWrap(True)
        body.addWidget(self.context_summary)

    def _build_following_steps(self) -> None:
        """Die lokale FIN-Clusterberechnung wird in Schritt 05 eingehängt."""
        _, body = self._workspace(
            "05 · Clusteranalyse",
            "Lokale DTC-Cluster und zweiter ChatGPT-Durchlauf. "
            "Technische Unterlagen dienen der Erklärung und Plausibilisierung.",
        )
        self.cluster_base_status = QLabel(objectName="PageSubtitle")
        self.cluster_base_status.setWordWrap(True)
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
        body.addWidget(self.cluster_result_status)
        self.local_cluster_holder = QWidget()
        self.local_cluster_layout = QVBoxLayout(self.local_cluster_holder)
        self.local_cluster_layout.setContentsMargins(0, 0, 0, 0)
        self.local_cluster_layout.addWidget(
            QLabel("Die vorhandene lokale Clusteranalyse wird hier eingebunden.")
        )
        body.addWidget(self.local_cluster_holder, 1)
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
        layout.addWidget(widget)
        widget.show()

    def _refresh_project_selector(self) -> None:
        projects = self.project_store.list_projects()
        current = (self.profile_id, self._context_part)
        self.project_combo.blockSignals(True)
        self.project_combo.clear()
        self.project_combo.addItem("Projekt wählen", None)
        for project in projects:
            self.project_combo.addItem(
                project.title, (project.profile_id, project.part_number)
            )
        idx = self.project_combo.findData(current)
        self.project_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.project_combo.blockSignals(False)
        project = self.project_store.get(*current)
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
        self.state = self.progress_store.load(profile, part)
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
        self._refresh_controls()

    def set_context_busy(self, busy: bool) -> None:
        self._context_busy = busy
        self._refresh_controls()

    def set_context_scraper_busy(self, category: str, busy: bool) -> None:
        if busy:
            self._context_scrapers_busy.add(category)
        else:
            self._context_scrapers_busy.discard(category)
        self._refresh_controls()

    def refresh_context_files(self) -> None:
        """Kontextdaten der aktuellen Sachnummer ohne Dateiinhalt in GUI anzeigen."""
        self.context_files = self.context_store.list_files(
            self.profile_id, self._context_part
        )
        counts = {name: 0 for name in CATEGORY_LABELS}
        for file in self.context_files:
            counts[file.category] += 1
        for key, count_label in self.context_counts.items():
            count_label.setText(str(counts[key]))
        self.context_model.set_rows([
            (
                CATEGORY_LABELS[item.category], item.original_name,
                f"{item.size_bytes / (1024**2):.1f} MB",
                item.sha256[:12],
                item.imported_at.strftime("%d.%m.%Y %H:%M"),
            )
            for item in self.context_files
        ])
        self.context_summary.setText(
            f"{len(self.context_files)} Unterlagen in "
            f"{sum(v > 0 for v in counts.values())} von "
            f"{len(counts)} Kategorien · "
            "Dateien werden nicht automatisch an ChatGPT gesendet."
        )

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
            self.state = self.progress_store.load(profile_id, part)
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
        if self.state.paused or not 0 <= index < STEP_COUNT:
            return
        self.state = replace(self.state, step=index)
        self._error_step = None
        self._notice = ""
        self._save()

    def _move(self, delta: int) -> None:
        if self.state.paused:
            return
        self._open_step(max(0, min(STEP_COUNT - 1, self.state.step + delta)))

    def _toggle_pause(self) -> None:
        self.state = replace(self.state, paused=not self.state.paused)
        self._save()

    def _review(self) -> None:
        if self.state.paused or self.state.step not in (3, 4):
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
                source = self.qec_store.active_source()
                self._source_name = source.original_name if source else ""
            if self.analysis_store is not None:
                for finding in self.analysis_store.list_case_findings(limit=10000):
                    self._chatgpt_by_case.setdefault(finding["case_id"], finding)
        except (OSError, ValueError) as exc:
            # Keine rohen Berichtsdetails oder FINs in Logs/Dialoge übertragen.
            self._data_error = (
                "QEC-/ChatGPT-Daten konnten nicht geladen werden: "
                + type(exc).__name__
            )
        self.refresh_context_files()
        self._refresh_project_selector()
        self.refresh()

    def _update_tables(self) -> None:
        self._scoped_rows = self._rows_for_context()
        self.fin_model.set_rows([
            (
                r["fin"], r["case_id"], r["reference"], r["part_number"],
                r["finding"], "Ja" if r["tp_dashboard"] else "Fehlt",
                r["decision"], "Ja" if r["report"] else "Nein",
            )
            for r in self._scoped_rows
        ])
        self.qec_model.set_rows([
            (
                r["fin"], r["case_id"], r["reference"], r["part_number"],
                info.date_label if info else "—",
                "Gespeichert" if info else "Ausstehend",
            )
            for r in self._scoped_rows
            for info in [local_qec_archive(self.qec_root, r["fin"], r["reference"])]
        ])
        self.ntf_model.set_rows([
            (
                r["fin"], r["case_id"], r["finding"], r["decision"],
                self._chatgpt_by_case[r["case_id"]]["bewertung"].get(
                    "ntf_bewertung", "Nicht bewertet"
                ) if r["case_id"] in self._chatgpt_by_case else "—",
                self._chatgpt_by_case[r["case_id"]]["review_status"]
                if r["case_id"] in self._chatgpt_by_case else "—",
            )
            for r in self._scoped_rows
        ])

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

    def set_download_busy(self, busy: bool, message: str = "") -> None:
        self._busy = busy
        if message:
            self.qec_status.setText(message)
        self._refresh_controls()

    def _refresh_controls(self) -> None:
        paused = self.state.paused
        has_rows = bool(self._scoped_rows)
        self.previous_button.setEnabled(not paused and self.state.step > 0)
        self.next_button.setEnabled(not paused and self.state.step < STEP_COUNT - 1)
        self.pause_button.setText("Fortsetzen" if paused else "Pausieren")
        self.qec_import_button.setEnabled(not paused and not self._import_busy)
        for button in self.context_import_buttons.values():
            button.setEnabled(not paused and not self._context_busy)
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
            not paused and not self._context_busy and bool(self.context_files)
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
            busy = category in self._context_scrapers_busy
            buttons["all"].setEnabled(not paused and not busy and bool(self._scoped_rows))
            buttons["selected"].setEnabled(
                not paused and not busy and bool(
                    self.qec_table.selectionModel().selectedRows()
                )
            )
            buttons["cancel"].setEnabled(busy)
        self.cancel_import_button.setEnabled(self._import_busy)
        self.resume_import_button.setEnabled(
            not paused and not self._import_busy and self._import_can_resume
        )
        self.qec_portal_button.setEnabled(not paused and self.profile_id == "coolant_pump")
        self.qec_export_button.setEnabled(not paused and has_rows)
        self.download_all_button.setEnabled(not paused and not self._busy and has_rows)
        self.download_selected_button.setEnabled(
            not paused and not self._busy and bool(
                self.qec_table.selectionModel().selectedRows()
            )
        )
        self.cancel_download_button.setEnabled(self._busy)
        self.local_qec_button.setEnabled(not paused and not self._busy)
        self.ai_export_button.setEnabled(not paused and has_rows)
        self.ai_import_button.setEnabled(not paused)
        for button in self.review_buttons.values():
            button.setEnabled(not paused)

    def refresh(self) -> None:
        self._update_tables()
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
            "done" if len(self.context_files) and 3 in self.state.reviewed_steps else (
                "partial" if self.context_files else "pending"
            ),
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
        self.qec_status.setText(
            self.qec_status.text() if self._busy else
            f"{downloaded} von {total} FINs mit QEC-Bericht · "
            "markierte Tabellenzeilen für gezielten Abruf"
        )
        self.ntf_status.setText(
            f"NTF: {stats['ntf']} · Kein NTF: {stats['not_ntf']} · "
            f"Offen: {stats['open']} · ChatGPT-Vorschläge getrennt von QEC-Entscheidungen"
        )
        names = (
            f"{total} FINs", f"{downloaded}/{total} Berichte",
            f"{reviewed}/{stats['cases']} geprüft", f"{len(self.context_files)} Unterlagen",
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
            button.setEnabled(not self.state.paused)
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
        if self.state.paused:
            self.note.setText("Workflow pausiert · Fortschritt lokal gespeichert.")
        elif self._data_error:
            self.note.setText(self._data_error)
        elif self._notice:
            self.note.setText(self._notice)
        else:
            self.note.setText(
                "Grün: vollständig · Gelb: teilweise · Grau: offen. "
                "Die aktuelle Station ist hervorgehoben."
            )
        self._refresh_controls()
