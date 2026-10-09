"""Case detail, evidence and timeline page."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSortFilterProxyModel, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
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

from ntf_insight.analysis.evidence_engine import generate_case_evidence
from ntf_insight.analysis.fin_diagnostics import (
    FIN_ONLY_PREFIX,
    build_fin_only_previews,
)
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
from ntf_insight.app.widgets.quicktest_browser import QuickTestBrowser
from ntf_insight.ingestion.manual_entry import ManualCaseService, ManualEntryError
from ntf_insight.domain.events import PartReplacement
from ntf_insight.reporting.markdown import save_case_report
from ntf_insight.storage.reference_repositories import ReferenceRepository
from ntf_insight.storage.repositories import CaseRepository
from ntf_insight.storage.quicktest_store import QuickTestStore
from ntf_insight.storage.source_knowledge_store import SourceKnowledgeStore


class CasePage(QWidget):
    """Inspect FIN/case combinations and edit persistent manual information."""

    case_saved = Signal(str)

    def __init__(
        self,
        repository: CaseRepository,
        references: ReferenceRepository,
        manual_service: ManualCaseService | None = None,
    ) -> None:
        super().__init__()
        self.repository = repository
        self.references = references
        self.manual_service = manual_service
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
        self.view_cases = [
            *repository.list_cases(),
            *self.fin_only_previews.values(),
        ]

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)

        self.detail_tabs = QTabWidget()
        outer_layout.addWidget(self.detail_tabs)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        scroll.setWidget(content)
        self.detail_tabs.addTab(scroll, "FIN / Fallanalyse")

        if manual_service is not None:
            self.quicktest_browser = QuickTestBrowser(
                QuickTestStore(manual_service.store)
            )
            self.detail_tabs.addTab(self.quicktest_browser, "QuickTests nach FIN")
        else:
            self.quicktest_browser = None

        layout = QVBoxLayout(content)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(12)

        layout.addWidget(QLabel("Fälle / FIN", objectName="PageTitle"))
        intro = QLabel(
            "FINs mit QuickTests werden auch ohne NTF-/QEC-Fall angezeigt. "
            "Mit einem Schadteilfall werden Diagnose, Tausch und Befund "
            "für die Vorher-/Nachher-Analyse verknüpft.",
            objectName="PageSubtitle",
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.selector = QComboBox(self)
        self.selector.setVisible(False)
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

        export_button = QPushButton("Markdown-Bericht exportieren…")
        self.export_button = export_button
        export_button.clicked.connect(self._export_report)
        selector_row.addWidget(export_button)
        layout.addLayout(selector_row)

        case_rows: list[CaseRow] = []
        for case in self.view_cases:
            is_preview = case.case_id.startswith(FIN_ONLY_PREFIX)
            replacement = case.investigated_replacement()
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
                    dtc_count=len(case.diagnostics),
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
                )
            )

        self.case_model = CaseTableModel(case_rows)
        self.case_proxy = QSortFilterProxyModel(self)
        self.case_proxy.setSourceModel(self.case_model)
        self.case_proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.case_proxy.setFilterKeyColumn(-1)
        search.textChanged.connect(self._filter_cases)

        self.case_table = QTableView()
        self.case_table.setModel(self.case_proxy)
        self.case_table.setMaximumHeight(190)
        self.case_table.setAlternatingRowColors(True)
        self.case_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.case_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.case_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.case_table.setSortingEnabled(True)
        self.case_table.verticalHeader().setVisible(False)
        self.case_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.case_table.clicked.connect(self._case_clicked)
        self.case_table.selectionModel().currentRowChanged.connect(
            lambda current, _previous: self._case_clicked(current)
        )
        layout.addWidget(self.case_table)

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
        self.confidence_value = QLabel("—")
        self.recurrence_value = QLabel("—")

        fields = (
            ("Bauteil", self.component_value),
            ("QEC-/dokumentiertes Tauschdatum", self.replacement_value),
            ("AutoExport-Reparaturdatum", self.autoexport_date_value),
            ("Für NTF verwendeter Tauschanker", self.effective_swap_value),
            ("Datumsabgleich", self.date_match_value),
            ("Aktuelle Bewertung", self.root_cause_value),
            ("Lieferantenbeteiligung", self.supplier_value),
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

        if self.selector.count():
            self.case_table.selectRow(0)
            self._refresh()
        else:
            self._clear_view()

    def _filter_cases(self, text: str) -> None:
        """Keep the editable case in sync with the visible filtered selection."""
        self.case_proxy.setFilterFixedString(text)
        if self.case_proxy.rowCount() == 0:
            self.case_table.clearSelection()
            self.selector.setCurrentIndex(-1)
            self.add_event_button.setEnabled(False)
            self.correct_button.setEnabled(False)
            self._clear_view()
            return

        self.case_table.selectRow(0)
        self._case_clicked(self.case_proxy.index(0, 0))

    def _case_clicked(self, index) -> None:
        source_index = self.case_proxy.mapToSource(self.case_proxy.index(index.row(), 0))
        case_id = self.case_model.case_id_at(source_index.row())
        if case_id is None:
            return
        selector_index = self.selector.findData(case_id)
        if selector_index >= 0:
            self.selector.setCurrentIndex(selector_index)

    def _clear_view(self) -> None:
        for value in (
            self.component_value, self.replacement_value, self.autoexport_date_value,
            self.effective_swap_value, self.date_match_value,
            self.date_comparison_note, self.root_cause_value,
            self.supplier_value, self.confidence_value, self.recurrence_value,
            self.assessment_text, self.recurrence_text, self.evidence_balance,
        ):
            value.setText("—")
        self.evidence_model.set_rows([])
        self.timeline_model.set_entries([])
        self.time_plot.set_entries([])

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
        self.confirm_swap_button.setEnabled(False)
        if case is None:
            self._clear_view()
            return

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
                f"{len(case.diagnostics)} DTC-Beobachtungen, "
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
        self.detail_tabs.setCurrentWidget(self.quicktest_browser)
        if fin:
            self.quicktest_browser.select_fin(fin)

    def select_case(self, case_id: str) -> None:
        """Select a case after the shared application data is reloaded."""
        for row in range(self.case_model.rowCount()):
            if self.case_model.case_id_at(row) == case_id:
                source = self.case_model.index(row, 0)
                proxy = self.case_proxy.mapFromSource(source)
                if proxy.isValid():
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
