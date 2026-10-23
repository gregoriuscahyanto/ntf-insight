"""Offscreen GUI regressions: real representatives and safe manual TIPS links."""
from __future__ import annotations

import os
from datetime import datetime
import csv

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from ntf_insight.app.widgets.representative_case_panel import RepresentativeCasePanel
from ntf_insight.app.widgets.representative_scatter import (
    representative_mds_coordinates,
)
from ntf_insight.domain.case import NTFCase
from ntf_insight.domain.events import (
    DiagnosticEvent, PartReplacement, SupplierFinding,
)
from ntf_insight.domain.vehicle import Vehicle
from ntf_insight.storage.duckdb_store import DuckDBStore
from ntf_insight.storage.source_knowledge_store import SourceKnowledgeStore


def example(name: str, fin: str, codes: tuple[str, ...]) -> NTFCase:
    return NTFCase(
        case_id=name, vehicle=Vehicle(vin=fin, model_series="214"),
        component_type="Coolant Pump", component_profile_id="coolant_pump",
        replacements=[
            PartReplacement(event_id="swap-" + name, vin=fin,
                            component_type="Coolant Pump",
                            occurred_at=datetime(2026, 5, 5)),
        ],
        investigated_replacement_id="swap-" + name,
        diagnostics=[
            DiagnosticEvent(vin=fin, ecu="CPC3", dtc_code=code,
                            occurred_at=datetime(2026, 4, 20),
                            source_ref=f"raw:test#csv:{name}:{code}")
            for code in codes
        ],
    )


def fixtures():
    return [
        example("A", "W1TTEST0000000001", ("P101", "P102")),
        example("B", "W1TTEST0000000002", ("P101", "P102")),
        example("C", "W1TTEST0000000003", ("P201", "P202")),
        example("D", "W1TTEST0000000004", ("P201", "P202")),
        example("E", "W1TTEST0000000005", ()),
    ]


def test_representatives_render_actual_qec_ids_budget_and_mds() -> None:
    app = QApplication.instance() or QApplication([])
    cases = fixtures()
    panel = RepresentativeCasePanel(cases)
    assert not hasattr(panel, "budget")
    assert panel.minimum.value() == 0.60
    panel.run_analysis()
    assert panel.plan is not None
    assert len(panel.plan.clusters) == 2
    assert panel.plan.covered_count == 4
    assert "80.0%" in panel.summary.text()
    assert "nicht zugeordnet" in panel.summary.text()
    assert panel.group_model.rowCount() == 2
    assert "keine feste Obergrenze" in panel.summary.text()
    assert "ohne Selbst" in panel.group_model.headers[4]
    assert all(group.weakest_internal_similarity >= 0.60
               for group in panel.plan.clusters)
    assert panel.member_model.rowCount() == 2
    assert panel.map.items_by_case
    assert set(panel.map.items_by_case) == {"A", "B", "C", "D"}
    coords = representative_mds_coordinates(panel.plan)
    assert coords == representative_mds_coordinates(panel.plan)
    assert all(len(value) == 2 for value in coords.values())
    assert panel.group_note.text().startswith("R1")
    assert "ohne 100%-Selbstvergleich" in panel.group_note.text()
    assert panel.unassigned_model.rowCount() == 1
    assert panel.unassigned_model.rows[0][0] == "E"
    assert "vor Tausch" in panel.unassigned_model.rows[0][2]

    panel.group_table.selectRow(1)
    assert panel.group_note.text().startswith("R2")
    case_id = panel.plan.clusters[1].representative_case_id
    row = next(
        index for index, values in enumerate(panel.member_model.rows)
        if values[0] == case_id
    )
    panel.member_table.selectRow(row)
    emitted = []
    panel.case_requested.connect(emitted.append)
    panel.open_case_button.click()
    assert emitted == [case_id]

    # Map highlight/zoom never reclassifies a QEC case as a new NTF finding.
    class Wheel:
        def __init__(self):
            self.accepted = False

        def angleDelta(self):
            return QPoint(0, 120)

        def accept(self):
            self.accepted = True

        def ignore(self):
            pass

    wheel = Wheel()
    panel.map.wheelEvent(wheel)
    assert wheel.accepted
    assert panel.map._zoom > 1
    panel.map.reset_zoom()
    assert panel.map._zoom == 1
    panel.close()
    app.processEvents()


