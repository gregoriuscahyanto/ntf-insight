"""Fall-zu-Fall clustering, similarity heatmap and comparable repair histories."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QScrollArea,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ntf_insight.analysis.case_clustering import (
    CaseClusterResult,
    CaseMatch,
    case_match_explanation,
    cluster_diagnostic_cases,
    cluster_insights,
    matches_for,
    resolution_observation,
)
from ntf_insight.app.models.case_similarity_matrix_model import CaseSimilarityMatrixModel
from ntf_insight.app.models.simple_table_model import SimpleTableModel
from ntf_insight.domain.case import NTFCase


class CaseClusterPanel(QWidget):
    """Keep diagnostic matching separate from observed intervention/outcome evidence."""

    case_requested = Signal(str)  # Navigate to real case detail, never a FIN preview.

    def __init__(self, cases: list[NTFCase]) -> None:
        super().__init__()
        self.cases = sorted(cases, key=lambda case: case.case_id)
        self.by_id = {case.case_id: case for case in self.cases}
        self.result: CaseClusterResult | None = None
        self._neighbours: list[CaseMatch] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll)

        content = QWidget()
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(12, 14, 12, 16)
        layout.setSpacing(12)

        intro = QLabel(
            "Fälle mit vergleichbarem Diagnosebild werden gruppiert. "
            "Nur Informationen VOR dem untersuchten Tausch bestimmen die Ähnlichkeit. "
            "Dokumentierte Maßnahmen und Nachtests werden danach separat angezeigt.",
            objectName="PageSubtitle",
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        controls = QHBoxLayout()
        form = QFormLayout()
        self.threshold = QDoubleSpinBox()
        self.threshold.setRange(0.05, 1.00)
        self.threshold.setDecimals(2)
        self.threshold.setSingleStep(0.05)
        self.threshold.setValue(0.65)
        self.threshold.setToolTip(
            "Mindestwert jeder Paarähnlichkeit innerhalb eines Clusters. "
            "Ohne gemeinsame DTCs werden keine Cluster erzeugt."
        )
        form.addRow("Cluster-Schwelle", self.threshold)

        self.focus = QComboBox()
        self.focus.setMinimumWidth(230)
        for case in self.cases:
            self.focus.addItem(
                f"{case.case_id} · {case.vin}",
                case.case_id,
            )
        form.addRow("Vergleichsfall", self.focus)
        controls.addLayout(form)
        controls.addStretch(1)
        self.summary = QLabel(objectName="PageSubtitle")
        self.summary.setWordWrap(True)
        controls.addWidget(self.summary, 1)
        layout.addLayout(controls)

        layout.addWidget(
            QLabel("Cluster-Steckbriefe und Vertreterfälle", objectName="CardTitle")
        )
        profile_hint = QLabel(
            "Ein Clustervertreter ist der diagnostisch ähnlichste reale Fall "
            "innerhalb seiner Gruppe, keine berechnete Musterreparatur. "
            "Nachtests und historische Maßnahmen fließen nicht in die "
            "Clusterbildung ein.",
            objectName="PageSubtitle",
        )
        profile_hint.setWordWrap(True)
        layout.addWidget(profile_hint)
        self.cluster_profile_model = SimpleTableModel(
            (
                "Cluster", "Fälle", "Versch. FINs",
                "Repräsentativer Fall", "Gemeinsame ECU:DTCs",
                "Schwächstes Paar", "Merkmalsabdeckung",
                "Fälle mit Vor-/Nachtest",
            )
        )
        self.cluster_profile_table = QTableView()
        self.cluster_profile_table.setModel(self.cluster_profile_model)
        self._configure_table(self.cluster_profile_table, 170, stretch=False)
        for col, width in enumerate((90, 55, 85, 155, 240, 110, 130, 180)):
            self.cluster_profile_table.setColumnWidth(col, width)
        self.cluster_profile_table.clicked.connect(self._focus_cluster_representative)
        layout.addWidget(self.cluster_profile_table)

        layout.addWidget(
            QLabel("Fall-Cluster (hierarchisch, Complete-Link)", objectName="CardTitle")
        )
        self.cluster_model = SimpleTableModel(
            ("Cluster", "Fall", "FIN / VIN", "Bauteil", "Gemeinsame DTCs")
        )
        self.cluster_table = QTableView()
        self.cluster_table.setModel(self.cluster_model)
        self._configure_table(self.cluster_table, 170)
        self.cluster_table.doubleClicked.connect(self._open_cluster_case)
        layout.addWidget(self.cluster_table)

        matrix_header = QHBoxLayout()
        matrix_header.addWidget(QLabel("Ähnlichkeitsmatrix", objectName="CardTitle"))
        matrix_header.addStretch()
        self.matrix_note = QLabel(objectName="PageSubtitle")
        matrix_header.addWidget(self.matrix_note)
        layout.addLayout(matrix_header)

        self.matrix = QTableView()
        self.matrix.setAlternatingRowColors(False)
        self.matrix.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.matrix.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.matrix.setMinimumHeight(270)
        self.matrix.setMaximumHeight(350)
        self.matrix.horizontalHeader().setDefaultSectionSize(92)
        self.matrix.verticalHeader().setDefaultSectionSize(30)
        layout.addWidget(self.matrix)

        neighbour_header = QHBoxLayout()
        neighbour_header.addWidget(
            QLabel("Ähnliche Fälle und dokumentierte Maßnahmen", objectName="CardTitle")
        )
        neighbour_header.addStretch(1)
        self.open_case_button = QPushButton("Vergleichsfall öffnen")
        self.open_case_button.setEnabled(False)
        self.open_case_button.setToolTip(
            "Öffnet den ausgewählten historischen Fall in „Fälle / FIN“. "
            "Die Ähnlichkeit ist kein Nachweis einer passenden Reparatur."
        )
        self.open_case_button.clicked.connect(self._open_selected_neighbor)
        neighbour_header.addWidget(self.open_case_button)
        layout.addLayout(neighbour_header)
        caveat = QLabel(
            "Die Maßnahmen sind historische Hinweise, keine automatisch validierten "
            "Lösungsempfehlungen. „DTC nicht erneut beobachtet“ bedeutet nicht, "
            "dass die Ursache eindeutig behoben wurde.",
            objectName="PageSubtitle",
        )
        caveat.setWordWrap(True)
        layout.addWidget(caveat)

        self.neighbor_model = SimpleTableModel(
            ("Vergleichsfall", "Ähnlichkeit", "Datengrundlage", "Gemeinsame DTCs",
             "Dokumentierte Maßnahmen", "Nachtest / Beobachtung", "Cluster")
        )
        self.neighbor_table = QTableView()
        self.neighbor_table.setModel(self.neighbor_model)
        self._configure_table(self.neighbor_table, 230, stretch=False)
        for col, width in enumerate((145, 110, 125, 200, 270, 370, 95)):
            self.neighbor_table.setColumnWidth(col, width)
        self.neighbor_table.clicked.connect(self._show_neighbor_detail)
        # Update explanations for keyboard navigation as well as mouse clicks.
        self.neighbor_table.selectionModel().currentRowChanged.connect(
            lambda current, _previous: self._show_neighbor_detail(current)
        )
        self.neighbor_table.doubleClicked.connect(self._open_neighbor_double_click)
        layout.addWidget(self.neighbor_table)

        self.detail = QLabel(
            "Vergleichsfall auswählen, um die diagnostischen Gemeinsamkeiten und "
            "Maßnahmen vollständig anzuzeigen.",
            objectName="PageSubtitle",
        )
        self.detail.setWordWrap(True)
        self.detail.setTextInteractionFlags(
            self.detail.textInteractionFlags()
            | Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self.detail)
        layout.addStretch(1)

        self.threshold.valueChanged.connect(self._rebuild)
        self.focus.currentIndexChanged.connect(self._update_focus)
        self._rebuild()

    @staticmethod
    def _configure_table(table: QTableView, height: int, *, stretch: bool = True) -> None:
        table.setMaximumHeight(height)
        table.setMinimumHeight(min(height, 140))
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        if stretch:
            table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        else:
            table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)

    def _rebuild(self) -> None:
        if not self.cases:
            self.summary.setText(
                "0 echte QEC-/NTF-Fälle. Ein FIN-QuickTest allein ist noch "
                "kein Schadteilfall. Importiere Fälle über „Datenquellen“ "
                "oder erfasse einen nachgewiesenen Fall unter „Fälle / FIN“."
            )
            self.cluster_profile_model.set_rows([])
            self.cluster_model.set_rows([])
            self._update_focus()
            return
        self.result = cluster_diagnostic_cases(
            self.cases, threshold=self.threshold.value()
        )
        profiles = cluster_insights(self.result, self.cases)
        self._cluster_profiles = profiles
        self.cluster_profile_model.set_rows([
            (
                f"Cluster {profile.cluster_id}",
                profile.case_count,
                profile.vehicle_count,
                profile.representative_case_id,
                ", ".join(
                    f"{ecu}:{code}" for ecu, code in profile.common_faults
                ) or "Keine allen Fällen gemeinsame DTC-Kombination",
                f"{profile.weakest_pair_similarity:.0%}",
                f"{profile.mean_feature_coverage:.0%}",
                f"{profile.cases_with_pre_and_post_test}/{profile.case_count}",
            )
            for profile in profiles
        ])
        rows = []
        for cluster in self.result.clusters:
            common = ", ".join(
                f"{ecu}:{code}" for ecu, code in cluster.common_faults
            ) or "Keine für alle identische DTC-Kombination"
            for case_id in cluster.case_ids:
                case = self.by_id[case_id]
                rows.append((
                    f"Cluster {cluster.cluster_id}", case_id, case.vin,
                    case.component_type, common,
                ))
        for case_id in self.result.unassigned:
            case = self.by_id[case_id]
            rows.append(("Einzelfall / unzugeordnet", case_id, case.vin, case.component_type, "—"))
        self.cluster_model.set_rows(rows)

        if len(self.cases) < 2:
            count_description = (
                "Mindestens zwei reale FIN/Fälle werden für einen "
                "Fall-zu-Fall-Vergleich benötigt."
            )
        else:
            count_description = (
                f"{len(self.result.clusters)} Cluster mit ≥2 Fällen · "
                f"{len(self.result.unassigned)} Einzelfälle/noch unzugeordnet. "
                "Keine Cluster auf Basis unklarer Tauschanker."
            )
        self.summary.setText(
            f"{len(self.cases)} echte Fälle · {count_description}"
        )
        self._update_focus()

    def _update_focus(self) -> None:
        case_id = self.focus.currentData()
        if not isinstance(case_id, str) or self.result is None:
            self.neighbor_model.set_rows([])
            self._neighbours = []
            self.detail.setText(
                "Mindestens zwei echte FIN-/NTF-Fälle mit vergleichbaren "
                "Diagnoseinformationen werden benötigt. Mehrere QuickTests "
                "derselben FIN erzeugen keine zusätzlichen Fälle."
            )
            self.open_case_button.setEnabled(False)
            return

        neighbours = matches_for(case_id, self.result.matches)
        neighbours = [item for item in neighbours if item.score is not None]
        self._neighbours = neighbours[:30]
        self.open_case_button.setEnabled(False)

        rows = []
        for item in self._neighbours:
            other_id = item.right_case_id if item.left_case_id == case_id else item.left_case_id
            candidate = self.by_id[other_id]
            observed = resolution_observation(candidate)
            measures = " · ".join(observed.measures) if observed.measures else "Keine Maßnahme dokumentiert"
            cluster_number = self.result.cluster_for(other_id)
            rows.append((
                other_id,
                f"{item.score:.0%}",
                f"{item.coverage:.0%}",
                ", ".join(f"{ecu}:{code}" for ecu, code in item.shared_faults) or "—",
                measures,
                observed.outcome,
                f"Cluster {cluster_number}" if cluster_number else "Einzelfall",
            ))
        self.neighbor_model.set_rows(rows)
        if not rows:
            self.detail.setText(
                "Kein diagnostisch vergleichbarer Fall vorhanden. Fehlende DTC-/Beanstandungsdaten "
                "werden nicht als 100 % Übereinstimmung gewertet."
            )
        else:
            own_cluster = self.result.cluster_for(case_id)
            self.detail.setText(
                f"Fokus: {case_id} · "
                + (f"Cluster {own_cluster}" if own_cluster else "noch keinem Cluster zugeordnet")
                + ". Vergleichsfall auswählen, um auch Unterschiede und "
                "dokumentierte Nachtests zu prüfen."
            )

        # Keep the matrix useful even for larger future datasets by focusing on the
        # selected case and its nearest neighbours rather than a huge unreadable grid.
        closest = [
            match.right_case_id if match.left_case_id == case_id else match.left_case_id
            for match in neighbours
        ]
        displayed = [case_id, *closest[:23]]
        # Fill the remaining space with incomparable cases as well. A visible
        # "k. A." is more honest than quietly omitting cases without data.
        if len(displayed) < 24:
            displayed.extend(
                other_id
                for other_id in sorted(self.by_id)
                if other_id not in displayed
            )
        displayed = displayed[:24]
        self.matrix_model = CaseSimilarityMatrixModel(
            displayed, self.result.matches
        )
        self.matrix.setModel(self.matrix_model)
        self.matrix.resizeColumnsToContents()
        self.matrix.resizeRowsToContents()
        self.matrix_note.setText(
            f"{len(displayed)} von {len(self.cases)} Fällen (Fokus + nächste Nachbarn)"
        )

    def focus_case(self, case_id: str) -> bool:
        """Focus one real case, suitable for navigation from the FIN page."""
        index = self.focus.findData(case_id)
        if index < 0:
            return False
        self.focus.setCurrentIndex(index)
        self._update_focus()
        return True

    def _focus_cluster_representative(self, index) -> None:
        if not index.isValid() or self.result is None:
            return
        if not 0 <= index.row() < len(self._cluster_profiles):
            return
        self.focus_case(self._cluster_profiles[index.row()].representative_case_id)

    def _open_cluster_case(self, index) -> None:
        if not index.isValid():
            return
        case_id = self.cluster_model.rows[index.row()][1]
        if isinstance(case_id, str) and case_id in self.by_id:
            self.case_requested.emit(case_id)

    def _selected_neighbor_case(self) -> str | None:
        index = self.neighbor_table.currentIndex()
        if not index.isValid() or not 0 <= index.row() < len(self._neighbours):
            return None
        match = self._neighbours[index.row()]
        focused = self.focus.currentData()
        return (
            match.right_case_id if match.left_case_id == focused
            else match.left_case_id
        )

    def _open_selected_neighbor(self) -> None:
        case_id = self._selected_neighbor_case()
        if case_id is not None and case_id in self.by_id:
            self.case_requested.emit(case_id)

    def _open_neighbor_double_click(self, index) -> None:
        if index.isValid():
            self.neighbor_table.selectRow(index.row())
            self._open_selected_neighbor()

    def _show_neighbor_detail(self, index) -> None:
        if not index.isValid() or not 0 <= index.row() < len(self._neighbours):
            self.open_case_button.setEnabled(False)
            self.detail.setText(
                "Vergleichsfall auswählen, um die diagnostischen Gemeinsamkeiten "
                "und dokumentierten Maßnahmen zu sehen."
            )
            return
        match = self._neighbours[index.row()]
        focused = self.focus.currentData()
        other_id = (
            match.right_case_id if match.left_case_id == focused
            else match.left_case_id
        )
        observed = resolution_observation(self.by_id[other_id])
        measures = "; ".join(observed.measures) or "Keine dokumentierte Maßnahme"
        own_fin = self.by_id[focused].vin
        other_fin = self.by_id[other_id].vin
        related_fin = (
            "\nHinweis: Beide Fälle betreffen dieselbe FIN; ein wiederholter "
            "Werkstattvorgang kann unabhängige Bestätigung vortäuschen."
            if own_fin == other_fin else ""
        )
        self.detail.setText(
            f"Fall {other_id} (FIN {other_fin})\n"
            + case_match_explanation(
                self.by_id[focused], self.by_id[other_id], match
            )
            + "\nDokumentierte Maßnahmen: " + measures
            + "\nBeobachteter Verlauf nach letzter Maßnahme: " + observed.outcome
            + related_fin
        )
        self.open_case_button.setEnabled(True)
