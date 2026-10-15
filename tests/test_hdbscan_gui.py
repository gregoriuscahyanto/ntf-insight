"""Offscreen ML GUI tests: HDBSCAN is experimental and never edits QEC cases."""
from __future__ import annotations

import csv
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication, QFileDialog

from ntf_insight.app.widgets.hdbscan_panel import HDBSCANPanel

from test_hdbscan_clustering import sample


def test_hdbscan_panel_groups_members_noise_and_navigation() -> None:
    app = QApplication.instance() or QApplication([])
    cases = sample()
    panel = HDBSCANPanel(cases)
    assert panel.selection_method.currentData() == "leaf"
    panel.selection_method.setCurrentIndex(
        panel.selection_method.findData("eom")
    )
    panel.run_analysis()
    assert panel.result is not None
    assert len(panel.result.clusters) == 2
    assert panel.result.clustered_count == 12
    assert panel.group_model.rowCount() == 2
    assert panel.member_model.rowCount() == 6
    assert panel.noise_model.rowCount() == 3
    assert "2 HDBSCAN-Gruppen" in panel.summary.text()
    assert "HDBSCAN-Gruppen" in panel.summary.text()
    assert "synthetisch" not in panel.summary.text().casefold()
    assert len(panel.map.items_by_case) == 13
    assert panel.result.noise_case_ids == ("OUTLIER",)
    assert all(
        c.representative_case_id in c.case_ids for c in panel.result.clusters
    )
    assert "H1" in panel.group_note.text()
    assert panel.export_button.isEnabled()

    panel.group_table.selectRow(1)
    assert panel.group_note.text().startswith("H2")
    representative = panel.result.clusters[1].representative_case_id
    member_index = next(
        i for i, row in enumerate(panel.member_model.rows)
        if row[0] == representative
    )
    panel.member_table.selectRow(member_index)
    chosen = []
    panel.case_requested.connect(chosen.append)
    panel.open_button.click()
    assert chosen[-1] == representative

    class Wheel:
        def __init__(self):
            self.called = False
        def angleDelta(self):
            return QPoint(0, 120)
        def accept(self):
            self.called = True
        def ignore(self):
            pass

    w = Wheel()
    panel.map.wheelEvent(w)
    assert w.called
    assert panel.map._zoom > 1
    panel.map.reset_zoom()
    assert panel.map._zoom == 1
    panel.close()
    app.processEvents()


def test_hdbscan_panel_parameter_change_recalculates_both_plot_and_grouping() -> None:
    app = QApplication.instance() or QApplication([])
    panel = HDBSCANPanel(sample())
    panel.run_analysis()
    original_coordinates = panel.result.coordinates
    panel.source.setCurrentIndex(panel.source.findData("quicktest"))
    panel.run_analysis()
    assert panel.result.eligible_case_ids == ()
    assert panel.result.clusters == ()
    assert panel.result.coordinates == ()
    assert panel.map.items_by_case == {}
    assert panel.noise_model.rowCount() == 15
    assert panel.export_button.isEnabled() is False
    panel.source.setCurrentIndex(panel.source.findData("all"))
    panel.run_analysis()
    assert panel.result.coordinates == original_coordinates
    panel.close()
    app.processEvents()


def test_local_hdbscan_csv_contains_only_real_qec_members(tmp_path, monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    panel = HDBSCANPanel(sample())
    panel.selection_method.setCurrentIndex(
        panel.selection_method.findData("eom")
    )
    panel.run_analysis()
    target = tmp_path / "hdbscan.csv"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName",
        lambda *args, **kwargs: (str(target), "CSV-Dateien (*.csv)"),
    )
    panel.export_button.click()
    with target.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream, delimiter=";"))
    assert len(rows) == panel.result.clustered_count
    assert {row["QEC-Fall"] for row in rows} == {
        cid for group in panel.result.clusters for cid in group.case_ids
    }
    assert all(row["Methodenstatus"].startswith("Exploratives ML") for row in rows)
    assert all(row["QEC-Fall"] in panel.by_id for row in rows)
    assert not any(row["QEC-Fall"] == "OUTLIER" for row in rows)
    panel.close()
    app.processEvents()


