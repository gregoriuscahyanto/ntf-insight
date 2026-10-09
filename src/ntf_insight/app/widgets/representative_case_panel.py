"""FIN workspace: real medoid representatives and explicit TIPS episode review."""

from __future__ import annotations

from collections import Counter

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ntf_insight.analysis.case_clustering import _component_key
from ntf_insight.analysis.representative_clustering import (
    RepresentativePlan,
    select_representative_cases,
)
from ntf_insight.analysis.tips_case_matching import (
    TipsLinkCandidate,
    confirm_tips_link,
    suggest_tips_links,
)
from ntf_insight.app.models.simple_table_model import SimpleTableModel
from ntf_insight.app.widgets.representative_scatter import RepresentativeScatter
from ntf_insight.domain.case import NTFCase
from ntf_insight.storage.duckdb_store import DuckDBStore
from ntf_insight.storage.source_knowledge_store import SourceKnowledgeStore


def _table(model: SimpleTableModel, height: int) -> QTableView:
    view = QTableView()
    view.setModel(model)
    view.setMinimumHeight(min(135, height))
    view.setMaximumHeight(height)
    view.setAlternatingRowColors(True)
    view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    view.verticalHeader().setVisible(False)
    view.horizontalHeader().setSectionResizeMode(
        QHeaderView.ResizeMode.ResizeToContents
    )
    view.horizontalHeader().setStretchLastSection(True)
    return view


