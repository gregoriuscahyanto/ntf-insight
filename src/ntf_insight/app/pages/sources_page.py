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
    QPushButton,
    QSizePolicy,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ntf_insight.app.models.simple_table_model import SimpleTableModel
from ntf_insight.app.widgets.file_drop_zone import FileDropZone
from ntf_insight.ingestion.artifacts import SourceType
from ntf_insight.ingestion.batch_import import ImportSummary, LocalBatchImporter
from ntf_insight.ingestion.source_detection import detect_source_type
from ntf_insight.ingestion.service import SourceImportService
from ntf_insight.storage.reference_repositories import ReferenceRepository
from ntf_insight.storage.repositories import CaseRepository


class _SourceImportWorker(QThread):
    imported = Signal(object)
    failed = Signal(str)
    progress = Signal(str)

    def __init__(
        self,
        sources: SourceImportService,
        paths: list[Path],
        forced_type: SourceType | None,
    ) -> None:
        super().__init__()
        self.sources = sources
        self.paths = paths
        self.forced_type = forced_type

    def run(self) -> None:
        try:
            summary = LocalBatchImporter(self.sources).import_paths(
                self.paths,
                on_progress=self.progress.emit,
                forced_source_type=self.forced_type,
            )
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")
            return
        self.imported.emit(summary)


class SourcesPage(QWidget):
    sources_updated = Signal()
    SOURCE_LABELS = {
        SourceType.VEHICLE_CASE_LIST: "Fall-/FIN-Liste",
        SourceType.SHORT_TEST: "Kurztest",
        SourceType.REPLACEMENT_LIST: "Tauschliste",
        SourceType.SUPPLIER_FINDING: "Lieferantenbefund",
        SourceType.WORKSHOP_HISTORY: "Werkstatt-/Claim-Historie",
        SourceType.SMR_D: "SMR-D",
        SourceType.DIAGNOSTIC_DESCRIPTION: "CDD-Diagnosebeschreibung",
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
        self.import_service = (
            SourceImportService(Path(raw_dir), Path(database_path))
            if raw_dir and database_path
            else None
        )

        layout = QVBoxLayout(self)
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
            "CDD, SMR-D und unbekannte PDFs bleiben vorerst im Rohdatenarchiv.",
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
        self.import_status.setText(
            f"{len(paths)} Datei(en)/ZIP-Paket(e) werden lokal geprüft und importiert …"
        )
        self._pending_reload = False
        self._worker = _SourceImportWorker(
            self.import_service, [Path(path) for path in paths], forced_type
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
            f"{summary.events_linked} zugeordnete Ereignisse"
        )
        if summary.issues:
            text += (
                f" · {len(summary.issues)} Hinweise (z. B. "
                + "; ".join(summary.issues[:2])
                + ")"
            )
        self.import_status.setText(text)
        self._pending_reload = bool(summary.cases_created or summary.events_linked)
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
        if self._pending_reload:
            self.sources_updated.emit()

    def _artifacts(self):
        if self.import_service is None:
            return []
        return self.import_service.list_artifacts()

    def _refresh_all(self) -> None:
        artifacts = self._artifacts()
        self._refresh_artifacts(artifacts)
        self._refresh_readiness(artifacts)

    def _refresh_artifacts(self, artifacts) -> None:
        rows = []
        for artifact in artifacts:
            runs = self.import_service.store.load_parse_runs(artifact.sha256) if self.import_service else []
            latest = runs[-1] if runs else None
            parse_status = (
                f"{latest.status} · {latest.parser_name} {latest.parser_version}"
                if latest is not None
                else "Nicht geparst"
            )
            rows.append(
                (
                    artifact.original_name,
                    self.SOURCE_LABELS.get(artifact.source_type, str(artifact.source_type)),
                    artifact.source_system,
                    artifact.vin_hint,
                    f"{artifact.size_bytes:,} B",
                    artifact.sha256,
                    parse_status,
                    artifact.imported_at.astimezone().strftime("%Y-%m-%d %H:%M"),
                )
            )
        self.artifact_model.set_rows(rows)
        has_artifacts = bool(rows)
        self.artifact_table.setVisible(has_artifacts)
        self.archive_empty.setVisible(not has_artifacts)

    def _refresh_readiness(self, artifacts) -> None:
        counts = Counter(artifact.source_type for artifact in artifacts)
        case_count = len(self.cases.list_cases())
        trigger_count = len(self.references.list_triggers())
        change_count = len(self.references.list_changes())

        def current(source_type: SourceType, fallback: str) -> str:
            archived = counts[source_type]
            if archived:
                suffix = "Datei" if archived == 1 else "Dateien"
                return f"{archived} {suffix} archiviert"
            return fallback

        demo_case = f"{case_count} Demo-Fälle (intern)" if self.mode == "demo" else f"{case_count} Fälle"
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
                "Sichere Archivierung; Semantikparser ausstehend",
                current(SourceType.DIAGNOSTIC_DESCRIPTION, "Keine Originaldatei"),
            ),
            (
                "Fall-/FIN-Liste",
                "Fallumfang und Fahrzeugidentität",
                "QEC-Excel-Parser bereit",
                current(SourceType.VEHICLE_CASE_LIST, demo_case),
            ),
            (
                "Kurztests",
                "Diagnosesitzungen, DTCs, Steuergeräte-Stände",
                "PDF-QuickTest und AutoExport-CSV Parser bereit",
                current(SourceType.SHORT_TEST, "Keine Originaldatei"),
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
                "Schnittstelle bereit; konkretes Format ausstehend",
                current(SourceType.SUPPLIER_FINDING, "Keine Originaldatei"),
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
                current(SourceType.WORKSHOP_HISTORY, "Keine Originaldatei"),
            ),
            (
                "Verbaute Population",
                "Nenner für Lieferanten-/Bauteilraten",
                "Kanonisches Modell bereit",
                current(SourceType.INSTALLED_POPULATION, "Keine Originaldatei"),
            ),
        ]
        self.readiness_model.set_rows(rows)
