"""Offscreen GUI regressions: real representatives and safe manual TIPS links."""
from __future__ import annotations

import os
from datetime import datetime

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication, QMessageBox

from ntf_insight.app.widgets.representative_case_panel import RepresentativeCasePanel
from ntf_insight.app.widgets.representative_scatter import (
    representative_mds_coordinates,
)
from ntf_insight.analysis.representative_clustering import select_representative_cases
from ntf_insight.domain.case import NTFCase
from ntf_insight.domain.events import DiagnosticEvent, PartReplacement
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
    panel.budget.setValue(12)
    panel.minimum.setValue(0.30)
    panel.run_analysis()
    assert panel.plan is not None
    assert len(panel.plan.clusters) == 2
    assert panel.plan.covered_count == 4
    assert "80.0%" in panel.summary.text()
    assert "nicht zugeordnet" in panel.summary.text()
    assert panel.group_model.rowCount() == 2
    assert panel.member_model.rowCount() == 2
    assert panel.map.items_by_case
    assert set(panel.map.items_by_case) == {"A", "B", "C", "D"}
    coords = representative_mds_coordinates(panel.plan)
    assert coords == representative_mds_coordinates(panel.plan)
    assert all(len(value) == 2 for value in coords.values())
    assert panel.group_note.text().startswith("R1")

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


def test_case_workspace_has_distinct_representative_tab(tmp_path, monkeypatch) -> None:
    from ntf_insight.app.windows.main_window import MainWindow

    monkeypatch.setenv("NTF_INSIGHT_DATA_DIR", str(tmp_path / "empty"))
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    cases = window.pages["cases"]
    tabs = cases.detail_tabs
    assert tabs.tabText(0) == "2D-Streudiagramm"
    assert tabs.tabText(1) == "FIN / Fallanalyse"
    assert tabs.tabText(2) == "QuickTests nach FIN"
    assert tabs.tabText(3) == "Repräsentative Cluster"
    assert cases.representative_panel is tabs.widget(3)
    # The original strict cluster and scatter remain separate implementations.
    assert cases.scatter_panel is tabs.widget(0)
    window.close()
    app.processEvents()
