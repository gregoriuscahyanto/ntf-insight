"""Local CPC3 software evidence panel for one FIN, without remote access."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QHeaderView, QLabel, QTableView, QVBoxLayout, QWidget,
)

from ntf_insight.analysis.cpc3_software import assess_ecu_software
from ntf_insight.app.models.simple_table_model import SimpleTableModel
from ntf_insight.domain.case import NTFCase
from ntf_insight.storage.source_knowledge_store import SourceKnowledgeStore


def _table(model: SimpleTableModel, *, max_height: int) -> QTableView:
    view = QTableView()
    view.setModel(model)
    view.setMinimumHeight(65)
    view.setMaximumHeight(max_height)
    view.setAlternatingRowColors(True)
    view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    view.horizontalHeader().setSectionResizeMode(
        QHeaderView.ResizeMode.ResizeToContents
    )
    view.horizontalHeader().setStretchLastSection(True)
    return view


class CPC3SoftwarePanel(QWidget):
    """Distinguishes SW observations, update intervals and observable DTC delta."""

    def __init__(
        self, source_knowledge: SourceKnowledgeStore | None = None,
        *, ecu: str = "CPC3",
    ) -> None:
        super().__init__()
        self.source_knowledge = source_knowledge
        self.ecu = str(ecu).strip().upper() or "CPC3"
        self._current_case: NTFCase | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 8)
        layout.setSpacing(8)
        self.heading = QLabel(
            f"{self.ecu} · Softwarestand beim Pumpentausch",
            objectName="CardTitle",
        )
        layout.addWidget(self.heading)
        self.swap_summary = QLabel(objectName="PageSubtitle")
        self.swap_summary.setTextFormat(Qt.TextFormat.PlainText)
        self.swap_summary.setWordWrap(True)
        layout.addWidget(self.swap_summary)
        self.evidence_note = QLabel(objectName="PageSubtitle")
        self.evidence_note.setTextFormat(Qt.TextFormat.PlainText)
        self.evidence_note.setWordWrap(True)
        layout.addWidget(self.evidence_note)

        self.version_model = SimpleTableModel((
            "CPC3-SW", "Erste Beobachtung", "Letzte Beobachtung",
            "Anzahl", "Quellen", "Beobachtete CPC3-DTCs",
        ))
        layout.addWidget(_table(self.version_model, max_height=175))
        self.change_heading = QLabel(
            f"{self.ecu} · SW-Wechsel und Diagnoseverhalten",
            objectName="CardTitle",
        )
        layout.addWidget(self.change_heading)
        self.change_model = SimpleTableModel((
            "SW vorher", "SW nachher", "Letzter alter Stand",
            "Erster neuer Stand", "DTC neu gesehen",
            "DTC im neuen Test nicht gesehen", "Datenqualität", "Quellbeleg",
        ))
        layout.addWidget(_table(self.change_model, max_height=185))
        self.clear()

    def set_ecu(self, ecu: str) -> None:
        """Follow the ECU chosen in the all-pump overview on detail navigation."""
        selected = str(ecu or "").strip().upper()
        if not selected or selected == self.ecu:
            return
        self.ecu = selected
        self.heading.setText(
            f"{self.ecu} · Softwarestand beim Pumpentausch"
        )
        self.change_heading.setText(
            f"{self.ecu} · SW-Wechsel und Diagnoseverhalten"
        )
        if self._current_case is not None:
            self.show_case(self._current_case)

    def clear(self) -> None:
        self._current_case = None
        self.swap_summary.setText("Keine FIN / kein Fall ausgewählt.")
        self.evidence_note.setText("Keine CPC3-Softwaredaten ausgewertet.")
        self.version_model.set_rows([])
        self.change_model.set_rows([])

    @staticmethod
    def _when(value, precision: str | None = None) -> str:
        if precision == "date":
            return f"{value:%d.%m.%Y} (nur Datum)"
        return f"{value:%d.%m.%Y %H:%M}"

    @classmethod
    def _state_description(cls, state) -> str:
        if state is None:
            return "nicht belegbar"
        moment = cls._when(
            state.occurred_at, getattr(state, "time_precision", None),
        )
        return (
            f"{state.software_version} "
            f"(Messung {moment}; "
            f"Quelle: {state.source_ref or 'nicht angegeben'})"
        )

    def show_case(self, case: NTFCase) -> None:
        self._current_case = case
        rows = ()
        truncated = False
        if self.source_knowledge is not None:
            rows, truncated = self.source_knowledge.ecu_software_rows_for_fins(
                [case.vin], self.ecu,
            ).get(case.vin, ([], False))
        review = assess_ecu_software(
            case, ecu=self.ecu, autoexport_rows=rows, truncated=truncated,
        )
        self.heading.setText(
            f"{self.ecu} · Softwarestand beim Pumpentausch"
        )
        if review.replacement_day is None:
            anchor = "Kein dokumentierter Pumpentauschanker"
        else:
            anchor = f"Tauschanker {review.replacement_day:%d.%m.%Y}"
        before = (
            "widersprüchliche SW-Messungen"
            if review.before_ambiguous
            else self._state_description(review.last_before_swap)
        )
        after = (
            "widersprüchliche SW-Messungen"
            if review.after_ambiguous
            else self._state_description(review.first_after_swap)
        )
        self.swap_summary.setText(
            f"{anchor}. {self.ecu}-SW zuletzt VOR dem Tauschtag: {before}. "
            f"{self.ecu}-SW erstmals NACH dem Tauschtag: {after}. "
            "Der exakte SW-Stand beim eigentlichen Pumpenausfall ist "
            "damit nicht automatisch belegt."
        )
        comparable = sum(
            evidence.comparable_tests for evidence in review.changes
        )
        note = (
            f"{review.observation_count} {self.ecu}-SW-Beobachtungen; "
            f"{len(review.versions)} unterschiedliche SW-Stände; "
            f"{len(review.changes)} zeitlich eingegrenzte SW-Standabweichungen. "
            f"{comparable} Standwechsel mit vergleichbaren vollständigen "
            f"{self.ecu}-QuickTests. Ein DTC-Unterschied ist eine Beobachtung, "
            "kein Nachweis einer SW-Wirkung oder Lieferantenverursachung. "
            "Welche Funktionen oder Kalibrierungen geändert wurden, ist "
            "ohne freigegebene Software-Release-Notes nicht bestimmbar."
        )
        if review.on_swap_day:
            note += (
                f" {review.on_swap_day} Messungen am Tauschtag "
                "wurden zeitlich nicht vor/nach eingeordnet."
            )
        if review.ambiguous_days:
            note += (
                f" {len(review.ambiguous_days)} Tage mit widersprüchlichen "
                "SW-Ständen waren für den Versionswechsel nicht auswertbar."
            )
        if review.truncated:
            note += (
                " AutoExport-Quellenlimit erreicht: Auswertung unvollständig, "
                "kein Negativnachweis zulässig."
            )
        if review.documented_actions:
            samples = "; ".join(
                f"{action.occurred_at:%d.%m.%Y}: "
                f"{action.action or 'SW-Ereignis'} "
                f"(SW {action.software_version or 'unbekannt'})"
                for action in review.documented_actions[:3]
            )
            extra = " …" if len(review.documented_actions) > 3 else ""
            note += (
                f" {len(review.documented_actions)} dokumentierte "
                f"{self.ecu}-Softwareereignisse: {samples}{extra}."
            )
        self.evidence_note.setText(note)

        self.version_model.set_rows([
            (
                item.version,
                self._when(item.first_seen, item.first_precision),
                self._when(item.last_seen, item.last_precision),
                item.observation_count,
                ", ".join(item.sources),
                ", ".join(item.observed_dtcs) or "Keine Codes beobachtet",
            )
            for item in review.versions
        ])
        self.change_model.set_rows([
            (
                evidence.change.previous_version,
                evidence.change.new_version,
                self._when(
                    evidence.change.last_previous_at,
                    getattr(evidence.change.previous, "time_precision", None),
                ),
                self._when(
                    evidence.change.first_observed_at,
                    getattr(evidence.change.current, "time_precision", None),
                ),
                (
                    ", ".join(evidence.new_dtcs) or "Keine"
                    if evidence.comparable_tests else "Nicht vergleichbar"
                ),
                (
                    ", ".join(evidence.absent_in_new_test) or "Keine"
                    if evidence.comparable_tests else "Nicht vergleichbar"
                ),
                (
                    "Zwei vollständige CPC3-QuickTests"
                    if evidence.comparable_tests
                    else "Kein vollständiges QuickTest-Paar"
                ),
                evidence.change.current.source_ref or "—",
            )
            for evidence in review.changes
        ])
