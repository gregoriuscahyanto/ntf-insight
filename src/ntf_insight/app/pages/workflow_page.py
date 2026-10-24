"""Kompakter sechsstufiger Arbeitsbereich für die lokale NTF-Prüfung.

Die sechs Workflow-Stationen stehen nebeneinander. Darunter zeigt eine
QStackedWidget genau EINEN Arbeitsschritt; nur Tabellen scrollen intern.
Rohdatenparser, QEC-Downloader und ChatGPT-Vertrag werden nicht dupliziert.
"""
from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import QSortFilterProxyModel, Qt, Signal
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QProgressBar, QPushButton, QSizePolicy, QStackedWidget, QTableView,
    QVBoxLayout, QWidget,
)

from ntf_insight.acquisition.qec_archive import local_qec_archive
from ntf_insight.acquisition.qec_tool import QecTarget, parse_qec_targets
from ntf_insight.app.models.simple_table_model import SimpleTableModel
from ntf_insight.components.registry import list_component_profiles
from ntf_insight.reporting.chatgpt_exchange import ChatGPTAnalyseStore
from ntf_insight.storage.workflow_progress import (
    STEP_COUNT, WorkflowProgressStore, normalize_part_number,
)


def _create_table(headers: tuple[str, ...]) -> tuple[QTableView, SimpleTableModel]:
    """Eine echte FIN-Tabelle statt unscrollbarer Kachelinhalte."""
    model = SimpleTableModel(headers)
    table = QTableView()
    table.setModel(model)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setAlternatingRowColors(True)
    table.verticalHeader().setVisible(False)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    table.setMinimumHeight(140)
    table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    return table, model


