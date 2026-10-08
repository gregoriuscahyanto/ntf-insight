"""German-language dialogs for manual FIN/case and engineering-event entry."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from PySide6.QtCore import QDate, QDateTime, QTime, Qt
from PySide6.QtGui import QIntValidator
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateTimeEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QStackedWidget,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ntf_insight.app.models.simple_table_model import SimpleTableModel
from ntf_insight.domain.case import NTFCase
from ntf_insight.domain.enums import SupplierFindingResult
from ntf_insight.domain.events import (
    CaseEvent,
    DiagnosticEvent,
    DiagnosticSession,
    ECUStateObservation,
    PartReplacement,
    RepairEvent,
    SoftwareEvent,
    SupplierFinding,
)
from ntf_insight.domain.manual import ManualChange
from ntf_insight.domain.vehicle import Vehicle
from ntf_insight.ingestion.manual_entry import EVENT_TYPES


EVENT_LABELS = {
    "diagnostic_session": "Kurztest",
    "diagnostic": "DTC / Diagnosefehler",
    "replacement": "Bauteiltausch",
    "repair": "Werkstatt / Maßnahme",
    "software": "HW-/SW-Update",
    "ecu_state": "ECU-HW-/SW-Stand",
    "supplier": "Lieferantenbefund",
    "note": "Freie Notiz",
}

EVENT_SCHEMAS: dict[str, tuple[tuple[str, str, str], ...]] = {
    "diagnostic_session": (
        ("label", "Bezeichnung", "line"),
        ("ecu_count", "Anzahl Steuergeräte", "int"),
        ("dtc_count", "Anzahl DTCs (0 = fehlerfrei)", "int"),
    ),
    "diagnostic": (
        ("ecu", "Steuergerät *", "line"),
        ("dtc_code", "DTC-Code *", "line"),
        ("dtc_text", "DTC-Text", "line"),
        ("status", "Status", "line"),
        ("occurrence_count", "Auftreten (Anzahl)", "int"),
        ("session_id", "Zugehöriger Kurztest", "session"),
    ),
    "replacement": (
        ("component_type", "Bauteil *", "line"),
        ("old_part_number", "Alte Teilenummer", "line"),
        ("new_part_number", "Neue Teilenummer", "line"),
        ("supplier", "Lieferant", "line"),
        ("serial_number", "Seriennummer", "line"),
        ("batch", "Charge", "line"),
    ),
    "repair": (
        ("complaint", "Beanstandung", "text"),
        ("action", "Maßnahme", "text"),
        ("notes", "Notizen", "text"),
    ),
    "software": (
        ("ecu", "Steuergerät *", "line"),
        ("software_version", "SW-Version", "line"),
        ("hardware_version", "HW-Version", "line"),
        ("coding", "Codierung", "line"),
        ("action", "Update / Änderung", "text"),
    ),
    "ecu_state": (
        ("ecu", "Steuergerät *", "line"),
        ("software_version", "SW-Version", "line"),
        ("hardware_version", "HW-Version", "line"),
        ("coding", "Codierung", "line"),
        ("session_id", "Zugehöriger Kurztest", "session"),
    ),
    "supplier": (
        ("supplier", "Lieferant", "line"),
        ("result", "Befund", "result"),
        ("complaint_reproduced", "Beanstandung reproduziert", "bool_choice"),
        ("failure_mode", "Fehlerbild", "text"),
        ("notes", "Notizen", "text"),
    ),
    "note": (("notes", "Notiz *", "text"),),
}


def _line(value: str = "") -> QLineEdit:
    widget = QLineEdit()
    widget.setText(value)
    return widget


def _optional_int(value: str) -> int | None:
    return int(value.strip()) if value.strip() else None


class NewCaseDialog(QDialog):
    """Create a new persistent case without importing synthetic/demo records."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Neuen FIN/Fall anlegen")
        self.setMinimumWidth(510)

        layout = QVBoxLayout(self)
        intro = QLabel("Pflichtfelder: Fall-ID, FIN und Bauteil. Eine FIN kann mehrere Fälle haben.")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        form = QFormLayout()
        self.case_id = _line()
        self.case_id.setPlaceholderText("z. B. NTF-2026-001")
        self.vin = _line()
        self.vin.setPlaceholderText("FIN / VIN")
        self.component = QComboBox()
        self.component.addItem("Kühlmittelpumpe", ("Coolant Pump", "coolant_pump"))
        self.component.addItem("HV-Batterie", ("HV Battery", "hv_battery"))
        self.component.addItem("Anderes Bauteil", None)
        self.custom_component = _line()
        self.custom_component.setPlaceholderText("Bauteilbezeichnung")
        self.custom_component.setVisible(False)
        self.component.currentIndexChanged.connect(self._component_changed)

        self.model_series = _line()
        self.variant = _line()
        self.market = _line()
        form.addRow("Fall-ID *", self.case_id)
        form.addRow("FIN / VIN *", self.vin)
        form.addRow("Bauteil *", self.component)
        form.addRow("", self.custom_component)
        form.addRow("Baureihe", self.model_series)
        form.addRow("Variante", self.variant)
        form.addRow("Markt", self.market)
        layout.addLayout(form)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setText("Fall anlegen")
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Abbrechen")
        self.buttons.accepted.connect(self._validate_accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    def _component_changed(self) -> None:
        self.custom_component.setVisible(self.component.currentData() is None)

    def _validate_accept(self) -> None:
        if not self.case_id.text().strip() or not self.vin.text().strip():
            QMessageBox.warning(self, "Pflichtfelder", "Bitte Fall-ID und FIN eingeben.")
            return
        if self.component.currentData() is None and not self.custom_component.text().strip():
            QMessageBox.warning(self, "Pflichtfelder", "Bitte das Bauteil benennen.")
            return
        self.accept()

    def build_case(self) -> NTFCase:
        profile = self.component.currentData()
        name, profile_id = profile if profile is not None else (
            self.custom_component.text().strip(), None
        )
        return NTFCase(
            case_id=self.case_id.text().strip(),
            vehicle=Vehicle(
                vin=self.vin.text().strip(),
                model_series=self.model_series.text().strip() or None,
                variant=self.variant.text().strip() or None,
                market=self.market.text().strip() or None,
            ),
            component_type=name,
            component_profile_id=profile_id,
        )


class ManualEventDialog(QDialog):
    """Create or correct one typed engineering event for a known FIN/case."""

    def __init__(
        self,
        case: NTFCase,
        parent: QWidget | None = None,
        *,
        kind: str | None = None,
        existing: CaseEvent | None = None,
    ) -> None:
        super().__init__(parent)
        self.case = case
        self.existing = existing
        self.setWindowTitle(
            f"{'Ereignis korrigieren' if existing else 'Ereignis hinzufügen'} – {case.case_id}"
        )
        self.setMinimumSize(610, 525)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"FIN: {case.vin} · Bauteil: {case.component_type}"))
        form = QFormLayout()

        self.kind_combo = QComboBox()
        for key, label in EVENT_LABELS.items():
            self.kind_combo.addItem(label, key)
        if kind is not None:
            selected = self.kind_combo.findData(kind)
            if selected >= 0:
                self.kind_combo.setCurrentIndex(selected)
        self.kind_combo.setEnabled(existing is None)
        form.addRow("Ereignisart", self.kind_combo)

        self.occurred_at = QDateTimeEdit()
        self.occurred_at.setCalendarPopup(True)
        self.occurred_at.setDisplayFormat("dd.MM.yyyy HH:mm")
        self.occurred_at.setDateTime(QDateTime.currentDateTime())
        if existing is not None:
            dt = existing.occurred_at
            self.occurred_at.setDateTime(
                QDateTime(QDate(dt.year, dt.month, dt.day), QTime(dt.hour, dt.minute))
            )
        form.addRow("Zeitpunkt *", self.occurred_at)

        self.date_only = QCheckBox("Nur Datum bekannt (12:00 als Platzhalter)")
        self.date_only.setChecked(
            existing is not None and getattr(existing, "time_precision", "") == "date"
        )
        self.date_only.toggled.connect(self._date_precision_changed)
        form.addRow("", self.date_only)

        self.mileage = _line(
            str(existing.mileage_km)
            if existing is not None and existing.mileage_km is not None else ""
        )
        self.mileage.setValidator(QIntValidator(0, 2_000_000_000, self))
        self.mileage.setPlaceholderText("Optional – leer = unbekannt")
        form.addRow("Kilometerstand", self.mileage)
        layout.addLayout(form)

        self.pages = QStackedWidget()
        self.fields: dict[str, dict[str, Any]] = {}
        for event_kind, schema in EVENT_SCHEMAS.items():
            page = QWidget()
            page_form = QFormLayout(page)
            values: dict[str, Any] = {}
            for field_name, label, field_type in schema:
                widget = self._field_widget(field_type, field_name)
                page_form.addRow(label, widget)
                values[field_name] = widget
            self.fields[event_kind] = values
            self.pages.addWidget(page)
        layout.addWidget(self.pages, 1)

        self.anchor = QCheckBox("Als untersuchten Bauteiltausch verwenden")
        self.anchor.setChecked(case.investigated_replacement_id is None)
        layout.addWidget(self.anchor)
        self.kind_combo.currentIndexChanged.connect(self._kind_changed)
        self._kind_changed()

        if existing is not None:
            self._fill_existing(existing)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setText("Speichern")
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Abbrechen")
        self.buttons.accepted.connect(self._validate_accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    def _field_widget(self, field_type: str, field_name: str) -> Any:
        if field_type == "line":
            return _line()
        if field_type == "text":
            widget = QPlainTextEdit()
            widget.setMaximumHeight(75)
            return widget
        if field_type == "int":
            widget = _line()
            widget.setValidator(QIntValidator(0, 2_000_000_000, self))
            widget.setPlaceholderText("Leer = unbekannt")
            return widget
        combo = QComboBox()
        if field_type == "session":
            combo.addItem("Kein Kurztest zugeordnet", None)
            for session in self.case.diagnostic_sessions:
                combo.addItem(
                    f"{session.occurred_at:%d.%m.%Y %H:%M} – {session.label}",
                    session.session_id,
                )
        elif field_type == "result":
            for result, label in (
                (SupplierFindingResult.UNKNOWN, "Unbekannt"),
                (SupplierFindingResult.NTF, "NTF"),
                (SupplierFindingResult.FAULT_FOUND, "Fehler gefunden"),
                (SupplierFindingResult.OTHER, "Sonstiger Befund"),
            ):
                combo.addItem(label, result)
        elif field_type == "bool_choice":
            combo.addItem("Unbekannt", None)
            combo.addItem("Ja", True)
            combo.addItem("Nein", False)
        return combo

    def _date_precision_changed(self, checked: bool) -> None:
        if checked:
            dt = self.occurred_at.dateTime()
            self.occurred_at.setDateTime(QDateTime(dt.date(), QTime(12, 0)))

    def _kind_changed(self) -> None:
        kind = self.kind_combo.currentData()
        index = list(EVENT_SCHEMAS).index(kind)
        self.pages.setCurrentIndex(index)
        self.anchor.setVisible(kind == "replacement" and self.existing is None)
        if kind == "replacement":
            field = self.fields["replacement"]["component_type"]
            if not field.text().strip():
                field.setText(self.case.component_type)

    def _fill_existing(self, event: CaseEvent) -> None:
        kind = self.kind_combo.currentData()
        for field_name, widget in self.fields[kind].items():
            value = getattr(event, field_name, None)
            if isinstance(widget, QComboBox):
                index = widget.findData(value)
                if index >= 0:
                    widget.setCurrentIndex(index)
            elif isinstance(widget, QPlainTextEdit):
                widget.setPlainText("" if value is None else str(value))
            else:
                widget.setText("" if value is None else str(value))

    @property
    def selected_kind(self) -> str:
        kind = str(self.kind_combo.currentData())
        return "repair" if kind == "note" else kind

    @property
    def set_replacement_anchor(self) -> bool:
        return self.selected_kind == "replacement" and self.anchor.isChecked()

    def build_event(self) -> CaseEvent:
        visible_kind = str(self.kind_combo.currentData())
        kind = self.selected_kind
        fields = self.fields[visible_kind]
        params: dict[str, Any] = {}
        for name, widget in fields.items():
            if isinstance(widget, QComboBox):
                params[name] = widget.currentData()
            elif isinstance(widget, QPlainTextEdit):
                params[name] = widget.toPlainText().strip() or None
            else:
                value = widget.text().strip()
                params[name] = _optional_int(value) if name in {
                    "ecu_count", "dtc_count", "occurrence_count"
                } else (value or None)

        if visible_kind == "note":
            if not params.get("notes"):
                raise ValueError("Bitte eine Notiz eingeben.")
            params["action"] = "Manuelle Notiz"

        if visible_kind == "diagnostic_session":
            params["label"] = params.get("label") or "Manueller Kurztest"

        if kind in {"diagnostic", "software", "ecu_state"} and not params.get("ecu"):
            raise ValueError("Bitte das Steuergerät eingeben.")
        if kind == "diagnostic" and not params.get("dtc_code"):
            raise ValueError("Bitte den DTC-Code eingeben.")
        if kind == "replacement" and not params.get("component_type"):
            raise ValueError("Bitte das Bauteil eingeben.")

        occurred_at = self.occurred_at.dateTime().toPython()
        if self.date_only.isChecked():
            occurred_at = occurred_at.replace(hour=12, minute=0, second=0, microsecond=0)
            params["time_precision"] = "date"

        params.update(
            vin=self.case.vin,
            occurred_at=occurred_at,
            mileage_km=_optional_int(self.mileage.text()),
        )
        if self.existing is not None:
            params["event_id"] = self.existing.event_id
            if isinstance(self.existing, DiagnosticSession):
                params["session_id"] = self.existing.session_id
        return EVENT_TYPES[kind].model_validate(params)

    def _validate_accept(self) -> None:
        try:
            self.build_event()
        except (ValueError, TypeError) as exc:
            QMessageBox.warning(self, "Eingabe prüfen", str(exc))
            return
        self.accept()


class ManualHistoryDialog(QDialog):
    """Browse manual revisions, including before/after values for corrections."""

    def __init__(
        self,
        case_id: str,
        changes: list[ManualChange],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Änderungsverlauf – {case_id}")
        self.resize(900, 560)
        self.changes = changes

        layout = QVBoxLayout(self)
        rows = [
            (
                change.occurred_at.astimezone().strftime("%d.%m.%Y %H:%M"),
                str(change.action),
                change.entity_type,
                change.actor,
                change.event_id or "—",
            )
            for change in changes
        ]
        self.model = SimpleTableModel(
            ("Zeitpunkt", "Aktion", "Datenart", "Benutzer", "Ereignis-ID"), rows
        )
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table)

        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setPlaceholderText("Änderung auswählen, um Vorher-/Nachher-Werte zu sehen.")
        layout.addWidget(self.detail)
        self.table.clicked.connect(self._show_detail)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _show_detail(self, index) -> None:
        if not index.isValid() or not (0 <= index.row() < len(self.changes)):
            return
        change = self.changes[index.row()]
        before = json.loads(change.before_json) if change.before_json else None
        after = json.loads(change.after_json)
        self.detail.setPlainText(
            json.dumps(
                {"vorher": before, "nachher": after, "originalquelle": change.source_ref},
                indent=2, ensure_ascii=False,
            )
        )