class RepresentativeCasePanel(QWidget):
    """Budget-constrained experiment plan, not a proven root-cause classifier."""

    case_requested = Signal(str)
    tips_linked = Signal(str)

    def __init__(
        self,
        cases: list[NTFCase],
        source_knowledge: SourceKnowledgeStore | None = None,
        store: DuckDBStore | None = None,
    ) -> None:
        super().__init__()
        self.cases = sorted(cases, key=lambda item: item.case_id)
        self.by_id = {case.case_id: case for case in self.cases}
        self._family_by_id = {
            case.case_id: _component_key(case) for case in self.cases
        }
        self.knowledge = source_knowledge
        self.store = store
        self.plan: RepresentativePlan | None = None
        self.candidates: tuple[TipsLinkCandidate, ...] = ()
        self._activated = False
        self._group_ids: list[int] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll)
        content = QWidget()
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(22, 18, 22, 25)
        layout.setSpacing(11)

        layout.addWidget(QLabel(
            "Repräsentative Fallauswahl für die Entwicklung",
            objectName="PageTitle",
        ))
        explanation = QLabel(
            "Ziel: mit einem begrenzten Untersuchungsbudget möglichst viele "
            "hinreichend ähnliche, echte QEC-Fälle abdecken. Die Zahlen unten "
            "sind diagnostische ÄhnlichkeitsINDIZES, keine Ursachen- oder "
            "Reparaturwahrscheinlichkeiten. Nicht passende Fälle werden "
            "ausdrücklich NICHT zwangsweise einem Cluster zugeordnet.",
            objectName="PageSubtitle",
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)

        controls = QGridLayout()
        controls.addWidget(QLabel("Bauteilfamilie"), 0, 0)
        self.family = QComboBox()
        family_counts = Counter(self._family_by_id.values())
        family_label = {
            self._family_by_id[case.case_id]: case.component_type
            for case in self.cases
        }
        for family in sorted(family_counts):
            self.family.addItem(
                f"{family_label[family]} ({family_counts[family]})", family
            )
        controls.addWidget(self.family, 0, 1)
        controls.addWidget(QLabel("Max. Untersuchungsfälle"), 0, 2)
        self.budget = QSpinBox()
        self.budget.setRange(1, 100)
        self.budget.setValue(12)
        controls.addWidget(self.budget, 0, 3)
        controls.addWidget(QLabel("Mind. Index zum Repräsentanten"), 0, 4)
        self.minimum = QDoubleSpinBox()
        self.minimum.setRange(0.05, 1.0)
        self.minimum.setSingleStep(0.05)
        self.minimum.setDecimals(2)
        self.minimum.setValue(0.35)
        controls.addWidget(self.minimum, 0, 5)

        controls.addWidget(QLabel("DTC-Quellen"), 1, 0)
        self.source = QComboBox()
        self.source.addItem("QuickTest + AutoExport", "all")
        self.source.addItem("Nur QuickTest", "quicktest")
        self.source.addItem("Nur AutoExport", "autoexport")
        controls.addWidget(self.source, 1, 1)
        controls.addWidget(QLabel("Vor-Tausch-Zeitraum"), 1, 2)
        self.lookback = QComboBox()
        self.lookback.addItem("Gesamte Vorher-Historie", None)
        for value in (30, 90, 180, 365):
            self.lookback.addItem(f"{value} Tage", value)
        controls.addWidget(self.lookback, 1, 3)
        controls.addWidget(QLabel("Häufige DTCs (max. Anteil)"), 1, 4)
        self.frequency = QComboBox()
        for value in (0.25, 0.35, 0.50, 1.0):
            self.frequency.addItem(
                f"{value:.0%} aller QEC-Fälle der Bauteilfamilie", value
            )
        self.frequency.setCurrentIndex(1)
        controls.addWidget(self.frequency, 1, 5)
        layout.addLayout(controls)

        action = QHBoxLayout()
        self.run_button = QPushButton("Repräsentanten berechnen")
        self.run_button.clicked.connect(self.run_analysis)
        action.addWidget(self.run_button)
        self.reset_button = QPushButton("MDS-Zoom zurücksetzen")
        self.reset_button.clicked.connect(lambda: self.map.reset_zoom())
        action.addWidget(self.reset_button)
        action.addStretch(1)
        layout.addLayout(action)
        self.summary = QLabel(objectName="PageSubtitle")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)

        self.map = RepresentativeScatter()
        self.map.case_picked.connect(self._select_case_from_plot)
        layout.addWidget(self.map)
        geometry_note = QLabel(
            "Farbe = explorative Repräsentanten-Gruppe R1, R2, … · "
            "Großer, nummerierter Punkt = tatsächlicher ausgewählter "
            "Untersuchungsfall (Medoid) · Grau = nicht zugeordnet. "
            "MDS stellt die verwendete Screening-Distanz zweidimensional "
            "NUR näherungsweise dar; maßgeblich sind die Zahlen der Tabelle. "
            "Die blauen Complete-Link-Cluster im anderen Reiter bleiben unverändert.",
            objectName="PageSubtitle",
        )
        geometry_note.setWordWrap(True)
        layout.addWidget(geometry_note)

        layout.addWidget(QLabel(
            "Cluster und ausgewählte Untersuchungsfälle",
            objectName="CardTitle",
        ))
        self.group_model = SimpleTableModel((
            "Gruppe", "Repräsentativer QEC-Fall", "Fälle", "FINs",
            "Ø Index", "Niedrigster Index",
            "Schwächstes internes Paar", "Gemeinsame ECU:DTC",
            "SSL-Befunde", "Prüfwarnungen",
        ))
        self.group_table = _table(self.group_model, 285)
        self.group_table.selectionModel().currentRowChanged.connect(
            self._group_changed
        )
        layout.addWidget(self.group_table)

        self.group_note = QLabel(objectName="PageSubtitle")
        self.group_note.setWordWrap(True)
        layout.addWidget(self.group_note)
        layout.addWidget(QLabel(
            "Mitglieder der ausgewählten repräsentativen Gruppe",
            objectName="CardTitle",
        ))
        self.member_model = SimpleTableModel((
            "QEC-Fall", "FIN", "Index zum Repräsentanten",
            "Gemeinsame ECU:DTC", "SSL-Endbefund (nur Validierung)",
        ))
        self.member_table = _table(self.member_model, 245)
        layout.addWidget(self.member_table)
        open_row = QHBoxLayout()
        self.open_case_button = QPushButton(
            "Ausgewählten Fall in FIN / Fallanalyse öffnen"
        )
        self.open_case_button.clicked.connect(self._open_selected_case)
        open_row.addWidget(self.open_case_button)
        open_row.addStretch(1)
        layout.addLayout(open_row)

        layout.addWidget(QLabel(
            "TIPS-Vorgänge einem tatsächlichen QEC-Fall zuordnen",
            objectName="CardTitle",
        ))
        tips_intro = QLabel(
            "TIPS-Fallnummern sind Werkstattvorgänge und nicht automatisch "
            "QEC-Schadteilfälle. Ein Vorschlag erfordert dieselbe FIN und "
            "eine zeitliche Nähe zum dokumentierten Tausch. Mehrere QEC-Fälle "
            "derselben FIN müssen EINZELN überprüft werden. Eine manuelle "
            "Bestätigung schreibt nur die ausdrücklich gewählte Verknüpfung; "
            "Original-TIPS-Zeilen bleiben erhalten.",
            objectName="PageSubtitle",
        )
        tips_intro.setWordWrap(True)
        layout.addWidget(tips_intro)
        tips_bar = QHBoxLayout()
        self.review_button = QPushButton("TIPS-Zuordnungsvorschläge prüfen")
        self.review_button.clicked.connect(self.load_tips_review)
        tips_bar.addWidget(self.review_button)
        self.confirm_button = QPushButton("Ausgewählte Verknüpfung bestätigen")
        self.confirm_button.setEnabled(False)
        self.confirm_button.clicked.connect(self._confirm_link)
        tips_bar.addWidget(self.confirm_button)
        tips_bar.addStretch(1)
        layout.addLayout(tips_bar)
        self.review_summary = QLabel(objectName="PageSubtitle")
        self.review_summary.setWordWrap(True)
        layout.addWidget(self.review_summary)
        self.tips_model = SimpleTableModel((
            "TIPS-Vorgang", "FIN", "Erfasst am", "Vorgeschlagener QEC-Fall",
            "Tage zu Tausch", "Prüfstatus",
        ))
        self.tips_table = _table(self.tips_model, 300)
        self.tips_table.selectionModel().currentRowChanged.connect(
            self._tips_changed
        )
        layout.addWidget(self.tips_table)
        self.review_note = QLabel(
            "Nach der manuellen Verknüpfung werden alle Fall-/Clusteransichten "
            "aus der lokalen Datenbank neu geladen. Kundenbeanstandungen "
            "fließen ausschließlich dann in den Score, wenn sie nachweislich "
            "VOR dem untersuchten Tausch dokumentiert sind.",
            objectName="PageSubtitle",
        )
        self.review_note.setWordWrap(True)
        layout.addWidget(self.review_note)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if not self._activated:
            self._activated = True
            self.run_analysis()

    def run_analysis(self) -> None:
        family = self.family.currentData()
        subset = [
            case for case in self.cases
            if self._family_by_id[case.case_id] == family
        ]
        self.plan = select_representative_cases(
            subset,
            budget=self.budget.value(),
            minimum_similarity=self.minimum.value(),
            lookback_days=self.lookback.currentData(),
            dtc_source=self.source.currentData(),
            maximum_common_frequency=self.frequency.currentData(),
        )
        plan = self.plan
        self.summary.setText(
            f"{plan.total_cases} echte QEC-/NTF-Fälle / "
            f"{plan.vehicle_count} verschiedene FINs in dieser Bauteilfamilie · "
            f"Untersuchungsbudget: maximal {plan.budget} Fälle · "
            f"{len(plan.clusters)} Repräsentanten ausgewählt · "
            f"{plan.covered_count} Fälle ({plan.coverage:.1%}) vorläufig "
            f"diagnostisch abgedeckt · {len(plan.unassigned)} nicht zugeordnet · "
            f"{plan.missing_pre_diagnostics} ohne Vorher-DTC · "
            f"{plan.without_swap_anchor} ohne Tauschanker. "
            "Eine Auswahl deckt keine gesicherte Fehlerursache ab. "
            "Die Kriterien sind vorläufig und müssen mit QEC-Fachfällen validiert werden."
        )
        self.group_model.set_rows([
            (
                f"R{group.cluster_id}",
                group.representative_case_id,
                group.case_count,
                group.vehicle_count,
                f"{group.mean_similarity:.1%}",
                f"{group.weakest_representative_similarity:.1%}",
                f"{group.weakest_internal_similarity:.1%}"
                if group.weakest_internal_similarity is not None else "k. A.",
                ", ".join(f"{ecu}:{dtc}" for ecu, dtc in group.common_faults[:5])
                or "Kein über alle Mitglieder gemeinsamer DTC",
                group.with_qec_ssl_finding,
                "; ".join(group.review_warnings) or "Manuell fachlich prüfen",
            )
            for group in plan.clusters
        ])
        self._group_ids = [group.cluster_id for group in plan.clusters]
        self.open_case_button.setEnabled(bool(plan.clusters))
        self.group_note.setText(
            "Wähle eine Gruppe für ihre QEC-/FIN-Mitglieder und "
            "den realen Repräsentanten. "
            "Nicht zugeordnete Fälle werden NICHT als ähnlich ausgegeben."
        )
        self.member_model.set_rows([])
        self.map.set_plan(plan, subset)
        if plan.clusters:
            self.group_table.selectRow(0)
            self._group_changed(self.group_model.index(0, 0), None)

    def _group_changed(self, current, _previous) -> None:
        if self.plan is None or current is None or not current.isValid():
            return
        index = current.row()
        if not 0 <= index < len(self.plan.clusters):
            return
        group = self.plan.clusters[index]
        self.member_model.set_rows([
            (
                member.case_id,
                self.by_id[member.case_id].vin,
                f"{member.similarity:.1%}",
                ", ".join(f"{ecu}:{dtc}" for ecu, dtc in member.shared_faults[:8])
                or "—",
                str(getattr(self.by_id[member.case_id], "qec_ssl_end_finding", "")
                    or "nicht dokumentiert")[:180],
            )
            for member in group.members
        ])
        self.group_note.setText(
            f"R{group.cluster_id} · Repräsentant "
            f"{group.representative_case_id} · "
            f"{group.case_count} QEC-Fälle / {group.vehicle_count} FINs. "
            f"Schwächste Ähnlichkeit zum Repräsentanten: "
            f"{group.weakest_representative_similarity:.1%}; "
            f"schwächstes Paar innerhalb der Gruppe: "
            f"{group.weakest_internal_similarity:.1%}"
            if group.weakest_internal_similarity is not None
            else "Keine interne Paarähnlichkeit berechenbar."
        )
        self.map.set_plan(
            self.plan,
            [case for case in self.cases if (
                self._family_by_id[case.case_id]
            ) == self.family.currentData()],
            group.cluster_id,
        )
        row_index = next(
            (i for i, member in enumerate(group.members)
             if member.case_id == group.representative_case_id), 0,
        )
        self.member_table.selectRow(row_index)

    def _select_case_from_plot(self, case_id: str) -> None:
        if self.plan is None:
            return
        for i, group in enumerate(self.plan.clusters):
            for j, member in enumerate(group.members):
                if member.case_id == case_id:
                    self.group_table.selectRow(i)
                    self.member_table.selectRow(j)
                    return

    def _open_selected_case(self) -> None:
        index = self.member_table.currentIndex()
        if index.isValid():
            case_id = str(self.member_model.rows[index.row()][0])
            self.case_requested.emit(case_id)

    def load_tips_review(self) -> None:
        if self.knowledge is None:
            self.review_summary.setText("Keine lokale Quellenwissen-Datenbank.")
            self.tips_model.set_rows([])
            return
        self.candidates = suggest_tips_links(self.cases, self.knowledge)
        counts = Counter(item.status for item in self.candidates)
        unique_tips = {
            (item.fin, item.tips_case_id, item.creation_date)
            for item in self.candidates
        }
        reviewable = sum(item.can_confirm for item in self.candidates)
        self.review_summary.setText(
            f"{len(unique_tips)} unterschiedliche TIPS-Episoden · "
            f"{reviewable} mögliche QEC-Verknüpfungen zur manuellen Prüfung · "
            f"{counts.get('Bereits verknüpft', 0)} verknüpft · "
            f"{counts.get('Ohne QEC-Fall', 0)} ohne QEC-FIN. "
            "Bei mehreren möglichen QEC-Fällen derselben FIN kann ein TIPS "
            "mehr als einmal als Prüfkandidat erscheinen. "
            "Die Originale werden nicht automatisch zusammengeführt."
        )
        self.tips_model.set_rows([
            (
                item.tips_case_id, item.fin, item.creation_date,
                item.qec_case_id or "Kein QEC-Fall",
                f"{item.delta_days:+.1f}" if item.delta_days is not None else "k. A.",
                item.status,
            )
            for item in self.candidates
        ])
        self.confirm_button.setEnabled(False)

    def _tips_changed(self, current, _previous) -> None:
        if current is None or not current.isValid():
            self.confirm_button.setEnabled(False)
            return
        if 0 <= current.row() < len(self.candidates):
            self.confirm_button.setEnabled(
                self.store is not None
                and self.candidates[current.row()].can_confirm
            )

    def _confirm_link(self) -> None:
        index = self.tips_table.currentIndex()
        if (not index.isValid() or self.store is None
                or index.row() >= len(self.candidates)):
            return
        item = self.candidates[index.row()]
        if not item.can_confirm or not item.qec_case_id:
            return
        response = QMessageBox.question(
            self,
            "TIPS-/QEC-Zuordnung bestätigen",
            f"TIPS {item.tips_case_id} (FIN {item.fin}) mit dem "
            f"QEC-Fall {item.qec_case_id} verbinden?\n"
            f"Tage zum dokumentierten Tausch: {item.delta_days:+.1f}.\n\n"
            "Bitte zuerst Kundenbeanstandung, Reparaturereignis und "
            "weitere QEC-Fälle derselben FIN fachlich überprüfen. "
            "Diese Aktion dokumentiert eine manuelle Zuordnung; "
            "sie bestätigt keine Fehlerursache.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if response != QMessageBox.StandardButton.Yes:
            return
        try:
            case = confirm_tips_link(self.store, item)
        except Exception as exc:
            QMessageBox.warning(
                self, "Zuordnung nicht gespeichert", str(exc)
            )
            return
        self.tips_linked.emit(case.case_id)
