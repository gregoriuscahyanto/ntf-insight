"""Projektseite: Bauteilprofil, Sachnummer und wichtige Steuergeräte editieren."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPlainTextEdit, QPushButton, QVBoxLayout, QWidget,
)

from ntf_insight.components.registry import list_component_profiles
from ntf_insight.storage.workflow_projects import NTFProject, WorkflowProjectStore


def _component_label(profile_id: str) -> str:
    profiles = {
        "coolant_pump": "Kühlmittelpumpe",
        "hv_battery": "HV-Batterie",
    }
    return profiles.get(profile_id, profile_id.replace("_", " ").title())


class ProjectSettingsPage(QWidget):
    """Neue Sachnummer erzeugt ein eigenes Projekt, nicht eine neue globale DB."""

    project_selected = Signal(str, str)

    def __init__(self, projects: WorkflowProjectStore) -> None:
        super().__init__(objectName="ProjectSettingsPage")
        self.projects = projects
        self._is_new = False
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(12)
        outer.addWidget(QLabel("Projekteinstellungen", objectName="PageTitle"))
        outer.addWidget(QLabel(
            "Bauteil und Sachnummer legen die Projektkohorte fest. "
            "Wichtige Steuergeräte sind frei editierbar und werden nicht "
            "automatisch als verursachende Steuergeräte bewertet.",
            objectName="PageSubtitle",
        ))
        selectors = QHBoxLayout()
        self.project_selector = QComboBox()
        self.project_selector.setAccessibleName("Vorhandenes Projekt")
        self.project_selector.currentIndexChanged.connect(self._load_selection)
        selectors.addWidget(self.project_selector, 1)
        self.create_button = QPushButton("+ Neues Projekt")
        self.create_button.clicked.connect(self.start_new)
        selectors.addWidget(self.create_button)
        outer.addLayout(selectors)

        form = QFormLayout()
        self.profile_combo = QComboBox()
        for profile in list_component_profiles():
            self.profile_combo.addItem(_component_label(profile.profile_id), profile.profile_id)
        self.profile_combo.currentIndexChanged.connect(self._set_default_component)
        form.addRow("Bauteilprofil", self.profile_combo)
        self.part_edit = QLineEdit()
        self.part_edit.setMaxLength(120)
        self.part_edit.setPlaceholderText("z. B. A 123 456 78 90")
        form.addRow("Sachnummer", self.part_edit)
        self.component_edit = QLineEdit()
        self.component_edit.setMaxLength(100)
        form.addRow("Bauteilbezeichnung", self.component_edit)
        self.ecus_edit = QPlainTextEdit()
        self.ecus_edit.setMaximumHeight(130)
        self.ecus_edit.setPlaceholderText("Je Zeile ein relevantes Steuergerät, z. B. CPC3")
        form.addRow("Wichtige Steuergeräte", self.ecus_edit)
        self.description_edit = QPlainTextEdit()
        self.description_edit.setMaximumHeight(100)
        self.description_edit.setPlaceholderText("Optional: Untersuchungsumfang, Besonderheiten")
        form.addRow("Projektbeschreibung", self.description_edit)
        outer.addLayout(form)

        buttons = QHBoxLayout()
        self.save_button = QPushButton("Projekt speichern")
        self.save_button.setObjectName("ClusterStartButton")
        self.save_button.clicked.connect(self._save_project)
        buttons.addWidget(self.save_button)
        self.open_button = QPushButton("Workflow öffnen")
        self.open_button.clicked.connect(self._open_project)
        buttons.addWidget(self.open_button)
        buttons.addStretch(1)
        outer.addLayout(buttons)
        self.status = QLabel(objectName="PageSubtitle")
        self.status.setWordWrap(True)
        outer.addWidget(self.status)
        outer.addStretch(1)
        self.refresh_projects()

    def refresh_projects(self, *, select: tuple[str, str] | None = None) -> None:
        current = select or self.project_selector.currentData()
        self.project_selector.blockSignals(True)
        self.project_selector.clear()
        for project in self.projects.list_projects():
            self.project_selector.addItem(
                project.title, (project.profile_id, project.part_number),
            )
        if current is not None:
            idx = self.project_selector.findData(current)
            if idx >= 0:
                self.project_selector.setCurrentIndex(idx)
        self.project_selector.blockSignals(False)
        if not self._is_new:
            self._load_selection()

    def _set_default_component(self) -> None:
        if self._is_new:
            self.component_edit.setText(
                _component_label(str(self.profile_combo.currentData() or "coolant_pump"))
            )

    def _load_selection(self, *_args) -> None:
        selected = self.project_selector.currentData()
        if selected is None:
            return
        project = self.projects.get(selected[0], selected[1])
        if project is None:
            return
        self._is_new = False
        index = self.profile_combo.findData(project.profile_id)
        if index >= 0:
            self.profile_combo.setCurrentIndex(index)
        self.profile_combo.setEnabled(False)
        self.part_edit.setText(project.part_number)
        self.part_edit.setReadOnly(True)
        self.component_edit.setText(project.component_name)
        self.ecus_edit.setPlainText("\n".join(project.ecu_names))
        self.description_edit.setPlainText(project.description)
        self.save_button.setText("Einstellungen speichern")
        self.status.setText(
            "Sachnummer ändern = neues Projekt. "
            "Steuergeräte können jederzeit hinzugefügt oder entfernt werden."
        )

    def start_new(self) -> None:
        self._is_new = True
        self.profile_combo.setEnabled(True)
        self.part_edit.setReadOnly(False)
        self.part_edit.clear()
        self.ecus_edit.clear()
        self.description_edit.clear()
        self._set_default_component()
        self.save_button.setText("Neues Projekt erstellen")
        self.status.setText(
            "Neue Sachnummer eingeben. Bestehende Fall-/Quellendaten "
            "werden dadurch nicht überschrieben."
        )
        self.part_edit.setFocus()

    def select_project(self, profile: str, part: str) -> None:
        self._is_new = False
        self.refresh_projects(select=(profile, part))

    def _draft_project(self) -> NTFProject:
        return NTFProject(
            profile_id=str(self.profile_combo.currentData() or ""),
            part_number=self.part_edit.text(),
            component_name=self.component_edit.text(),
            ecu_names=tuple(
                x.strip() for x in self.ecus_edit.toPlainText().splitlines() if x.strip()
            ),
            description=self.description_edit.toPlainText(),
        )

    def _save_project(self) -> None:
        try:
            project = self.projects.save(
                self._draft_project(), create_only=self._is_new,
            )
        except ValueError as exc:
            QMessageBox.warning(self, "Projekteinstellungen", str(exc))
            return
        self._is_new = False
        self.refresh_projects(select=(project.profile_id, project.part_number))
        self.status.setText(f"Projekt {project.title} gespeichert.")
        self.project_selected.emit(project.profile_id, project.part_number)

    def _open_project(self) -> None:
        if self._is_new:
            self._save_project()
            return
        project = self._draft_project()
        if not self.projects.get(project.profile_id, project.part_number):
            self.status.setText("Bitte zuerst ein Projekt speichern.")
            return
        self.project_selected.emit(project.profile_id, project.part_number)