def test_tips_review_gui_requires_confirmation_and_updates_local_case(
    tmp_path, monkeypatch,
) -> None:
    app = QApplication.instance() or QApplication([])
    cases = [fixtures()[0]]
    store = DuckDBStore(tmp_path / "local.duckdb")
    store.save_cases(cases)
    knowledge = SourceKnowledgeStore(store)
    knowledge.save_records("a" * 64, "autoexport_rows", [
        {
            "category": "autoexport_tips", "fin": cases[0].vin,
            "source_location": "csv:row:1", "reference": "TIPS-1",
            "label": "2026-04-22",
            "data": {
                "Fin": cases[0].vin, "CaseId": "TIPS-1",
                "CreationDate": "2026-04-22",
                "InitialWorkshopMessageCustomerComplaint": "Synthetisch",
            },
        },
    ])
    panel = RepresentativeCasePanel(cases, knowledge, store)
    panel.load_tips_review()
    assert panel.tips_model.rowCount() == 1
    assert "1 mögliche QEC-Verknüpfungen" in panel.review_summary.text()
    panel.tips_table.selectRow(0)
    assert panel.confirm_button.isEnabled()
    called = []
    panel.tips_linked.connect(called.append)
    monkeypatch.setattr(
        QMessageBox, "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.No,
    )
    panel.confirm_button.click()
    assert not called
    assert not store.get_case("A").tips_observations

    monkeypatch.setattr(
        QMessageBox, "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )
    panel.confirm_button.click()
    assert called == ["A"]
    assert store.get_case("A").tips_observations[0].tips_case_id == "TIPS-1"
    assert knowledge.count_rows("autoexport_tips") == 1
    panel.close()
    app.processEvents()


def test_case_workspace_has_only_one_clustering_tab(tmp_path, monkeypatch) -> None:
    from ntf_insight.app.windows.main_window import MainWindow

    monkeypatch.setenv("NTF_INSIGHT_DATA_DIR", str(tmp_path / "empty"))
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    cases = window.pages["cases"]
    tabs = cases.detail_tabs
    assert tabs.count() == 5
    assert tabs.tabText(3) == "QuickTest-Gesamtauswertung"
    assert tabs.tabText(4) == "ECU · SW-Übersicht"
    assert tabs.widget(4) is cases.cpc3_overview
    assert tabs.tabText(0) == "Clusteranalyse"
    assert tabs.tabText(1) == "FIN / Fallanalyse"
    assert tabs.tabText(2) == "QuickTests nach FIN"
    assert cases.cluster_workspace is cases.autoexport_fin_workspace
    assert cases.cluster_workspace is tabs.widget(0)
    assert cases.cluster_workspace.method_combo.count() == 3
    assert cases.cluster_workspace.start_button.isEnabled()
    window.close()
    app.processEvents()


def test_local_investigation_plan_csv_contains_real_medoid_and_members(
    tmp_path, monkeypatch,
) -> None:
    app = QApplication.instance() or QApplication([])
    cases = fixtures()
    panel = RepresentativeCasePanel(cases)
    panel.run_analysis()
    assert panel.export_button.isEnabled()
    target = tmp_path / "medoid_plan.csv"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName",
        lambda *args, **kwargs: (str(target), "CSV-Dateien (*.csv)"),
    )
    panel.export_button.click()
    with target.open(encoding="utf-8-sig", newline="") as stream:
        result = list(csv.DictReader(stream, delimiter=";"))
    assert len(result) == panel.plan.covered_count
    reps = set(panel.plan.representative_ids)
    assert reps and reps <= {row["QEC-Fall"] for row in result}
    assert all(row["Repräsentant"] in reps for row in result)
    assert all(row["Hinweis"].startswith("Ähnlichkeit") for row in result)
    panel.close()
    app.processEvents()



def test_ssl_fallback_is_displayed_consistently_in_group_and_members() -> None:
    app = QApplication.instance() or QApplication([])
    cases = fixtures()
    cases[0].supplier_findings.append(SupplierFinding(
        vin=cases[0].vin, occurred_at=datetime(2026, 5, 20),
        failure_mode="Synthetic SSL end finding from QEC event",
        source_ref="Schadteile QEC!5",
    ))
    panel = RepresentativeCasePanel(cases)
    panel.run_analysis()
    group = next(
        item for item in panel.plan.clusters
        if "A" in item.case_ids
    )
    assert group.with_qec_ssl_finding == 1
    row = next(index for index, item in enumerate(panel.plan.clusters)
               if item.cluster_id == group.cluster_id)
    panel.group_table.selectRow(row)
    recorded = next(values for values in panel.member_model.rows
                    if values[0] == "A")
    assert "Synthetic SSL end finding" in recorded[4]
    assert "Nur 1/2 Fälle mit SSL-Endbefund" in group.review_warnings
    panel.close()
    app.processEvents()
