"""Main PySide6 desktop window with live refresh after manual case revisions."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QMainWindow, QMessageBox, QStackedWidget, QWidget

from ntf_insight.app.bootstrap import load_application_data
from ntf_insight.app.pages.case_page import CasePage
from ntf_insight.app.pages.dashboard_page import DashboardPage
from ntf_insight.app.pages.workflow_page import WorkflowPage
from ntf_insight.app.pages.data_quality_page import DataQualityPage
from ntf_insight.app.pages.dtc_page import DTCExplorerPage
from ntf_insight.app.pages.prediction_page import PredictionPage
from ntf_insight.app.pages.sources_page import SourcesPage
from ntf_insight.app.pages.source_knowledge_page import SourceKnowledgePage
from ntf_insight.app.pages.supplier_page import SupplierPage
from ntf_insight.app.widgets.navigation import NavigationPanel
from ntf_insight.ingestion.manual_entry import ManualCaseService
from ntf_insight.storage.duckdb_store import DuckDBStore
from ntf_insight.storage.dtc_review_store import DtcReviewStore
from ntf_insight.storage.quicktest_store import QuickTestStore
from ntf_insight.storage.source_knowledge_store import SourceKnowledgeStore
from ntf_insight.storage.qec_workflow_store import QecWorkflowStore
from ntf_insight.storage.workflow_progress import WorkflowProgressStore


class MainWindow(QMainWindow):
    """Top-level NTF Insight desktop window."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("NTF Insight")
        self.resize(1320, 820)
        self.setMinimumSize(1080, 700)

        self.application_data = load_application_data()
        self.repository = self.application_data.cases
        self.reference_repository = self.application_data.references
        self.manual_service = ManualCaseService(
            DuckDBStore(self.application_data.paths.database_path)
        )
        self._case_quicktest_import_pending = False

        root = QWidget(objectName="AppRoot")
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.navigation = NavigationPanel()
        self.stack = QStackedWidget()
        self.pages = self._create_pages()
        for page in self.pages.values():
            self.stack.addWidget(page)

        layout.addWidget(self.navigation)
        layout.addWidget(self.stack, 1)
        self.setCentralWidget(root)

        self.navigation.page_selected.connect(self.show_page)
        self.navigation.select_page("workflow")

    def _create_pages(self) -> dict[str, QWidget]:
        # Fachmarkierungen bleiben im selben lokalen DuckDB wie die Quellen,
        # aber in einer separaten, importunabhängigen Tabelle gespeichert.
        review_store = DtcReviewStore(self.manual_service.store)
        knowledge = SourceKnowledgeStore(self.manual_service.store)
        pages = {
            "dashboard": DashboardPage(
                self.repository,
                self.application_data.mode,
                QuickTestStore(self.manual_service.store),
            ),
            "sources": SourcesPage(
                self.repository,
                self.reference_repository,
                self.application_data.mode,
                str(self.application_data.paths.data_dir),
                str(self.application_data.paths.raw_dir),
                str(self.application_data.paths.database_path),
            ),
            "knowledge": SourceKnowledgePage(knowledge),
            "cases": CasePage(
                self.repository, self.reference_repository, self.manual_service,
                review_store=review_store,
                download_root=self.application_data.paths.data_dir / "quicktests",
            ),
            "dtcs": DTCExplorerPage(
                self.repository, self.reference_repository,
                source_knowledge=knowledge, review_store=review_store,
            ),
            "suppliers": SupplierPage(self.repository),
            "prediction": PredictionPage(self.repository, str(self.application_data.paths.database_path), self.application_data.mode),
            "quality": DataQualityPage(self.repository, self.reference_repository),
        }
        pages["workflow"] = WorkflowPage(
            WorkflowProgressStore(self.manual_service.store),
            qec_store=QecWorkflowStore(self.manual_service.store),
            repository=self.repository,
            quicktests=QuickTestStore(self.manual_service.store),
            mode=self.application_data.mode,
        )
        pages["workflow"].navigate.connect(self._workflow_navigate)
        pages["workflow"].action_requested.connect(self._workflow_action)
        pages["cases"].case_saved.connect(self._reload_after_manual_change)
        pages["cases"].quicktests_downloaded.connect(self._import_downloaded_case_quicktests)
        pages["cases"].qec_reports_downloaded.connect(self._import_downloaded_case_quicktests)
        pages["sources"].sources_updated.connect(self._reload_after_source_import)
        transfer = pages["sources"].portable_backup_panel
        if transfer is not None:
            transfer.set_guard(self._portable_transfer_ready)
            transfer.transfer_busy.connect(self._portable_transfer_busy)
            transfer.restored.connect(self._portable_restored)
        analysis_export = pages["sources"].ki_analyse_panel
        if analysis_export is not None:
            analysis_export.set_guard(self._portable_transfer_ready)
            analysis_export.transfer_busy.connect(self._portable_transfer_busy)
        return pages

    def _import_downloaded_case_quicktests(self, paths: list) -> None:
        """Archive QuickTest/QEC files from the case table with source provenance."""
        if not paths:
            return
        source_page = self.pages["sources"]
        if (
            source_page._worker is not None
            or (
                source_page.ki_analyse_panel is not None
                and (
                    source_page.ki_analyse_panel.worker is not None
                    or source_page.ki_analyse_panel.import_worker is not None
                )
            )
            or (
                source_page.portable_backup_panel is not None
                and source_page.portable_backup_panel.worker is not None
            )
        ):
            # PDFs remain safely on disk and can be imported through Datenquellen.
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(
                self, "Quellenimport ist beschäftigt",
                "Die QEC-/QuickTest-Dateien wurden gespeichert, aber ein anderer Quellenimport "
                "läuft bereits. Bitte die Dateien anschließend unter Datenquellen importieren.",
            )
            return
        self._case_quicktest_import_pending = True
        source_page._archive_paths(paths)

    def _portable_transfer_ready(self) -> bool:
        """Never replace data while a source import or background download runs."""
        source = self.pages["sources"]
        cases = self.pages["cases"]
        qec = cases.qec_download
        tips = getattr(cases, 'tips_download', None)
        exporter = cases.fin_zip_export
        return (
            source._worker is None
            and source._diagnostics_worker is None
            and (
                source.ki_analyse_panel is None
                or (
                    source.ki_analyse_panel.worker is None
                    and source.ki_analyse_panel.import_worker is None
                )
            )
            and not self._case_quicktest_import_pending
            and cases._quicktest_worker is None
            and (qec is None or qec.worker is None)
            and (tips is None or tips.worker is None)
            and (exporter is None or exporter.worker is None)
        )

    def _portable_transfer_busy(self, busy: bool) -> None:
        """Avoid any GUI-driven writes during DuckDB snapshot/restore."""
        self.stack.setEnabled(not busy)
        self.navigation.setEnabled(not busy)

    def _portable_restored(self, result: object) -> None:
        """Build fresh repositories directly from the transferred DuckDB."""
        self._case_quicktest_import_pending = False
        self._reload_data()
        self.navigation.select_page("cases")
        QMessageBox.information(
            self, "Gesamtdatenstand wiederhergestellt",
            f"{result.case_count} Fall/Fälle und {result.quicktest_count} "
            "bereits geparste QuickTests sind sofort verfügbar. "
            "Originale, manuelle Änderungen und weitere Analysewerte wurden "
            "aus demselben Paket übernommen. Kein erneutes Parsen nötig.",
        )

    def _reload_after_source_import(self, summary: str, quicktests_saved: int = 0) -> None:
        """Refresh all views while preserving case analysis after case-led downloads."""
        from_case_download = self._case_quicktest_import_pending
        current_case = (
            self.pages["cases"].selector.currentData() if from_case_download else None
        )
        self._case_quicktest_import_pending = False
        self._reload_data()
        if from_case_download:
            if current_case:
                self.pages["cases"].select_case(current_case)
            self.navigation.select_page("cases")
            return
        self.pages["sources"].import_status.setText(summary)
        if quicktests_saved:
            self.navigation.select_page("cases")
            self.pages["cases"].show_quicktests()
        else:
            self.navigation.select_page("sources")

    def _reload_after_manual_change(self, case_id: str) -> None:
        """Reload persisted data and rebuild derived views after one successful edit."""
        self._reload_data()
        self.pages["cases"].select_case(case_id)
        self.navigation.select_page("cases")

    def _reload_data(self) -> None:
        """Rebuild repositories and projections from durable local storage."""
        self.application_data = load_application_data(self.application_data.paths)
        self.repository = self.application_data.cases
        self.reference_repository = self.application_data.references

        old_pages = list(self.pages.values())
        for old in old_pages:
            self.stack.removeWidget(old)
            old.deleteLater()

        self.pages = self._create_pages()
        for page in self.pages.values():
            self.stack.addWidget(page)


    def _workflow_navigate(self, page: str, tab: str) -> None:
        """Bestehende Analyse- und Quellenseiten nutzen, keine Parallel-UI."""
        if page == "cases" and tab == "cluster":
            self.pages["cases"].detail_tabs.setCurrentWidget(
                self.pages["cases"].cluster_workspace
            )
        elif page == "cases" and tab == "quicktests":
            case = self.pages["cases"]
            if case.quicktest_browser is not None:
                case.detail_tabs.setCurrentWidget(case.quicktest_browser)
        self.navigation.select_page(page)

    def _workflow_action(self, action: str) -> None:
        source = self.pages["sources"]
        if action == "self_import":
            self.navigation.select_page("sources")
            source.archive_button.click()
        elif action == "qec":
            self.navigation.select_page("sources")
            if source.qec_workflow is not None:
                source.qec_workflow.refresh()
        elif action in {"pc_export", "pc_import"}:
            self.navigation.select_page("sources")
            panel = source.portable_backup_panel
            if panel is not None:
                (panel.export_button if action == "pc_export" else panel.restore_button).click()
        elif action in {"ai_export", "ai_import"}:
            self.navigation.select_page("sources")
            panel = source.ki_analyse_panel
            if panel is not None:
                (panel.export_button if action == "ai_export" else panel.import_button).click()

    def show_page(self, key: str) -> None:
        page = self.pages.get(key)
        if page is None:
            return
        if key == "workflow":
            page.refresh()
        if key == "cases":
            page.cluster_workspace.refresh_review_priorities()
            page._refresh_quicktest_download_dates()
            page._refresh_qec_download_dates()
            page._refresh_local_tips_status()
            page._refresh_shared_credentials_status()
        self.stack.setCurrentWidget(page)
        self.stack.setFocus(Qt.FocusReason.OtherFocusReason)