def test_hdbscan_tools_are_in_single_cluster_workspace(tmp_path, monkeypatch) -> None:
    from ntf_insight.app.windows.main_window import MainWindow

    monkeypatch.setenv("NTF_INSIGHT_DATA_DIR", str(tmp_path / "empty"))
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    page = window.pages["cases"]
    assert page.detail_tabs.count() == 4
    assert page.detail_tabs.tabText(0) == "Clusteranalyse"
    panel = page.cluster_workspace
    assert panel.method_combo.currentData() == "leaf"
    assert panel.method_combo.count() == 3
    assert panel.start_button.text() == "Clusteranalyse starten"
    assert panel.plot is not None
    window.close()
    app.processEvents()


def test_method_comparison_shows_both_on_same_cases_and_export_only_aggregates(
    tmp_path, monkeypatch,
) -> None:
    app = QApplication.instance() or QApplication([])
    panel = HDBSCANPanel(sample())
    assert panel.selection_method.currentData() == "leaf"
    panel.compare_button.click()
    report = panel.comparison
    assert report is not None
    assert report.eom.selection_method == "eom"
    assert report.leaf.selection_method == "leaf"
    assert panel.comparison_model.rowCount() == 2
    assert panel.comparison_model.rows[0][0] == "EOM"
    assert panel.comparison_model.rows[1][0] == "LEAF"
    assert "Paar-Zuordnungs" in panel.comparison_summary.text()
    assert "13" in panel.comparison_summary.text()
    assert panel.quality_button.isEnabled()
    assert panel.result is not None
    assert panel.result.selection_method == "leaf"
    target = tmp_path / "aggregate_only.csv"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName",
        lambda *args, **kwargs: (str(target), "CSV-Dateien (*.csv)"),
    )
    panel.quality_button.click()
    content = target.read_text(encoding="utf-8-sig")
    assert "W1TTEST" not in content
    assert "CPC3" not in content
    assert "A0" not in content
    assert "CaseId" not in content
    with target.open(encoding="utf-8-sig", newline="") as stream:
        lines = list(csv.DictReader(stream, delimiter=";"))
    assert len(lines) == 2
    assert {line["Methode"] for line in lines} == {"eom", "leaf"}
    assert all(line["QEC mit Diagnosedaten"] == "13" for line in lines)
    assert all("Fallpaare unter 45 Prozent" in line for line in lines)
    panel.close()
    app.processEvents()


def test_large_clusters_no_misleading_star_and_leaf_method_propagated() -> None:
    app = QApplication.instance() or QApplication([])
    panel = HDBSCANPanel(sample())
    panel.selection_method.setCurrentIndex(
        panel.selection_method.findData("eom")
    )
    panel.run_analysis()
    assert panel.result.selection_method == "eom"
    # No connector lines for unselected clusters.
    panel.map.set_result(panel.result, panel.cases)
    assert panel.map.connector_count == 0
    group = panel.result.clusters[0]
    panel.map.set_result(
        panel.result, panel.cases, highlighted_cluster=group.cluster_id
    )
    assert panel.map.connector_count <= group.case_count - 1
    # Recalculation with Leaf changes method, never old plotted scores.
    original = panel.result.distances
    panel.selection_method.setCurrentIndex(
        panel.selection_method.findData("leaf")
    )
    panel.run_analysis()
    assert panel.result.selection_method == "leaf"
    assert panel.result.distances == original
    panel.close()
    app.processEvents()



def test_ml_evidence_audit_and_common_dtc_sensitivity_mode_are_visible() -> None:
    app = QApplication.instance() or QApplication([])
    panel = HDBSCANPanel(sample())
    panel.run_analysis()
    assert panel.evidence_audit is not None
    assert panel.evidence_audit.scoped_cases == 15
    assert panel.evidence_audit.eligible_cases == 13
    assert "QuickTest und AutoExport" in panel.evidence_summary.text()
    assert panel.frequency_model.rowCount() >= 6
    assert not panel.filter_common.isChecked()
    assert panel.result.common_dtc_cutoff is None
    original = panel.result.distances
    panel.filter_common.setChecked(True)
    panel.run_analysis()
    assert panel.result.common_dtc_cutoff == 0.35
    assert panel.result.distances != original
    assert panel.evidence_audit.eligible_cases == 13
    assert "Häufigkeitsfilter: an" in panel.summary.text()
    panel.compare_button.click()
    assert panel.comparison.common_dtc_cutoff == 0.35
    assert panel.comparison.eligible_case_count == len(panel.result.eligible_case_ids)
    panel.close()
    app.processEvents()


