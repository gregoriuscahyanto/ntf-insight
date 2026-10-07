"""DTC cluster visualization plus transparent case-similarity baseline."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QAbstractItemView,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QSpinBox,
    QTabWidget,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ntf_insight.analysis.dtc_clusters import build_dtc_network
from ntf_insight.analysis.similarity import all_pairwise_similarities
from ntf_insight.app.models.simple_table_model import SimpleTableModel
from ntf_insight.app.widgets.dtc_cluster_graph import DTCClusterGraph
from ntf_insight.storage.repositories import CaseRepository


class SimilarityPage(QWidget):
    def __init__(self, repository: CaseRepository) -> None:
        super().__init__()
        self.repository = repository
        self.network = build_dtc_network(repository.list_cases())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(14)

        layout.addWidget(QLabel("DTC-Cluster", objectName="PageTitle"))
        subtitle = QLabel(
            "Das Netzwerk visualisiert DTCs, die in denselben Fällen gemeinsam auftreten. "
            "Die Cluster sind aktuell deskriptiv und erklärbar; sie sind noch kein HDBSCAN-/ML-Ergebnis.",
            objectName="PageSubtitle",
        )
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        tabs = QTabWidget()
        tabs.addTab(self._build_network_tab(), "DTC-Netzwerk")
        tabs.addTab(self._build_similarity_tab(), "Fallähnlichkeit")
        layout.addWidget(tabs, 1)
        self.tabs = tabs

    def _build_network_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 14, 12, 12)
        layout.setSpacing(10)

        controls = QHBoxLayout()
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)

        self.min_cases = QSpinBox()
        self.min_cases.setRange(1, 999)
        self.min_cases.setValue(1)
        self.min_cases.setToolTip("Nur DTCs anzeigen, die in mindestens so vielen Fällen vorkommen.")
        form.addRow("Min. Fälle", self.min_cases)

        self.max_nodes = QSpinBox()
        self.max_nodes.setRange(5, 100)
        self.max_nodes.setValue(30)
        self.max_nodes.setToolTip("Begrenzt die Anzahl dargestellter DTC-Knoten für eine lesbare Grafik.")
        form.addRow("Max. DTCs", self.max_nodes)

        controls.addLayout(form)
        controls.addSpacing(20)
        self.network_summary = QLabel(objectName="PageSubtitle")
        self.network_summary.setWordWrap(True)
        controls.addWidget(self.network_summary, 1)
        layout.addLayout(controls)

        self.cluster_graph = DTCClusterGraph()
        layout.addWidget(self.cluster_graph, 1)

        hint = QLabel(
            "Knoten = ECU:DTC · Knotengröße = Anzahl Fälle · Verbindung = gemeinsames Auftreten im selben Fall. "
            "Mausrad zoomt, Ziehen verschiebt die Ansicht; Details stehen im Tooltip.",
            objectName="PageSubtitle",
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.min_cases.valueChanged.connect(self._refresh_network)
        self.max_nodes.valueChanged.connect(self._refresh_network)
        self._refresh_network()
        return page

    def _refresh_network(self) -> None:
        nodes, edges, clusters = self.cluster_graph.set_network(
            self.network,
            min_cases=self.min_cases.value(),
            max_nodes=self.max_nodes.value(),
        )
        self.network_summary.setText(
            f"{nodes} DTCs · {edges} Koauftretens-Beziehungen · {clusters} sichtbare Cluster"
        )

    def _build_similarity_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 14, 12, 12)
        layout.setSpacing(10)

        explanation = QLabel(
            "Erklärbare Basis-Ähnlichkeit zwischen Fällen. Lieferant und Charge werden bewusst nicht als "
            "Ähnlichkeitsmerkmale verwendet.",
            objectName="PageSubtitle",
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)

        rows = []
        for result in all_pairwise_similarities(self.repository.list_cases()):
            shared_faults = ", ".join(f"{ecu}:{dtc}" for ecu, dtc in result.shared_faults)
            rows.append(
                (
                    result.left_case_id,
                    result.right_case_id,
                    f"{result.score:.0%}",
                    shared_faults or None,
                    ", ".join(result.shared_ecus) or None,
                    "Ja" if result.same_recurrence_pattern else "Nein",
                )
            )

        model = SimpleTableModel(
            (
                "Fall A",
                "Fall B",
                "Ähnlichkeit",
                "Gemeinsame DTCs",
                "Gemeinsame Steuergeräte",
                "Gleiches Wiederholungsmuster",
            ),
            rows,
        )
        table = QTableView()
        table.setModel(model)
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(table, 1)
        self.model = model
        return page
