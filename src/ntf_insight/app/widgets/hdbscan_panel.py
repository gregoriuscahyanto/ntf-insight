"""Visible, auditable, optional ML exploration; does not replace strict clusters."""
from __future__ import annotations

import csv

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QGridLayout, QHBoxLayout, QLabel, QMessageBox,
    QPushButton, QScrollArea, QSpinBox, QVBoxLayout, QWidget,
)

from ntf_insight.analysis.case_clustering import _component_key
from ntf_insight.analysis.diagnostic_evidence_audit import (
    DiagnosticEvidenceAudit, audit_diagnostic_evidence,
)
from ntf_insight.analysis.mechanism_review import (
    ConfirmedMechanism, read_confirmed_mechanisms, review_cluster_mechanisms,
    write_review_template,
)
from ntf_insight.analysis.supervised_pair_validation import (
    evaluate_supervised_pairs,
)
from ntf_insight.analysis.hdbscan_clustering import (
    HDBSCANMethodComparison, MLClusterResult, cluster_hdbscan_cases,
    compare_hdbscan_methods,
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
        self.comparison: HDBSCANMethodComparison | None = None
        self.evidence_audit: DiagnosticEvidenceAudit | None = None
        self.confirmed_mechanisms: tuple[ConfirmedMechanism, ...] = ()
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
        grid.addWidget(QLabel("HDBSCAN-Gruppenauswahl"), 1, 4)
        self.selection_method = QComboBox()
        self.selection_method.addItem("Leaf – kleinere Dichtegruppen", "leaf")
        self.selection_method.addItem("EOM – persistente Hauptgruppen", "eom")
        self.selection_method.setToolTip(
            "Leaf bevorzugt Blätter der Dichtehierarchie; EOM kann "
            "große, diagnostisch heterogene Gruppen bilden. "
            "Beide benutzen dieselben diagnostischen Vektoren."
        )
        grid.addWidget(self.selection_method, 1, 5)
        self.filter_common = QCheckBox(
            "Häufige ECU:DTC ab 35 % testweise aus ML-Merkmalen ausschließen"
        )
        self.filter_common.setChecked(False)
        self.filter_common.setToolTip(
            "Experimenteller Sensitivitätsvergleich. Nicht behaupten, "
            "dass häufige Kommunikations-DTCs technisch irrelevant sind. "
            "Fälle ohne verbleibenden DTC werden getrennt ausgewiesen."
        )
        grid.addWidget(self.filter_common, 2, 0, 1, 6)
        body.addLayout(grid)

        actions = QHBoxLayout()
        self.run_button = QPushButton("HDBSCAN berechnen")
        self.run_button.clicked.connect(self.run_analysis)
        actions.addWidget(self.run_button)
        self.compare_button = QPushButton("EOM / Leaf vergleichen")
        self.compare_button.clicked.connect(self.compare_methods)
        actions.addWidget(self.compare_button)
        self.quality_button = QPushButton("Qualitätsbericht ohne FIN")
        self.quality_button.setEnabled(False)
        self.quality_button.clicked.connect(self.export_quality_report)
        actions.addWidget(self.quality_button)
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
        self.comparison_summary = QLabel(
            "EOM/Leaf-Vergleich: noch nicht berechnet. "
            "Der Vergleich nutzt beide Methoden auf demselben Datenbestand "
            "mit identischen DTC-Quellen und Zeitraum.",
            objectName="PageSubtitle",
        )
        self.comparison_summary.setWordWrap(True)
        body.addWidget(self.comparison_summary)
        self.comparison_model = SimpleTableModel((
            "Methode", "Cluster", "Fälle", "Ausreißer", "Größte Gruppe",
            "Gruppen mit gemeinsamem DTC", "Gruppen ohne schwache Paare",
            "Fallpaare <45 % / alle", "Median der Gruppenmediane",
        ))
        self.comparison_table = _table(self.comparison_model, 110)
        body.addWidget(self.comparison_table)
        self.map = HDBSCANScatter()
        self.map.case_picked.connect(self._picked)
        self.zoom_button.clicked.connect(self.map.reset_zoom)
        body.addWidget(self.map)
        note = QLabel(
            "2D-MDS aus derselben hochdimensionalen Distanzmatrix wie "
            "HDBSCAN (keine Clusterung der 2D-Pixel). "
            "Großes Symbol H1/H2 = ausgewählter echter QEC-Medoid; "
            "graue Punkte = HDBSCAN-Rauschen. Nicht darstellbare Fälle "
            "ohne Vorher-Diagnose bleiben ausdrücklich außerhalb des Plots. "
            "Verbindungslinien erscheinen nur bei einer ausgewählten, "
            "kleinen Gruppe und hinreichender Paarähnlichkeit; dadurch "
            "bilden heterogene Großgruppen keine irreführenden Sterne. "
            "2D-Entfernung und HDBSCAN-Zugehörigkeitsstärke sind "
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
            "Median aller Paare", "Unteres 10%-Quantil", "Paare <45 % / alle",
            "Bewertung", "Min. HDBSCAN-Zugehörigkeit", "Gemeinsame ECU:DTC",
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

        body.addWidget(QLabel(
            "Diagnosebasis prüfen: warum werden Fälle ausgeschlossen?",
            objectName="CardTitle",
        ))
        self.evidence_summary = QLabel(objectName="PageSubtitle")
        self.evidence_summary.setWordWrap(True)
        body.addWidget(self.evidence_summary)
        self.frequency_model = SimpleTableModel((
            "ECU", "DTC", "QEC-Fälle mit DTC", "Anteil an Fällen mit Vorher-DTC",
            "Häufigkeitsprüfung (KEIN Ursachenurteil)",
        ))
        self.frequency_table = _table(self.frequency_model, 210)
        body.addWidget(self.frequency_table)

        body.addWidget(QLabel(
            "Fachlich bestätigte Fehlermechanismen – unabhängige Validierung",
            objectName="CardTitle",
        ))
        instructions = QLabel(
            "Die QEC-SSL-Endbefunde erscheinen nur als Referenz in einer "
            "lokalen Prüfvorlage. Nicht als bestätigte Fehlerursache "
            "übernehmen! Ein Fachprüfer muss einen spezifischen Mechanismus "
            "mit unabhängiger Evidenz und Datum ausdrücklich bestätigen. "
            "Diese Labels ändern NIEMALS die HDBSCAN-Zuordnung.",
            objectName="PageSubtitle",
        )
        instructions.setWordWrap(True)
        body.addWidget(instructions)
        review_controls = QHBoxLayout()
        self.template_button = QPushButton(
            "Fachprüfvorlage lokal exportieren (mit FIN und SSL)"
        )
        self.template_button.clicked.connect(self.export_review_template)
        review_controls.addWidget(self.template_button)
        self.import_review_button = QPushButton(
            "Bestätigte Fehlermechanismen lokal einlesen"
        )
        self.import_review_button.clicked.connect(self.import_mechanism_labels)
        review_controls.addWidget(self.import_review_button)
        self.pair_test_button = QPushButton("FIN-getrenntes Paarmodell prüfen")
        self.pair_test_button.setEnabled(False)
        self.pair_test_button.clicked.connect(self.test_supervised_pairs)
        review_controls.addWidget(self.pair_test_button)
        body.addLayout(review_controls)
        self.mechanism_summary = QLabel(
            "Noch keine Fachbestätigungen geladen. "
            "Alle Cluster sind unvalidierte Diagnostik-Vergleichsgruppen.",
            objectName="PageSubtitle",
        )
        self.mechanism_summary.setWordWrap(True)
        body.addWidget(self.mechanism_summary)
        self.mechanism_model = SimpleTableModel((
            "ML-Gruppe", "QEC-Fälle", "Fachlich bestätigt", "Bestätigte FINs",
            "Gleiche Ursachenpaare", "Abweichende Ursachenpaare",
            "Übereinstimmung NUR auf geprüften Paaren", "Fachliche Bewertung",
        ))
        self.mechanism_table = _table(self.mechanism_model, 220)
        body.addWidget(self.mechanism_table)
        self.pair_test_summary = QLabel(
            "Kein Paarmodell trainiert. Erst unabhängige Fachlabels laden.",
            objectName="PageSubtitle",
        )
        self.pair_test_summary.setWordWrap(True)
        body.addWidget(self.pair_test_summary)
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
            audit = audit_diagnostic_evidence(
                subset,
                dtc_source=self.source.currentData() or "all",
                lookback_days=self.lookback.currentData(),
                common_cutoff=0.35,
            )
            result = cluster_hdbscan_cases(
                subset,
                min_cluster_size=self.min_cluster_size.value(),
                min_samples=self.min_samples.value(),
                selection_method=self.selection_method.currentData(),
                common_dtc_cutoff=0.35 if self.filter_common.isChecked() else None,
                dtc_source=self.source.currentData() or "all",
                lookback_days=self.lookback.currentData(),
            )
        except ValueError as exc:
            self.summary.setText(f"HDBSCAN nicht berechenbar: {exc}")
            self.group_model.set_rows([])
            self.member_model.set_rows([])
            self.noise_model.set_rows([])
            self.result = None
            self.evidence_audit = None
            self.export_button.setEnabled(False)
            self.evidence_summary.setText(f"Diagnosedaten nicht auswertbar: {exc}")
            return
        self.result = result
        self.evidence_audit = audit
        if not {review.case_id for review in self.confirmed_mechanisms}.issubset(
            {case.case_id for case in subset}
        ):
            self.confirmed_mechanisms = ()
            self.pair_test_button.setEnabled(False)
            self.pair_test_summary.setText(
                "Fachbestätigungen zurückgesetzt: andere Bauteilfamilie."
            )
        self.comparison = None
        self.comparison_model.set_rows([])
        self.quality_button.setEnabled(False)
        self.comparison_summary.setText(
            "EOM/Leaf-Vergleich noch nicht berechnet. "
            "Vergleiche dieselben QEC-Fälle, bevor du eine Clusteranzahl bewertest."
        )
        self.summary.setText(
            f"{result.case_count} QEC-Fälle / {result.vehicle_count} FINs · "
            f"{len(result.eligible_case_ids)} mit Tauschanker und Vorher-DTC · "
            f"{len(result.excluded_case_ids)} nicht projizierbar "
            f"(davon {len(result.frequency_filtered_case_ids)} durch "
            "experimentellen DTC-Häufigkeitsfilter) · "
            f"{result.feature_count} TF-IDF-Merkmalsspalten · "
            f"{len(result.clusters)} HDBSCAN-Gruppen (automatisch) · "
            f"{result.clustered_count} Fälle ({result.coverage:.1%}) "
            f"explorativ gruppiert · "
            f"{len(result.noise_case_ids)} HDBSCAN-Ausreißer. "
            f"Parameter: Auswahl={result.selection_method.upper()}, "
            f"min_cluster_size={result.min_cluster_size}, "
            f"min_samples={result.min_samples}; "
            f"Quelle: {self.source.currentText()}; "
            f"Zeitfenster: {self.lookback.currentText()}; "
            f"Häufigkeitsfilter: {'an (35 %)' if result.common_dtc_cutoff is not None else 'aus'}. "
            "Die Gruppenanzahl ist keine Gütebewertung."
        )
        self.group_model.set_rows([
            (
                f"H{group.cluster_id}", group.representative_case_id,
                group.case_count, group.vehicle_count,
                f"{group.mean_to_representative:.1%}",
                f"{group.weakest_internal_similarity:.1%}",
                f"{group.median_internal_similarity:.1%}",
                f"{group.p10_internal_similarity:.1%}",
                f"{group.weak_pair_count} / {group.internal_pair_count}",
                group.screening_status,
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
        availability = {row.case_id: row for row in audit.cases}
        self.evidence_summary.setText(
            f"QEC-Grundgesamtheit {audit.scoped_cases}, davon "
            f"{audit.eligible_cases} mit geeigneter Vor-Tausch-Diagnose · "
            f"{audit.without_anchor} ohne Tauschanker · "
            f"{audit.without_any_dtc} ohne QEC-DTC-Zeilen · "
            f"{audit.only_after_swap_or_undated} mit DTC, aber nicht sicher vorher · "
            f"{audit.no_selected_source} ohne Vorher-DTC aus gewählter Quelle · "
            f"{audit.outside_lookback} außerhalb des gewählten Vorher-Fensters. "
            f"{audit.with_source_overlap} QEC-Fälle zeigen dieselbe ECU:DTC-"
            f"Kombination in QuickTest und AutoExport "
            f"({audit.overlapping_fault_occurrences} Fall-DTC-Überlappungen; "
            "als Mengenmerkmale nicht doppelt gezählt). "
            f"{len(audit.high_prevalence_faults)} ECU:DTC erreichen mindestens "
            "35 % der auswertbaren QEC-Fälle. Hohe Häufigkeit bedeutet "
            "NICHT technisch irrelevant."
        )
        self.frequency_model.set_rows([
            (
                item.fault[0], item.fault[1], item.case_count,
                f"{item.proportion:.1%}",
                "Häufig, fachliche Relevanz ungeklärt"
                if item.screened_common else "Unter Screening-Grenze",
            ) for item in audit.frequencies[:30]
        ])
        self.noise_model.set_rows([
            (
                cid, self.by_id[cid].vin,
                "HDBSCAN-Rauschen / keine stabile Dichtegruppe",
            ) for cid in result.noise_case_ids
        ] + [
            (
                cid, self.by_id[cid].vin,
                (
                    "Nur häufige DTCs nach experimentellem Screening"
                    if cid in result.frequency_filtered_case_ids
                    else availability[cid].reason
                ),
            ) for cid in result.excluded_case_ids
        ])
        self.member_model.set_rows([])
        self.open_button.setEnabled(bool(result.clusters))
        self.export_button.setEnabled(bool(result.clusters))
        self.map.set_result(result, subset)
        self._refresh_mechanism_review()
        self.pair_test_summary.setText(
            "Kein neues Paarmodell geprüft. "
            "Für eine FIN-getrennte Bewertung Fachbestätigungen laden "
            "und auf 'Paarmodell prüfen' klicken."
        )
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

    def compare_methods(self) -> None:
        """Compare EOM and Leaf on the exact current cohort and parameters."""
        self.run_analysis()
        if self.result is None:
            return
        try:
            report = compare_hdbscan_methods(
                self._subset(),
                min_cluster_size=self.min_cluster_size.value(),
                min_samples=self.min_samples.value(),
                dtc_source=self.source.currentData() or "all",
                lookback_days=self.lookback.currentData(),
                common_dtc_cutoff=0.35 if self.filter_common.isChecked() else None,
            )
        except ValueError as exc:
            self.comparison_summary.setText(f"Vergleich nicht berechenbar: {exc}")
            self.quality_button.setEnabled(False)
            return
        self.comparison = report
        self.comparison_model.set_rows([
            (
                line.selection_method.upper(),
                line.group_count,
                line.clustered_cases,
                line.noise_cases,
                line.largest_cluster_size,
                line.groups_with_common_faults,
                line.groups_without_weak_pairs,
                f"{line.weak_pair_count} / {line.all_internal_pair_count} "
                f"({line.weak_pair_fraction:.1%})",
                f"{line.median_of_group_medians:.1%}"
                if line.median_of_group_medians is not None else "Keine Gruppen",
            )
            for line in report.rows
        ])
        self.comparison_summary.setText(
            f"EOM/Leaf-Vergleich auf identischen "
            f"{report.eligible_case_count} für diese Merkmalsvariante "
            "auswertbaren QEC-Fällen · "
            f"{report.both_grouped_cases} Fälle in beiden Verfahren gruppiert · "
            f"{'Paar-Zuordnungs-Übereinstimmung: ' + format(report.pair_coassignment_jaccard, '.1%') if report.pair_coassignment_jaccard is not None else 'Keine gruppierten Paare in beiden Varianten'}. "
            "Dabei werden echte Fallpaare verglichen, nicht willkürliche "
            "Cluster-IDs H1/H2. Ein hoher Wert bestätigt keine gleiche Ursache. "
            "Prüfe zusätzlich gemeinsame ECU:DTC und SSL-Endbefunde."
        )
        self.quality_button.setEnabled(True)

    def export_quality_report(self) -> None:
        """Export purely aggregate counts and scores; no QEC IDs, FINs or DTCs."""
        report = self.comparison
        if report is None:
            return
        target, _ = QFileDialog.getSaveFileName(
            self, "Anonymisierte HDBSCAN-Methodenqualität exportieren",
            "NTF_HDBSCAN_Methodenvergleich_aggregiert.csv",
            "CSV-Dateien (*.csv)",
        )
        if not target:
            return
        try:
            with open(target, "w", encoding="utf-8-sig", newline="") as output:
                writer = csv.writer(output, delimiter=";")
                writer.writerow((
                    "Methode", "QEC mit Diagnosedaten", "Cluster",
                    "Gruppierte Fälle", "Ausreißer", "Größter Cluster",
                    "Gruppen mit durchgehendem ECU:DTC",
                    "Gruppen ohne schwache Fallpaare",
                    "Fallpaare unter 45 Prozent", "Alle internen Fallpaare",
                    "Anteil schwacher Paare",
                    "Median aller Gruppen-Paarmediane",
                    "Paar-Zuordnungs-Übereinstimmung EOM/Leaf",
                    "In beiden Methoden gruppierte Fälle",
                    "min_cluster_size", "min_samples",
                    "DTC-Quellen", "Vor-Tausch-Tage",
                    "Häufigkeitsfilter ECU:DTC", "Methodenstatus",
                ))
                for line in report.rows:
                    writer.writerow((
                        line.selection_method,
                        report.eligible_case_count,
                        line.group_count,
                        line.clustered_cases,
                        line.noise_cases,
                        line.largest_cluster_size,
                        line.groups_with_common_faults,
                        line.groups_without_weak_pairs,
                        line.weak_pair_count,
                        line.all_internal_pair_count,
                        f"{line.weak_pair_fraction:.6f}",
                        (
                            f"{line.median_of_group_medians:.6f}"
                            if line.median_of_group_medians is not None else ""
                        ),
                        (
                            f"{report.pair_coassignment_jaccard:.6f}"
                            if report.pair_coassignment_jaccard is not None
                            else "Nicht berechenbar"
                        ),
                        report.both_grouped_cases,
                        report.min_cluster_size,
                        report.min_samples,
                        report.dtc_source,
                        report.lookback_days or "gesamte Vorher-Historie",
                        (
                            f"Ab {report.common_dtc_cutoff:.0%}"
                            if report.common_dtc_cutoff is not None else "Aus"
                        ),
                        "ML explorativ; keinerlei Ursache bestätigt",
                    ))
        except OSError as exc:
            QMessageBox.warning(
                self, "Aggregierter Qualitätsbericht nicht gespeichert", str(exc),
            )

    def export_review_template(self) -> None:
        """Local-only CSV with sensitive QEC SSL and VIN for human review."""
        target, _ = QFileDialog.getSaveFileName(
            self,
            "Vertrauliche Fachprüfvorlage LOKAL speichern (FIN und SSL enthalten)",
            "NTF_QEC_Fachpruefung_vertraulich.csv",
            "CSV-Dateien (*.csv)",
        )
        if not target:
            return
        try:
            with open(target, "w", encoding="utf-8-sig", newline="") as stream:
                write_review_template(stream, self._subset())
        except OSError as exc:
            QMessageBox.warning(self, "Fachprüfvorlage nicht gespeichert", str(exc))

    def import_mechanism_labels(self) -> None:
        """Read an explicitly edited, reviewed CSV; never infer from QEC text."""
        target, _ = QFileDialog.getOpenFileName(
            self, "Lokale Fachbestätigungen auswählen",
            "", "CSV-Dateien (*.csv)",
        )
        if not target:
            return
        try:
            with open(target, encoding="utf-8-sig", newline="") as stream:
                confirmed = read_confirmed_mechanisms(stream, self._subset())
        except (OSError, UnicodeError, ValueError) as exc:
            QMessageBox.warning(
                self, "Fachbestätigungen nicht übernommen", str(exc),
            )
            return
        self.confirmed_mechanisms = confirmed
        self.pair_test_button.setEnabled(bool(confirmed))
        self.pair_test_summary.setText(
            "Noch kein trainiertes Paarmodell. Geladene Fachbestätigungen "
            "werden nur für die NACHGELAGERTE Prüfung angezeigt."
        )
        self._refresh_mechanism_review()

    def _refresh_mechanism_review(self) -> None:
        if self.result is None:
            self.mechanism_model.set_rows([])
            return
        review = review_cluster_mechanisms(
            self._subset(), self.result, self.confirmed_mechanisms,
        )
        self.mechanism_model.set_rows([
            (
                f"H{row.cluster_id}",
                row.case_count,
                row.confirmed_cases,
                row.independently_confirmed_vehicles,
                row.same_mechanism_pairs,
                row.different_mechanism_pairs,
                (
                    f"{row.labeled_pair_agreement:.1%}"
                    if row.labeled_pair_agreement is not None
                    else "Nicht auswertbar"
                ),
                row.review_note,
            )
            for row in review.audits
        ])
        observed = (
            f"{review.observed_pair_agreement:.1%}"
            if review.observed_pair_agreement is not None else "Nicht auswertbar"
        )
        self.mechanism_summary.setText(
            f"Nur EXPLIZIT bestätigte Mechanismen: "
            f"{review.reviewed_case_count}/{review.total_case_count} QEC-Fälle; "
            f"{review.clustered_reviewed_count} bestätigte Fälle in den "
            f"aktuellen ML-Gruppen. {review.evaluated_cross_fin_pairs} "
            f"vergleichbare Fachlabel-Paare verschiedener FINs: "
            f"{review.agreeing_cross_fin_pairs} gleich, "
            f"{review.contradicting_cross_fin_pairs} abweichend. "
            f"Übereinstimmung auf der geprüften TEILMENGE: {observed}. "
            "Ungeprüfte Gruppenmitglieder erhalten KEINE Ursachenzuordnung. "
            "Keine Veränderung an HDBSCAN, Medoids oder Originalquellen."
        )

    def test_supervised_pairs(self) -> None:
        """Never use unreviewed SSL text as ground truth, never auto-deploy."""
        if not self.confirmed_mechanisms:
            self.pair_test_summary.setText(
                "Keine unabhängig bestätigten Fehlermechanismen geladen. "
                "Kein Modell trainiert."
            )
            return
        evaluation = evaluate_supervised_pairs(
            self._subset(),
            self.confirmed_mechanisms,
            dtc_source=self.source.currentData() or "all",
            lookback_days=self.lookback.currentData(),
        )
        if not evaluation.validated:
            self.pair_test_summary.setText(
                f"Fachlich geeignete Fälle: {evaluation.eligible_confirmations}; "
                f"bestätigte Mechanismen: {evaluation.confirmed_mechanisms}; "
                f"unabhängige FINs: {evaluation.independent_vehicles}. "
                f"{evaluation.status}"
            )
            return
        self.pair_test_summary.setText(
            f"Experimentelles Paarmodell, kein produktives Clustering: "
            f"{evaluation.train_case_count} Trainings-QEC-Fälle / "
            f"{evaluation.test_case_count} Test-QEC-Fälle aus getrennten FINs; "
            f"Test: {evaluation.test_pair_count} Fallpaare "
            f"({evaluation.test_same_mechanism_pairs} gleiche, "
            f"{evaluation.test_different_mechanism_pairs} verschiedene "
            f"bestätigte Mechanismen). Precision: {evaluation.test_precision:.1%}, "
            f"Recall: {evaluation.test_recall:.1%}, "
            f"Average Precision: {evaluation.test_average_precision:.1%} "
            f"bei {evaluation.test_positive_fraction:.1%} positiven Paaren. "
            f"{evaluation.status}"
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
            f"Cosinus-Paar: {group.weakest_internal_similarity:.1%}, "
            f"Median: {group.median_internal_similarity:.1%}, "
            f"10%-Quantil: {group.p10_internal_similarity:.1%} · "
            f"{group.weak_pair_count} von {group.internal_pair_count} "
            "Fallpaaren unter 45 % · "
            f"Bewertung: {group.screening_status} · "
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
                    "min_cluster_size", "min_samples", "HDBSCAN-Methode",
                    "10%-Quantil interne Paare", "Schwache Paare",
                    "Bewertung", "Häufigkeitsfilter ECU:DTC", "Methodenstatus",
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
                            self.result.selection_method,
                            group.p10_internal_similarity,
                            group.weak_pair_count,
                            group.screening_status,
                            (
                                f"Ab {self.result.common_dtc_cutoff:.0%}"
                                if self.result.common_dtc_cutoff is not None else "Aus"
                            ),
                            "Exploratives ML – gleiche Fehlerursache NICHT bestätigt",
                        ))
        except OSError as exc:
            QMessageBox.warning(
                self, "CSV-Export fehlgeschlagen", str(exc),
            )
