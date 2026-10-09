"""Visible, auditable, optional ML exploration; does not replace strict clusters."""
from __future__ import annotations

import csv

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QGridLayout, QHBoxLayout, QLabel, QMessageBox,
    QPushButton, QScrollArea, QSpinBox, QVBoxLayout, QWidget,
)

from ntf_insight.analysis.case_clustering import _component_key, signature_for
from ntf_insight.analysis.hdbscan_clustering import (
    MLClusterResult, cluster_hdbscan_cases,
)
from ntf_insight.analysis.qec_findings import qec_ssl_finding_label
from ntf_insight.app.models.simple_table_model import SimpleTableModel
from ntf_insight.app.widgets.hdbscan_scatter import HDBSCANScatter
from ntf_insight.app.widgets.representative_case_panel import _table
from ntf_insight.domain.case import NTFCase


class HDBSCANPanel(QWidget):
    """Experimental sklearn HDBSCAN on real QEC pre-intervention signatures."""

    case_requested = Signal(str)

    def __init__(self, cases: list[NTFCase]) -> None:
        super().__init__()
        self.cases = sorted(cases, key=lambda case: case.case_id)
        self.by_id = {case.case_id: case for case in self.cases}
        self.family_map = {
            case.case_id: _component_key(case) for case in self.cases
        }
        self.result: MLClusterResult | None = None
        self._activated = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        layout.addWidget(scroll)
        container = QWidget()
        scroll.setWidget(container)
        body = QVBoxLayout(container)
        body.setContentsMargins(22, 18, 22, 25)
        body.setSpacing(10)
        body.addWidget(QLabel(
            "Experimentelle ML-Clusterung mit HDBSCAN",
            objectName="PageTitle",
        ))
        lead = QLabel(
            "HDBSCAN erkennt Dichtegruppen ohne vorgegebene Clusterzahl. "
            "Eingaben: vor dem Tausch belegte ECU:DTC, Beanstandungs-Tokens, "
            "ECU-/Softwarestände und Fahrzeugkontext, als IDF-gewichtete "
            "Mehransichtsvektoren. SSL-Endbefunde und Reparaturergebnisse "
            "sind ausschließlich NACH der Gruppierung zur Prüfung sichtbar. "
            "Keine Gruppe beweist dieselbe technische Fehlerursache.",
            objectName="PageSubtitle",
        )
        lead.setWordWrap(True)
        body.addWidget(lead)

        grid = QGridLayout()
        grid.addWidget(QLabel("Bauteilfamilie"), 0, 0)
        self.family = QComboBox()
        labels = {
            self.family_map[case.case_id]: case.component_type for case in self.cases
        }
        for key in sorted(labels):
            count = sum(v == key for v in self.family_map.values())
            self.family.addItem(f"{labels[key]} ({count})", key)
        grid.addWidget(self.family, 0, 1)
        grid.addWidget(QLabel("Min. Clustergröße"), 0, 2)
        self.min_cluster_size = QSpinBox()
        self.min_cluster_size.setRange(2, 25)
        self.min_cluster_size.setValue(3)
        self.min_cluster_size.setToolTip(
            "Kleinste mögliche Dichtegruppe (Standard 3 QEC-Fälle). "
            "Eine größere Zahl begünstigt wenige, größere Gruppen."
        )
        grid.addWidget(self.min_cluster_size, 0, 3)
        grid.addWidget(QLabel("MinSamples / Konservativität"), 0, 4)
        self.min_samples = QSpinBox()
        self.min_samples.setRange(1, 25)
        self.min_samples.setValue(2)
        self.min_samples.setToolTip(
            "Mindestdichte-Nachbarschaft inklusive des Falls selbst, "
            "größer = mehr Ausreißer. Scikit-learn-HDBSCAN."
        )
        grid.addWidget(self.min_samples, 0, 5)

        grid.addWidget(QLabel("DTC-Quellen"), 1, 0)
        self.source = QComboBox()
        self.source.addItem("QuickTest + AutoExport", "all")
        self.source.addItem("Nur QuickTest", "quicktest")
        self.source.addItem("Nur AutoExport", "autoexport")
        grid.addWidget(self.source, 1, 1)
        grid.addWidget(QLabel("Vor-Tausch-Zeitraum"), 1, 2)
        self.lookback = QComboBox()
        self.lookback.addItem("Gesamte Vorher-Historie", None)
        for days in (30, 90, 180, 365):
            self.lookback.addItem(f"Letzte {days} Tage", days)
        grid.addWidget(self.lookback, 1, 3)
        body.addLayout(grid)

        actions = QHBoxLayout()
        self.run_button = QPushButton("HDBSCAN berechnen")
        self.run_button.clicked.connect(self.run_analysis)
        actions.addWidget(self.run_button)
        self.export_button = QPushButton("ML-Gruppen lokal als CSV exportieren")
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self.export_csv)
        actions.addWidget(self.export_button)
        self.zoom_button = QPushButton("Zoom zurücksetzen")
        actions.addWidget(self.zoom_button)
        actions.addStretch(1)
        body.addLayout(actions)

        self.summary = QLabel(objectName="PageSubtitle")
        self.summary.setWordWrap(True)
        body.addWidget(self.summary)
        self.map = HDBSCANScatter()
        self.map.case_picked.connect(self._picked)
        self.zoom_button.clicked.connect(self.map.reset_zoom)
        body.addWidget(self.map)
        note = QLabel(
            "2D-MDS aus EXAKT der hochdimensionalen Distanzmatrix, auf der "
            "HDBSCAN arbeitet (keine Clusterung der 2D-Pixel). "
            "Großes Symbol H1/H2 = ausgewählter echter QEC-Medoid; "
            "graue Punkte = HDBSCAN-Rauschen. Nicht darstellbare Fälle "
            "ohne Vorher-Diagnose bleiben ausdrücklich außerhalb des Plots. "
            "Die 2D-Entfernung und die HDBSCAN-Zugehörigkeitsstärke sind "
            "KEINE Wahrscheinlichkeit gleicher Fehlerursachen.",
            objectName="PageSubtitle",
        )
        note.setWordWrap(True)
        body.addWidget(note)
        body.addWidget(QLabel(
            "Gefundene ML-Gruppen (explorativ)",
            objectName="CardTitle",
        ))
        self.group_model = SimpleTableModel((
            "Gruppe", "QEC-Repräsentant", "Fälle", "FINs",
            "Ø Cosinus zu Rep. (ohne Selbst)", "Schwächstes internes Paar",
            "Min. HDBSCAN-Zugehörigkeit", "Gemeinsame ECU:DTC",
            "Häufige ECU:DTC", "QEC SSL-Endbefunde", "Prüfwarnungen",
        ))
        self.group_table = _table(self.group_model, 275)
        self.group_table.selectionModel().currentRowChanged.connect(
            self._group_changed
        )
        body.addWidget(self.group_table)
        self.group_note = QLabel(objectName="PageSubtitle")
        self.group_note.setWordWrap(True)
        body.addWidget(self.group_note)
        body.addWidget(QLabel(
            "Fälle der ausgewählten HDBSCAN-Gruppe",
            objectName="CardTitle",
        ))
        self.member_model = SimpleTableModel((
            "QEC-Fall", "FIN", "Cosinus zum Medoid",
            "HDBSCAN-Stabilität (keine Ursachenchance)",
            "Gemeinsame ECU:DTC zum Medoid", "SSL-Endbefund (post hoc)",
        ))
        self.member_table = _table(self.member_model, 245)
        body.addWidget(self.member_table)
        open_buttons = QHBoxLayout()
        self.open_button = QPushButton("Ausgewählten Fall analysieren")
        self.open_button.clicked.connect(self.open_selected_case)
        open_buttons.addWidget(self.open_button)
        open_buttons.addStretch(1)
        body.addLayout(open_buttons)
        body.addWidget(QLabel(
            "Ausreißer und Fälle ohne ausreichende Vor-Tausch-Diagnose",
            objectName="CardTitle",
        ))
        self.noise_model = SimpleTableModel(("QEC-Fall", "FIN", "Grund"))
        self.noise_table = _table(self.noise_model, 260)
        self.noise_table.doubleClicked.connect(self._open_noise_case)
        body.addWidget(self.noise_table)
        footer = QLabel(
            "Interpretation: Dichtecluster können Fälle mit unterschiedlichen "
            "technischen Fehlerursachen enthalten. Besonders problematisch sind "
            "fehlende gemeinsame ECU:DTC-Kernmerkmale, unterschiedliche "
            "SSL-Endbefunde, schwache interne Ähnlichkeit oder instabile "
            "Gruppenzugehörigkeit. HDBSCAN ist ein experimentelles, "
            "unüberwachtes ML-Modell – kein Reparaturempfehlungssystem. "
            "Originaldaten bleiben lokal und unverändert.",
            objectName="PageSubtitle",
        )
        footer.setWordWrap(True)
        body.addWidget(footer)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if not self._activated:
            self._activated = True
            self.run_analysis()

    def _subset(self) -> list[NTFCase]:
        family = self.family.currentData()
        return [
            case for case in self.cases
            if self.family_map[case.case_id] == family
        ]

    def run_analysis(self) -> None:
        subset = self._subset()
        try:
            result = cluster_hdbscan_cases(
                subset,
                min_cluster_size=self.min_cluster_size.value(),
                min_samples=self.min_samples.value(),
                dtc_source=self.source.currentData() or "all",
                lookback_days=self.lookback.currentData(),
            )
        except ValueError as exc:
            self.summary.setText(f"HDBSCAN nicht berechenbar: {exc}")
            self.group_model.set_rows([])
            self.member_model.set_rows([])
            self.noise_model.set_rows([])
            self.result = None
            self.export_button.setEnabled(False)
            return
        self.result = result
        self.summary.setText(
            f"{result.case_count} QEC-Fälle / {result.vehicle_count} FINs · "
            f"{len(result.eligible_case_ids)} mit Tauschanker und Vorher-DTC · "
            f"{len(result.excluded_case_ids)} ohne geeignete Diagnosebasis · "
            f"{result.feature_count} TF-IDF-Merkmalsspalten · "
            f"{len(result.clusters)} HDBSCAN-Gruppen (automatisch) · "
            f"{result.clustered_count} Fälle ({result.coverage:.1%}) "
            f"explorativ gruppiert · "
            f"{len(result.noise_case_ids)} HDBSCAN-Ausreißer. "
            f"Parameter: min_cluster_size={result.min_cluster_size}, "
            f"min_samples={result.min_samples}; "
            f"Quelle: {self.source.currentText()}; "
            f"Zeitfenster: {self.lookback.currentText()}. "
            "Die Gruppenanzahl ist keine Gütebewertung."
        )
        self.group_model.set_rows([
            (
                f"H{group.cluster_id}", group.representative_case_id,
                group.case_count, group.vehicle_count,
                f"{group.mean_to_representative:.1%}",
                f"{group.weakest_internal_similarity:.1%}",
                f"{group.min_membership_strength:.1%}",
                ", ".join(f"{e}:{d}" for e, d in group.common_faults[:8])
                or "Kein durchgehender gemeinsamer DTC",
                ", ".join(
                    f"{e}:{d} ({n}/{group.case_count})"
                    for (e, d), n in group.majority_faults[:6]
                ) or "Keine häufigen gemeinsamen DTCs",
                group.ssl_finding_count,
                "; ".join(group.warnings) or "Fachliche Ursachenprüfung erforderlich",
            ) for group in result.clusters
        ])
        sigs = {
            c.case_id: signature_for(
                c, dtc_source=result.dtc_source,
                lookback_days=result.lookback_days,
            ) for c in subset
        }
        self.noise_model.set_rows([
            (
                cid, self.by_id[cid].vin,
                "HDBSCAN-Rauschen / keine stabile Dichtegruppe",
            ) for cid in result.noise_case_ids
        ] + [
            (
                cid, self.by_id[cid].vin,
                "Tauschanker fehlt" if not sigs[cid].has_replacement_anchor
                else "Keine belegte Vor-Tausch-ECU:DTC-Diagnose",
            ) for cid in result.excluded_case_ids
        ])
        self.member_model.set_rows([])
        self.open_button.setEnabled(bool(result.clusters))
        self.export_button.setEnabled(bool(result.clusters))
        self.map.set_result(result, subset)
        if result.clusters:
            self.group_table.selectRow(0)
            self._group_changed(self.group_model.index(0, 0), None)
        else:
            self.group_note.setText(
                "HDBSCAN findet unter diesen Parametern keine Dichtegruppe. "
                "Die Fälle sind nicht verloren: sie stehen als Ausreißer "
                "oder Fälle ohne Diagnosebasis unten. Parametervergleich "
                "ist eine Sensitivitätsprüfung, keine nachträgliche Beweisführung."
            )

    def _group_changed(self, index, _previous) -> None:
        if not index or not index.isValid() or self.result is None:
            return
        i = index.row()
        if not 0 <= i < len(self.result.clusters):
            return
        group = self.result.clusters[i]
        self.member_model.set_rows([
            (
                member.case_id, self.by_id[member.case_id].vin,
                f"{member.similarity_to_representative:.1%}",
                f"{member.membership_strength:.1%}",
                ", ".join(f"{ecu}:{dtc}" for ecu, dtc in member.shared_faults[:8])
                or "—",
                qec_ssl_finding_label(self.by_id[member.case_id])[:180],
            )
            for member in group.members
        ])
        self.group_note.setText(
            f"H{group.cluster_id}: {group.case_count} QEC-Fälle / "
            f"{group.vehicle_count} FINs · Repräsentant: "
            f"{group.representative_case_id} · schwächstes internes "
            f"Cosinus-Paar: {group.weakest_internal_similarity:.1%} · "
            f"kleinste Dichtestabilität: "
            f"{group.min_membership_strength:.1%}. "
            "Diese Kennzahlen sind keine Ursachenwahrscheinlichkeit. "
            + ("Warnungen: " + "; ".join(group.warnings)
               if group.warnings else "Fachliche SSL-/Ursachenprüfung offen.")
        )
        self.map.set_result(self.result, self._subset(), group.cluster_id)
        row = next(
            (i for i, item in enumerate(group.members)
             if item.case_id == group.representative_case_id), 0
        )
        self.member_table.selectRow(row)

    def _picked(self, case_id: str) -> None:
        if self.result is None:
            return
        for i, group in enumerate(self.result.clusters):
            for j, member in enumerate(group.members):
                if member.case_id == case_id:
                    self.group_table.selectRow(i)
                    self.member_table.selectRow(j)
                    return
        self.case_requested.emit(case_id)

    def _open_noise_case(self, index) -> None:
        if index.isValid() and index.row() < self.noise_model.rowCount():
            self.case_requested.emit(str(self.noise_model.rows[index.row()][0]))

    def open_selected_case(self) -> None:
        idx = self.member_table.currentIndex()
        if idx.isValid() and idx.row() < self.member_model.rowCount():
            self.case_requested.emit(str(self.member_model.rows[idx.row()][0]))

    def export_csv(self) -> None:
        if self.result is None or not self.result.clusters:
            return
        filepath, _ = QFileDialog.getSaveFileName(
            self, "Experimentelle ML-Cluster lokal exportieren",
            "NTF_Experimental_HDBSCAN_Clusters.csv", "CSV-Dateien (*.csv)",
        )
        if not filepath:
            return
        try:
            with open(filepath, "w", encoding="utf-8-sig", newline="") as output:
                writer = csv.writer(output, delimiter=";")
                writer.writerow((
                    "ML-Gruppe", "QEC-Fall", "FIN", "Repräsentant",
                    "Cosinus zum Repräsentanten", "HDBSCAN-Stabilität",
                    "Gemeinsame ECU:DTC zum Repräsentanten",
                    "Schwächstes internes Cosinus-Paar",
                    "SSL-Endbefund nur zur Validierung", "Warnungen",
                    "DTC-Quelle", "Vor-Tausch-Zeitraum",
                    "min_cluster_size", "min_samples", "Methodenstatus",
                ))
                for group in self.result.clusters:
                    for member in group.members:
                        writer.writerow((
                            f"H{group.cluster_id}", member.case_id,
                            self.by_id[member.case_id].vin,
                            group.representative_case_id,
                            member.similarity_to_representative,
                            member.membership_strength,
                            ", ".join(f"{e}:{d}" for e, d in member.shared_faults),
                            group.weakest_internal_similarity,
                            qec_ssl_finding_label(self.by_id[member.case_id]),
                            "; ".join(group.warnings),
                            self.result.dtc_source,
                            self.result.lookback_days or "gesamte Vorher-Historie",
                            self.result.min_cluster_size,
                            self.result.min_samples,
                            "Exploratives ML – gleiche Fehlerursache NICHT bestätigt",
                        ))
        except OSError as exc:
            QMessageBox.warning(
                self, "CSV-Export fehlgeschlagen", str(exc),
            )
