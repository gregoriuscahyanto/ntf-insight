"""Data-source readiness, drag/drop import, raw archive and provenance view."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ntf_insight.app.models.simple_table_model import SimpleTableModel
from ntf_insight.app.widgets.file_drop_zone import FileDropZone
from ntf_insight.ingestion.artifacts import SourceType
from ntf_insight.ingestion.service import SourceImportService
from ntf_insight.storage.reference_repositories import ReferenceRepository
from ntf_insight.storage.repositories import CaseRepository


class SourcesPage(QWidget):
    SOURCE_LABELS = {
        SourceType.VEHICLE_CASE_LIST: "Fall-/FIN-Liste",
        SourceType.SHORT_TEST: "Kurztest",
        SourceType.REPLACEMENT_LIST: "Tauschliste",
        SourceType.SUPPLIER_FINDING: "Lieferantenbefund",
        SourceType.WORKSHOP_HISTORY: "Werkstatt-/Claim-Historie",
        SourceType.SMR_D: "SMR-D",
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
            "Drag & Drop und Mehrfachauswahl sind möglich. "
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
        for source_type, label in self.SOURCE_LABELS.items():
            self.source_type.addItem(label, source_type)
        controls.addWidget(self.source_type)

        self.source_system = QLineEdit()
        self.source_system.setPlaceholderText("Quellsystem (optional)")
        self.source_system.setMaximumWidth(190)
        controls.addWidget(self.source_system)

        self.vin_hint = QLineEdit()
        self.vin_hint.setPlaceholderText("FIN-/VIN-Hinweis (optional)")
        self.vin_hint.setMaximumWidth(210)
        controls.addWidget(self.vin_hint)

        self.archive_button = QPushButton("Dateien auswählen…")
        self.archive_button.setEnabled(self.import_service is not None)
        self.archive_button.clicked.connect(self._archive_file)
        controls.addWidget(self.archive_button)
        controls.addStretch(1)
        layout.addLayout(controls)

        self.drop_zone = FileDropZone()
        self.drop_zone.setEnabled(self.import_service is not None)
        self.drop_zone.files_dropped.connect(self._archive_paths)
        layout.addWidget(self.drop_zone)

        self.import_status = QLabel(
            "Die Datei wird zunächst nur unverändert archiviert; Parsen und Fallzuordnung folgen "
            "sobald ein passender Parser verfügbar ist.",
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
        if path.name.casefold().endswith(".smr-d"):
            return SourceType.SMR_D
        selected = self.source_type.currentData()
        return selected if isinstance(selected, SourceType) else SourceType.OTHER

    def _archive_paths(self, paths: list[Path]) -> None:
        if self.import_service is None or not paths:
            return

        archived = []
        errors: list[str] = []
        source_system = self.source_system.text().strip() or None
        vin_hint = self.vin_hint.text().strip() or None

        for path in paths:
            try:
                artifact = self.import_service.import_raw(
                    Path(path),
                    self._source_type_for_path(Path(path)),
                    source_system=source_system,
                    vin_hint=vin_hint,
                )
                archived.append(artifact)
            except Exception as exc:  # GUI boundary: collect errors and keep importing.
                errors.append(f"{Path(path).name}: {exc}")

        if archived and not errors:
            total_bytes = sum(item.size_bytes for item in archived)
            self.import_status.setText(
                f"{len(archived)} Datei(en) archiviert · {total_bytes:,} B · Parse-Status: nicht geparst."
            )
        elif archived:
            self.import_status.setText(
                f"{len(archived)} Datei(en) archiviert, {len(errors)} Fehler: "
                + " | ".join(errors[:3])
            )
        else:
            self.import_status.setText("Import fehlgeschlagen: " + " | ".join(errors[:3]))

        self._refresh_all()

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
                "Fall-/FIN-Liste",
                "Fallumfang und Fahrzeugidentität",
                "Kanonisches Modell bereit",
                current(SourceType.VEHICLE_CASE_LIST, demo_case),
            ),
            (
                "Kurztests",
                "Diagnosesitzungen, DTCs, Steuergeräte-Stände",
                "Schnittstelle bereit; konkretes Format ausstehend",
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
                "Schnittstelle bereit; konkretes Format ausstehend",
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