class WorkflowPage(QWidget):
    """Die Startseite bleibt geöffnet; Stationen ändern den lokalen Inhalt."""

    navigate = Signal(str, str)  # Nur für bereits bestehende Detailansichten ab Schritt 4
    action_requested = Signal(str)

    STEPS = (
        ("QEC-FIN-Liste", "QEC-Kohorte", "sources", "qec_list"),
        ("QEC-Befundung", "Berichte", "cases", "qec_reports"),
        ("NTF-Entscheidung", "Prüfung", "sources", "qec_decision"),
        ("Diagnose", "CPC3 / TP", "cases", "quicktests"),
        ("Clusteranalyse", "Muster", "cases", "cluster"),
        ("Auswertung", "Ergebnis", "sources", "chatgpt"),
    )

    def __init__(
        self, progress_store: WorkflowProgressStore, *, qec_store=None,
        repository=None, quicktests=None, mode="local",
    ) -> None:
        super().__init__(objectName="WorkflowPage")
        self.progress_store = progress_store
        self.qec_store = qec_store
        self.repository = repository
        self.quicktests = quicktests
        self.mode = mode
        self.profile_id, part = progress_store.current_context()
        self.state = progress_store.load(self.profile_id, part)
        self.qec_root = progress_store.store.path.parent / "qec"
        self._all_rows: list[dict] = []
        self._scoped_rows: list[dict] = []
        self._chatgpt_by_case: dict[str, dict] = {}
        self._source_name = ""
        self._data_error = ""
        self._notice = ""
        self._error_step: int | None = None
        self._busy = False
        self.analysis_store = ChatGPTAnalyseStore(progress_store.store) if qec_store else None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 13, 18, 13)
        outer.setSpacing(7)

        header = QHBoxLayout()
        header.addWidget(QLabel("NTF · Analyseworkflow", objectName="PageTitle"))
        header.addStretch(1)
        self.profile = QComboBox()
        self.profile.setAccessibleName("Bauteilprofil")
        for item in list_component_profiles():
            label = (
                "Kühlmittelpumpe" if item.profile_id == "coolant_pump"
                else "HV-Batterie" if item.profile_id == "hv_battery"
                else item.display_name
            )
            self.profile.addItem(label, item.profile_id)
        self.profile.setCurrentIndex(max(0, self.profile.findData(self.profile_id)))
        self.profile.currentIndexChanged.connect(self._change_context)
        header.addWidget(self.profile)
        self.part_number = QLineEdit(part)
        self.part_number.setPlaceholderText("Sachnummer · alle")
        self.part_number.setMaximumWidth(215)
        self.part_number.setAccessibleName("Sachnummer zur QEC-Kohortenfilterung")
        self.part_number.editingFinished.connect(self._change_context)
        header.addWidget(self.part_number)
        outer.addLayout(header)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setMaximumHeight(16)
        self.progress.setTextVisible(False)
        outer.addWidget(self.progress)
        self.progress_label = QLabel(objectName="PageSubtitle")
        outer.addWidget(self.progress_label)

        # Ein horizontaler Prozess: keine 2x3-Flächen, kein Seiten-Scrollbereich.
        steps = QHBoxLayout()
        steps.setSpacing(6)
        self.cards: list[QPushButton] = []
        for i, (name, *_rest) in enumerate(self.STEPS):
            button = QPushButton(objectName="WorkflowStep")
            button.setCheckable(True)
            button.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            button.setMinimumHeight(77)
            button.setMaximumHeight(86)
            button.setAccessibleName(f"Schritt {i + 1}: {name} öffnen")
            button.setToolTip(f"{name} auswählen und Inhalte darunter anzeigen")
            button.clicked.connect(lambda _checked=False, index=i: self._open_step(index))
            self.cards.append(button)
            steps.addWidget(button, 1)
            if i + 1 < len(self.STEPS):
                arrow = QLabel("›")
                arrow.setObjectName("WorkflowArrow")
                arrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
                steps.addWidget(arrow)
        outer.addLayout(steps)

        controls = QHBoxLayout()
        self.previous_button = QPushButton("← Zurück")
        self.previous_button.clicked.connect(lambda: self._move(-1))
        controls.addWidget(self.previous_button)
        self.current_title = QLabel(objectName="CardTitle")
        controls.addWidget(self.current_title, 1)
        self.pause_button = QPushButton("Pausieren")
        self.pause_button.clicked.connect(self._toggle_pause)
        controls.addWidget(self.pause_button)
        self.next_button = QPushButton("Weiter →")
        self.next_button.clicked.connect(lambda: self._move(1))
        controls.addWidget(self.next_button)
        outer.addLayout(controls)

        self.workspaces = QStackedWidget()
        self.workspaces.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        outer.addWidget(self.workspaces, 1)
        self._build_step_one()
        self._build_step_two()
        self._build_step_three()
        self._build_following_steps()

        self.note = QLabel(objectName="PageSubtitle")
        self.note.setWordWrap(True)
        outer.addWidget(self.note)
        self.refresh_data()

    def _workspace(self, title: str, subtitle: str = "") -> tuple[QWidget, QVBoxLayout]:
        widget = QWidget()
        body = QVBoxLayout(widget)
        body.setContentsMargins(0, 4, 0, 0)
        body.setSpacing(7)
        heading = QLabel(title, objectName="CardTitle")
        body.addWidget(heading)
        if subtitle:
            label = QLabel(subtitle, objectName="PageSubtitle")
            label.setWordWrap(True)
            body.addWidget(label)
        self.workspaces.addWidget(widget)
        return widget, body

    @staticmethod
    def _add_action(row: QHBoxLayout, title: str, signal, *, tooltip: str = "") -> QPushButton:
        button = QPushButton(title, objectName="WorkflowAction")
        button.setToolTip(tooltip)
        button.clicked.connect(signal)
        row.addWidget(button)
        return button

    def _build_step_one(self) -> None:
        _, body = self._workspace(
            "01 · QEC-FIN-Liste",
            "QEC-Excel einlesen, FINs zur Sachnummer anzeigen und als CSV speichern.",
        )
        actions = QHBoxLayout()
        self.qec_import_button = self._add_action(
            actions, "QEC-FIN-Liste importieren",
            lambda: self.action_requested.emit("qec_list_import"),
        )
        self.qec_portal_button = self._add_action(
            actions, "QEC öffnen · FIN-Liste herunterladen",
            lambda: self.action_requested.emit("qec_list_portal"),
            tooltip="Öffnet QEC im Browser. Sachnummern-Filter und Excel-Export "
                    "erfolgen dort manuell; ein automatischer QEC-FIN-Export "
                    "ist noch nicht verifiziert.",
        )
        self.qec_export_button = self._add_action(
            actions, "Gefilterte FIN-Liste als CSV",
            lambda: self.action_requested.emit("qec_list_csv"),
            tooltip="Exportiert die bereits lokal importierte QEC-Liste "
                    "für die eingegebene Sachnummer.",
        )
        actions.addStretch(1)
        body.addLayout(actions)
        self.source_label = QLabel(objectName="PageSubtitle")
        body.addWidget(self.source_label)
        self.fin_search = QLineEdit()
        self.fin_search.setPlaceholderText("FIN, QEC-Fall oder Referenz suchen …")
        body.addWidget(self.fin_search)
        self.fin_table, self.fin_model = _create_table((
            "FIN", "QEC-Fall", "Referenz", "Sachnummer",
            "SSL-Endbefund", "TP", "NTF-Status", "QEC-Bericht",
        ))
        self.fin_proxy = QSortFilterProxyModel(self)
        self.fin_proxy.setSourceModel(self.fin_model)
        self.fin_proxy.setFilterKeyColumn(-1)
        self.fin_proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.fin_table.setModel(self.fin_proxy)
        self.fin_search.textChanged.connect(self.fin_proxy.setFilterFixedString)
        body.addWidget(self.fin_table, 1)

    def _build_step_two(self) -> None:
        _, body = self._workspace(
            "02 · QEC-Befundungsberichte",
            "Abruf ausschließlich für die QEC-FINs und Referenzen der gewählten Sachnummer.",
        )
        actions = QHBoxLayout()
        self.download_all_button = self._add_action(
            actions, "Alle QEC-Berichte herunterladen / aktualisieren",
            lambda: self.action_requested.emit("qec_download_all"),
        )
        self.download_selected_button = self._add_action(
            actions, "Markierte herunterladen",
            lambda: self.action_requested.emit("qec_download_selected"),
        )
        self.cancel_download_button = self._add_action(
            actions, "Abruf abbrechen",
            lambda: self.action_requested.emit("qec_download_cancel"),
        )
        self.local_qec_button = self._add_action(
            actions, "Lokale Berichte einlesen",
            lambda: self.action_requested.emit("qec_import_local"),
        )
        actions.addStretch(1)
        body.addLayout(actions)
        self.qec_status = QLabel(objectName="PageSubtitle")
        self.qec_status.setWordWrap(True)
        body.addWidget(self.qec_status)
        self.qec_table, self.qec_model = _create_table((
            "FIN", "QEC-Fall", "Referenz", "Sachnummer",
            "Letzter Download", "Downloadstatus",
        ))
        self.qec_table.selectionModel().selectionChanged.connect(
            lambda *_: self._refresh_controls()
        )
        body.addWidget(self.qec_table, 1)

    def _build_step_three(self) -> None:
        _, body = self._workspace(
            "03 · NTF-Entscheidung mit ChatGPT",
            "Vorschläge sind zunächst ungeprüft und werden nicht automatisch zu QEC-Fallentscheidungen.",
        )
        actions = QHBoxLayout()
        self.ai_export_button = self._add_action(
            actions, "Für ChatGPT exportieren (ZIP)",
            lambda: self.action_requested.emit("ai_export"),
            tooltip="Versioniertes Analysepaket mit JSON-Ergebnisvorlage und Schema.",
        )
        self.ai_import_button = self._add_action(
            actions, "ChatGPT-Ergebnis importieren (JSON)",
            lambda: self.action_requested.emit("ai_import"),
            tooltip="Prüft Paket-ID, Fallzuordnung und Belege. "
                    "Eine QEC-Entscheidung wird dabei nicht überschrieben.",
        )
        actions.addStretch(1)
        body.addLayout(actions)
        self.ntf_status = QLabel(objectName="PageSubtitle")
        body.addWidget(self.ntf_status)
        self.ntf_table, self.ntf_model = _create_table((
            "FIN", "QEC-Fall", "SSL-Endbefund", "QEC-Entscheidung",
            "ChatGPT-Vorschlag", "Prüfstatus",
        ))
        body.addWidget(self.ntf_table, 1)

    def _build_following_steps(self) -> None:
        targets = (
            ("04 · CPC3 / Diagnosen",
             "QuickTests, TP-Dashboard, TIPS und Werkstatthistorie sind weiter "
             "in der vorhandenen FIN-/Fallanalyse verfügbar.",
             "Diagnosen öffnen", "cases", "quicktests"),
            ("05 · Clusteranalyse",
             "NTF-Fälle nach Diagnoseähnlichkeit untersuchen. "
             "Ein Cluster ist kein Lieferanten-Nachweis.",
             "Clusteranalyse öffnen", "cases", "cluster"),
            ("06 · Auswertung und Datenaustausch",
             "Ergebnisse und PC-Datenstand können mit vorhandenen Formaten "
             "lokal ausgetauscht werden.",
             "Auswertung öffnen", "sources", "chatgpt"),
        )
        self.review_buttons: dict[int, QPushButton] = {}
        for step, (title, hint, page, tab) in enumerate(targets, start=3):
            _, body = self._workspace(title, hint)
            actions = QHBoxLayout()
            self._add_action(
                actions, "Detailansicht öffnen" if step == 5 else title.split("· ", 1)[-1] + " öffnen",
                lambda _checked=False, p=page, t=tab: self.navigate.emit(p, t),
            )
            if step == 5:
                self._add_action(
                    actions, "Eigene Dateien importieren",
                    lambda: self.action_requested.emit("self_import"),
                )
                self._add_action(
                    actions, "PC-Export",
                    lambda: self.action_requested.emit("pc_export"),
                )
                self._add_action(
                    actions, "PC-Import",
                    lambda: self.action_requested.emit("pc_import"),
                )
            if step in (4, 5):
                button = self._add_action(
                    actions, "Fachlich geprüft",
                    self._review,
                )
                self.review_buttons[step] = button
            actions.addStretch(1)
            body.addLayout(actions)
            body.addStretch(1)
        # Kompatibilität zu früheren Tests und anderen internen Aufrufern.
        self.review_button = self.review_buttons[4]

    def _change_context(self) -> None:
        profile_id = self.profile.currentData()
        if not profile_id:
            return
        try:
            part = normalize_part_number(self.part_number.text())
        except ValueError:
            self.set_notice("Sachnummer enthält ungültige Zeichen oder ist zu lang.", error=True)
            return
        self.part_number.setText(part)
        if (profile_id, part) != (self.profile_id, self.progress_store.current_context()[1]):
            self.profile_id = profile_id
            self.progress_store.select_context(profile_id, part)
            self.state = self.progress_store.load(profile_id, part)
        self.refresh()

    def _save(self) -> None:
        self.progress_store.save(self.profile_id, self.part_number.text(), self.state)
        self.refresh()

    def _open_step(self, index: int) -> None:
        if self.state.paused or not 0 <= index < STEP_COUNT:
            return
        self.state = replace(self.state, step=index)
        self._error_step = None
        self._notice = ""
        self._save()

    def _move(self, delta: int) -> None:
        if self.state.paused:
            return
        self._open_step(max(0, min(STEP_COUNT - 1, self.state.step + delta)))

    def _toggle_pause(self) -> None:
        self.state = replace(self.state, paused=not self.state.paused)
        self._save()

    def _review(self) -> None:
        if self.state.paused or self.state.step not in (4, 5):
            return
        reviews = set(self.state.reviewed_steps)
        if self.state.step in reviews:
            reviews.remove(self.state.step)
        else:
            reviews.add(self.state.step)
        self.state = replace(self.state, reviewed_steps=tuple(sorted(reviews)))
        self._save()

    @staticmethod
    def _part_key(value: str) -> str:
        return "".join(char for char in normalize_part_number(value) if char.isalnum())

    def _rows_for_context(self) -> list[dict]:
        if self.profile_id != "coolant_pump":
            return []
        part = self._part_key(self.part_number.text())
        return [
            row for row in self._all_rows
            if not part or self._part_key(row.get("part_number", "")) == part
        ]

    def refresh_data(self) -> None:
        """Teure QEC-Dateien nur bei Quellenwechsel/explicit Refresh neu lesen."""
        self._data_error = ""
        self._all_rows = []
        self._chatgpt_by_case = {}
        try:
            if self.qec_store is not None:
                self._all_rows = self.qec_store.rows(self.qec_root)
                source = self.qec_store.active_source()
                self._source_name = source.original_name if source else ""
            if self.analysis_store is not None:
                for finding in self.analysis_store.list_case_findings(limit=10000):
                    self._chatgpt_by_case.setdefault(finding["case_id"], finding)
        except (OSError, ValueError) as exc:
            # Keine rohen Berichtsdetails oder FINs in Logs/Dialoge übertragen.
            self._data_error = (
                "QEC-/ChatGPT-Daten konnten nicht geladen werden: "
                + type(exc).__name__
            )
        self.refresh()

    def _update_tables(self) -> None:
        self._scoped_rows = self._rows_for_context()
        self.fin_model.set_rows([
            (
                r["fin"], r["case_id"], r["reference"], r["part_number"],
                r["finding"], "Ja" if r["tp_dashboard"] else "Fehlt",
                r["decision"], "Ja" if r["report"] else "Nein",
            )
            for r in self._scoped_rows
        ])
        self.qec_model.set_rows([
            (
                r["fin"], r["case_id"], r["reference"], r["part_number"],
                info.date_label if info else "—",
                "Gespeichert" if info else "Ausstehend",
            )
            for r in self._scoped_rows
            for info in [local_qec_archive(self.qec_root, r["fin"], r["reference"])]
        ])
        self.ntf_model.set_rows([
            (
                r["fin"], r["case_id"], r["finding"], r["decision"],
                self._chatgpt_by_case[r["case_id"]]["bewertung"].get(
                    "ntf_bewertung", "Nicht bewertet"
                ) if r["case_id"] in self._chatgpt_by_case else "—",
                self._chatgpt_by_case[r["case_id"]]["review_status"]
                if r["case_id"] in self._chatgpt_by_case else "—",
            )
            for r in self._scoped_rows
        ])

    def qec_targets(self, *, selected_only: bool = False) -> list[QecTarget]:
        """Niemals außerhalb der Sachnummern-Kohorte oder Referenz herunterladen."""
        if self.profile_id != "coolant_pump":
            return []
        if selected_only:
            selected_rows = {
                index.row() for index in self.qec_table.selectionModel().selectedRows()
            }
            rows = [
                row for index, row in enumerate(self._scoped_rows)
                if index in selected_rows
            ]
        else:
            rows = self._scoped_rows
        targets: list[QecTarget] = []
        seen = set()
        for row in rows:
            try:
                parsed = parse_qec_targets(row["fin"])
            except ValueError:
                continue
            reference = str(row["reference"] or "").strip()
            if reference and (not reference.isdigit() or len(reference) > 14):
                continue
            target = QecTarget(
                fin=parsed[0].fin,
                part_number=str(row["part_number"] or ""),
                reference=reference,
            )
            key = target.fin, target.reference, target.part_number
            if key not in seen:
                seen.add(key)
                targets.append(target)
        return targets

    def set_notice(self, message: str, *, error: bool = False) -> None:
        self._notice = message
        self._error_step = self.state.step if error else None
        self.note.setText(message)
        self.note.setProperty("isError", error)
        self.note.style().unpolish(self.note)
        self.note.style().polish(self.note)

    def set_download_busy(self, busy: bool, message: str = "") -> None:
        self._busy = busy
        if message:
            self.qec_status.setText(message)
        self._refresh_controls()

    def _refresh_controls(self) -> None:
        paused = self.state.paused
        has_rows = bool(self._scoped_rows)
        self.previous_button.setEnabled(not paused and self.state.step > 0)
        self.next_button.setEnabled(not paused and self.state.step < STEP_COUNT - 1)
        self.pause_button.setText("Fortsetzen" if paused else "Pausieren")
        self.qec_import_button.setEnabled(not paused)
        self.qec_portal_button.setEnabled(not paused and self.profile_id == "coolant_pump")
        self.qec_export_button.setEnabled(not paused and has_rows)
        self.download_all_button.setEnabled(not paused and not self._busy and has_rows)
        self.download_selected_button.setEnabled(
            not paused and not self._busy and bool(
                self.qec_table.selectionModel().selectedRows()
            )
        )
        self.cancel_download_button.setEnabled(self._busy)
        self.local_qec_button.setEnabled(not paused and not self._busy)
        self.ai_export_button.setEnabled(not paused and has_rows)
        self.ai_import_button.setEnabled(not paused)
        for button in self.review_buttons.values():
            button.setEnabled(not paused)

    def refresh(self) -> None:
        self._update_tables()
        if self.qec_store is not None:
            stats = self.qec_store.summarize_rows(self._scoped_rows)
        else:
            stats = dict.fromkeys(
                ("fins", "cases", "downloaded", "with_tp", "open", "ntf", "not_ntf"), 0
            )
        total, downloaded = stats["fins"], stats["downloaded"]
        reviewed = stats["ntf"] + stats["not_ntf"]
        statuses = [
            "done" if total else "pending",
            "done" if total and downloaded == total else (
                "partial" if downloaded else "pending"
            ),
            "done" if stats["cases"] and not stats["open"] else (
                "partial" if reviewed or self._chatgpt_by_case else "pending"
            ),
            "done" if total and stats["with_tp"] == total else (
                "partial" if stats["with_tp"] else "pending"
            ),
            "done" if 4 in self.state.reviewed_steps else "pending",
            "done" if 5 in self.state.reviewed_steps else "pending",
        ]
        fraction = sum(1 if status == "done" else 0.5 if status == "partial" else 0
                       for status in statuses)
        if self._data_error:
            statuses[0] = "error"
        elif self._error_step is not None:
            statuses[self._error_step] = "error"
        self.progress.setValue(round(fraction / STEP_COUNT * 100))
        self.progress_label.setText(
            f"{stats['cases']} QEC-Fälle · {total} FINs · "
            f"{downloaded} FINs mit QEC-Bericht · {reviewed} fachlich entschieden "
            f"· {self.progress.value()} % Bearbeitungsstand"
        )
        if self._source_name:
            self.source_label.setText(f"QEC-Quelle: {self._source_name}")
        else:
            self.source_label.setText(
                "Noch keine aktive QEC-FIN-Liste. Bitte Original-Excel importieren."
            )
        self.qec_status.setText(
            self.qec_status.text() if self._busy else
            f"{downloaded} von {total} FINs mit QEC-Bericht · "
            "markierte Tabellenzeilen für gezielten Abruf"
        )
        self.ntf_status.setText(
            f"NTF: {stats['ntf']} · Kein NTF: {stats['not_ntf']} · "
            f"Offen: {stats['open']} · ChatGPT-Vorschläge getrennt von QEC-Entscheidungen"
        )
        names = (
            f"{total} FINs", f"{downloaded}/{total} Berichte",
            f"{reviewed}/{stats['cases']} geprüft", f"{stats['with_tp']} TP-FINs",
            "Geprüft" if statuses[4] == "done" else "Offen",
            "Geprüft" if statuses[5] == "done" else "Offen",
        )
        lamps = {"done": "●", "partial": "●", "pending": "○", "error": "!"}
        for i, button in enumerate(self.cards):
            status = statuses[i]
            button.setProperty("workflowState", status)
            button.setProperty("isCurrent", i == self.state.step)
            button.setChecked(i == self.state.step)
            button.setText(
                f"{i + 1:02d}  {self.STEPS[i][0]}\n"
                f"{lamps[status]}  {names[i]}"
            )
            button.setEnabled(not self.state.paused)
            button.style().unpolish(button)
            button.style().polish(button)
        self.workspaces.setCurrentIndex(self.state.step)
        self.current_title.setText(
            f"{self.STEPS[self.state.step][0]} · Schritt {self.state.step + 1}/{STEP_COUNT}"
        )
        if self.state.step in self.review_buttons:
            button = self.review_buttons[self.state.step]
            button.setText(
                "Bestätigung zurücknehmen"
                if self.state.step in self.state.reviewed_steps
                else "Als fachlich geprüft markieren"
            )
        if self.state.paused:
            self.note.setText("Workflow pausiert · Fortschritt lokal gespeichert.")
        elif self._data_error:
            self.note.setText(self._data_error)
        elif self._notice:
            self.note.setText(self._notice)
        else:
            self.note.setText(
                "Grün: vollständig · Gelb: teilweise · Grau: offen. "
                "Die aktuelle Station ist hervorgehoben."
            )
        self._refresh_controls()
