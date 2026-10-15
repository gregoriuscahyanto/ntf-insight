"""Case detail, evidence and timeline page."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSortFilterProxyModel, Qt, Signal, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTableView,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ntf_insight.acquisition.credentials import (
    LoginCredentials, clear_saved_credentials, load_saved_credentials, save_credentials,
)
from ntf_insight.acquisition.diagnosis_viewer import parse_fins, recently_attempted, scan_local_quicktests
from ntf_insight.acquisition.qec_archive import local_qec_archive
from ntf_insight.acquisition.qec_tool import QecTarget, parse_qec_targets
from ntf_insight.app.quicktest_download_worker import DownloadWorker
from ntf_insight.analysis.evidence_engine import generate_case_evidence
from ntf_insight.analysis.qec_findings import qec_ssl_finding_label
from ntf_insight.analysis.diagnostic_observations import unique_diagnostic_observations
from ntf_insight.analysis.fin_diagnostics import (
    FIN_ONLY_PREFIX,
    build_fin_only_previews,
)
from ntf_insight.analysis.ecu_version_changes import detect_ecu_version_changes
from ntf_insight.analysis.recurrence import analyze_recurrence, format_faults
from ntf_insight.analysis.replacement_dates import compare_replacement_dates
from ntf_insight.analysis.timeline import build_timeline
from ntf_insight.app.dialogs.manual_entry_dialogs import (
    ManualEventDialog,
    ManualHistoryDialog,
    NewCaseDialog,
)
from ntf_insight.app.models.case_table_model import CaseRow, CaseTableModel
from ntf_insight.app.models.simple_table_model import SimpleTableModel
from ntf_insight.app.models.timeline_table_model import TimelineTableModel
from ntf_insight.app.widgets.event_time_plot import EventTimePlot
from ntf_insight.app.widgets.cpc3_software_panel import CPC3SoftwarePanel
from ntf_insight.app.widgets.cpc3_pump_overview_panel import CPC3PumpOverviewPanel
from ntf_insight.app.widgets.quicktest_browser import QuickTestBrowser
from ntf_insight.app.widgets.qec_case_download import QecCaseDownloadPanel
from ntf_insight.app.widgets.fin_zip_export import FinZipExportPanel
from ntf_insight.app.widgets.case_checkbox_delegate import CaseCheckboxDelegate
from ntf_insight.app.widgets.autoexport_fin_workspace import AutoExportFinWorkspace
from ntf_insight.ingestion.manual_entry import ManualCaseService, ManualEntryError
from ntf_insight.ingestion.real_source_parsers import canonical_fin
from ntf_insight.domain.events import PartReplacement
from ntf_insight.reporting.markdown import save_case_report
from ntf_insight.storage.reference_repositories import ReferenceRepository
from ntf_insight.storage.repositories import CaseRepository
from ntf_insight.storage.quicktest_store import QuickTestStore
from ntf_insight.storage.dtc_review_store import DtcReviewStore
from ntf_insight.storage.source_knowledge_store import SourceKnowledgeStore


class CasePage(QWidget):
    """Inspect FIN/case combinations and edit persistent manual information."""

    case_saved = Signal(str)
    quicktests_downloaded = Signal(object)
    qec_reports_downloaded = Signal(object)

    def __init__(
        self,
        repository: CaseRepository,
        references: ReferenceRepository,
        manual_service: ManualCaseService | None = None,
        *,
        review_store: DtcReviewStore | None = None,
        download_root: Path | None = None,
        qec_data_dir: Path | None = None,
    ) -> None:
        super().__init__()
        self.repository = repository
        self.references = references
        self.manual_service = manual_service
        self.review_store = review_store
        self.quicktest_download_root = Path(download_root) if download_root is not None else None
        self.qec_data_dir = (
            Path(qec_data_dir) if qec_data_dir is not None
            else self.quicktest_download_root.parent if self.quicktest_download_root is not None
            else None
        )
        self._quicktest_worker: DownloadWorker | None = None
        self._quicktest_files_for_import: list[Path] = []
        self.source_knowledge = (
            SourceKnowledgeStore(manual_service.store)
            if manual_service is not None else None
        )
        self.fin_only_previews = (
            build_fin_only_previews(
                QuickTestStore(manual_service.store),
                {case.vin for case in repository.list_cases()},
            )
            if manual_service is not None
            else {}
        )
        self.real_cases = repository.list_cases()
        self.view_cases = [
            *self.real_cases,
            *self.fin_only_previews.values(),
        ]
        self._case_by_id = {case.case_id: case for case in self.view_cases}
        self._tips_fins = (
            self.source_knowledge.autoexport_source_fins("autoexport_tips")
            if self.source_knowledge is not None else frozenset()
        )
        self._syncing_quicktest_fin = False

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)

        self.detail_tabs = QTabWidget()
        outer_layout.addWidget(self.detail_tabs)

        # ONE visible cluster-analysis surface for all unique FINs.
        # AutoExport and QEC pre-swap features enter the SAME HDBSCAN
        # model; there is no separate AutoExport/KMeans or embedded old page.
        self.cluster_workspace = AutoExportFinWorkspace(
            self.source_knowledge, self.real_cases,
            population_metrics=(
                self.source_knowledge.autoexport_population()
                if self.source_knowledge is not None else {}
            ),
            review_store=review_store,
            quicktest_fins=(
                tuple(QuickTestStore(manual_service.store).list_fins())
                if manual_service is not None else ()
            ),
        )
        # Compatibility alias for local FIN navigation and prior tests.
        self.autoexport_fin_workspace = self.cluster_workspace
        self.detail_tabs.addTab(self.cluster_workspace, "Clusteranalyse")
        self.cluster_workspace.fin_requested.connect(
            self._open_autoexport_fin_history
        )
        self.cluster_workspace.case_requested.connect(self.select_case)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        scroll.setWidget(content)
        self.analysis_tab = scroll
        self.detail_tabs.addTab(scroll, "FIN / Fallanalyse")

        if manual_service is not None:
            self.quicktest_browser = QuickTestBrowser(
                QuickTestStore(manual_service.store)
            )
            self.detail_tabs.addTab(self.quicktest_browser, "QuickTests nach FIN")
        else:
            self.quicktest_browser = None

        # One case per row (not one row per FIN): SW intervention, observed
        # versions and actual CPC3 quick-test outcomes for all pump cases.
        # Heavy local AutoExport reads start only when this tab is opened.
        self.cpc3_overview = CPC3PumpOverviewPanel(
            self.real_cases, self.source_knowledge,
        )
        self.detail_tabs.addTab(
            self.cpc3_overview, "ECU · SW-Übersicht",
        )
        self.cpc3_overview.case_requested.connect(self.select_case)
        self.detail_tabs.currentChanged.connect(
            lambda _index: (
                self.cpc3_overview.ensure_loaded()
                if self.detail_tabs.currentWidget() is self.cpc3_overview
                else None
            )
        )

        layout = QVBoxLayout(content)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(12)

        layout.addWidget(QLabel("FIN / Fallanalyse", objectName="PageTitle"))
        intro = QLabel(
            "FINs mit QuickTests werden auch ohne NTF-/QEC-Fall angezeigt. "
            "Mit einem Schadteilfall werden Diagnose, Tausch und Befund "
            "für die Vorher-/Nachher-Analyse verknüpft.",
            objectName="PageSubtitle",
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.selector = QComboBox(self)
        self.selector.setMinimumWidth(260)
        shared_header = QHBoxLayout()
        shared_header.setContentsMargins(22, 12, 22, 8)
        shared_header.addWidget(QLabel("Fälle / FIN", objectName="PageTitle"))
        shared_header.addStretch(1)
        shared_header.addWidget(QLabel("Aktive FIN / Fall:"))
        shared_header.addWidget(self.selector)
        outer_layout.insertLayout(0, shared_header)
        for case in self.view_cases:
            title = (
                f"Nur QuickTests · {case.vin}"
                if case.case_id.startswith(FIN_ONLY_PREFIX)
                else f"{case.case_id} · {case.vin}"
            )
            self.selector.addItem(title, case.case_id)
        self.selector.currentIndexChanged.connect(self._refresh)

        selector_row = QHBoxLayout()
        search = QLineEdit()
        self.case_search = search
        search.setPlaceholderText("Fall, FIN / VIN, Bauteil oder Bewertung suchen …")
        search.setClearButtonEnabled(True)
        selector_row.addWidget(search, 1)

        create_button = QPushButton("+ Neuer Fall")
        create_button.setToolTip("Neuen FIN/Fall manuell erfassen")
        create_button.setEnabled(self.manual_service is not None)
        create_button.clicked.connect(self._create_case)
        selector_row.addWidget(create_button)

        self.add_event_button = QPushButton("+ Ereignis")
        self.add_event_button.setToolTip("Kurztest, DTC, Tausch oder weitere Information ergänzen")
        self.add_event_button.setEnabled(self.manual_service is not None)
        self.add_event_button.clicked.connect(self._add_event)
        selector_row.addWidget(self.add_event_button)

        self.find_similar_button = QPushButton("In Clusteranalyse zeigen")
        self.find_similar_button.setToolTip(
            "Zeigt den gewählten Schadteilfall in der Clusteranalyse "
            "mit Berechnungstabellen. FIN-only-QuickTests bilden keine "
            "zusätzlichen Schadteilfälle."
        )
        self.find_similar_button.setEnabled(False)
        self.find_similar_button.clicked.connect(self._request_similar_cases)
        selector_row.addWidget(self.find_similar_button)

        export_button = QPushButton("Markdown-Bericht exportieren…")
        self.export_button = export_button
        export_button.clicked.connect(self._export_report)
        selector_row.addWidget(export_button)
        layout.addLayout(selector_row)

        case_rows: list[CaseRow] = []
        for case in self.view_cases:
            is_preview = case.case_id.startswith(FIN_ONLY_PREFIX)
            replacement = case.investigated_replacement()
            tips_status = (
                "Ja" if any(obs.tips_case_id for obs in case.tips_observations)
                else "FIN-Hinweis" if case.vin in self._tips_fins
                else "—"
            )
            recurrence = analyze_recurrence(case)
            if is_preview:
                recurrence_text = "Ohne Tauschanker"
            elif recurrence.assessable:
                recurrence_text = "Ja" if recurrence.has_recurrence else "Nein"
            else:
                recurrence_text = "Unbekannt"
            case_rows.append(
                CaseRow(
                    case_id=case.case_id,
                    vin=case.vin,
                    component=case.component_type,
                    dtc_count=len(unique_diagnostic_observations(case.diagnostics)),
                    replacement=(
                        replacement.occurred_at.strftime("%Y-%m-%d")
                        if replacement is not None
                        else None
                    ),
                    recurrence=recurrence_text,
                    assessment=(
                        "Kein NTF-Fall"
                        if is_preview
                        else str(case.assessment.root_cause)
                        if case.assessment is not None
                        else None
                    ),
                    tips_status=tips_status,
                )
            )

        self.case_model = CaseTableModel(case_rows)
        self.case_model.selection_changed.connect(self._update_quicktest_selection)
        self.case_model.selection_changed.connect(self._update_qec_selection)
        self.case_model.selection_changed.connect(self._update_fin_zip_selection)
        self.case_proxy = QSortFilterProxyModel(self)
        self.case_proxy.setSourceModel(self.case_model)
        self.case_proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.case_proxy.setFilterKeyColumn(-1)
        search.textChanged.connect(self._filter_cases)

        self.case_table = QTableView()
        self.case_table.setModel(self.case_proxy)
        self.case_table.setItemDelegateForColumn(
            CaseTableModel.CHECK_COLUMN, CaseCheckboxDelegate(self.case_table)
        )
        self.case_table.setMaximumHeight(190)
        self.case_table.setAlternatingRowColors(True)
        self.case_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.case_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.case_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.case_table.setSortingEnabled(True)
        self.case_table.verticalHeader().setVisible(False)
        self.case_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.case_table.horizontalHeader().setSectionResizeMode(
            CaseTableModel.CHECK_COLUMN, QHeaderView.ResizeMode.Fixed
        )
        self.case_table.horizontalHeader().resizeSection(CaseTableModel.CHECK_COLUMN, 64)
        self.case_table.horizontalHeader().setSectionResizeMode(
            CaseTableModel.QUICKTEST_DATE_COLUMN, QHeaderView.ResizeMode.ResizeToContents
        )
        self.case_table.horizontalHeader().setSectionResizeMode(
            CaseTableModel.QEC_DATE_COLUMN, QHeaderView.ResizeMode.ResizeToContents
        )
        self.case_table.horizontalHeader().setSectionResizeMode(
            CaseTableModel.TIPS_COLUMN, QHeaderView.ResizeMode.ResizeToContents
        )
        self.case_table.clicked.connect(self._case_clicked)
        self.case_table.clicked.connect(self._case_table_quicktest_link_clicked)
        self.case_table.clicked.connect(self._case_table_qec_link_clicked)
        self.case_table.selectionModel().currentRowChanged.connect(
            lambda current, _previous: self._case_clicked(current)
        )
        layout.addWidget(self.case_table)

        layout.addWidget(QLabel("QuickTest-Abruf für Fälle / FIN", objectName="CardTitle"))
        login_row = QHBoxLayout()
        self.quicktest_user_id = QLineEdit()
        self.quicktest_user_id.setPlaceholderText("Mercedes SSO · Benutzer-ID")
        self.quicktest_user_id.setMaximumWidth(240)
        login_row.addWidget(self.quicktest_user_id)
        self.quicktest_password = QLineEdit()
        self.quicktest_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.quicktest_password.setPlaceholderText(
            "Passwort (leer lassen, wenn sicher gespeichert)"
        )
        login_row.addWidget(self.quicktest_password, 1)
        self.quicktest_remember_login = QCheckBox("Sicher speichern")
        self.quicktest_remember_login.setToolTip(
            "Benutzer-ID und Passwort ausschließlich im Windows-Anmeldeinformationsmanager "
            "speichern, niemals in lokalen Konfigurationsdateien."
        )
        self.quicktest_remember_login.setChecked(True)
        login_row.addWidget(self.quicktest_remember_login)
        self.quicktest_forget_login = QPushButton("Anmeldedaten löschen")
        self.quicktest_forget_login.clicked.connect(self._forget_quicktest_login)
        login_row.addWidget(self.quicktest_forget_login)
        layout.addLayout(login_row)

        try:
            credentials = load_saved_credentials()
        except RuntimeError:
            credentials = None
        if credentials:
            self.quicktest_user_id.setText(credentials.user_id)
        self.shared_credentials_status = QLabel(objectName="PageSubtitle")
        self.shared_credentials_status.setWordWrap(True)
        self.shared_credentials_status.setToolTip(
            "Gemeinsame Benutzer-ID und Passwort für Diagnosis Viewer und QEC. "
            "Nur im Windows-Anmeldeinformationsmanager gespeichert. "
            "PING ID wird weiterhin manuell bestätigt."
        )
        layout.addWidget(self.shared_credentials_status)
        self._refresh_shared_credentials_status()

        download_row = QHBoxLayout()
        self.quicktest_download_all_button = QPushButton(
            "Alle Quicktests herunterladen/aktualisieren"
        )
        self.quicktest_download_all_button.clicked.connect(
            lambda: self._start_quicktest_download(selected_only=False)
        )
        download_row.addWidget(self.quicktest_download_all_button)
        self.quicktest_download_selected_button = QPushButton(
            "Quicktests für ausgewählte Fälle herunterladen/aktualisieren"
        )
        self.quicktest_download_selected_button.clicked.connect(
            lambda: self._start_quicktest_download(selected_only=True)
        )
        self.quicktest_download_selected_button.setEnabled(False)
        download_row.addWidget(self.quicktest_download_selected_button)
        self.quicktest_retry_24h = QCheckBox("24-Stunden-Sperre einmalig übergehen")
        self.quicktest_retry_24h.setToolTip(
            "Standardmäßig werden FINs mit Abrufversuch innerhalb der letzten "
            "24 Stunden nicht erneut heruntergeladen."
        )
        download_row.addWidget(self.quicktest_retry_24h)
        self.quicktest_cancel_button = QPushButton("Abbrechen")
        self.quicktest_cancel_button.setEnabled(False)
        self.quicktest_cancel_button.clicked.connect(self._cancel_quicktest_download)
        download_row.addWidget(self.quicktest_cancel_button)
        layout.addLayout(download_row)

        self.quicktest_download_status = QLabel(
            "Fälle über die Checkbox links auswählen. "
            "Blau unterstrichene Abrufdaten öffnen den lokalen FIN-Ordner.",
            objectName="PageSubtitle",
        )
        self.quicktest_download_status.setWordWrap(True)
        layout.addWidget(self.quicktest_download_status)
        self._refresh_quicktest_download_dates()
        self._update_quicktest_selection()

        # QEC reuses the existing CheckState column AND Mercedes-SSO login row.
        # Its buttons mirror the existing QuickTest action row and status.
        self.qec_download = None
        if self.qec_data_dir is not None:
            self.qec_download = QecCaseDownloadPanel(
                self.qec_data_dir,
                all_targets=self._all_qec_targets,
                selected_targets=self._selected_qec_targets,
                login_resolver=self._resolve_qec_credentials,
            )
            self.qec_download.downloads_completed.connect(
                lambda _results: self._refresh_qec_download_dates()
            )
            self.qec_download.import_requested.connect(self.qec_reports_downloaded.emit)
            layout.addWidget(self.qec_download)
        self._refresh_qec_download_dates()
        self._update_qec_selection()

        # Exporte pro FIN, nicht pro Schadteilfall: nutzt dieselben
        # persistenten Checkboxen wie QuickTest und QEC.
        self.fin_zip_export = None
        if self.qec_data_dir is not None:
            self.fin_zip_export = FinZipExportPanel(
                self.qec_data_dir,
                all_fins=self.case_model.all_fins,
                selected_fins=self.case_model.selected_fins,
            )
            layout.addWidget(self.fin_zip_export)
        self._update_fin_zip_selection()

        summary = QGridLayout()
        summary.setHorizontalSpacing(24)
        summary.setVerticalSpacing(6)

        self.component_value = QLabel("—")
        self.replacement_value = QLabel("—")
        self.autoexport_date_value = QLabel("—")
        self.effective_swap_value = QLabel("—")
        self.date_match_value = QLabel("—")
        self.root_cause_value = QLabel("—")
        self.supplier_value = QLabel("—")
        self.ssl_finding_value = QLabel("—")
        self.ssl_finding_value.setWordWrap(True)
        self.confidence_value = QLabel("—")
        self.recurrence_value = QLabel("—")
        for value in (
            self.replacement_value, self.autoexport_date_value,
            self.effective_swap_value, self.date_match_value,
        ):
            value.setWordWrap(True)
            value.setToolTip(
                "Belegtes Quelldatum und der für die NTF-Regeln verwendete "
                "Tauschanker können voneinander abweichen."
            )

        fields = (
            ("Bauteil", self.component_value),
            ("QEC-/dokumentiertes Tauschdatum", self.replacement_value),
            ("AutoExport-Reparaturdatum", self.autoexport_date_value),
            ("Für NTF verwendeter Tauschanker", self.effective_swap_value),
            ("Datumsabgleich", self.date_match_value),
            ("Aktuelle Bewertung", self.root_cause_value),
            ("Lieferantenbeteiligung", self.supplier_value),
            ("QEC · SSL-Endbefund", self.ssl_finding_value),
            ("Konfidenz", self.confidence_value),
            ("Gleicher Fehler nach Tausch", self.recurrence_value),
        )
        for index, (title, value) in enumerate(fields):
            label = QLabel(title, objectName="CardTitle")
            value.setStyleSheet("font-weight: 600;")
            summary.addWidget(label, index // 3 * 2, index % 3)
            summary.addWidget(value, index // 3 * 2 + 1, index % 3)
        layout.addLayout(summary)

        self.date_comparison_note = QLabel("—", objectName="PageSubtitle")
        self.date_comparison_note.setWordWrap(True)
        layout.addWidget(self.date_comparison_note)
        self.confirm_swap_button = QPushButton(
            "AutoExport-Datum als Tauschanker bestätigen…"
        )
        self.confirm_swap_button.setEnabled(False)
        self.confirm_swap_button.setToolTip(
            "Nur nach Prüfung der Werkstattunterlagen: Legt einen manuellen "
            "Tauschanker mit Audit-Eintrag an. Der ursprüngliche QEC-Termin "
            "und der AutoExport-Reparatureintrag bleiben erhalten."
        )
        self.confirm_swap_button.clicked.connect(self._confirm_autoexport_swap)
        layout.addWidget(self.confirm_swap_button)

        self.assessment_text = QLabel("—", objectName="PageSubtitle")
        self.assessment_text.setWordWrap(True)
        layout.addWidget(self.assessment_text)

        self.recurrence_text = QLabel("—", objectName="PageSubtitle")
        self.recurrence_text.setWordWrap(True)
        layout.addWidget(self.recurrence_text)

        layout.addWidget(QLabel("Zeitliches Auftreten", objectName="CardTitle"))
        time_hint = QLabel(
            "QEC-Tauschanker (gestrichelt) und AutoExport-Reparaturkandidat "
            "(gepunktet) werden getrennt gezeigt. Beide Daten können abweichen. "
            "ECU-Stand = beobachtete HW-/SW-Version eines Steuergeräts; "
            "Lieferantenbefund = Ergebnis einer Schadteilprüfung, keine Schuldzuweisung.",
            objectName="PageSubtitle",
        )
        time_hint.setWordWrap(True)
        layout.addWidget(time_hint)

        plot_controls = QHBoxLayout()
        time_filter = QLineEdit()
        self.time_filter = time_filter
        time_filter.setPlaceholderText(
            "Nur DTCs filtern: Steuergerät (z. B. CPC3) oder DTC (z. B. P26F100) …"
        )
        time_filter.setToolTip(
            "Filtert ausschließlich DTC-Beobachtungen. Kurztests, "
            "Steuergeräte-HW-/SW-Stände, Tausch-/Reparaturdaten, "
            "Werkstatt und Lieferantenbefunde bleiben sichtbar."
        )
        time_filter.setClearButtonEnabled(True)
        plot_controls.addWidget(time_filter, 1)
        plot_controls.addWidget(QLabel("X-Achse:"))
        self.axis_selector = QComboBox()
        self.axis_selector.addItem("Datum / Uhrzeit", "date")
        self.axis_selector.addItem("Kilometerstand", "mileage")
        self.axis_selector.setToolTip(
            "Kilometerpositionen stammen aus den importierten Daten; "
            "fehlende km werden rechts als 'km unbekannt' gezeigt."
        )
        plot_controls.addWidget(self.axis_selector)
        layout.addLayout(plot_controls)

        self.time_plot = EventTimePlot()
        time_filter.textChanged.connect(self.time_plot.set_filter_text)
        self.axis_selector.currentIndexChanged.connect(
            lambda _index: self.time_plot.set_axis_mode(
                self.axis_selector.currentData()
            )
        )
        layout.addWidget(self.time_plot)

        # FIN-wide CPC3-SW evidence also includes AutoExport rows not attached
        # to the current QEC case. Read-only, no inferred update dates.
        self.cpc3_panel = CPC3SoftwarePanel(self.source_knowledge)
        self.cpc3_overview.ecu_selected.connect(self.cpc3_panel.set_ecu)
        layout.addWidget(self.cpc3_panel)

        layout.addWidget(QLabel(
            "Erkannte HW-/SW-Standabweichungen", objectName="CardTitle"
        ))
        self.version_change_summary = QLabel(
            "Noch keine Versionsvergleiche", objectName="PageSubtitle"
        )
        self.version_change_summary.setWordWrap(True)
        self.version_change_summary.setToolTip(
            "Vergleich jeweils derselben ECU zwischen QuickTests. "
            "Eine andere Version belegt kein tatsächliches Flash-Datum "
            "und keinen Hardwaretausch."
        )
        layout.addWidget(self.version_change_summary)

        self.version_change_model = SimpleTableModel((
            "ECU", "Art", "Vorher", "Nachher",
            "Letzter alter Stand", "Erster neuer Stand",
            "km vorher", "km nachher", "Quelle (neu)",
        ))
        self.version_change_table = QTableView()
        self.version_change_table.setModel(self.version_change_model)
        self.version_change_table.setMaximumHeight(205)
        self.version_change_table.setMinimumHeight(90)
        self.version_change_table.setAlternatingRowColors(True)
        self.version_change_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.version_change_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.version_change_table.verticalHeader().setVisible(False)
        change_header = self.version_change_table.horizontalHeader()
        change_header.setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        change_header.setStretchLastSection(True)
        layout.addWidget(self.version_change_table)

        layout.addWidget(QLabel("Generierte Evidenz", objectName="CardTitle"))
        self.evidence_model = SimpleTableModel(
            ("Signal", "Kategoriehinweis", "Richtung", "Vorläufiges Gewicht", "Beschreibung")
        )
        self.evidence_table = QTableView()
        self.evidence_table.setModel(self.evidence_model)
        self.evidence_table.setMaximumHeight(190)
        self.evidence_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.evidence_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.evidence_table.setAlternatingRowColors(True)
        self.evidence_table.verticalHeader().setVisible(False)
        evidence_header = self.evidence_table.horizontalHeader()
        evidence_header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        evidence_header.setStretchLastSection(True)
        layout.addWidget(self.evidence_table)

        self.evidence_balance = QLabel("—", objectName="PageSubtitle")
        self.evidence_balance.setWordWrap(True)
        layout.addWidget(self.evidence_balance)

        timeline_row = QHBoxLayout()
        timeline_row.addWidget(QLabel("Timeline", objectName="CardTitle"))
        timeline_row.addStretch()

        self.correct_button = QPushButton("Markiertes Ereignis korrigieren")
        self.correct_button.setToolTip("Originaldaten bleiben erhalten; Korrekturen erscheinen im Änderungsverlauf.")
        self.correct_button.setEnabled(self.manual_service is not None)
        self.correct_button.clicked.connect(self._correct_event)
        timeline_row.addWidget(self.correct_button)

        history_button = QPushButton("Änderungsverlauf")
        self.history_button = history_button
        history_button.setEnabled(self.manual_service is not None)
        history_button.clicked.connect(self._show_history)
        timeline_row.addWidget(history_button)
        layout.addLayout(timeline_row)

        self.timeline_model = TimelineTableModel()
        self.timeline = QTableView()
        self.timeline.setModel(self.timeline_model)
        self.timeline.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.timeline.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.timeline.setAlternatingRowColors(True)
        self.timeline.verticalHeader().setVisible(False)
        header = self.timeline.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setStretchLastSection(True)
        layout.addWidget(self.timeline, 1)

        layout.addWidget(QLabel(
            "AutoExport-Gesamthistorie nach FIN (auch ohne QEC-Fall)",
            objectName="CardTitle",
        ))
        self.autoexport_history_note = QLabel(
            "Rohdaten aller bekannten DTC-, Werkstatt- und TIPS-Quellen. "
            "Sie sind keine zusätzlichen Schadteilfälle und keine bestätigten Ursachen.",
            objectName="PageSubtitle",
        )
        self.autoexport_history_note.setWordWrap(True)
        layout.addWidget(self.autoexport_history_note)

        fin_query = QHBoxLayout()
        fin_query.addWidget(QLabel("FIN:"))
        self.autoexport_fin_lookup = QLineEdit()
        self.autoexport_fin_lookup.setPlaceholderText(
            "17-stellige FIN eingeben; kein QEC-Fall erforderlich"
        )
        self.autoexport_fin_lookup.setMaximumWidth(340)
        fin_query.addWidget(self.autoexport_fin_lookup)
        self.autoexport_history_button = QPushButton("FIN-Historie suchen")
        self.autoexport_history_button.clicked.connect(
            lambda: self._load_autoexport_history(reset=True)
        )
        self.autoexport_fin_lookup.returnPressed.connect(
            lambda: self._load_autoexport_history(reset=True)
        )
        fin_query.addWidget(self.autoexport_history_button)
        fin_query.addStretch(1)
        layout.addLayout(fin_query)

        self.autoexport_history_model = SimpleTableModel((
            "Quellzeit (UTC falls Z)", "Typ", "DTC / Fallreferenz",
            "km", "Originaldiagnose / Eintrag", "Quellfundstelle",
        ))
        self.autoexport_history_table = QTableView()
        self.autoexport_history_table.setModel(self.autoexport_history_model)
        self.autoexport_history_table.setMinimumHeight(175)
        self.autoexport_history_table.setMaximumHeight(260)
        self.autoexport_history_table.setAlternatingRowColors(True)
        self.autoexport_history_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.autoexport_history_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.autoexport_history_table.verticalHeader().setVisible(False)
        self.autoexport_history_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        self.autoexport_history_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.autoexport_history_table)

        history_footer = QHBoxLayout()
        self.autoexport_history_count = QLabel(objectName="PageSubtitle")
        self.autoexport_history_count.setWordWrap(True)
        history_footer.addWidget(self.autoexport_history_count, 1)
        self.autoexport_history_more = QPushButton("Weitere 200")
        self.autoexport_history_more.clicked.connect(
            lambda: self._load_autoexport_history(reset=False)
        )
        history_footer.addWidget(self.autoexport_history_more)
        layout.addLayout(history_footer)
        self._autoexport_history_offset = 0
        self.autoexport_history_button.setEnabled(self.source_knowledge is not None)
        self.autoexport_history_more.setEnabled(False)

        if self.quicktest_browser is not None:
            self.quicktest_browser.fin_selector.currentIndexChanged.connect(
                lambda _index: self._on_quicktest_fin_changed()
            )

        if self.selector.count():
            self.case_table.selectRow(0)
            self._refresh()
        else:
            self._clear_view()


    def _qec_archive_for_case(self, case):
        if self.qec_data_dir is None:
            return None
        reference = str(getattr(case, "qec_reference", "") or "").strip()
        return local_qec_archive(
            self.qec_data_dir / "qec", str(case.vin), reference,
        ) if reference else None

    def _refresh_qec_download_dates(self) -> None:
        """Show only local QEC folders matching this case's FIN + exact ref."""
        history = {}
        for case in self.view_cases:
            archive = self._qec_archive_for_case(case)
            if archive:
                history[case.case_id] = (archive.date_label, archive.folder)
        self.case_model.set_qec_history(history)

    def _qec_target_for_case(self, case) -> QecTarget | None:
        try:
            valid = parse_qec_targets(str(case.vin or ""))
        except ValueError:
            return None
        reference = str(getattr(case, "qec_reference", "") or "").strip()
        if reference and (not reference.isdigit() or len(reference) > 14):
            return None  # A malformed reference is never silently widened to every case.
        return QecTarget(valid[0].fin, reference=reference)

    def _qec_targets(self, cases) -> list[QecTarget]:
        targets: list[QecTarget] = []
        seen: set[tuple[str, str]] = set()
        for case in cases:
            target = self._qec_target_for_case(case)
            if target is None:
                continue
            key = target.fin, target.reference
            if key not in seen:
                seen.add(key)
                targets.append(target)
        return targets

    def _all_qec_targets(self) -> list[QecTarget]:
        return self._qec_targets(self.view_cases)

    def _selected_qec_targets(self) -> list[QecTarget]:
        """Use exactly the same persistent case-checkbox state as QuickTest."""
        ids = self.case_model.checked_case_ids()
        return self._qec_targets(
            [case for case in self.view_cases if case.case_id in ids]
        )

    def _update_qec_selection(self) -> None:
        if self.qec_download is not None:
            self.qec_download.set_selection_count(
                len(self._all_qec_targets()),
                len(self._selected_qec_targets()),
            )

    def _update_fin_zip_selection(self) -> None:
        if self.fin_zip_export is not None:
            self.fin_zip_export.set_selection_count(
                len(self.case_model.all_fins()),
                len(self.case_model.selected_fins()),
            )

    def _case_table_qec_link_clicked(self, index) -> None:
        if not index.isValid() or index.column() != CaseTableModel.QEC_DATE_COLUMN:
            return
        source = self.case_proxy.mapToSource(index)
        folder = self.case_model.qec_folder_at(source.row())
        if folder is None:
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder))):
            QMessageBox.warning(
                self, "QEC-Fallordner",
                "Der lokale QEC-Fallordner konnte nicht geöffnet werden.",
            )

    def _refresh_shared_credentials_status(self) -> None:
        try:
            stored = load_saved_credentials()
        except RuntimeError:
            stored = None
        if stored:
            self.shared_credentials_status.setText(
                "✓ Mercedes-SSO für QuickTest und QEC sicher gespeichert · "
                "PING ID bei Bedarf am Smartphone bestätigen"
            )
            self.shared_credentials_status.setStyleSheet(
                "color: #268b52; font-weight: 600;"
            )
        else:
            self.shared_credentials_status.setText(
                "Noch keine gemeinsamen SSO-Zugangsdaten gespeichert. "
                "Alternativ Anmeldung manuell in Edge abschließen."
            )
            self.shared_credentials_status.setStyleSheet("")

    def _resolve_qec_credentials(self) -> LoginCredentials | None:
        """Read the same visible user ID/password and OS vault as QuickTest."""
        credentials = self._resolve_quicktest_credentials()
        self.quicktest_password.clear()
        self._refresh_shared_credentials_status()
        return credentials

    def _refresh_quicktest_download_dates(self) -> None:
        """Show persisted FIN manifests and PDF-only folders without a network request."""
        if self.quicktest_download_root is None:
            self.case_model.set_quicktest_history({})
            return
        history = {
            result.fin: (
                result.last_attempt_at if result.files else "",
                self.quicktest_download_root / result.fin,
                len(result.files),
            )
            for result in scan_local_quicktests(self.quicktest_download_root)
        }
        self.case_model.set_quicktest_history(history)

    def _update_quicktest_selection(self) -> None:
        selected = self.case_model.checked_case_ids()
        can_run = self.quicktest_download_root is not None and self._quicktest_worker is None
        self.quicktest_download_all_button.setEnabled(can_run and bool(self.case_model.all_fins()))
        self.quicktest_download_selected_button.setEnabled(can_run and bool(selected))
        self.quicktest_download_selected_button.setToolTip(
            f"{len(selected)} ausgewählte(r) Fall/Fälle · "
            f"{len(self.case_model.selected_fins())} eindeutige FIN(s)"
        )

    def _case_table_quicktest_link_clicked(self, index) -> None:
        if not index.isValid() or index.column() != CaseTableModel.QUICKTEST_DATE_COLUMN:
            return
        source = self.case_proxy.mapToSource(index)
        folder = self.case_model.folder_at(source.row())
        if folder is None:
            return  # "n.a." without an existing folder must not open anything.
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder))):
            QMessageBox.warning(
                self, "QuickTest-Verzeichnis",
                f"Der lokale QuickTest-Ordner konnte nicht geöffnet werden:\n{folder}",
            )

    def _forget_quicktest_login(self) -> None:
        try:
            clear_saved_credentials()
        except RuntimeError as exc:
            QMessageBox.warning(self, "Gespeicherte Zugangsdaten", str(exc))
            return
        self.quicktest_user_id.clear()
        self.quicktest_password.clear()
        self._refresh_shared_credentials_status()
        self.quicktest_download_status.setText(
            "SSO-Zugangsdaten wurden aus dem Betriebssystem-Tresor gelöscht."
        )

    def _resolve_quicktest_credentials(self) -> LoginCredentials | None:
        """Never persist plaintext credentials or request automatic PING-ID approval."""
        user_id = self.quicktest_user_id.text().strip()
        password = self.quicktest_password.text()
        if password and not user_id:
            raise ValueError("Für das Passwort muss eine Benutzer-ID eingetragen werden.")
        if user_id and password:
            if self.quicktest_remember_login.isChecked():
                try:
                    save_credentials(user_id, password)
                except RuntimeError as exc:
                    answer = QMessageBox.question(
                        self, "Sicheres Speichern nicht verfügbar",
                        str(exc) + "\n\nNur für diesen Abruf ohne Speicherung fortfahren?",
                    )
                    if answer != QMessageBox.StandardButton.Yes:
                        raise ValueError("Abruf abgebrochen.")
            self._refresh_shared_credentials_status()
            return LoginCredentials(user_id, password)
        if user_id:
            try:
                stored = load_saved_credentials()
            except RuntimeError:
                stored = None
            if stored is not None and stored.user_id == user_id:
                return stored
            raise ValueError(
                "Für diese Benutzer-ID ist kein Passwort im System-Tresor hinterlegt. "
                "Bitte einmal das Passwort eingeben oder beide Eingabefelder "
                "für die manuelle SSO-Anmeldung leer lassen."
            )
        return None

    def _start_quicktest_download(self, *, selected_only: bool) -> None:
        if self._quicktest_worker is not None or self.quicktest_download_root is None:
            return
        fins = self.case_model.selected_fins() if selected_only else self.case_model.all_fins()
        if not fins:
            return
        valid_fins: list[str] = []
        invalid_fins: list[str] = []
        for fin in fins:
            try:
                valid_fins.extend(parse_fins(fin))
            except ValueError:
                invalid_fins.append(fin)
        if invalid_fins:
            QMessageBox.warning(
                self, "FIN-Prüfung",
                f"{len(invalid_fins)} ungültige FIN(s) werden nicht abgerufen:\n"
                + ", ".join(invalid_fins[:5]),
            )
        if not valid_fins:
            return

        # No need to ask for credentials when all FINs were attempted recently.
        new_requests = self.quicktest_retry_24h.isChecked() or any(
            recently_attempted(self.quicktest_download_root, fin) is None
            for fin in valid_fins
        )
        try:
            login = self._resolve_quicktest_credentials() if new_requests else None
        except ValueError as exc:
            QMessageBox.warning(self, "SSO-Anmeldung", str(exc))
            return

        self._quicktest_files_for_import = []
        self._quicktest_worker = DownloadWorker(
            valid_fins,
            self.quicktest_download_root,
            self.quicktest_download_root.parent / "edge-diagnosis-viewer-profile",
            login=login,
            retry_recent=self.quicktest_retry_24h.isChecked(),
        )
        self.quicktest_password.clear()
        self._refresh_shared_credentials_status()
        self._quicktest_worker.progress.connect(self.quicktest_download_status.setText)
        self._quicktest_worker.completed.connect(self._quicktest_download_completed)
        self._quicktest_worker.failed.connect(self._quicktest_download_failed)
        self._quicktest_worker.finished.connect(self._quicktest_download_worker_finished)
        self.quicktest_cancel_button.setEnabled(True)
        self._update_quicktest_selection()
        self.quicktest_download_status.setText(
            f"{len(valid_fins)} FIN(s): Abruf über Microsoft Edge wird gestartet …"
        )
        self._quicktest_worker.start()

    def _cancel_quicktest_download(self) -> None:
        if self._quicktest_worker is not None:
            self._quicktest_worker.cancel.set()
            self.quicktest_cancel_button.setEnabled(False)
            self.quicktest_download_status.setText("Abruf wird angehalten …")

    def _quicktest_download_completed(self, results) -> None:
        self._refresh_quicktest_download_dates()
        files = [
            path for result in results if not result.status.startswith("Übersprungen")
            for path in result.files
        ]
        self._quicktest_files_for_import = list(dict.fromkeys(files))
        errors = sum(len(result.errors) for result in results)
        skipped = sum(result.status.startswith("Übersprungen") for result in results)
        without_data = sum(len(result.no_quicktest_sessions) for result in results)
        self.quicktest_download_status.setText(
            f"Abruf beendet: {len(results)} FIN(s), "
            f"{len(self._quicktest_files_for_import)} PDF(s), "
            f"{without_data} S3-Sitzung(en) ohne QuickTest übersprungen, "
            f"{skipped} FIN(s) innerhalb von 24 h übersprungen, {errors} Fehler. "
            "Vorhandene PDFs werden ins lokale Quellenarchiv übernommen."
        )

    def _quicktest_download_failed(self, message: str) -> None:
        self._refresh_quicktest_download_dates()
        self.quicktest_download_status.setText(f"QuickTest-Abruf fehlgeschlagen: {message}")

    def _quicktest_download_worker_finished(self) -> None:
        worker = self._quicktest_worker
        self._quicktest_worker = None
        if worker is not None:
            worker.deleteLater()
        self.quicktest_cancel_button.setEnabled(False)
        self._update_quicktest_selection()
        paths = self._quicktest_files_for_import
        self._quicktest_files_for_import = []
        if paths:
            # Import after the worker has finished; MainWindow may rebuild CasePage.
            self.quicktests_downloaded.emit(paths)

    def _filter_cases(self, text: str) -> None:
        """Keep the editable case in sync with the visible filtered selection."""
        self.case_proxy.setFilterFixedString(text)
        if self.case_proxy.rowCount() == 0:
            self.case_table.clearSelection()
            self.selector.setCurrentIndex(-1)
            self.add_event_button.setEnabled(False)
            self.correct_button.setEnabled(False)
            self.find_similar_button.setEnabled(False)
            self._clear_view()
            return

        self.case_table.selectRow(0)
        self._case_clicked(self.case_proxy.index(0, 0))

    def _case_clicked(self, index) -> None:
        if not index.isValid():
            return
        source_index = self.case_proxy.mapToSource(self.case_proxy.index(index.row(), 0))
        case_id = self.case_model.case_id_at(source_index.row())
        if case_id is None:
            return
        selector_index = self.selector.findData(case_id)
        if selector_index >= 0:
            self.selector.setCurrentIndex(selector_index)

    def _relay_tips_link(self, case_id: str) -> None:
        """Emit through a CasePage slot owned by Qt, not a shared emitter."""
        self.case_saved.emit(case_id)

    def _request_similar_cases(self) -> None:
        """Show the selected true QEC/NTF case in the local scatter tab."""
        case_id = self.selector.currentData()
        if isinstance(case_id, str) and self.cluster_workspace.focus_case(case_id):
            self.detail_tabs.setCurrentWidget(self.cluster_workspace)

    def _on_quicktest_fin_changed(self) -> None:
        """Follow an explicit FIN selection from the QuickTest browser."""
        if self._syncing_quicktest_fin or self.quicktest_browser is None:
            return
        fin = self.quicktest_browser.fin_selector.currentText()
        current_id = self.selector.currentData()
        if current_id and any(
            case.case_id == current_id and case.vin == fin for case in self.view_cases
        ):
            return
        matching = [case for case in self.view_cases if case.vin == fin]
        if matching:
            self.select_case(matching[0].case_id, show_analysis=False)

    def _clear_view(self) -> None:
        for value in (
            self.component_value, self.replacement_value, self.autoexport_date_value,
            self.effective_swap_value, self.date_match_value,
            self.date_comparison_note, self.root_cause_value,
            self.supplier_value, self.ssl_finding_value,
            self.confidence_value, self.recurrence_value,
            self.assessment_text, self.recurrence_text, self.evidence_balance,
        ):
            value.setText("—")
        self.evidence_model.set_rows([])
        self.timeline_model.set_entries([])
        self.time_plot.set_entries([])
        self.version_change_model.set_rows([])
        self.version_change_summary.setText("Keine FIN / kein Fall ausgewählt.")
        self.cpc3_panel.clear()
        self.autoexport_history_model.set_rows([])
        self.autoexport_history_note.setText("Keine FIN ausgewählt.")
        self.autoexport_history_count.setText("—")
        self.autoexport_history_more.setEnabled(False)

    def _open_autoexport_fin_history(self, fin: str) -> None:
        """Open the same vehicle's QEC case (when known) AND FIN history."""
        matching = sorted(
            (
                case.case_id for case in self.real_cases
                if case.vin == fin and case.component_profile_id == "coolant_pump"
                and getattr(case, "qec_reference", None)
            )
        )
        if matching:
            # The local QEC selector also offers other cases of this FIN.
            self.select_case(matching[0])
        self.detail_tabs.setCurrentWidget(self.analysis_tab)
        self.autoexport_fin_lookup.setText(fin)
        self._load_autoexport_history(reset=True)

    def _load_autoexport_history(self, *, reset: bool = False) -> None:
        """Read bounded FIN-wide raw observations, never infer an NTF case."""
        if reset:
            self._autoexport_history_offset = 0
        if self.source_knowledge is None:
            self.autoexport_history_note.setText(
                "Keine lokale AutoExport-Datenbank angeschlossen."
            )
            self.autoexport_history_model.set_rows([])
            self.autoexport_history_more.setEnabled(False)
            return
        fin = canonical_fin(self.autoexport_fin_lookup.text())
        if fin is None:
            self.autoexport_history_note.setText(
                "Bitte eine gültige 17-stellige FIN eingeben."
            )
            self.autoexport_history_model.set_rows([])
            self.autoexport_history_more.setEnabled(False)
            self.autoexport_history_count.setText("Keine FIN ausgewählt.")
            return
        counts = self.source_knowledge.fin_history_counts(fin)
        total = sum(counts.values())
        entries = self.source_knowledge.list_fin_history(
            fin, limit=200, offset=self._autoexport_history_offset
        )
        rows = []
        for item in entries:
            data = item["data"]
            kind = item["category"]
            if kind == "autoexport_dtc":
                title = (data.get("EcuNm") or "") + ":" + (
                    data.get("EcuFaultNm") or ""
                )
                detail = (data.get("EcuFaultTxt") or "") + (
                    " · Status: " + str(data["EcuFaultStateTxt"])
                    if data.get("EcuFaultStateTxt") else ""
                ) + (
                    " · Häufigkeit: " + str(data["FrequencyCounter"])
                    if data.get("FrequencyCounter") else ""
                )
            elif kind == "autoexport_tips":
                title = "TIPS " + (data.get("CaseId") or "ohne ID")
                detail = data.get(
                    "InitialWorkshopMessageCustomerComplaint"
                ) or data.get("InitialWorkshopMessageWorkshopFindings") or ""
            else:
                title = data.get("PartLetterCd") or "Werkstatt"
                detail = " · ".join(
                    str(s) for s in (
                        data.get("RepairTypeNmGerman"),
                        data.get("ComplDsc"),
                    ) if s
                )
            rows.append((
                item["label"] or "Uhrzeit unbekannt",
                {"autoexport_dtc": "DTC", "autoexport_tips": "TIPS",
                 "autoexport_repair": "Werkstatt"}.get(kind, kind),
                title,
                data.get("KmReadingNum") or "—",
                (detail[:220] + "…" if len(detail) > 220 else detail) or "—",
                item["source_location"] + " · " + item["source_sha256"][:10],
            ))
        if reset:
            self.autoexport_history_model.set_rows(rows)
        else:
            # Preserve the first rows and append the next source page.
            self.autoexport_history_model.set_rows([
                *self.autoexport_history_model.rows, *rows
            ])
        self._autoexport_history_offset += len(entries)
        self.autoexport_history_more.setEnabled(
            self._autoexport_history_offset < total
        )
        self.autoexport_history_note.setText(
            "FIN " + fin + ": "
            f"{counts.get('autoexport_dtc', 0)} historische DTC-Rohzeilen, "
            f"{counts.get('autoexport_repair', 0)} Werkstattzeilen, "
            f"{counts.get('autoexport_tips', 0)} TIPS-Vorgänge. "
            "Quelleinträge bleiben vollständig und einzeln erhalten; "
            "Datum/Uhrzeit im Export werden nicht als lokale Uhrzeit umgerechnet. "
            "Gleicher DTC-Code in mehreren Zeilen bedeutet nicht automatisch "
            "eine neue Ursache oder einen neuen NTF-Fall."
        )
        self.autoexport_history_count.setText(
            f"{self._autoexport_history_offset} / {total} Rohzeilen geladen "
            "(Details aller Quellfelder unter »Quellenwissen«)."
        )

    def _display_version_changes(self, case) -> None:
        changes = detect_ecu_version_changes(case.ecu_states)
        count_hw = sum(item.kind == "hw" for item in changes)
        count_sw = sum(item.kind == "sw" for item in changes)
        if changes:
            self.version_change_summary.setText(
                f"{count_hw} HW- und {count_sw} SW-Standabweichung(en) "
                f"in {len(case.ecu_states)} ECU-Beobachtungen erkannt. "
                "Der geänderte Stand wurde beim späteren QuickTest festgestellt; "
                "der genaue Änderungszeitpunkt ist unbekannt."
            )
        elif not case.ecu_states:
            self.version_change_summary.setText(
                "Noch keine HW-/SW-Stände aus QuickTests vorhanden."
            )
        else:
            self.version_change_summary.setText(
                "Keine belegte HW-/SW-Standabweichung zwischen "
                "vergleichbaren QuickTests. Fehlende oder widersprüchliche "
                "Versionsangaben werden nicht als Änderung gewertet."
            )
        self.version_change_model.set_rows([
            (
                change.ecu,
                "Hardware" if change.kind == "hw" else "Software",
                change.previous_version,
                change.new_version,
                change.previous.occurred_at.strftime("%d.%m.%Y %H:%M"),
                change.current.occurred_at.strftime("%d.%m.%Y %H:%M"),
                change.previous.mileage_km,
                change.current.mileage_km,
                change.current.source_ref,
            )
            for change in changes
        ])

    def _refresh(self) -> None:
        case_id = self.selector.currentData()
        is_preview = isinstance(case_id, str) and case_id.startswith(FIN_ONLY_PREFIX)
        case = (
            self.fin_only_previews.get(case_id)
            if is_preview
            else self.repository.get_case(case_id)
            if case_id
            else None
        )
        editable = self.manual_service is not None and not is_preview and case is not None
        self.add_event_button.setEnabled(editable)
        self.correct_button.setEnabled(editable)
        self.history_button.setEnabled(editable)
        self.export_button.setEnabled(case is not None and not is_preview)
        self.find_similar_button.setEnabled(
            case is not None and not is_preview
        )
        self.confirm_swap_button.setEnabled(False)
        if case is None:
            self._clear_view()
            return

        # Keep selected QEC/NTF case and FIN-specific QuickTests aligned.
        if self.repository.get_case(case.case_id) is not None:
            self.cluster_workspace.focus_case(case.case_id)
        else:
            self.cluster_workspace.clear_focus()
        # Shared dropdown selection must also highlight the analysis table.
        for source_row in range(self.case_model.rowCount()):
            if self.case_model.case_id_at(source_row) != case.case_id:
                continue
            proxy_index = self.case_proxy.mapFromSource(
                self.case_model.index(source_row, 0)
            )
            if not proxy_index.isValid() and self.case_search.text():
                self.case_search.blockSignals(True)
                self.case_search.clear()
                self.case_search.blockSignals(False)
                self.case_proxy.setFilterFixedString("")
                proxy_index = self.case_proxy.mapFromSource(
                    self.case_model.index(source_row, 0)
                )
            if proxy_index.isValid():
                selection = self.case_table.selectionModel()
                selection.blockSignals(True)
                self.case_table.selectRow(proxy_index.row())
                selection.blockSignals(False)
            break
        if self.quicktest_browser is not None:
            self._syncing_quicktest_fin = True
            try:
                self.quicktest_browser.select_fin(case.vin)
            finally:
                self._syncing_quicktest_fin = False

        self._display_version_changes(case)
        self.cpc3_panel.show_case(case)
        # Case change refreshes the corresponding VIN-wide history; an
        # independent direct FIN lookup remains possible without a case.
        self.autoexport_fin_lookup.setText(case.vin)
        self._load_autoexport_history(reset=True)

        if is_preview:
            entries = build_timeline(case)
            self.component_value.setText("Noch keinem Schadteilfall zugeordnet")
            self.replacement_value.setText("Nicht dokumentiert")
            self.autoexport_date_value.setText("Noch kein Fallbezug")
            self.effective_swap_value.setText("Fehlt")
            self.date_match_value.setText("Nicht beurteilbar")
            self.date_comparison_note.setText(
                "AutoExport-Reparaturen werden erst nach eindeutiger FIN-/Fall- "
                "und Teilenummernzuordnung als mögliche Tauschkandidaten gezeigt."
            )
            self.root_cause_value.setText("Nicht bestimmbar")
            self.supplier_value.setText("Nicht bestimmbar")
            self.ssl_finding_value.setText("Kein QEC-Schadteilfall")
            self.confidence_value.setText("—")
            self.recurrence_value.setText("Nicht beurteilbar")
            self.assessment_text.setText(
                "FIN-Diagnose aus QuickTests: Es liegt noch kein verknüpfter "
                "NTF-/QEC-Fall vor. Diese Fahrzeugdaten sind sichtbar und "
                "dauerhaft gespeichert, aber keine Reparatur- oder "
                "Lieferantenursache wird daraus abgeleitet."
            )
            self.recurrence_text.setText(
                f"{len(case.diagnostic_sessions)} QuickTest(s), "
                f"{len(unique_diagnostic_observations(case.diagnostics))} DTC-Beobachtungen, "
                f"{len(case.ecu_states)} Steuergeräte-Stände. "
                "Für eine Vorher-/Nachher-Bewertung fehlt der zugehörige Tausch."
            )
            self.evidence_model.set_rows([])
            self.evidence_balance.setText(
                "Kein NTF-Fall vorhanden – keine Root-Cause-Evidenz bewertet. "
                "Details unter »QuickTests nach FIN«."
            )
            self.time_plot.set_entries(entries)
            self.timeline_model.set_entries(entries)
            return

        replacement = case.investigated_replacement()
        recurrence = analyze_recurrence(case)
        assessment = case.assessment
        generated = generate_case_evidence(case, self.references)
        date_comparison = compare_replacement_dates(
            case, self.source_knowledge
        )
        timeline_entries = build_timeline(
            case, date_comparison=date_comparison
        )

        self.component_value.setText(case.component_type)
        self.replacement_value.setText(
            date_comparison.qec_anchor.occurred_at.strftime("%d.%m.%Y")
            if date_comparison.qec_anchor else "Fehlt"
        )
        self.effective_swap_value.setText(
            (
                replacement.occurred_at.strftime("%d.%m.%Y")
                + (
                    " (manuell bestätigt)"
                    if getattr(replacement, "confirmed_from_autoexport", False)
                    else " (QEC / vorläufig)"
                    if "Schadteile QEC" in (replacement.source_ref or "")
                    else " (dokumentiert)"
                )
            )
            if replacement else "Fehlt"
        )
        self.confirm_swap_button.setEnabled(
            editable
            and date_comparison.preferred_candidate is not None
            and not getattr(replacement, "confirmed_from_autoexport", False)
        )
        if date_comparison.preferred_candidate is not None:
            auto_repair = date_comparison.preferred_candidate.repair
            self.autoexport_date_value.setText(
                auto_repair.occurred_at.strftime("%d.%m.%Y")
                + " (Kandidat)"
            )
        elif date_comparison.candidates:
            dates = sorted({
                candidate.repair.occurred_at.strftime("%d.%m.%Y")
                for candidate in date_comparison.candidates
            })
            self.autoexport_date_value.setText(
                f"{len(date_comparison.candidates)} Kandidaten: "
                + ", ".join(dates[:4])
                + (" …" if len(dates) > 4 else "")
            )
        else:
            self.autoexport_date_value.setText("Kein passender Eintrag")
        self.date_match_value.setText(date_comparison.status)
        self.date_comparison_note.setText(
            "Quellenabgleich: " + date_comparison.note
        )
        self.root_cause_value.setText(str(assessment.root_cause) if assessment else "Nicht bewertet")
        self.supplier_value.setText(
            str(assessment.supplier_involvement) if assessment else "Unbekannt"
        )
        self.ssl_finding_value.setText(qec_ssl_finding_label(case))
        self.confidence_value.setText(str(assessment.confidence) if assessment else "—")

        if not recurrence.assessable:
            recurrence_label = "Unzureichende Daten"
        else:
            recurrence_label = "Ja" if recurrence.has_recurrence else "Nein"
        self.recurrence_value.setText(recurrence_label)

        self.assessment_text.setText(
            assessment.summary if assessment and assessment.summary else "Keine Bewertung verfügbar."
        )

        if recurrence.replacement is None:
            recurrence_summary = "Kein untersuchter Bauteiltausch verfügbar."
        elif not recurrence.assessable:
            missing = []
            if not recurrence.has_pre_test:
                missing.append("Kurztest vor dem Tausch")
            if not recurrence.has_post_test:
                missing.append("Kurztest nach dem Tausch")
            recurrence_summary = (
                "Wiederauftreten kann nicht zuverlässig bewertet werden; es fehlt: " + " und ".join(missing) + "."
            )
        else:
            elapsed = (
                f"{recurrence.first_recurrence_after.days} d"
                if recurrence.first_recurrence_after is not None
                else "—"
            )
            distance = (
                f"{recurrence.distance_to_recurrence_km} km"
                if recurrence.distance_to_recurrence_km is not None
                else "—"
            )
            recurrence_summary = (
                f"Gleich: {format_faults(recurrence.same_faults)}  |  "
                f"Verschwunden: {format_faults(recurrence.disappeared_faults)}  |  "
                f"Neu: {format_faults(recurrence.new_faults)}  |  "
                f"Erstes Wiederauftreten: {elapsed} / {distance}"
            )
        self.recurrence_text.setText(recurrence_summary)

        evidence_rows = [
            (
                item.code,
                str(item.category_hint) if item.category_hint else None,
                str(item.direction),
                f"{item.weight:.2f}",
                item.description,
            )
            for item in generated.evidence
        ]
        self.evidence_model.set_rows(evidence_rows)
        balances = generated.balance_by_category()
        if balances:
            balance_text = ", ".join(
                f"{category}: {score:+.2f}"
                for category, score in sorted(
                    balances.items(), key=lambda item: abs(item[1]), reverse=True
                )
            )
            self.evidence_balance.setText(
                "Vorläufige Evidenzbilanz (kein finales Root-Cause-Urteil): " + balance_text
            )
        else:
            self.evidence_balance.setText(
                "Noch keine bewertete generische Evidenz; weitere Quelldaten oder bauteilspezifische Regeln sind erforderlich."
            )
        self.time_plot.set_entries(timeline_entries)
        self.timeline_model.set_entries(timeline_entries)


    def show_quicktests(self, fin: str | None = None) -> None:
        """Open the FIN-scoped report browser, with or without a QEC case."""
        if self.quicktest_browser is None:
            return
        if fin is None:
            selected = next(
                (case for case in self.view_cases
                 if case.case_id == self.selector.currentData()),
                None,
            )
            fin = selected.vin if selected else None
        if fin:
            self.quicktest_browser.select_fin(fin)
        self.detail_tabs.setCurrentWidget(self.quicktest_browser)

    def select_case(self, case_id: str, *, show_analysis: bool = True) -> None:
        """Select a case across all three linked tabs, optionally switch tab."""
        for row in range(self.case_model.rowCount()):
            if self.case_model.case_id_at(row) == case_id:
                source = self.case_model.index(row, 0)
                proxy = self.case_proxy.mapFromSource(source)
                if not proxy.isValid():
                    # A previous FIN text search may hide the case selected
                    # from the cluster-neighbour comparison.
                    self.case_search.clear()
                    proxy = self.case_proxy.mapFromSource(source)
                if proxy.isValid():
                    if show_analysis:
                        self.detail_tabs.setCurrentWidget(self.analysis_tab)
                    self.case_table.selectRow(proxy.row())
                    self._case_clicked(proxy)
                return

    def _selected_case(self):
        case_id = self.selector.currentData()
        return self.repository.get_case(case_id) if case_id else None

    def _persistent_case(self):
        case = self._selected_case()
        if case is None or self.manual_service is None:
            return None
        if self.manual_service.store.get_case(case.case_id) is None:
            QMessageBox.information(
                self,
                "Demo-Daten",
                "Demo-Fälle werden nicht als echte Daten gespeichert. "
                "Bitte zunächst über „+ Neuer Fall“ einen echten FIN/Fall anlegen.",
            )
            return None
        return case

    def _create_case(self) -> None:
        if self.manual_service is None:
            return
        dialog = NewCaseDialog(self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        try:
            case = self.manual_service.create_case(dialog.build_case())
        except Exception as exc:
            QMessageBox.warning(self, "Fall konnte nicht angelegt werden", str(exc))
            return
        self.case_saved.emit(case.case_id)

    def _add_event(self) -> None:
        if self.manual_service is None:
            return
        case = self._persistent_case()
        if case is None:
            return
        dialog = ManualEventDialog(case, self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        try:
            self.manual_service.add_event(
                case.case_id,
                dialog.selected_kind,
                dialog.build_event(),
                set_replacement_anchor=dialog.set_replacement_anchor,
            )
        except (ValueError, ManualEntryError, OSError) as exc:
            QMessageBox.warning(self, "Ereignis konnte nicht gespeichert werden", str(exc))
            return
        self.case_saved.emit(case.case_id)

    def _confirm_autoexport_swap(self) -> None:
        """Audited human confirmation; never automatically reassign the anchor."""
        case = self._persistent_case()
        if case is None or self.manual_service is None:
            return
        comparison = compare_replacement_dates(case, self.source_knowledge)
        candidate = comparison.preferred_candidate
        qec = comparison.qec_anchor
        if candidate is None or qec is None:
            QMessageBox.information(
                self, "Kein eindeutiger Kandidat",
                "Bitte zunächst einen eindeutig passenden AutoExport-"
                "Reparatureintrag mit FIN und Teilenummer zuordnen.",
            )
            return
        current_anchor = case.investigated_replacement()
        if getattr(current_anchor, "confirmed_from_autoexport", False):
            QMessageBox.information(
                self, "Tauschanker bereits bestätigt",
                "Der untersuchte Tauschanker wurde bereits manuell bestätigt.",
            )
            return
        repair = candidate.repair
        confirm = QMessageBox.question(
            self,
            "Tatsächlichen Pumpentausch bestätigen?",
            "AutoExport enthält zunächst nur ein Reparaturdatum.\n\n"
            f"QEC: {qec.occurred_at:%d.%m.%Y} · {qec.mileage_km} km\n"
            f"AutoExport: {repair.occurred_at:%d.%m.%Y} · "
            f"{repair.mileage_km} km\n"
            f"Abgleich: {candidate.association}\n\n"
            "Hast du anhand der Werkstattunterlagen geprüft, dass die "
            "Pumpe tatsächlich an diesem AutoExport-Datum ausgetauscht wurde?\n\n"
            "Nur bei Ja wird ein neuer manueller, auditierter Tauschanker "
            "für die Vorher-/Nachher-Analyse gesetzt. Die beiden "
            "ursprünglichen Quellen bleiben unverändert erhalten.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        verified = PartReplacement(
            vin=case.vin,
            occurred_at=repair.occurred_at,
            time_precision=getattr(repair, "time_precision", "date"),
            mileage_km=repair.mileage_km,
            component_type=qec.component_type,
            old_part_number=qec.old_part_number,
            new_part_number=qec.new_part_number,
            supplier=qec.supplier,
            confirmed_from_autoexport=True,
            repair_source_ref=repair.source_ref,
            initial_qec_event_id=qec.event_id,
            confirmation_basis="Werkstattunterlagen durch Nutzer verifiziert",
        )
        try:
            self.manual_service.add_event(
                case.case_id, "replacement", verified,
                set_replacement_anchor=True,
            )
        except (ValueError, ManualEntryError, OSError) as exc:
            QMessageBox.warning(self, "Bestätigung fehlgeschlagen", str(exc))
            return
        self.case_saved.emit(case.case_id)

    def _correct_event(self) -> None:
        if self.manual_service is None:
            return
        case = self._persistent_case()
        if case is None:
            return
        index = self.timeline.currentIndex()
        entry = self.timeline_model.entry_at(index.row()) if index.isValid() else None
        if entry is None:
            QMessageBox.information(
                self, "Ereignis wählen",
                "Bitte zuerst eine Zeile in der Ereignistabelle markieren.",
            )
            return

        if entry.kind in {"ecu_hw_change", "ecu_sw_change"}:
            QMessageBox.information(
                self,
                "Automatisch erkannte Standabweichung",
                "Diese Zeile ist ein abgeleiteter Vergleich aus zwei "
                "unveränderten QuickTest-Beobachtungen. "
                "Bitte gegebenenfalls die Originalquelle prüfen. "
                "Ein tatsächliches Update kann separat als "
                "HW-/SW-Ereignis dokumentiert werden.",
            )
            return

        if entry.kind == "replacement_candidate":
            QMessageBox.information(
                self,
                "AutoExport-Quelldatum",
                "Dies ist ein automatisch erkannter Reparaturkandidat aus "
                "AutoExport und kein bestätigtes Tauschevent. "
                "Für eine Korrektur bitte den tatsächlichen Tausch als "
                "separates Ereignis mit dokumentierter Quelle erfassen.",
            )
            return

        dialog = ManualEventDialog(case, self, kind=entry.kind, existing=entry.event)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        try:
            self.manual_service.correct_event(
                case.case_id, entry.kind, entry.event.event_id, dialog.build_event()
            )
        except (ValueError, ManualEntryError, OSError) as exc:
            QMessageBox.warning(self, "Korrektur nicht gespeichert", str(exc))
            return
        self.case_saved.emit(case.case_id)

    def _show_history(self) -> None:
        case = self._persistent_case()
        if case is None or self.manual_service is None:
            return
        changes = self.manual_service.store.load_manual_changes(case.case_id)
        dialog = ManualHistoryDialog(case.case_id, changes, self)
        dialog.exec()

    def _export_report(self) -> None:
        case_id = self.selector.currentData()
        case = self.repository.get_case(case_id) if case_id else None
        if case is None:
            return
        suggested = f"{case.case_id}.md"
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "NTF-Fallbericht exportieren",
            suggested,
            "Markdown (*.md)",
        )
        if not filename:
            return
        path = filename if filename.lower().endswith(".md") else filename + ".md"
        save_case_report(Path(path), case, self.references)
