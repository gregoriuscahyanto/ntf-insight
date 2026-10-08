"""Fall-zu-Fall clustering, similarity heatmap and comparable repair histories."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QScrollArea,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ntf_insight.analysis.case_clustering import (
    CaseClusterResult,
    CaseMatch,
    cluster_diagnostic_cases,
    matches_for,
    resolution_observation,
)
from ntf_insight.app.models.case_similarity_matrix_model import CaseSimilarityMatrixModel
from ntf_insight.app.models.simple_table_model import SimpleTableModel
from ntf_insight.domain.case import NTFCase


class CaseClusterPanel(QWidget):
    """Keep diagnostic matching separate from observed intervention/outcome evidence."""

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

        layout.addWidget(QLabel("Fall-Cluster (hierarchisch, Complete-Link)", objectName="CardTitle"))
        self.cluster_model = SimpleTableModel(
            ("Cluster", "Fall", "FIN / VIN", "Bauteil", "Gemeinsame DTCs")
        )
        self.cluster_table = QTableView()
        self.cluster_table.setModel(self.cluster_model)
        self._configure_table(self.cluster_table, 170)
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

        layout.addWidget(QLabel("Ähnliche Fälle und dokumentierte Maßnahmen", objectName="CardTitle"))
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
             "Dokumentierte Maßnahmen", "Nachtest / Beobachtung")
        )
        self.neighbor_table = QTableView()
        self.neighbor_table.setModel(self.neighbor_model)
        self._configure_table(self.neighbor_table, 230, stretch=False)
        for col, width in enumerate((130, 115, 120, 200, 270, 355)):
            self.neighbor_table.setColumnWidth(col, width)
        self.neighbor_table.clicked.connect(self._show_neighbor_detail)
        layout.addWidget(self.neighbor_table)

        self.detail = QLabel(
            "Vergleichsfall auswählen, um die diagnostischen Gemeinsamkeiten und "
            "Maßnahmen vollständig anzuzeigen.",
            objectName="PageSubtitle",
        )
        self.detail.setWordWrap(True)
        self.detail.setTextInteractionFlags(
            self.detail.textInteractionFlags()
            | self.detail.TextInteractionFlag.TextSelectableByMouse
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
            self.summary.setText("Noch keine Fälle vorhanden. Fälle / FIN zum Anlegen öffnen.")
            self.cluster_model.set_rows([])
            self._update_focus()
            return
        self.result = cluster_diagnostic_cases(
            self.cases, threshold=self.threshold.value()
        )
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

        self.summary.setText(
            f"{len(self.cases)} Fälle · {len(self.result.clusters)} Cluster mit ≥2 Fällen · "
            f"{len(self.result.unassigned)} unzugeordnet"
        )
        self._update_focus()

    def _update_focus(self) -> None:
        case_id = self.focus.currentData()
        if not isinstance(case_id, str) or self.result is None:
            self.neighbor_model.set_rows([])
            self._neighbours = []
            self.detail.setText("Wähle einen Fall mit Diagnoseinformationen.")
            return

        neighbours = matches_for(case_id, self.result.matches)
        neighbours = [item for item in neighbours if item.score is not None]
        self._neighbours = neighbours[:30]

        rows = []
        for item in self._neighbours:
            other_id = item.right_case_id if item.left_case_id == case_id else item.left_case_id
            candidate = self.by_id[other_id]
            observed = resolution_observation(candidate)
            measures = " · ".join(observed.measures) if observed.measures else "Keine Maßnahme dokumentiert"
            rows.append((
                other_id,
                f"{item.score:.0%}",
                f"{item.coverage:.0%}",
                ", ".join(f"{ecu}:{code}" for ecu, code in item.shared_faults) or "—",
                measures,
                observed.outcome,
            ))
        self.neighbor_model.set_rows(rows)
        if not rows:
            self.detail.setText(
                "Kein diagnostisch vergleichbarer Fall vorhanden. Fehlende DTC-/Beanstandungsdaten "
                "werden nicht als 100 % Übereinstimmung gewertet."
            )
        else:
            self.detail.setText("Vergleichsfall in der unteren Tabelle auswählen.")

        # Keep the matrix useful even for larger future datasets by focusing on the
        # selected case and its nearest neighbours rather than a huge unreadable grid.
        closest = [
            match.right_case_id if match.left_case_id == case_id else match.left_case_id
            for match in neighbours
        ]
        displayed = [case_id, *closest[:23]]
        self.matrix_model = CaseSimilarityMatrixModel(
            displayed, self.result.matches
        )
        self.matrix.setModel(self.matrix_model)
        self.matrix.resizeColumnsToContents()
        self.matrix.resizeRowsToContents()
        self.matrix_note.setText(
            f"{len(displayed)} von {len(self.cases)} Fällen (Fokus + nächste Nachbarn)"
        )

    def _show_neighbor_detail(self, index) -> None:
        if not index.isValid() or index.row() >= len(self._neighbours):
            return
        match = self._neighbours[index.row()]
        focused = self.focus.currentData()
        other_id = match.right_case_id if match.left_case_id == focused else match.left_case_id
        observed = resolution_observation(self.by_id[other_id])
        measures = "; ".join(observed.measures) or "Keine dokumentierte Maßnahme"
        self.detail.setText(
            f"Fall {other_id}: {match.reason}\n"
            f"Diagnostische Ähnlichkeit: {match.score:.0%} · "
            f"Merkmalsabdeckung: {match.coverage:.0%}\n"
            f"Dokumentierte Maßnahmen: {measures}\n"
            f"Beobachteter Verlauf: {observed.outcome}"
        )
