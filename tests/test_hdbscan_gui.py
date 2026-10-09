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
    panel.run_analysis()
    assert panel.result is not None
    assert len(panel.result.clusters) == 2
    assert panel.result.clustered_count == 12
    assert panel.group_model.rowCount() == 2
    assert panel.member_model.rowCount() == 6
    assert panel.noise_model.rowCount() == 3
    assert "keine" not in panel.summary.text().casefold()
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


def test_hdbscan_tab_lives_alongside_existing_case_and_strict_cluster_tabs(
    tmp_path, monkeypatch,
) -> None:
    from ntf_insight.app.windows.main_window import MainWindow

    monkeypatch.setenv("NTF_INSIGHT_DATA_DIR", str(tmp_path / "empty"))
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    page = window.pages["cases"]
    assert page.detail_tabs.tabText(0) == "2D-Streudiagramm"
    assert page.detail_tabs.tabText(3) == "Repräsentative Cluster"
    assert page.detail_tabs.tabText(4) == "ML-Cluster (HDBSCAN)"
    assert page.detail_tabs.widget(4) is page.hdbscan_panel
    assert page.detail_tabs.widget(3) is page.representative_panel
    assert page.detail_tabs.widget(0) is page.scatter_panel
    window.close()
    app.processEvents()
