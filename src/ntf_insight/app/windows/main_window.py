"""Main PySide6 desktop window with live refresh after manual case revisions."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from PySide6.QtCore import Qt, QEventLoop, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QDialog, QFileDialog, QGraphicsBlurEffect, QHBoxLayout,
    QInputDialog, QMainWindow, QMessageBox, QProgressDialog, QPushButton,
    QStackedWidget, QVBoxLayout, QWidget,
)

from ntf_insight.acquisition.qec_tool import QEC_START
from ntf_insight.acquisition.diagnosis_viewer import parse_fins
from ntf_insight.storage.cluster_evidence_store import CATEGORY_LABELS
from ntf_insight.app.workers.cluster_context_workers import (
    ClusterContextExportWorker, ClusterEvidenceImportWorker,
)
from ntf_insight.app.workers.project_transfer_worker import ProjectTransferWorker
from ntf_insight.app.workers.project_delete_worker import ProjectDeleteWorker
from ntf_insight.ingestion.project_portable import PROJECT_EXTENSION
from ntf_insight.ingestion.artifacts import SourceType
from ntf_insight.app.bootstrap import load_application_data
from ntf_insight.app.pages.case_page import CasePage
from ntf_insight.app.pages.dashboard_page import DashboardPage
from ntf_insight.app.pages.workflow_page import WorkflowPage
from ntf_insight.app.pages.project_settings_page import ProjectSettingsPage
from ntf_insight.app.pages.data_quality_page import DataQualityPage
from ntf_insight.app.pages.dtc_page import DTCExplorerPage
from ntf_insight.app.pages.prediction_page import PredictionPage
from ntf_insight.app.pages.sources_page import SourcesPage
from ntf_insight.app.pages.source_knowledge_page import SourceKnowledgePage
from ntf_insight.app.pages.supplier_page import SupplierPage
from ntf_insight.app.widgets.navigation import NavigationPanel
from ntf_insight.app.widgets.loading_overlay import LoadingOverlay
from ntf_insight.ingestion.manual_entry import ManualCaseService
from ntf_insight.storage.duckdb_store import DuckDBStore
from ntf_insight.storage.dtc_review_store import DtcReviewStore
from ntf_insight.storage.quicktest_store import QuickTestStore
from ntf_insight.storage.source_knowledge_store import SourceKnowledgeStore
from ntf_insight.storage.qec_workflow_store import QecWorkflowStore
from ntf_insight.storage.workflow_progress import WorkflowProgressStore
from ntf_insight.storage.workflow_projects import NTFProject, WorkflowProjectStore


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
        self._workflow_source_import_pending = False
        self._workflow_qec_download_pending = False
        self._workflow_last_qec_files: list[Path] = []
        self._workflow_quicktest_download_pending = False
        self._context_scraper_failed: set[str] = set()
        self._context_worker = None
        self._project_transfer_worker = None
        self._project_transfer_dialog = None
        self._project_transfer_failure: str | None = None
        self._diagnostics_dialog: QProgressDialog | None = None
        self._diagnostics_path: Path | None = None
        self._diagnostics_error_text: str | None = None
        self._diagnostics_started_at = 0.0
        self._diagnostics_phase = ""
        self._project_dialog: QDialog | None = None
        self._project_delete_worker = None
        self._project_delete_result = None
        self._project_import_result = None
        self._pending_first_context: tuple[str, str] | None = None
        self._pending_ai_round: int | None = None
        self._pending_cluster_context: tuple[str, str, str] | None = None

        root = QWidget(objectName="AppRoot")
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.navigation = NavigationPanel()
        self.stack = QStackedWidget()
        self.pages = self._create_pages()
        for name, page in self.pages.items():
            if name != "project_settings":
                self.stack.addWidget(page)

        layout.addWidget(self.navigation)
        layout.addWidget(self.stack, 1)
        self.setCentralWidget(root)
        self._loading_overlay = LoadingOverlay(root)
        self._modal_shade = QWidget(root)
        self._modal_shade.setObjectName("ProjectModalShade")
        self._modal_shade.setStyleSheet(
            "QWidget#ProjectModalShade { background-color: rgba(10,21,37,105); }"
        )
        self._modal_shade.hide()

        self.navigation.page_selected.connect(self.show_page)
        self.navigation.select_page("workflow")

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._project_delete_worker is not None:
            event.ignore()
            QMessageBox.warning(
                self, "Projektlöschung läuft",
                "Die Projektlöschung muss zuerst abgeschlossen werden. "
                "Das App-Fenster bleibt geöffnet, bis Dateien und Datenbank "
                "konsistent aktualisiert sind.",
            )
            return
        dashboard_worker = getattr(self.pages.get("dashboard"), "_worker", None)
        if dashboard_worker is not None and dashboard_worker.isRunning():
            dashboard_worker.wait()  # DuckDB-Verbindungen vollständig schließen.
        super().closeEvent(event)

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
        pages["project_settings"] = ProjectSettingsPage(
            WorkflowProjectStore(self.manual_service.store)
        )
        pages["dashboard"].project_selected.connect(self._project_selected)
        pages["dashboard"].loading_finished.connect(self._finish_loading)
        pages["project_settings"].project_selected.connect(self._project_selected)
        pages["project_settings"].project_delete_requested.connect(
            self._project_delete_requested
        )
        pages["workflow"].navigate.connect(self._workflow_navigate)
        pages["workflow"].step_loading.connect(self._workflow_step_busy)
        pages["workflow"].action_requested.connect(self._workflow_action)
        pages["workflow"].project_selected.connect(self._project_selected)
        pages["workflow"].cohort_updated.connect(self._sync_local_cluster)
        pages["workflow"].mount_local_cluster(pages["cases"].cluster_workspace)
        sources = pages["sources"]
        sources.diagnostics_started.connect(self._diagnostics_started)
        sources.diagnostics_progress.connect(self._diagnostics_progress)
        sources.diagnostics_saved.connect(self._diagnostics_saved)
        sources.diagnostics_error.connect(self._diagnostics_failed)
        sources.diagnostics_ended.connect(self._diagnostics_ended)
        if pages["sources"].qec_workflow is not None:
            pages["sources"].qec_workflow.set_project_scope(
                pages["workflow"]._context_part
            )
        pages["cases"].cluster_requested.connect(self._open_cluster_from_case)
        if pages["cases"].qec_download is not None:
            pages["cases"].qec_download.downloads_completed.connect(
                lambda _results: pages["workflow"].refresh_data()
            )
        if pages["sources"].ki_analyse_panel is not None:
            pages["sources"].ki_analyse_panel.analysis_updated.connect(
                pages["workflow"].refresh_data
            )
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
            analysis_export.first_package_export_started.connect(
                self._first_export_started
            )
            analysis_export.first_package_exported.connect(self._first_export_completed)
            analysis_export.analysis_imported.connect(self._ai_import_completed)
        return pages

    def _adopt_existing_qec(self) -> None:
        """Bestehende QEC-Fälle zuordnen, niemals erneut importieren oder löschen."""
        workflow = self.pages["workflow"]
        if not self._portable_transfer_ready():
            workflow.set_notice(
                "Bestehenden Bestand erst nach Abschluss aller Transfers übernehmen.",
                error=True,
            )
            return
        if workflow.profile_id != "coolant_pump":
            workflow.set_notice("QEC-Altbestandsübernahme ist zurzeit pumpenspezifisch.")
            return
        from collections import Counter
        from ntf_insight.storage.cluster_evidence_store import part_key

        candidates: dict[str, str] = {}
        counts = Counter()
        for row in workflow._all_rows:
            original = str(row.get("part_number") or "").strip()
            key = part_key(original)
            if key:
                candidates.setdefault(key, original)
                counts[key] += 1
        if not candidates:
            workflow.set_notice(
                "Keine importierten QEC-Fälle mit Sachnummer gefunden.", error=True
            )
            return
        values = sorted(candidates, key=lambda k: (-counts[k], candidates[k]))
        labels = [
            f"{candidates[key]}  ·  {counts[key]} QEC-Fälle"
            for key in values
        ]
        chosen, accepted = QInputDialog.getItem(
            self, "Bestehenden Kühlmittelpumpen-Bestand zuordnen",
            "Für welche Sachnummer soll ein Projekt angelegt werden?",
            labels, 0, False,
        )
        if not accepted:
            return
        part = candidates[values[labels.index(chosen)]]
        answer = QMessageBox.question(
            self, "Vorhandene Daten übernehmen",
            f"Projekt 'Kühlmittelpumpe [{part}]' anlegen und vorhandene QEC-"
            "Fälle dieser Sachnummer zuordnen?\n\n"
            "Die Fall-, FIN-, Diagnose- und Rohdaten bleiben unverändert. "
            "Es wird nichts gelöscht und kein zweiter Import gestartet.\n\n"
            "Quellen können weiterhin Daten anderer Sachnummern enthalten. "
            "Ein projektbezogener Export muss diese Zuordnung prüfen.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        store = workflow.project_store
        project = store.get("coolant_pump", part)
        if project is None:
            try:
                project = store.save(
                    NTFProject("coolant_pump", part, "Kühlmittelpumpe", ()),
                    create_only=True,
                )
            except ValueError as exc:
                workflow.set_notice(str(exc), error=True)
                return
        migrated = False
        if len(counts) == 1:
            # Ein unscoped Altworfklow ist nur dann eindeutig übernehmbar,
            # wenn der vorhandene QEC-Master genau eine Sachnummer enthält.
            from ntf_insight.storage.workflow_progress import WorkflowProgress

            old_state = workflow.progress_store.load("coolant_pump", "")
            part_state = workflow.progress_store.load("coolant_pump", part)
            if old_state != WorkflowProgress() and part_state == WorkflowProgress():
                workflow.progress_store.save("coolant_pump", part, old_state)
                migrated = True
            with workflow.progress_store.store.connect() as con:
                con.execute("BEGIN TRANSACTION")
                try:
                    con.execute(
                        "INSERT INTO cluster_evidence_files "
                        "(profile_id,part_key,category,sha256) "
                        "SELECT profile_id,?,category,sha256 FROM cluster_evidence_files "
                        "WHERE profile_id=? AND part_key='' ON CONFLICT DO NOTHING",
                        [part_key(part), "coolant_pump"],
                    )
                    con.execute(
                        "INSERT INTO workflow_first_ai_packages "
                        "(profile_id,part_key,paket_id,sha256) "
                        "SELECT profile_id,?,paket_id,sha256 "
                        "FROM workflow_first_ai_packages "
                        "WHERE profile_id=? AND part_key='' ON CONFLICT DO NOTHING",
                        [part_key(part), "coolant_pump"],
                    )
                    con.execute(
                        "UPDATE workflow_second_ai_exports SET part_key=? "
                        "WHERE profile_id=? AND part_key=''",
                        [part_key(part), "coolant_pump"],
                    )
                    con.execute("COMMIT")
                except Exception:
                    con.execute("ROLLBACK")
                    raise
        self._project_selected(project.profile_id, project.part_number)
        workflow.set_notice(
            f"{counts[part_key(part)]} vorhandene QEC-Fälle der Sachnummer "
            f"{part} sind jetzt im Projekt sichtbar; kein erneuter Import."
            + (
                " Vorheriger Workflow-Stand ebenfalls übernommen."
                if migrated else ""
            )
            + (
                " Achtung: Unterlagen ohne Sachnummer bitte separat prüfen."
                if len(counts) > 1 else ""
            )
        )

    def _show_operation_progress(self, title: str, message: str) -> QProgressDialog:
        """Gemeinsamer modaler Fortschritt für ZIP, Projekt-Export und -Import."""
        self._begin_loading(message)
        dialog = QProgressDialog(message, "", 0, 0, self)
        dialog.setWindowTitle(title)
        dialog.setCancelButton(None)  # ZIP-/Datenbanktransaktion nie unsicher abbrechen.
        dialog.setMinimumWidth(510)
        dialog.setMinimumDuration(0)
        dialog.setAutoClose(False)
        dialog.setWindowModality(Qt.WindowModality.WindowModal)
        dialog.setWindowFlags(
            Qt.WindowType.Dialog | Qt.WindowType.CustomizeWindowHint
            | Qt.WindowType.WindowTitleHint
        )
        dialog.show()
        return dialog

    def _close_operation_progress(self, dialog: QProgressDialog) -> None:
        dialog.close()
        dialog.deleteLater()
        self._finish_loading()

    def _diagnostics_started(self, message: str) -> None:
        self._diagnostics_path = None
        self._diagnostics_error_text = None
        self._diagnostics_started_at = time.monotonic()
        self._diagnostics_phase = ""
        self._diagnostics_dialog = self._show_operation_progress(
            "Parser-Fehler-ZIP erstellen", message,
        )

    def _diagnostics_progress(self, message: str) -> None:
        dialog = self._diagnostics_dialog
        if dialog is None:
            return
        phase = message.partition(":")[0]
        if phase != self._diagnostics_phase:
            self._diagnostics_phase = phase
            self._diagnostics_started_at = time.monotonic()
        progress = re.search(r"(\\d+)\\s*/\\s*(\\d+)", message)
        if progress and int(progress.group(2)) > 0:
            done, total = (int(part) for part in progress.groups())
            dialog.setRange(0, total)
            dialog.setValue(min(done, total))
            elapsed = time.monotonic() - self._diagnostics_started_at
            eta = (
                f" · ungefähr noch {int(elapsed * (total - done) / done)} s"
                if 0 < done < total and elapsed >= 2 else
                " · Restzeit wird ermittelt" if done < total else ""
            )
            dialog.setLabelText(message + eta)
        else:
            dialog.setRange(0, 0)
            dialog.setLabelText(message + " · Dauer noch nicht abschätzbar")

    def _diagnostics_saved(self, destination: str) -> None:
        self._diagnostics_path = Path(destination)

    def _diagnostics_failed(self, message: str) -> None:
        self._diagnostics_error_text = message

    def _diagnostics_ended(self) -> None:
        dialog, self._diagnostics_dialog = self._diagnostics_dialog, None
        if dialog is not None:
            self._close_operation_progress(dialog)
        path, self._diagnostics_path = self._diagnostics_path, None
        error, self._diagnostics_error_text = self._diagnostics_error_text, None
        if error is not None:
            self.pages["workflow"].set_notice(
                "Fehler-ZIP konnte nicht erstellt werden: " + error,
                error=True,
            )
            QMessageBox.critical(
                self, "Fehler-ZIP nicht erstellt",
                "Es wurde kein neues Diagnosepaket gespeichert.\n\n" + error,
            )
            return
        if path is None or not path.exists() or path.stat().st_size <= 0:
            QMessageBox.critical(
                self, "Fehler-ZIP nicht gefunden",
                "Der Export hat keine überprüfbare, nicht leere ZIP-Datei "
                "am angegebenen Ziel hinterlassen.",
            )
            return
        self.pages["workflow"].set_notice(
            f"Parser-Diagnose-ZIP gespeichert: {path}",
        )
        confirmation = QMessageBox(self)
        confirmation.setWindowTitle("Fehler-ZIP erfolgreich erstellt")
        confirmation.setIcon(QMessageBox.Icon.Information)
        confirmation.setText(
            f"Die ZIP-Datei ist vollständig gespeichert.\\n\\n"
            f"Speicherort: {path}\\n"
            f"Größe: {path.stat().st_size:,} Byte"
        )
        open_folder = confirmation.addButton(
            "Ordner öffnen", QMessageBox.ButtonRole.ActionRole
        )
        confirmation.addButton(QMessageBox.StandardButton.OK)
        confirmation.exec()
        if confirmation.clickedButton() is open_folder:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))

    def _project_transfer_export(self) -> None:
        workflow = self.pages["workflow"]
        project = workflow.project_store.get(
            workflow.profile_id, workflow._context_part,
        )
        if project is None:
            workflow.set_notice(
                "Bitte erst ein Projekt auswählen oder bestehenden QEC-Bestand "
                "als Projekt übernehmen.", error=True,
            )
            return
        if not self._portable_transfer_ready():
            workflow.set_notice("Ein Import oder Download läuft bereits.", error=True)
            return
        note = (
            f"Projekt: {project.title}\n\n"
            "Es werden projektbezogene Einstellungen, Fall-/QEC-Daten, "
            "QuickTests, technische Unterlagen, manuelle Bewertungen und "
            "lokal gespeicherte ChatGPT-Pakete gesammelt.\n\n"
            "ACHTUNG: Gemeinsame Quelldateien (etwa eine QEC-Excel mit mehreren "
            "Sachnummern) werden als unveränderte Originale mitgenommen. "
            "Diese können auch Fälle anderer Projekte enthalten.\n\n"
            "Das Paket ist nicht verschlüsselt. Nur über freigegebene "
            "Unternehmensspeicher übertragen. Export erstellen?"
        )
        answer = QMessageBox.question(
            self, "Projektbezogenen Transfer freigeben", note,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        safe = "".join(
            char for char in project.part_number if char.isalnum()
        )[:35]
        name, _ = QFileDialog.getSaveFileName(
            self, "Projekt auf anderen PC übertragen",
            str(Path.home() / f"NTF_{safe}{PROJECT_EXTENSION}"),
            "NTF-Projekt (*.ntfproject)",
        )
        if not name:
            return
        package = Path(name)
        if package.suffix.lower() != PROJECT_EXTENSION:
            package = package.with_suffix(PROJECT_EXTENSION)
        self._start_project_transfer(
            "export", package,
            profile=project.profile_id, part=project.part_number,
        )

    def _project_transfer_import(self) -> None:
        workflow = self.pages["workflow"]
        if not self._portable_transfer_ready():
            workflow.set_notice("Ein Import oder Download läuft bereits.", error=True)
            return
        filename, _ = QFileDialog.getOpenFileName(
            self, "Projektpaket eines anderen PCs wählen",
            str(Path.home()), "NTF-Projekt (*.ntfproject)",
        )
        if not filename:
            return
        answer = QMessageBox.question(
            self, "Projekt importieren (andere Projekte behalten)",
            "Ein .ntfproject enthält die Daten und Dokumente eines Projekts.\n\n"
            "Ein NEUES Projekt wird der lokalen App hinzugefügt. "
            "Bereits vorhandene andere Projekte werden nicht ersetzt.\n\n"
            "Falls die gleiche Sachnummer hier bereits als Projekt existiert, "
            "wird der Import aus Sicherheitsgründen abgelehnt. "
            "Ein Zusammenführen wird ausdrücklich NICHT vorgenommen.\n\n"
            "Das Paket kann vertrauliche oder nicht anonymisierte Rohdaten "
            "enthalten. Nur vertrauenswürdige Dateien verwenden. Fortfahren?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._start_project_transfer("import", Path(filename))

    def _start_project_transfer(
        self, action: str, package: Path, *,
        profile: str = "", part: str = "",
    ) -> None:
        self._project_import_result = None
        self._project_transfer_worker = ProjectTransferWorker(
            action, self.application_data.paths.data_dir,
            package, profile=profile, part_number=part,
        )
        worker = self._project_transfer_worker
        worker.completed.connect(self._project_transfer_completed)
        self._project_transfer_failure = None
        dialog = self._show_operation_progress(
            "Projekt exportieren" if action == "export" else "Projekt importieren",
            "Projektpaket wird verarbeitet …",
        )
        self._project_transfer_dialog = dialog
        worker.progress.connect(self._project_transfer_progress)
        self._project_transfer_progress(0, "Projektpaket vorbereiten")
        dialog.show()
        worker.failed.connect(self._project_transfer_failed)
        worker.finished.connect(self._project_transfer_finished)
        self.pages["workflow"].set_notice(
            "Projektpaket erstellen …" if action == "export"
            else "Projektpaket prüfen und lokal hinzufügen …"
        )
        self._portable_transfer_busy(True)
        worker.start()

    def _project_transfer_progress(self, percent: int, message: str) -> None:
        workflow = self.pages["workflow"]
        workflow.update_project_transfer_progress(percent, message)
        dialog = self._project_transfer_dialog
        if dialog is not None:
            if percent < 0:
                dialog.setRange(0, 0)
            else:
                dialog.setRange(0, 100)
                dialog.setValue(max(0, min(100, percent)))
            dialog.setLabelText(workflow.project_transfer_eta.text())

    def _project_transfer_completed(self, result: object) -> None:
        workflow = self.pages["workflow"]
        if hasattr(result, "path"):
            warning = (
                "Ein QEC-Original kann weitere Sachnummern enthalten. "
                if result.shared_source_warning else ""
            )
            workflow.set_notice(
                f"Projektpaket erstellt: {result.path.name} · "
                f"{result.case_count} Fälle, {result.fin_count} FINs. "
                "Keine anderen Projekt-Tabellendaten übernommen. "
                + warning
            )
        else:
            self._project_import_result = result
            workflow.set_notice(
                f"Projekt importiert: {result.part_number} · "
                f"{result.case_count} Fälle. Andere Projekte bleiben erhalten."
            )

    def _project_transfer_failed(self, message: str) -> None:
        self._project_transfer_failure = message
        self.pages["workflow"].set_notice(
            "Projekttransfer nicht ausgeführt: " + message, error=True
        )

    def _project_transfer_finished(self) -> None:
        self.pages["workflow"].finish_project_transfer_progress()
        dialog, self._project_transfer_dialog = self._project_transfer_dialog, None
        if dialog is not None:
            self._close_operation_progress(dialog)
        worker, self._project_transfer_worker = self._project_transfer_worker, None
        if worker is not None:
            worker.deleteLater()
        self._portable_transfer_busy(False)
        result, self._project_import_result = self._project_import_result, None
        if self._project_transfer_failure:
            error, self._project_transfer_failure = self._project_transfer_failure, None
            QMessageBox.critical(
                self, "Projekttransfer fehlgeschlagen",
                "Das Projektpaket wurde nicht vollständig verarbeitet.\n\n" + error,
            )
        if result is not None:
            self._reload_data()
            self._project_selected(result.profile_id, result.part_number)

    def _project_delete_requested(
        self, profile: str, part: str, complete: bool,
    ) -> None:
        """Projekt nur bei inaktiven Import-/Transferarbeitern löschen."""
        settings = self.pages["project_settings"]
        if not self._portable_transfer_ready():
            settings.status.setText(
                "Projektlöschung nicht möglich, solange ein Import, "
                "Download oder Datentransfer läuft."
            )
            return
        if settings.projects.get(profile, part) is None:
            settings.status.setText("Projekt existiert nicht mehr.")
            settings.refresh_projects()
            return
        worker = ProjectDeleteWorker(
            self.application_data.paths.data_dir,
            profile, part, complete=complete,
        )
        self._project_delete_worker = worker
        self._project_delete_result = None
        worker.completed.connect(self._project_delete_completed)
        worker.failed.connect(self._project_delete_failed)
        worker.finished.connect(self._project_delete_finished)
        settings.status.setText(
            "Projektdaten werden kontrolliert gelöscht …" if complete
            else "Projektregistrierung wird entfernt …"
        )
        self._portable_transfer_busy(True)
        worker.start()

    def _project_delete_completed(self, result: object) -> None:
        self._project_delete_result = result

    def _project_delete_failed(self, message: str) -> None:
        self.pages["project_settings"].status.setText(message)

    def _project_delete_finished(self) -> None:
        worker, self._project_delete_worker = self._project_delete_worker, None
        if worker is not None:
            worker.deleteLater()
        self._portable_transfer_busy(False)
        result, self._project_delete_result = self._project_delete_result, None
        if result is None:
            return
        self._reload_data()
        workflow = self.pages["workflow"]
        settings = self.pages["project_settings"]
        projects = settings.projects.list_projects()
        if projects:
            # Falls das aktive Projekt gelöscht wurde, nächstes Projekt
            # auswählen; alle anderen Projektkontexte unverändert lassen.
            selected = workflow.project_store.get(
                workflow.profile_id, workflow._context_part
            )
            if selected is None:
                selected = projects[0]
                workflow.activate_project(
                    selected.profile_id, selected.part_number
                )
                if self.pages["sources"].qec_workflow is not None:
                    self.pages["sources"].qec_workflow.set_project_scope(
                        selected.part_number
                    )
            settings.select_project(selected.profile_id, selected.part_number)
        else:
            settings.refresh_projects()
        self._sync_local_cluster()
        if result.complete:
            message = (
                f"Projekt {result.project.title} gelöscht: "
                f"{result.cases_deleted} Fälle, "
                f"{result.report_count} QuickTests, "
                f"{result.files_deleted} Archivobjekte. "
                f"{result.shared_files_retained} gemeinsam verwendete "
                "Quellobjekte geschützt."
                + (" " + result.cleanup_warning if result.cleanup_warning else "")
            )
        else:
            message = (
                f"Projekt {result.project.title} entfernt. "
                "Alle vorhandenen QEC-/Diagnose- und Analysedaten "
                "bleiben lokal gespeichert."
            )
        settings.status.setText(message)
        self._show_project_settings()

    def _project_selected(self, profile: str, part: str) -> None:
        if not self._portable_transfer_ready():
            self.pages["workflow"].set_notice(
                "Projektwechsel erst nach Abschluss laufender Importe/Downloads.",
                error=True,
            )
            return
        self.pages["workflow"].activate_project(profile, part)
        if self.pages["sources"].qec_workflow is not None:
            self.pages["sources"].qec_workflow.set_project_scope(part)
        self.pages["project_settings"].select_project(profile, part)
        self._sync_local_cluster()
        if self._project_dialog is not None and self._project_dialog.isVisible():
            self._project_dialog.accept()
        self.navigation.select_page("workflow")

    def _sync_local_cluster(self) -> None:
        workflow = self.pages["workflow"]
        widget = self.pages["cases"].cluster_workspace
        if workflow.profile_id == "coolant_pump":
            widget.set_workflow_part_number(workflow._context_part)
            rows = workflow._rows_for_context()
            allowed = workflow.ssl_selection.allowed_fins(
                workflow.profile_id, workflow._context_part, rows,
            )
            widget.set_workflow_allowed_fins(allowed)
        else:
            widget.set_workflow_allowed_fins(set())

    def _open_cluster_from_case(self, case_id: str) -> None:
        workflow = self.pages["workflow"]
        self._sync_local_cluster()
        workflow._open_step(4)
        self.navigation.select_page("workflow")

    def _first_export_started(self, _destination: object) -> None:
        workflow = self.pages["workflow"]
        self._pending_first_context = (workflow.profile_id, workflow._context_part)

    def _first_export_completed(self, result: object) -> None:
        workflow = self.pages["workflow"]
        context = self._pending_first_context
        self._pending_first_context = None
        if context is None:
            return
        try:
            stored = workflow.ai_chain.register_first_export(
                context[0], context[1], result.pfad
            )
        except (OSError, ValueError) as exc:
            workflow.set_notice(
                "KI-Paket erstellt, aber automatische Übernahme fehlgeschlagen: "
                + str(exc), error=True,
            )
            return
        workflow.refresh_ai_chain()
        workflow.set_notice(
            "1. KI-Paket automatisch lokal gesichert: "
            + stored.paket_id[:12] + "… · kein erneutes Auswählen nötig."
        )

    def _ai_import_completed(self, result: object) -> None:
        round_number = self._pending_ai_round
        self._pending_ai_round = None
        if round_number is None:
            return
        workflow = self.pages["workflow"]
        try:
            linked = workflow.ai_chain.record_import(
                result["analyse_id"], round_number=round_number
            )
        except (OSError, ValueError) as exc:
            workflow.set_notice(
                "Analyse importiert, aber Workflow-Zuordnung ungültig: "
                + str(exc), error=True,
            )
            return
        workflow.refresh_ai_chain()
        workflow.refresh_data()
        if linked:
            workflow.set_notice(
                f"{round_number}. ChatGPT-Ergebnis automatisch im Projekt verknüpft."
            )

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
            and self._context_worker is None
            and self._project_transfer_worker is None
            and self._project_delete_worker is None
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
        self.navigation.select_page("workflow")
        QMessageBox.information(
            self, "Gesamtdatenstand wiederhergestellt",
            f"{result.case_count} Fall/Fälle und {result.quicktest_count} "
            "bereits geparste QuickTests sind sofort verfügbar. "
            "Originale, manuelle Änderungen und weitere Analysewerte wurden "
            "aus demselben Paket übernommen. Kein erneutes Parsen nötig.",
        )

    def _reload_after_source_import(self, summary: str, quicktests_saved: int = 0) -> None:
        """Quellen neu laden, Workflow-Kontext bei workflowgestarteten Imports behalten."""
        if (
            self._workflow_source_import_pending
            or self._workflow_qec_download_pending
            or self._workflow_quicktest_download_pending
        ):
            self._workflow_source_import_pending = False
            self._workflow_qec_download_pending = False
            self._workflow_quicktest_download_pending = False
            self._case_quicktest_import_pending = False
            self._reload_data()
            self.navigation.select_page("workflow")
            self.pages["workflow"].set_import_state(
                False, can_resume=bool(self._workflow_last_qec_files)
            )
            self.pages["workflow"].set_notice(summary)
            return
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

        if self._project_dialog is not None:
            self._project_dialog.close()
            self._project_dialog.deleteLater()
            self._project_dialog = None
        dashboard_worker = getattr(self.pages["dashboard"], "_worker", None)
        if dashboard_worker is not None and dashboard_worker.isRunning():
            dashboard_worker.wait()  # QThread nie während einer DB-Abfrage zerstören.
        old_pages = list(self.pages.values())
        for old in old_pages:
            if self.stack.indexOf(old) >= 0:
                self.stack.removeWidget(old)
            old.deleteLater()

        self.pages = self._create_pages()
        for name, page in self.pages.items():
            if name != "project_settings":
                self.stack.addWidget(page)


    @staticmethod
    def _workflow_focus(scroll, target: QWidget | None) -> None:
        """Nach dem Seitenwechsel direkt zum tatsächlichen Unterbereich springen."""
        if target is None:
            return
        scroll.ensureWidgetVisible(target, 24, 56)
        if target.focusPolicy() != Qt.FocusPolicy.NoFocus:
            target.setFocus(Qt.FocusReason.OtherFocusReason)

    def _workflow_navigate(self, page: str, tab: str) -> None:
        """Jede Karte führt zur konkreten Funktion statt nur zum Seitenanfang."""
        if page == "sources":
            source = self.pages["sources"]
            target = None
            if tab == "qec_list":
                target = (
                    source.qec_workflow.step1
                    if source.qec_workflow is not None else source.archive_button
                )
            elif tab == "qec_decision" and source.qec_workflow is not None:
                source.qec_workflow.refresh()
                target = source.qec_workflow.case_selector
            elif tab == "chatgpt" and source.ki_analyse_panel is not None:
                target = source.ki_analyse_panel.export_button
            self.navigation.select_page("sources")
            if target is not None:
                QTimer.singleShot(
                    0, lambda scroll=source.content_scroll, widget=target: (
                        self._workflow_focus(scroll, widget)
                    ),
                )
            return

        if page == "cases":
            cases = self.pages["cases"]
            if tab == "qec_reports":
                if cases.qec_download is None:
                    QMessageBox.information(
                        self, "QEC-Befundung",
                        "Der QEC-Abruf ist in dieser Installation nicht verfügbar.",
                    )
                    return
                cases.detail_tabs.setCurrentWidget(cases.analysis_tab)
                self.navigation.select_page("cases")
                QTimer.singleShot(
                    0, lambda scroll=cases.analysis_tab,
                    widget=cases.qec_download.all_button: (
                        self._workflow_focus(scroll, widget)
                    ),
                )
                return
            if tab == "cluster":
                self._open_cluster_from_case("")
                return
            elif tab == "quicktests" and cases.quicktest_browser is not None:
                cases.detail_tabs.setCurrentWidget(cases.quicktest_browser)

        self.navigation.select_page(page)

    def _workflow_start_import(self, action: str) -> None:
        """Bestehenden Quellenimport verwenden; Ergebnis im Workflow anzeigen."""
        source = self.pages["sources"]
        workflow = self.pages["workflow"]
        if (
            source._worker is not None or source._diagnostics_worker is not None
            or self._context_worker is not None
        ):
            workflow.set_notice("Ein anderer Quellenimport läuft bereits.", error=True)
            return
        if action in {"qec_list_import", "qec_list_resume"}:
            if action == "qec_list_import":
                files, _ = QFileDialog.getOpenFileNames(
                    self, "QEC-generierte FIN-Liste auswählen",
                    str(Path.home()), "QEC Excel (*.xlsx)",
                )
                if not files:
                    return
                self._workflow_last_qec_files = [Path(file) for file in files]
            else:
                if not self._workflow_last_qec_files:
                    workflow.set_notice("Kein letzter QEC-Dateiimport vorhanden.")
                    return
            before = source.source_type.currentIndex()
            index = source.source_type.findData(SourceType.VEHICLE_CASE_LIST)
            try:
                source.source_type.setCurrentIndex(index if index >= 0 else 0)
                source._archive_paths(
                    self._workflow_last_qec_files,
                    only_new=action == "qec_list_resume",
                )
            finally:
                source.source_type.setCurrentIndex(before)
        else:
            source._import_existing_qec()

        worker = source._worker
        if worker is None:
            workflow.set_notice(source.import_status.text(), error=True)
            return
        self._workflow_source_import_pending = True
        workflow.set_import_state(True)
        workflow.set_notice("QEC-Quelldaten werden importiert …")
        worker.progress.connect(workflow.set_notice)
        worker.failed.connect(self._workflow_import_failed)
        worker.finished.connect(self._workflow_import_finished)

    def _workflow_import_failed(self, message: str) -> None:
        self._workflow_source_import_pending = False
        self.pages["workflow"].set_import_state(
            False, can_resume=bool(self._workflow_last_qec_files)
        )
        self.pages["workflow"].set_notice(
            "QEC-Import fehlgeschlagen: " + message, error=True
        )

    def _workflow_import_finished(self) -> None:
        # Erfolgreiche Imports bauen die Seite bereits über sources_updated neu.
        if self._workflow_source_import_pending:
            self._workflow_source_import_pending = False
            self.pages["workflow"].set_import_state(
                False, can_resume=bool(self._workflow_last_qec_files)
            )

    def _workflow_start_qec_download(
        self, *, selected_only: bool, missing_only: bool = False,
    ) -> None:
        """Vorhandener QEC-Worker, aber exakt auf die Workflow-Sachnummer gefiltert."""
        workflow = self.pages["workflow"]
        cases = self.pages["cases"]
        panel = cases.qec_download
        source = self.pages["sources"]
        if panel is None:
            workflow.set_notice("QEC-Berichtsabruf ist nicht eingerichtet.", error=True)
            return
        if panel.worker is not None or source._worker is not None:
            workflow.set_notice("Download/Import läuft bereits.", error=True)
            return
        targets = workflow.qec_targets(selected_only=selected_only)
        if missing_only:
            coverage = workflow._source_coverage.get("qec")
            missing = set(coverage.missing_qec) if coverage else set()
            targets = [
                target for target in targets
                if (target.fin, target.reference) in missing
            ]
        if not targets:
            workflow.set_notice(
                "Keine passenden QEC-Fälle ohne heruntergeladenen aktuellen "
                "JSON-Bericht vorhanden.", error=True
            )
            return
        self._workflow_qec_download_pending = True
        panel._start(targets, bulk=not selected_only)
        worker = panel.worker
        if worker is None:
            # Abbruch im Bestätigungs- oder SSO-Dialog, keine Datenänderung.
            self._workflow_qec_download_pending = False
            return
        workflow.set_download_busy(
            True, f"QEC-Abruf für {len(targets)} Fall/Fälle gestartet …",
            scope="selected" if selected_only else "missing" if missing_only else "all",
        )
        worker.progress.connect(workflow.qec_status.setText)
        worker.failed.connect(
            lambda message: workflow.set_notice("QEC-Abruf: " + message, error=True)
        )
        worker.finished.connect(self._workflow_qec_finished)

    def _workflow_qec_finished(self) -> None:
        workflow = self.pages["workflow"]
        workflow.set_download_busy(False)
        # Wenn der Worker Dateien erzeugt hat, folgt deren Quellenimport.
        if not self._case_quicktest_import_pending:
            self._workflow_qec_download_pending = False
            workflow.refresh_data()

    def _context_parse_all(self, category: str) -> None:
        """Verifizierte Originale der aktuellen Quelle bewusst komplett neu parsen."""
        workflow = self.pages["workflow"]
        source = self.pages["sources"]
        status = workflow._source_coverage.get(category)
        kind = {
            "qec": SourceType.QEC_REPORT,
            "tp_dashboard": SourceType.TP_DASHBOARD,
            "diagnosis_viewer": SourceType.SHORT_TEST,
            "tips_writer": SourceType.TIPS_CASE,
        }.get(category)
        if kind is None or status is None or status.unsupported_parser:
            workflow.set_notice("Für diese Quelle ist kein Neuparsen verfügbar.", error=True)
            return
        if not self._portable_transfer_ready():
            workflow.set_notice("Ein anderer Download oder Parser läuft bereits.", error=True)
            return
        paths = list(dict.fromkeys(status.local_paths))
        if not paths:
            workflow.set_notice("Keine verifizierten lokalen Dokumente zum Neuparsen.", error=True)
            return
        answer = QMessageBox.question(
            self, "Alle Quelldokumente erneut parsen?",
            f"{len(paths)} lokale Dokumente der Quelle {category} werden "
            "erneut strukturiert eingelesen. Bei großen PDFs oder Sammel-CSV-Dateien "
            "kann dies lange dauern. Originaldateien werden nicht gelöscht.\n\n"
            "Wirklich das vollständige Neuparsen starten?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        index = source.source_type.findData(kind)
        before = source.source_type.currentIndex()
        try:
            source.source_type.setCurrentIndex(index if index >= 0 else 0)
            source._archive_paths(paths)
        finally:
            source.source_type.setCurrentIndex(before)
        worker = source._worker
        if worker is None:
            workflow.set_notice("Neuparsen konnte nicht gestartet werden.", error=True)
            return
        context = (workflow.profile_id, workflow._context_part)
        workflow.source_activity.record(*context, category, "Einlesen gestartet")
        workflow.set_context_parser_busy(category, True, "all")
        workflow.set_context_operation(
            category, True, f"Neuparsen gestartet: 0/{len(paths)} Dokumente"
        )
        worker.progress.connect(
            lambda message, cat=category:
            workflow.set_context_operation(cat, True, message)
        )
        worker.imported.connect(
            lambda summary, cat=category, ctx=context:
            self._resume_source_parsing_completed(cat, ctx, summary)
        )
        worker.failed.connect(
            lambda _message, cat=category, ctx=context:
            self._context_parse_failed(cat, ctx)
        )
        worker.finished.connect(
            lambda cat=category: self._context_parser_finished(cat)
        )

    def _context_parse_cancel(self, category: str) -> None:
        workflow = self.pages["workflow"]
        if category not in workflow._context_parsers_busy:
            return
        source = self.pages["sources"]
        if source._worker is None:
            return
        source._cancel_import()
        workflow.set_context_operation(
            category, True,
            "Abbruch angefordert · laufende Datei wird sicher fertig verarbeitet"
        )

    def _context_parser_finished(self, category: str) -> None:
        workflow = self.pages["workflow"]
        workflow.set_context_operation(category, False)
        workflow.set_context_parser_busy(category, False)

    def _resume_source_parsing(self, category: str) -> None:
        """Nur nicht indexierte vorhandene Dateien über bestehende Parser nachholen."""
        workflow = self.pages["workflow"]
        source = self.pages["sources"]
        if not self._portable_transfer_ready():
            workflow.set_notice(
                "Parsing erst nach Abschluss des laufenden Datenimports starten.",
                error=True,
            )
            return
        current = workflow._source_coverage.get(category)
        if current is None or not current.can_resume_parsing:
            workflow.set_notice(
                "Keine vorhandenen Dokumente mit fehlendem Parsergebnis "
                "für diese Quelle gefunden."
            )
            return
        paths = list(current.pending_paths)
        kind = {
            "qec": SourceType.QEC_REPORT,
            "diagnosis_viewer": SourceType.SHORT_TEST,
            "tips_writer": SourceType.TIPS_CASE,
            "tp_dashboard": SourceType.TP_DASHBOARD,
            "cdd_smrd": SourceType.DIAGNOSTIC_DESCRIPTION,
        }.get(category)
        if kind is None:
            workflow.set_notice(
                "Für diese Quelle gibt es noch keinen strukturierten Parser.",
                error=True,
            )
            return
        before = source.source_type.currentIndex()
        index = source.source_type.findData(kind)
        try:
            source.source_type.setCurrentIndex(index if index >= 0 else 0)
            source._archive_paths(paths)  # Nicht erneut bereits geparste Quellen.
        finally:
            source.source_type.setCurrentIndex(before)
        worker = source._worker
        if worker is None:
            workflow.set_notice(
                "Parser konnte nicht gestartet werden.", error=True,
            )
            return
        context = (workflow.profile_id, workflow._context_part)
        if category != "qec":
            workflow.source_activity.record(
                context[0], context[1], category, "Einlesen gestartet",
            )
        workflow.set_context_parser_busy(category, True, "resume")
        if category != "qec":
            workflow.set_context_operation(
                category, True, f"{len(paths)} ausstehende Dateien werden geparst …"
            )
            worker.progress.connect(
                lambda message, cat=category:
                workflow.set_context_operation(cat, True, message)
            )
        else:
            worker.progress.connect(workflow.qec_status.setText)
        worker.failed.connect(
            lambda _message, cat=category, ctx=(workflow.profile_id, workflow._context_part):
            self._context_parse_failed(cat, ctx)
        )
        worker.finished.connect(
            lambda cat=category: self._context_parser_finished(cat)
        )
        worker.imported.connect(
            lambda summary, ctx=context, cat=category:
            self._resume_source_parsing_completed(cat, ctx, summary)
        )
        workflow.set_notice(
            f"{category}: {len(paths)} vorhandene, noch nicht strukturierte "
            "Datei(en) werden über den bestehenden Parser nachverarbeitet."
        )

    def _resume_source_parsing_completed(
        self, category: str, context: tuple[str, str], summary: object,
    ) -> None:
        workflow = self.pages["workflow"]
        if category != "qec":
            result = (
                "Abgebrochen" if summary.cancelled
                else "Teilweise" if summary.files_failed and summary.files_parsed
                else "Fehlgeschlagen" if summary.files_failed
                else "Eingelesen" if summary.files_parsed
                else "Archiviert"
            )
            workflow.source_activity.record(
                context[0], context[1], category, result,
            )
        workflow.set_context_operation(category, False)
        workflow.refresh_data()
        workflow.set_notice(
            f"Parsing: {summary.files_parsed} Dateien bearbeitet · "
            f"{summary.files_failed} Fehler · "
            f"{summary.files_pending} ohne Parser. "
            "Bereits erfolgreich indexierte Dokumente wurden übersprungen.",
            error=bool(summary.files_failed),
        )

    def _context_parse(self, category: str) -> None:
        """Vorhandenen Importparser nutzen, ohne selbst fachliche Daten zu erfinden."""
        kind = {
            "tp_dashboard": SourceType.TP_DASHBOARD,
            "diagnosis_viewer": SourceType.SHORT_TEST,
            "tips_writer": SourceType.TIPS_CASE,
            "celonis": SourceType.OTHER,
            "cdd_smrd": None,  # Candela-CDD erkannt, SMR-D archiviert.
        }.get(category)
        workflow = self.pages["workflow"]
        source = self.pages["sources"]
        if category not in {
            "tp_dashboard", "diagnosis_viewer", "tips_writer",
            "celonis", "cdd_smrd",
        }:
            workflow.set_notice("Unbekannte Datenquelle.", error=True)
            return
        if not self._portable_transfer_ready() or source._worker is not None:
            workflow.set_notice("Ein Quellenimport läuft bereits.", error=True)
            return
        filenames, _ = QFileDialog.getOpenFileNames(
            self, f"{category} · Daten einlesen",
            str(Path.home()), "Quelldateien (*.*)",
        )
        if not filenames:
            return
        context = (workflow.profile_id, workflow._context_part)
        workflow.source_activity.record(
            context[0], context[1], category, "Einlesen gestartet",
        )
        before = source.source_type.currentIndex()
        index = source.source_type.findData(kind)
        try:
            source.source_type.setCurrentIndex(index if index >= 0 else 0)
            source._archive_paths([Path(name) for name in filenames])
        finally:
            source.source_type.setCurrentIndex(before)
        worker = source._worker
        if worker is None:
            workflow.source_activity.record(
                context[0], context[1], category, "Fehlgeschlagen",
            )
            workflow.set_notice(
                "Einlesen konnte nicht gestartet werden. "
                "Importstatus unter Datenquellen prüfen.", error=True,
            )
            workflow.refresh_context_files()
            return
        workflow.set_context_parser_busy(category, True, "files")
        workflow.set_context_operation(
            category, True, f"{len(filenames)} Dateien werden eingelesen …"
        )
        worker.progress.connect(
            lambda message, cat=category:
            workflow.set_context_operation(cat, True, message)
        )
        worker.finished.connect(
            lambda cat=category: self._context_parser_finished(cat)
        )
        worker.imported.connect(
            lambda summary, ctx=context, cat=category,
            paths=tuple(Path(name) for name in filenames):
            self._context_parse_completed(cat, ctx, summary, paths)
        )
        worker.failed.connect(
            lambda _message, ctx=context, cat=category:
            self._context_parse_failed(cat, ctx)
        )
        workflow.refresh_context_files()
        if category == "celonis":
            workflow.set_notice(
                "Celonis-Dateien werden archiviert. Ein strukturierter "
                "Celonis-Parser ist noch nicht implementiert."
            )
        else:
            workflow.set_notice(
                f"{len(filenames)} Datei(en) zur Einleseprüfung ausgewählt. "
                "Ergebnis und ggf. Parserprobleme unter Datenquellen prüfen."
            )

    def _context_parse_completed(
        self, category: str, context: tuple[str, str], summary: object,
        paths: tuple[Path, ...] = (),
    ) -> None:
        workflow = self.pages["workflow"]
        parsed = bool(summary.files_parsed or summary.quicktests_saved)
        result = (
            "Abgebrochen" if summary.cancelled
            else "Teilweise" if summary.files_failed and parsed
            else "Fehlgeschlagen" if summary.files_failed
            else "Archiviert" if category == "celonis" or not parsed
            else "Eingelesen"
        )
        workflow.set_context_operation(category, False)
        workflow.source_activity.record(context[0], context[1], category, result)
        workflow.refresh_context_files()
        if (
            paths and not summary.cancelled and self._context_worker is None
            and (
                summary.files_archived or summary.files_unchanged
                or summary.files_parsed or summary.duplicates
            )
        ):
            # Derselbe nachweisliche Beleg wird auch der ausgewählten
            # Sachnummernsammlung zugeordnet – ohne zweiten Parserlauf.
            worker = ClusterEvidenceImportWorker(
                workflow.context_store, context[0], context[1],
                category, list(paths),
            )
            self._context_worker = worker
            workflow.set_context_busy(True)
            worker.completed.connect(self._context_import_completed)
            worker.failed.connect(self._context_failed)
            worker.finished.connect(self._context_worker_finished)
            worker.start()

    def _context_parse_failed(
        self, category: str, context: tuple[str, str],
    ) -> None:
        workflow = self.pages["workflow"]
        workflow.set_context_operation(category, False)
        workflow.source_activity.record(
            context[0], context[1], category, "Fehlgeschlagen",
        )
        workflow.refresh_context_files()

    def _context_import(self, category: str) -> None:
        """Fachunterlagen unverändert im vorhandenen lokalen Rohdatenarchiv sammeln."""
        workflow = self.pages["workflow"]
        if category not in CATEGORY_LABELS:
            workflow.set_notice("Unbekannte Unterlagenkategorie.", error=True)
            return
        if not self._portable_transfer_ready() or self._context_worker is not None:
            workflow.set_notice("Ein Import oder Download läuft bereits.", error=True)
            return
        files, _ = QFileDialog.getOpenFileNames(
            self, f"{CATEGORY_LABELS[category]} auswählen",
            str(Path.home()), "Technische Dokumente (*.*)",
        )
        if not files:
            return
        worker = ClusterEvidenceImportWorker(
            workflow.context_store, workflow.profile_id, workflow._context_part,
            category, [Path(name) for name in files],
        )
        self._context_worker = worker
        workflow.set_context_busy(True)
        workflow.set_notice(
            f"{len(files)} Datei(en) werden lokal als "
            f"{CATEGORY_LABELS[category]} archiviert …"
        )
        worker.completed.connect(self._context_import_completed)
        worker.failed.connect(self._context_failed)
        worker.finished.connect(self._context_worker_finished)
        worker.start()

    def _context_import_completed(self, count: int) -> None:
        workflow = self.pages["workflow"]
        workflow.refresh_context_files()
        workflow.refresh()
        workflow.set_notice(f"{count} neue Unterlage(n) archiviert, Duplikate übersprungen.")

    def _context_failed(self, message: str) -> None:
        self.pages["workflow"].set_notice(
            "Unterlagenverarbeitung: " + message, error=True
        )

    def _context_worker_finished(self) -> None:
        worker, self._context_worker = self._context_worker, None
        if worker is not None:
            worker.deleteLater()
        workflow = self.pages["workflow"]
        workflow.set_context_busy(False)
        workflow.refresh_context_files()
        workflow.refresh()

    def _context_export(self) -> None:
        """Nur Schritt 05; erste Basis + erste ChatGPT-Auswertung automatisch."""
        workflow = self.pages["workflow"]
        workflow.refresh_ai_chain()
        package = workflow.first_package
        if package is None:
            workflow.set_notice(
                "Zuerst in Schritt 03 das erste KI-Paket erstellen.", error=True
            )
            return
        if package.analysis_id is None:
            workflow.set_notice(
                "Erstes ChatGPT-Ergebnis in Schritt 03 noch nicht importiert.",
                error=True,
            )
            return
        if self._context_worker is not None or not self._portable_transfer_ready():
            workflow.set_notice("Ein anderer Export oder Download läuft bereits.", error=True)
            return
        try:
            workflow.ai_chain.validate_cached_zip(package)
            first_result = workflow.ai_chain.first_result(package.paket_id)
            if first_result is None:
                raise ValueError("Zugehörige erste ChatGPT-Auswertung fehlt.")
        except (OSError, ValueError) as exc:
            workflow.set_notice("Erste KI-Analyse nicht verwendbar: " + str(exc), error=True)
            return
        originals = workflow.cluster_originals.isChecked()
        warning = (
            "Das zweite ChatGPT-Paket wird NUR LOKAL erzeugt.\n\n"
            "Es enthält die erste ChatGPT-Auswertung, die pseudonymisierte "
            "Analysebasis und das Inventar der Unterlagen aus Schritt 04. "
            "Auch pseudonymisierte Daten und Modell-Freitexte können "
            "vertraulich bzw. reidentifizierbar sein.\n\n"
        )
        if originals:
            warning += (
                "Unveränderte technische Originaldateien werden beigefügt. "
                "Diese können echte FINs, Namen und vertrauliche Entwicklungs-"
                "daten enthalten.\n\n"
            )
        warning += (
            "Es erfolgt KEIN Upload. Nur intern freigegeben übertragen. "
            "Lokales Clusterpaket jetzt erstellen?"
        )
        decision = QMessageBox.question(
            self, "Clusterpaket · Datenfreigabe", warning,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if decision != QMessageBox.StandardButton.Yes:
            return
        dest, _ = QFileDialog.getSaveFileName(
            self, "Zweiter ChatGPT-Durchlauf · Clusterkontext",
            str(Path.home() / "NTF_Clusterkontext_Durchlauf2.zip"),
            "Clusterpaket (*.zip)",
        )
        if not dest:
            return
        path = Path(dest)
        if path.suffix.lower() != ".zip":
            path = path.with_suffix(".zip")
        self._pending_cluster_context = (
            workflow.profile_id, workflow._context_part, package.paket_id,
        )
        worker = ClusterContextExportWorker(
            workflow.context_store, workflow.profile_id, workflow._context_part,
            package.path, path, include_originals=originals,
            first_result=first_result,
        )
        self._context_worker = worker
        workflow.set_context_busy(True)
        workflow.set_notice("Zweites Clusterpaket wird lokal erstellt …")
        worker.completed.connect(self._context_export_completed)
        worker.failed.connect(self._context_failed)
        worker.finished.connect(self._context_worker_finished)
        worker.start()

    def _context_export_completed(self, result: object) -> None:
        workflow = self.pages["workflow"]
        context = self._pending_cluster_context
        self._pending_cluster_context = None
        if context is None:
            workflow.set_notice("Clusterpaket erstellt, Projektbindung fehlt.", error=True)
            return
        try:
            workflow.ai_chain.register_second_export(
                context[0], context[1], result.parent_package_id,
                result.analysis_id,
            )
        except ValueError as exc:
            workflow.set_notice(
                "Clusterpaket erstellt, Rückimport-Kennung nicht gespeichert: "
                + str(exc), error=True,
            )
            return
        workflow.refresh_ai_chain()
        workflow.set_notice(
            f"2. KI-Paket erstellt: {result.path.name} · "
            f"{result.file_count} Unterlagen, "
            f"{result.included_files} Originale · "
            f"neue Analyse-ID {result.analysis_id}. "
            "Ergebnis-JSON später hier wieder importieren."
        )

    def _cluster_import(self) -> None:
        """Nur Antworten eines für dieses Projekt erzeugten 2. Pakets."""
        workflow = self.pages["workflow"]
        if not self._portable_transfer_ready():
            workflow.set_notice("Import/Export läuft noch.", error=True)
            return
        filename, _ = QFileDialog.getOpenFileName(
            self, "Zweites ChatGPT-Clusterergebnis auswählen",
            str(Path.home()), "ChatGPT Ergebnis (*.json)",
        )
        if not filename:
            return
        path = Path(filename)
        try:
            if not path.is_file() or path.stat().st_size > 16 * 1024 * 1024:
                raise ValueError("JSON-Datei fehlt oder ist zu groß.")
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            package_id = str(payload["paket_id"])
            analyse_id = str(payload["analyse_id"])
            package = workflow.ai_chain.latest_first_export(
                workflow.profile_id, workflow._context_part
            )
            if package is None or package.paket_id != package_id:
                raise ValueError("Falsche Paket-ID für das gewählte Projekt.")
            if not workflow.ai_chain.is_prepared_second(
                workflow.profile_id, workflow._context_part,
                package_id, analyse_id,
            ):
                raise ValueError(
                    "Diese Analyse-ID stammt nicht aus einem zweiten "
                    "Clusterpaket dieses Projekts."
                )
        except (OSError, ValueError, KeyError, TypeError) as exc:
            workflow.set_notice(
                "Zweites ChatGPT-Ergebnis nicht zuordenbar: " + str(exc),
                error=True,
            )
            return
        self._pending_ai_round = 2
        panel = self.pages["sources"].ki_analyse_panel
        if panel is not None:
            panel.import_from_path(path)

    def _context_remove(self) -> None:
        workflow = self.pages["workflow"]
        row_index = workflow.context_table.currentIndex().row()
        if row_index < 0 or row_index >= len(workflow.context_files):
            workflow.set_notice("Bitte eine Datei in der Tabelle markieren.")
            return
        item = workflow.context_files[row_index]
        answer = QMessageBox.question(
            self, "Zuordnung entfernen",
            "Unterlage nur aus dieser Sachnummern-Sammlung entfernen? "
            "Rohdaten und andere Zuordnungen bleiben erhalten.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        removed = workflow.context_store.remove_file(
            workflow.profile_id, workflow._context_part,
            item.category, item.sha256,
        )
        workflow.refresh_context_files()
        workflow.refresh()
        if removed:
            workflow.set_notice("Unterlagenzuordnung entfernt.")

    def _context_scrape(self, category: str, scope: str) -> None:
        """Vorhandene SSO-Downloader gezielt für die QEC-Sachnummernkohorte."""
        workflow = self.pages["workflow"]
        cases = self.pages["cases"]
        if category not in {"diagnosis_viewer", "tips_writer"}:
            workflow.set_notice(
                "Für TP Dashboard/Celonis ist noch kein Scraper implementiert. "
                "Die exportierte Datei bitte manuell importieren.",
                error=True,
            )
            return
        if scope == "cancel":
            self._context_scraper_failed.add(category)
            workflow.source_activity.record(
                workflow.profile_id, workflow._context_part, category,
                "Abgebrochen",
            )
            if category == "diagnosis_viewer":
                cases._cancel_quicktest_download()
            elif cases.tips_download is not None:
                cases.tips_download._cancel()
            return
        if scope not in {"all", "missing"}:
            workflow.set_notice("Unbekannte Abrufaktion.", error=True)
            return
        if not self._portable_transfer_ready() or self._context_worker is not None:
            workflow.set_notice("Ein Import oder Download läuft bereits.", error=True)
            return
        rows = workflow._scoped_rows
        raw_fins = sorted({str(row["fin"]).strip().upper() for row in rows})
        if scope == "missing":
            coverage = workflow._source_coverage.get(category)
            missing_fins = set(coverage.missing_fins) if coverage else set()
            raw_fins = [fin for fin in raw_fins if fin in missing_fins]
        fins: list[str] = []
        for fin in raw_fins:
            try:
                fins.extend(parse_fins(fin))
            except ValueError:
                continue
        fins = sorted(set(fins))
        if not fins:
            workflow.set_notice(
                "Keine gültigen FINs in der gewählten SSL-Endbefund-Auswahl.",
                error=True
            )
            return
        if scope == "all":
            answer = QMessageBox.question(
                self, "Alle FINs erneut abrufen?",
                f"Du startest für {len(fins)} FINs einen vollständigen erneuten "
                f"Abruf aus {category}. Das kann viel Zeit benötigen und "
                "zusätzliche Portalabfragen auslösen. Bereits vorhandene "
                "Dateien werden nicht absichtlich gelöscht.\n\n"
                "Stattdessen können auch nur fehlende FINs abgerufen werden. "
                "Vollständigen Neuabruf wirklich starten?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        if category == "diagnosis_viewer":
            cases._start_quicktest_download(
                selected_only=False, fins_override=fins,
                retry_missing=True,  # Beide expliziten Abrufe umgehen die 24h-Sperre.
            )
            worker = cases._quicktest_worker
            if worker is not None:
                self._workflow_quicktest_download_pending = True
        else:
            panel = cases.tips_download
            if panel is None:
                workflow.set_notice("TIPS-Writer-Abruf nicht verfügbar.", error=True)
                return
            panel._start(fins, bulk=True)
            worker = panel.worker
        if worker is None:
            # Nutzer hat SSO-/Mengenbestätigung abgebrochen.
            return
        self._context_scraper_failed.discard(category)
        workflow.source_activity.record(
            workflow.profile_id, workflow._context_part, category, "Gestartet",
        )
        workflow.set_context_scraper_busy(category, True, scope)
        workflow.refresh_context_files()
        workflow.set_notice(
            f"{category}: {len(fins)} FIN(s) werden mit dem vorhandenen "
            "SSO-Downloader abgerufen …"
        )
        worker.progress.connect(
            lambda message, c=category:
            workflow.set_context_operation(c, True, message)
        )
        worker.failed.connect(
            lambda msg, c=category: self._context_scraper_failed_notice(c, msg)
        )
        worker.finished.connect(
            lambda c=category: self._context_scraper_finished(c)
        )

    def _context_scraper_failed_notice(self, category: str, message: str) -> None:
        self._context_scraper_failed.add(category)
        workflow = self.pages["workflow"]
        workflow.source_activity.record(
            workflow.profile_id, workflow._context_part, category, "Fehlgeschlagen",
        )
        workflow.set_notice("Quellenabruf fehlgeschlagen: " + message, error=True)
        workflow.refresh_context_files()

    def _context_scraper_finished(self, category: str) -> None:
        workflow = self.pages["workflow"]
        workflow.set_context_scraper_busy(category, False)
        if category not in self._context_scraper_failed:
            workflow.source_activity.record(
                workflow.profile_id, workflow._context_part, category,
                "Abgeschlossen",
            )
        self._context_scraper_failed.discard(category)
        importing = False
        if category == "diagnosis_viewer":
            # Die vorhandene Downloadpipeline stößt ggf. einen Quellenimport an.
            importing = self.pages["sources"]._worker is not None
            if not importing:
                self._workflow_quicktest_download_pending = False
        workflow.refresh_data()
        if workflow._error_step is None:
            workflow.set_notice(
                "Download beendet. QuickTests werden jetzt ins Quellenarchiv "
                "übernommen …" if importing else
                "Quellenabruf abgeschlossen. Für die zweite Clusteranalyse "
                "danach ein aktuelles erstes KI-Analysepaket erzeugen."
            )

    def _workflow_action(self, action: str) -> None:
        workflow = self.pages["workflow"]
        source = self.pages["sources"]
        if action.startswith("parser_diagnostics:"):
            category = action.partition(":")[2]
            coverage = workflow._source_coverage.get(category)
            if coverage is None or not coverage.local_paths:
                workflow.set_notice(
                    "Keine verifizierten lokalen Unterlagen dieser Quelle vorhanden.",
                    error=True,
                )
                return
            source._export_parser_problems(
                category=category, scope_paths=coverage.local_paths,
            )
            return
        if action.startswith("context_files:"):
            self._context_import(action.partition(":")[2])
            return
        if action.startswith("context_parse_cancel:"):
            self._context_parse_cancel(action.partition(":")[2])
            return
        if action.startswith("context_parse_all:"):
            self._context_parse_all(action.partition(":")[2])
            return
        if action.startswith("context_parse_resume:"):
            self._resume_source_parsing(action.partition(":")[2])
            return
        if action == "qec_parse_resume":
            self._resume_source_parsing("qec")
            return
        if action.startswith("context_parse:"):
            self._context_parse(action.partition(":")[2])
            return
        if action.startswith("context_scrape:"):
            parts = action.split(":")
            if len(parts) == 3:
                self._context_scrape(parts[1], parts[2])
            return
        if action == "adopt_legacy":
            self._adopt_existing_qec()
            return
        if action in {"project_settings", "new_project"}:
            self._show_project_settings(new=action == "new_project")
            return
        if action == "cluster_export":
            self._context_export()
            return
        if action == "cluster_import":
            self._cluster_import()
            return
        if action == "context_remove":
            self._context_remove()
            return
        if action in {"qec_list_import", "qec_list_resume", "qec_import_local"}:
            self._workflow_start_import(action)
        elif action == "qec_list_cancel":
            if source.cancel_import_button.isEnabled():
                source.cancel_import_button.click()
                workflow.set_notice(
                    "QEC-Import wird nach der aktuellen Datei unterbrochen."
                )
        elif action == "qec_list_portal":
            if not QDesktopServices.openUrl(QUrl(QEC_START)):
                workflow.set_notice(
                    "QEC-Portal konnte nicht im Browser geöffnet werden.", error=True
                )
            else:
                workflow.set_notice(
                    "QEC-FIN-Liste im Portal nach Sachnummer filtern, "
                    "als Excel speichern und anschließend hier importieren. "
                    "Der direkte Sachnummer-Abruf ist noch nicht implementiert."
                )
        elif action == "qec_list_csv":
            if not workflow._scoped_rows or source.workflow_store is None:
                workflow.set_notice("Keine QEC-FINs zum Export vorhanden.", error=True)
                return
            part = workflow._context_part
            safe_part = "".join(
                char if char.isalnum() else "_" for char in part
            )[:36] or "alle"
            filename, _ = QFileDialog.getSaveFileName(
                self, "Gefilterte QEC-FIN-Liste lokal speichern",
                str(Path.home() / f"QEC_FIN_{safe_part}.csv"), "CSV (*.csv)",
            )
            if not filename:
                return
            dest = Path(filename)
            if dest.suffix.lower() != ".csv":
                dest = dest.with_suffix(".csv")
            try:
                count = source.workflow_store.export_csv(
                    dest, workflow.qec_root, part_number=part,
                    selected_fins={
                        str(row["fin"]).upper() for row in workflow._scoped_rows
                    },
                )
            except (OSError, ValueError) as exc:
                QMessageBox.warning(self, "QEC-FIN-Export", str(exc))
                return
            workflow.set_notice(
                f"{count} QEC-Fälle lokal exportiert. "
                "Die Datei enthält echte FINs: nur intern freigegeben weitergeben."
            )
        elif action in {
            "qec_download_all", "qec_download_selected", "qec_download_missing",
        }:
            self._workflow_start_qec_download(
                selected_only=action == "qec_download_selected",
                missing_only=action == "qec_download_missing",
            )
        elif action == "qec_download_cancel":
            panel = self.pages["cases"].qec_download
            if panel is not None and panel.cancel_button.isEnabled():
                panel.cancel_button.click()
                workflow.qec_status.setText("QEC-Abruf wird sicher angehalten …")
        elif action in {"ai_export", "ai_import"}:
            panel = source.ki_analyse_panel
            if panel is None:
                workflow.set_notice("ChatGPT-Austausch ist nicht verfügbar.", error=True)
                return
            if action == "ai_export":
                fins = {
                    str(row["fin"]).upper() for row in workflow._scoped_rows
                }
                if not fins:
                    workflow.set_notice(
                        "Keine FINs für den ersten ChatGPT-Export gewählt. "
                        "In Schritt 01 SSL-Endbefunde auswählen.",
                        error=True,
                    )
                    return
                panel.prepare_workflow_cohort(fins)
            if action == "ai_import":
                self._pending_ai_round = 1
            (panel.export_button if action == "ai_export" else panel.import_button).click()
        elif action == "project_export":
            self._project_transfer_export()
        elif action == "project_import":
            self._project_transfer_import()
        elif action == "self_import":
            self.navigation.select_page("sources")
            source.archive_button.click()

    def _workflow_step_busy(self, busy: bool) -> None:
        if busy:
            self._begin_loading("Workflow-Schritt wird geladen …")
        else:
            self._finish_loading()

    def _begin_loading(self, message: str) -> None:
        """Status vor teuren Seitenwechseln sichtbar machen."""
        self._loading_overlay.start(message)
        if self._project_dialog is None or not self._project_dialog.isVisible():
            effect = QGraphicsBlurEffect(self.stack)
            effect.setBlurRadius(5)
            self.stack.setGraphicsEffect(effect)
        QApplication.processEvents(
            QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents
        )

    def _finish_loading(self) -> None:
        self._loading_overlay.stop()
        if self._project_dialog is None or not self._project_dialog.isVisible():
            self.stack.setGraphicsEffect(None)

    def _show_project_settings(self, *, new: bool = False) -> None:
        """Projekteinstellungen als schwebende, modal bedienbare Projektkarte."""
        page = self.pages["project_settings"]
        workflow = self.pages["workflow"]
        project = workflow.project_store.get(
            workflow.profile_id, workflow._context_part,
        )
        page.select_project(workflow.profile_id, workflow._context_part)
        if new or project is None:
            page.start_new()
        if self._project_dialog is None:
            dialog = QDialog(self)
            dialog.setObjectName("ProjectSettingsDialog")
            dialog.setWindowTitle("Projekteinstellungen")
            dialog.setWindowFlags(
                Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint
            )
            dialog.setWindowModality(Qt.WindowModality.WindowModal)
            dialog.setMinimumSize(650, 545)
            dialog.resize(860, 690)
            dialog.setStyleSheet(
                "QDialog#ProjectSettingsDialog { background-color: "
                + ("#232c37" if self.navigation.theme_combo.currentData() == "dark"
                   else "#f4f6f9")
                + "; border: 1px solid #8799a9; border-radius: 12px; }"
            )
            frame = QVBoxLayout(dialog)
            frame.setContentsMargins(7, 7, 7, 7)
            frame.addWidget(page, 1)
            footer = QHBoxLayout()
            footer.addStretch(1)
            close = QPushButton("Schließen")
            close.clicked.connect(dialog.reject)
            footer.addWidget(close)
            frame.addLayout(footer)
            dialog.finished.connect(self._project_dialog_closed)
            self._project_dialog = dialog
        self._modal_shade.setGeometry(self.centralWidget().rect())
        self._modal_shade.raise_()
        self._modal_shade.show()
        effect = QGraphicsBlurEffect(self.stack)
        effect.setBlurRadius(7)
        self.stack.setGraphicsEffect(effect)
        dialog = self._project_dialog
        if dialog is not None:
            dialog.move(self.frameGeometry().center() - dialog.rect().center())
            dialog.open()

    def _project_dialog_closed(self, _code: int) -> None:
        self._modal_shade.hide()
        if not self._loading_overlay.isVisible():
            self.stack.setGraphicsEffect(None)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if hasattr(self, "_loading_overlay"):
            self._loading_overlay.setGeometry(self.centralWidget().rect())
            self._modal_shade.setGeometry(self.centralWidget().rect())

    def show_page(self, key: str) -> None:
        if key == "project_settings":
            self._show_project_settings()
            return
        page = self.pages.get(key)
        if page is None:
            return
        self.stack.setCurrentWidget(page)
        if key == "dashboard":
            self._begin_loading("Projektübersicht wird geladen …")
            if not page.refresh_async():
                self._finish_loading()
        elif key == "workflow":
            self._begin_loading("Workflowdaten werden geladen …")
            try:
                page.refresh_data()
            finally:
                self._finish_loading()
        elif key == "cases":
            self._begin_loading("FIN- und Diagnosebestände werden geladen …")
            try:
                page.cluster_workspace.refresh_review_priorities()
                page._refresh_quicktest_download_dates()
                page._refresh_qec_download_dates()
                page._refresh_local_tips_status()
                page._refresh_shared_credentials_status()
            finally:
                self._finish_loading()
        self.stack.setFocus(Qt.FocusReason.OtherFocusReason)