def test_expert_label_template_is_local_and_manual_review_is_distinct_from_ml(
    tmp_path, monkeypatch,
) -> None:
    import csv
    from PySide6.QtWidgets import QMessageBox

    app = QApplication.instance() or QApplication([])
    cases = sample()
    cases[0].qec_ssl_end_finding = "Synthetic QEC SSL text ONLY"
    panel = HDBSCANPanel(cases)
    panel.run_analysis()
    baseline = panel.result
    confidential = tmp_path / "review_with_fin_and_ssl.csv"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName",
        lambda *args, **kwargs: (str(confidential), "CSV-Dateien (*.csv)"),
    )
    panel.template_button.click()
    review = confidential.read_text(encoding="utf-8-sig")
    assert "W1TTEST" in review
    assert "Synthetic QEC SSL text ONLY" in review
    assert ";pending;" in review
    assert not panel.confirmed_mechanisms
    assert not panel.pair_test_button.isEnabled()
    # Human, independent test evidence is supplied explicitly.
    with confidential.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream, delimiter=";"))
    for row in rows:
        if row["qec_case_id"] in {"A0", "A1", "B0"}:
            row["review_status"] = "confirmed"
            row["mechanism_code"] = (
                "PCB_SHORT" if row["qec_case_id"].startswith("A")
                else "CORROSION_CONTACT"
            )
            row["reviewer"] = "Expert-TEST"
            row["evidence_ref"] = "Synthetic-8D-TEST"
            row["confirmed_on"] = "2026-10-09"
    with confidential.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0], delimiter=";")
        writer.writeheader()
        writer.writerows(rows)
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName",
        lambda *args, **kwargs: (str(confidential), "CSV-Dateien (*.csv)"),
    )
    panel.import_review_button.click()
    assert len(panel.confirmed_mechanisms) == 3
    assert panel.pair_test_button.isEnabled()
    assert panel.mechanism_model.rowCount() == len(panel.result.clusters)
    assert "3/15" in panel.mechanism_summary.text()
    assert panel.result == baseline  # posthoc labels never modify HDBSCAN
    panel.pair_test_button.click()
    assert "Kein Modell" in panel.pair_test_summary.text() or "keine belastbare" in panel.pair_test_summary.text()

    # An invalid edited file must not silently replace valid confirmations.
    confidential.write_text("invalid;csv\n", encoding="utf-8-sig")
    warnings = []
    monkeypatch.setattr(
        QMessageBox, "warning",
        lambda _parent, title, detail: warnings.append((title, detail)),
    )
    panel.import_review_button.click()
    assert warnings
    assert len(panel.confirmed_mechanisms) == 3
    panel.close()
    app.processEvents()


def test_aggregate_only_comparison_export_contains_no_dtc_or_ssl_or_fin(
    tmp_path, monkeypatch,
) -> None:
    app = QApplication.instance() or QApplication([])
    cases = sample()
    cases[0].qec_ssl_end_finding = "Synthetic sensitive reason"
    panel = HDBSCANPanel(cases)
    panel.filter_common.setChecked(True)
    panel.compare_button.click()
    target = tmp_path / "aggregate_only.csv"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName",
        lambda *args, **kwargs: (str(target), "CSV-Dateien (*.csv)"),
    )
    panel.quality_button.click()
    content = target.read_text(encoding="utf-8-sig")
    assert "W1TTEST" not in content
    assert "QEC-A0" not in content
    assert "CODE-A-ROOT-A" not in content
    assert "Synthetic sensitive reason" not in content
    assert "Häufigkeitsfilter ECU:DTC" in content
    assert "Ab 35%" in content
    panel.close()
    app.processEvents()
