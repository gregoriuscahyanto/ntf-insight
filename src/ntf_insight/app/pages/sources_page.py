"""Data-source readiness, drag/drop import, raw archive and provenance view."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTableView,
    QVBoxLayout,
    QScrollArea,
    QFrame,
    QWidget,
)

from ntf_insight.app.models.simple_table_model import SimpleTableModel
from ntf_insight.app.widgets.file_drop_zone import FileDropZone
from ntf_insight.app.widgets.qec_workflow_panel import QecWorkflowPanel
from ntf_insight.storage.qec_workflow_store import QecWorkflowStore
from ntf_insight.ingestion.qec_primary import active_qec_lists
from ntf_insight.ingestion.artifacts import ParseStatus, SourceType
from ntf_insight.ingestion.batch_import import ImportSummary, LocalBatchImporter
from ntf_insight.ingestion.source_detection import detect_source_type
from ntf_insight.ingestion.service import SourceImportService
from ntf_insight.storage.reference_repositories import ReferenceRepository
from ntf_insight.storage.repositories import CaseRepository
from ntf_insight.storage.quicktest_store import QuickTestStore
from ntf_insight.storage.source_knowledge_store import SourceKnowledgeStore


class _SourceImportWorker(QThread):
    imported = Signal(object)
    failed = Signal(str)
    progress = Signal(str)

    def __init__(
        self,
        sources: SourceImportService,
        paths: list[Path],
        forced_type: SourceType | None,
        source_system: str | None = None,
        vin_hint: str | None = None,
    ) -> None:
        super().__init__()
        self.sources = sources
        self.paths = paths
        self.forced_type = forced_type
        self.source_system = source_system
        self.vin_hint = vin_hint

    def run(self) -> None:
        try:
            summary = LocalBatchImporter(self.sources).import_paths(
                self.paths,
                on_progress=self.progress.emit,
                forced_source_type=self.forced_type,
                source_system=self.source_system,
                vin_hint=self.vin_hint,
            )
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")
            return
        self.imported.emit(summary)


class SourcesPage(QWidget):
    sources_updated = Signal(str, int)
    SOURCE_LABELS = {
        SourceType.VEHICLE_CASE_LIST: "QEC-Fall-/SSL-Endbefundliste",
        SourceType.SHORT_TEST: "Kurztest",
        SourceType.TP_DASHBOARD: "TP-Dashboard · CPC/SAM",
        SourceType.REPLACEMENT_LIST: "Tauschliste",
        SourceType.SUPPLIER_FINDING: "Lieferantenbefund",
        SourceType.WORKSHOP_HISTORY: "Werkstatt-/Claim-Historie",
        SourceType.SMR_D: "SMR-D",
        SourceType.DIAGNOSTIC_DESCRIPTION: "CDD-Diagnosebeschreibung",
        SourceType.PART_HISTORY: "Part History / Produktänderungen",
        SourceType.AUTOEXPORT_SUMMARY: "AutoExport-Zählwert",
        SourceType.TIPS_CASE: "AutoExport · TIPS-Fall",
        SourceType.HW_SW_CHANGE_HISTORY: "HW-/SW-Änderungshistorie",
        SourceType.VEHICLE_SOFTWARE_HISTORY: "Fahrzeug-SW-Historie",
        SourceType.INSTALLED_POPULATION: "Verbaute Population",
        SourceType.COMPONENT_MASTER_DATA: "Bauteil-/Lieferantenstammdaten",
        SourceType.OTHER: "Sonstiges",
    }

    def __init__(
        self,
        cases: CaseRepository,
        references: ReferenceRepository,
        mode: str = "demo",
        data_dir: str | None = None,
        raw_dir: str | None = None,
        database_path: str | None = None,
    ) -> None:
        super().__init__()
        self.cases = cases
        self.references = references
        self.mode = mode
        self._worker: _SourceImportWorker | None = None
        self._pending_reload = False
        self._quicktests_added = 0
        self.import_service = (
            SourceImportService(Path(raw_dir), Path(database_path))
            if raw_dir and database_path
            else None
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll)
        surface = QWidget()
        scroll.setWidget(surface)
        layout = QVBoxLayout(surface)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(14)

        layout.addWidget(QLabel("Datenquellen", objectName="PageTitle"))
        location = f" Lokales Datenverzeichnis: {data_dir}." if data_dir else ""
        subtitle = QLabel(
            "Originaldateien werden vor dem Parsen unverändert mit SHA-256-Provenienz archiviert. "
            "Dateien und ZIP-Pakete können per Drag & Drop importiert werden. "
            "Bekannte QEC-, AutoExport- und QuickTest-Formate werden lokal geparst. "
            f"Modus: {mode}.{location}",
            objectName="PageSubtitle",
        )
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        self.workflow_store = (
            QecWorkflowStore(self.import_service.store)
            if self.import_service is not None else None
        )
        self.qec_workflow = (
            QecWorkflowPanel(self.workflow_store, Path(data_dir))
            if self.workflow_store is not None and data_dir else None
        )
        if self.qec_workflow is not None:
            layout.addWidget(self.qec_workflow)
        self.active_qec_label = QLabel(objectName="PageSubtitle")
        self.active_qec_label.setWordWrap(True)
        layout.addWidget(self.active_qec_label)

        self.readiness_model = SimpleTableModel(
            ("Quelle", "Zweck", "Implementierung", "Aktuelle Daten")
        )
        readiness_table = QTableView()
        readiness_table.setModel(self.readiness_model)
        readiness_table.setMaximumHeight(285)
        readiness_table.setAlternatingRowColors(True)
        readiness_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        readiness_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        readiness_table.verticalHeader().setVisible(False)
        readiness_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(readiness_table)

        layout.addWidget(QLabel("Rohdatenarchiv", objectName="CardTitle"))
        controls = QHBoxLayout()
        self.source_type = QComboBox()
        self.source_type.setMinimumWidth(300)
        self.source_type.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        self.source_type.addItem("Automatisch erkennen (empfohlen)", None)
        for source_type, label in self.SOURCE_LABELS.items():
            self.source_type.addItem(label, source_type)
        controls.addWidget(self.source_type, 3)

        self.source_system = QLineEdit()
        self.source_system.setPlaceholderText("Quellsystem (optional)")
        self.source_system.setMinimumWidth(240)
        self.source_system.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        controls.addWidget(self.source_system, 2)

        self.vin_hint = QLineEdit()
        self.vin_hint.setPlaceholderText("FIN-/VIN-Hinweis (optional)")
        self.vin_hint.setMinimumWidth(260)
        self.vin_hint.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        controls.addWidget(self.vin_hint, 2)

        self.archive_button = QPushButton("Dateien auswählen…")
        self.archive_button.setMinimumWidth(210)
        self.archive_button.setSizePolicy(
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Fixed,
        )
        self.archive_button.setEnabled(self.import_service is not None)
        self.archive_button.clicked.connect(self._archive_file)
        controls.addWidget(self.archive_button)
        layout.addLayout(controls)

        self.drop_zone = FileDropZone()
        self.drop_zone.setEnabled(self.import_service is not None)
        self.drop_zone.files_dropped.connect(self._archive_paths)
        layout.addWidget(self.drop_zone)

        self.import_status = QLabel(
            "ZIP oder Dateien hineinziehen. Unterstützte Formate werden archiviert, "
            "geparst und bei eindeutiger FIN/Fall-Zuordnung übernommen. "
            "CDD, Part History, QEC und AutoExport werden als durchsuchbare Daten gespeichert; "
            "nicht unterstützte Dateien bleiben im Rohdatenarchiv.",
            objectName="PageSubtitle",
        )
        self.import_status.setWordWrap(True)
        layout.addWidget(self.import_status)

        self.archive_empty = QLabel(
            "Noch keine Originaldateien archiviert.\n"
            "Die Demo-Fälle sind interne Test-Fixtures und erscheinen bewusst nicht im Rohdatenarchiv.",
            objectName="EmptyState",
        )
        self.archive_empty.setWordWrap(True)
        layout.addWidget(self.archive_empty)

        archive_controls = QHBoxLayout()
        archive_controls.addWidget(QLabel("Archivansicht"))
        self.archive_view = QComboBox()
        self.archive_view.addItem("Verarbeitete Dateien", "processed")
        self.archive_view.addItem("Alle archivierten Dateien", "all")
        self.archive_view.addItem("Noch nicht verarbeitet / Fehler", "pending")
        self.archive_view.setMinimumWidth(270)
        self.archive_view.currentIndexChanged.connect(self._refresh_all)
        archive_controls.addWidget(self.archive_view)
        self.archive_counts = QLabel(objectName="PageSubtitle")
        archive_controls.addWidget(self.archive_counts, 1)
        self.retry_button = QPushButton("Markierte Datei neu prüfen…")
        self.retry_button.setToolTip(
            "Eine bereits archivierte Datei erneut erkennen und parsen. "
            "Die Originaldatei wird nicht gelöscht oder verändert."
        )
        self.retry_button.setEnabled(False)
        self.retry_button.clicked.connect(self._retry_archived)
        archive_controls.addWidget(self.retry_button)
        self.delete_button = QPushButton("Markierte Datei löschen…")
        self.delete_button.setEnabled(False)
        self.delete_button.setToolTip(
            "Original und zugehörige importierte Datensätze lokal löschen. "
            "QEC-Fälle mit manuellen Änderungen sind geschützt."
        )
        self.delete_button.clicked.connect(self._delete_archived)
        archive_controls.addWidget(self.delete_button)
        layout.addLayout(archive_controls)
        self._visible_artifacts = []

        self.artifact_model = SimpleTableModel(
            (
                "Datei",
                "Quelltyp",
                "System",
                "FIN-/VIN-Hinweis",
                "Größe",
                "SHA-256",
                "Parse-Status",
                "Importiert",
            )
        )
        self.artifact_table = QTableView()
        self.artifact_table.setModel(self.artifact_model)
        self.artifact_table.clicked.connect(self._artifact_selected)
        self.artifact_table.selectionModel().currentRowChanged.connect(
            lambda current, _previous: self._artifact_selected(current)
        )
        self.artifact_table.setAlternatingRowColors(True)
        self.artifact_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.artifact_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.artifact_table.verticalHeader().setVisible(False)
        self.artifact_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.artifact_table, 1)

        self._refresh_all()

    def _archive_file(self) -> None:
        if self.import_service is None:
            return
        filenames, _ = QFileDialog.getOpenFileNames(self, "Quelldateien archivieren")
        if filenames:
            self._archive_paths([Path(filename) for filename in filenames])

    def _artifact_selected(self, index) -> None:
        self.delete_button.setEnabled(
            self.import_service is not None and self._worker is None
            and index.isValid() and 0 <= index.row() < len(self._visible_artifacts)
        )
        self.retry_button.setEnabled(
            self.import_service is not None
            and self._worker is None
            and index.isValid()
            and 0 <= index.row() < len(self._visible_artifacts)
        )

    def _delete_archived(self) -> None:
        index = self.artifact_table.currentIndex()
        if self.import_service is None or self._worker is not None:
            return
        if not index.isValid() or index.row() >= len(self._visible_artifacts):
            return
        artifact = self._visible_artifacts[index.row()]
        answer = QMessageBox.question(
            self, "Quelldatei löschen?",
            f"'{artifact.original_name}' samt zugehörigen importierten Daten "
            "unwiderruflich aus dem lokalen Archiv entfernen? "
            "Manuelle QEC-Änderungen sind geschützt."
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.import_service.delete_artifact(artifact.sha256)
        except (OSError, ValueError, RuntimeError) as exc:
            QMessageBox.warning(self, "Löschen nicht möglich", str(exc))
            return
        self.import_status.setText(
            "Quelldatei gelöscht. Zugehörige Quellen-Daten wurden bereinigt. "
            "Ansichten werden neu geladen."
        )
        self._refresh_all()
        self.sources_updated.emit(self.import_status.text(), 0)

    def _retry_archived(self) -> None:
        """Re-parse an original source already in the local immutable archive."""
        index = self.artifact_table.currentIndex()
        if not index.isValid() or index.row() >= len(self._visible_artifacts):
            return
        artifact = self._visible_artifacts[index.row()]
        path = Path(artifact.archived_path)
        if not path.is_file():
            QMessageBox.warning(
                self, "Originaldatei nicht gefunden",
                "Die archivierte Quelldatei existiert nicht mehr. "
                "Bitte das Original erneut importieren.",
            )
            return
        if self.source_type.currentData() is not None:
            decision = QMessageBox.question(
                self, "Quellenart überschreiben?",
                "Die ausgewählte Quellenart wird für diese Datei verwendet. "
                "Möchtest du sie damit neu prüfen? "
                "Für die automatische Erkennung bitte vorher "
                "»Automatisch erkennen« auswählen.",
            )
            if decision != QMessageBox.StandardButton.Yes:
                return
        self._archive_paths([path])

    def _source_type_for_path(self, path: Path) -> SourceType:
        selected = self.source_type.currentData()
        if isinstance(selected, SourceType):
            return selected
        return detect_source_type(path)

    def _archive_paths(self, paths: list[Path]) -> None:
        if self.import_service is None or not paths or self._worker is not None:
            return

        forced = self.source_type.currentData()
        forced_type = forced if isinstance(forced, SourceType) else None
        self.archive_button.setEnabled(False)
        self.drop_zone.setEnabled(False)
        self.retry_button.setEnabled(False)
        self.delete_button.setEnabled(False)
        self.import_status.setText(
            f"{len(paths)} Datei(en)/ZIP-Paket(e) werden lokal geprüft und importiert …"
        )
        self._pending_reload = False
        self._quicktests_added = 0
        self._worker = _SourceImportWorker(
            self.import_service,
            [Path(path) for path in paths],
            forced_type,
            self.source_system.text().strip() or None,
            self.vin_hint.text().strip() or None,
        )
        self._worker.progress.connect(self.import_status.setText)
        self._worker.imported.connect(self._import_completed)
        self._worker.failed.connect(self._import_failed)
        self._worker.finished.connect(self._import_worker_finished)
        self._worker.start()

    def _import_completed(self, summary: ImportSummary) -> None:
        text = (
            f"Import: {summary.files_archived} neue Originaldateien, "
            f"{summary.files_parsed} geparst, {summary.files_pending} noch ohne Parser · "
            f"{summary.cases_created} neue Fälle, "
            f"{summary.qec_findings_linked} QEC-Fälle mit SSL-Endbefunden ergänzt, "
            f"{summary.qec_findings_conflicted} Referenzkonflikte, "
            f"{summary.quicktests_saved} QuickTest(s) dauerhaft nach FIN gespeichert, "
            f"{summary.fin_zips_imported} FIN-ZIP(s) übertragen, "
            f"{summary.fin_files_installed} neue QuickTest-/QEC-/TIPS-Dateien, "
            f"{summary.fin_file_conflicts} unveränderte Konfliktdateien · "
            f"{summary.events_linked} zugeordnete Ereignisse · "
            f"{summary.events_unassigned} Ereignisse ohne eindeutige QEC-Zuordnung · "
            f"{summary.rows_scanned} gepruefte CSV-Zeilen, "
            f"{summary.rows_skipped} nicht fallbezogen verwendbar "
            f"({summary.rows_invalid} ungueltig) · "
            f"{summary.tips_linked} TIPS verknuepft, "
            f"{summary.tips_unassigned} TIPS ohne eindeutigen QEC-Fall · "
            f"{summary.reference_sources} Referenzquellen, "
            f"{summary.reference_rows} strukturierte Quellzeilen"
        )
        if summary.issues:
            text += (
                f" · {len(summary.issues)} Hinweise (z. B. "
                + "; ".join(summary.issues[:2])
                + ")"
            )
        self.import_status.setText(text)
        self._quicktests_added = summary.quicktests_saved
        self._pending_reload = bool(
            summary.cases_created or summary.events_linked or summary.quicktests_saved
            or summary.reference_sources or summary.qec_findings_linked
            or summary.fin_files_installed
        )
        self._refresh_all()

    def _import_failed(self, message: str) -> None:
        self.import_status.setText(
            "Import abgebrochen: " + message
            + " · Bereits archivierte Originaldateien bleiben erhalten."
        )
        self._refresh_all()

    def _import_worker_finished(self) -> None:
        self.archive_button.setEnabled(self.import_service is not None)
        self.drop_zone.setEnabled(self.import_service is not None)
        worker = self._worker
        self._worker = None
        if worker is not None:
            worker.deleteLater()
        self._refresh_all()
        if self._pending_reload:
            self.sources_updated.emit(self.import_status.text(), self._quicktests_added)

    def _artifacts(self):
        if self.import_service is None:
            return []
        return self.import_service.list_artifacts()

    def _refresh_all(self) -> None:
        artifacts = self._artifacts()
        self._refresh_artifacts(artifacts)
        self._refresh_readiness(artifacts)
        active = active_qec_lists(artifacts)
        if len(active) == 1:
            self.active_qec_label.setText(
                f"Aktuell verwendete QEC-FIN-Liste: {active[0].original_name}"
            )
        elif active:
            self.active_qec_label.setText(
                f"Achtung: {len(active)} primäre QEC-Listen im Altbestand. "
                "Bitte die Datenbereinigung durchführen."
            )
        else:
            self.active_qec_label.setText("Aktuell keine QEC-FIN-Liste aktiv.")
        if self.qec_workflow is not None:
            self.qec_workflow.refresh()

    def _refresh_artifacts(self, artifacts) -> None:
        view = self.archive_view.currentData()
        rows = []
        self._visible_artifacts = []
        processed = 0
        pending = 0
        for artifact in artifacts:
            runs = self.import_service.store.load_parse_runs(
                artifact.sha256
            ) if self.import_service else []
            latest = max(
                runs, key=lambda run: run.completed_at or run.started_at,
                default=None,
            )
            is_processed = bool(
                latest is not None
                and latest.status in {ParseStatus.SUCCESS, ParseStatus.PARTIAL}
            )
            if is_processed:
                processed += 1
            else:
                pending += 1

            if view == "processed" and not is_processed:
                continue
            if view == "pending" and is_processed:
                continue
            status = (
                f"{latest.status} · {latest.parser_name} {latest.parser_version}"
                if latest is not None else "Nicht geparst"
            )
            self._visible_artifacts.append(artifact)
            rows.append(
                (
                    artifact.original_name,
                    self.SOURCE_LABELS.get(
                        artifact.source_type, str(artifact.source_type)
                    ),
                    artifact.source_system,
                    artifact.vin_hint,
                    f"{artifact.size_bytes:,} B",
                    artifact.sha256,
                    status,
                    artifact.imported_at.astimezone().strftime("%Y-%m-%d %H:%M"),
                )
            )
        self.artifact_model.set_rows(rows)
        self.retry_button.setEnabled(False)
        self.delete_button.setEnabled(False)
        self.archive_counts.setText(
            f"{processed} verarbeitet · {pending} weitere im Rohdatenarchiv. "
            "Nicht angezeigte Originale bleiben erhalten."
        )
        self.artifact_table.setVisible(bool(rows))
        self.archive_empty.setVisible(not rows)
        if not rows:
            self.archive_empty.setText(
                "Keine Dateien in dieser Ansicht. "
                "Über »Alle archivierten Dateien« sind auch alte oder "
                "nicht erkannte Originale erreichbar."
            )

    def _refresh_readiness(self, artifacts) -> None:
        counts = Counter(artifact.source_type for artifact in artifacts)
        all_cases = self.cases.list_cases()
        case_count = len(all_cases)
        quicktest_store = (
            QuickTestStore(self.import_service.store)
            if self.import_service is not None else None
        )
        qt_statistics = (
            quicktest_store.statistics()
            if quicktest_store is not None
            else {"reports": 0, "ecus": 0, "dtcs": 0, "parameters": 0}
        )
        quicktest_fin_count = (
            len(quicktest_store.list_fins())
            if quicktest_store is not None else 0
        )
        knowledge_counts = (
            SourceKnowledgeStore(self.import_service.store).summary()
            if self.import_service is not None else {}
        )
        repair_count = sum(len(case.repairs) for case in all_cases)
        linked_tips_count = sum(
            len(case.tips_observations) for case in all_cases
        )
        raw_tips_count = (
            SourceKnowledgeStore(self.import_service.store).count_rows(
                "autoexport_tips"
            ) if self.import_service is not None else 0
        )
        trigger_count = len(self.references.list_triggers())
        change_count = len(self.references.list_changes())

        def current(source_type: SourceType, fallback: str) -> str:
            archived = counts[source_type]
            if archived:
                suffix = "Datei" if archived == 1 else "Dateien"
                return f"{archived} {suffix} archiviert"
            return fallback

        demo_case = (
            f"{case_count} Demo-Fälle (intern)"
            if self.mode == "demo"
            else f"{case_count} QEC-/NTF-Fälle · "
                 f"{quicktest_fin_count} FIN mit QuickTests"
        )
        demo_triggers = (
            f"{trigger_count} Demo-Definitionen (intern)"
            if self.mode == "demo"
            else f"{trigger_count} Definitionen"
        )
        demo_changes = (
            f"{change_count} Demo-Änderung(en) (intern)"
            if self.mode == "demo"
            else f"{change_count} Änderung(en)"
        )

        rows = [
            (
                "CDD-Diagnosebeschreibung",
                "Candela-Steuergerätebeschreibung, keine SMR-D-Triggerlogik",
                "Candela-Diagnoseservices extrahiert; keine SMR-D-Trigger",
                f"{knowledge_counts.get('candela_services', 0)} Services in DuckDB",
            ),
            (
                "Part History",
                "Bauteilbezogene Revisions- und Fertigungsänderungen",
                "PDF-Historienparser bereit; globale Produktinformation",
                f"{knowledge_counts.get('part_history', 0)} Änderungen in DuckDB",
            ),
            (
                "AutoExport-Gesamtdaten",
                "DTC-/Werkstattzeilen auch ohne QEC-Fall",
                "CSV-Rohfelder und FIN-Bezug in DuckDB",
                f"{knowledge_counts.get('autoexport_rows', 0)} Zeilen gespeichert",
            ),
            (
                "TIPS-Fallberichte",
                "Initiale Kundenbeanstandung, Befund und Maßnahmen je FIN",
                "Alle Rohzeilen lokal; nur eindeutige zeitliche QEC-Zuordnung",
                f"{raw_tips_count} Quellzeilen · {linked_tips_count} mit Fall verbunden",
            ),
            (
                "Fall-/FIN-Liste",
                "Fallumfang und Fahrzeugidentität",
                "QEC-Fallparser + alle Excel-Blätter/Spalten",
                (
                    f"{counts[SourceType.VEHICLE_CASE_LIST]} Datei(en) · "
                    f"{case_count} Fälle · {knowledge_counts.get('qec_details', 0)} Quellzeilen"
                    if counts[SourceType.VEHICLE_CASE_LIST]
                    else demo_case
                ),
            ),
            (
                "Kurztests",
                "Diagnosesitzungen, DTCs, Steuergeräte-Stände",
                "PDF-QuickTest und AutoExport-CSV Parser bereit",
                (
                    f"{counts[SourceType.SHORT_TEST]} Datei(en) · "
                    f"{qt_statistics['reports']} FIN-QuickTests · "
                    f"{qt_statistics['ecus']} ECU-Stände · "
                    f"{qt_statistics['dtcs']} DTCs · "
                    f"{qt_statistics['parameters']} Snapshot-Parameter"
                    if counts[SourceType.SHORT_TEST]
                    else "Keine Originaldatei"
                ),
            ),
            (
                "Tauschliste",
                "Vorher-/Nachher-Anker, Bauteilmetadaten",
                "Schnittstelle bereit; konkretes Format ausstehend",
                current(SourceType.REPLACEMENT_LIST, "Keine Originaldatei"),
            ),
            (
                "Lieferantenbefunde",
                "Rückläuferbefund / NTF-Evidenz",
                "PDF-Analysebericht: lokaler Seitentext, kein automatisches NTF",
                f"{knowledge_counts.get('supplier_analysis_document', 0)} Seiten in DuckDB",
            ),
            (
                "SMR-D",
                "DTC-Trigger-, Freigabe- und Healing-Logik",
                "Schnittstelle bereit; konkretes Format ausstehend",
                current(SourceType.SMR_D, demo_triggers),
            ),
            (
                "HW-/SW-Änderungshistorie",
                "Release-Änderungen und betroffene DTCs/Funktionen",
                "Schnittstelle bereit; konkretes Format ausstehend",
                current(SourceType.HW_SW_CHANGE_HISTORY, demo_changes),
            ),
            (
                "Fahrzeug-HW-/SW-Stand",
                "Tatsächlicher Steuergeräte-Stand je FIN/Kurztest",
                "Kanonisches Modell bereit",
                current(SourceType.VEHICLE_SOFTWARE_HISTORY, "Keine Originaldatei"),
            ),
            (
                "Werkstatt-/Claim-Historie",
                "Beanstandung, Diagnose und Maßnahmen",
                "AutoExport-CSV Parser bereit",
                (
                    f"{counts[SourceType.WORKSHOP_HISTORY]} Datei(en) · "
                    f"{repair_count} Werkstatteinträge"
                    if counts[SourceType.WORKSHOP_HISTORY]
                    else "Keine Originaldatei"
                ),
            ),
            (
                "Verbaute Population",
                "Nenner für Lieferanten-/Bauteilraten",
                "Kanonisches Modell bereit",
                current(SourceType.INSTALLED_POPULATION, "Keine Originaldatei"),
            ),
        ]
        self.readiness_model.set_rows(rows)
