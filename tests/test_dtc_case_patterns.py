"""Offscreen regression for exploratory ECU:DTC pattern discovery.

No original vehicle, claim, TIPS or supplier data are included in this fixture.
"""
from __future__ import annotations

import os
from datetime import datetime

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from ntf_insight.analysis.case_clustering import cluster_diagnostic_cases
from ntf_insight.analysis.dtc_case_patterns import discover_case_dtc_patterns
from ntf_insight.app.widgets.case_scatter_plot import (
    CaseScatterPanel,
    UNASSIGNED,
)
from ntf_insight.domain.case import NTFCase
from ntf_insight.domain.events import (
    DiagnosticEvent,
    PartReplacement,
    SupplierFinding,
)
from ntf_insight.domain.vehicle import Vehicle


def make_case(case_id: str, vin: str, faults: tuple[str, ...]) -> NTFCase:
    swap_at = datetime(2026, 5, 1)
    case = NTFCase(
        case_id=case_id,
        vehicle=Vehicle(vin=vin),
        component_type="Coolant Pump",
        replacements=[
            PartReplacement(
                vin=vin, component_type="Coolant Pump", occurred_at=swap_at
            )
        ],
        diagnostics=[
            DiagnosticEvent(
                vin=vin, ecu="CPC3", dtc_code=code,
                occurred_at=datetime(2026, 4, 25), source_ref=(
                    f"raw:synthetic#csv:{case_id}:{index}"
                ),
            )
            for index, code in enumerate(faults)
        ],
    )
    return case


def test_patterns_are_overlapping_and_not_strict_complete_link_clusters() -> None:
    cases = [
        make_case("A", "FAKE-FIN-A", ("P1", "P2", "X1", "X2", "X3")),
        make_case("B", "FAKE-FIN-B", ("P1", "Y1", "Y2", "Y3", "Y4")),
        make_case("C", "FAKE-FIN-A", ("P2", "Z1", "Z2", "Z3", "Z4")),
        make_case("D", "FAKE-FIN-D", ("Q1",)),
    ]
    result = cluster_diagnostic_cases(cases)
    assert len(result.clusters) == 0

    patterns = discover_case_dtc_patterns(cases)
    assert len(patterns) == 2
    by_fault = {pattern.fault: pattern for pattern in patterns}
    assert by_fault[("CPC3", "P1")].case_ids == ("A", "B")
    assert by_fault[("CPC3", "P1")].vehicle_count == 2
    assert by_fault[("CPC3", "P2")].case_ids == ("A", "C")
    assert by_fault[("CPC3", "P2")].vehicle_count == 1
    # Case A intentionally belongs to both exploratory groups. Neither
    # group is a false confirmed repair/root-cause cluster.
    assert "A" in by_fault[("CPC3", "P1")].case_ids
    assert "A" in by_fault[("CPC3", "P2")].case_ids

    # Repeated DTC from another source does not create another case or
    # increase exact ECU:DTC case support.
    repeated = cases[0].diagnostics[0].model_copy(deep=True)
    repeated.event_id = "synthetic-duplicate-autoexport"
    repeated.source_ref = "raw:synthetic#csv:duplicate"
    cases[0].diagnostics.append(repeated)
    assert discover_case_dtc_patterns(cases) == patterns

    # Later fault and supplier conclusion never turn into an eligible pattern.
    cases[1].diagnostics.append(DiagnosticEvent(
        vin=cases[1].vin, ecu="CPC3", dtc_code="Q1",
        occurred_at=datetime(2026, 5, 20),
    ))
    cases[1].supplier_findings.append(SupplierFinding(
        vin=cases[1].vin, occurred_at=datetime(2026, 5, 21),
        failure_mode="SYNTHETIC OUTCOME",
    ))
    assert discover_case_dtc_patterns(cases) == patterns


def test_patterns_follow_selected_time_and_dtc_source_without_mixing_components() -> None:
    first = make_case("A", "FAKE-FIN-A", ("P1",))
    second = make_case("B", "FAKE-FIN-B", ("P1",))
    unrelated = make_case("HV", "FAKE-FIN-HV", ("P1",))
    unrelated.component_type = "HV Battery"
    assert len(discover_case_dtc_patterns([first, second, unrelated])) == 1

    assert not discover_case_dtc_patterns(
        [first, second], dtc_source="quicktest"
    )
    assert len(discover_case_dtc_patterns(
        [first, second], dtc_source="autoexport"
    )) == 1
    assert not discover_case_dtc_patterns(
        [first, second], lookback_days=2
    )
    assert len(discover_case_dtc_patterns(
        [first, second], lookback_days=30
    )) == 1


def test_scatter_visibly_highlights_unconfirmed_pattern_and_keeps_cluster_fill() -> None:
    app = QApplication.instance() or QApplication([])
    cases = [
        make_case("A", "FAKE-FIN-A", ("P1", "X1", "X2", "X3")),
        make_case("B", "FAKE-FIN-B", ("P1", "Y1", "Y2", "Y3")),
        make_case("C", "FAKE-FIN-C", ("P9",)),
    ]
    result = cluster_diagnostic_cases(cases)
    assert not result.clusters
    panel = CaseScatterPanel(cases, result)
    assert panel.patterns
    assert panel.pattern_combo.currentData() == ("CPC3", "P1")
    assert "DTC-Mustersuche" in panel.pattern_note.text()
    assert "2 echte QEC-Fälle" in panel.pattern_note.text()
    assert panel.pattern_model.rowCount() >= 1

    # Strict-Complete-Link membership must not magically change.
    assert not panel.result.clusters
    point = panel.plot.items_by_case["B"]
    assert point.pen().color().name() == "#e0a300"
    assert point.brush().color().name() == UNASSIGNED
    assert "nur Kandidaten" in point.toolTip()

    original = [(p.case_id, p.x, p.y) for p in panel.projection.points]
    panel.pattern_combo.setCurrentIndex(0)
    assert panel.plot.items_by_case["B"].pen().color().name() != "#e0a300"
    assert original == [(p.case_id, p.x, p.y) for p in panel.projection.points]
    assert not panel.result.clusters
    panel.pattern_combo.setCurrentIndex(1)
    assert panel.plot.items_by_case["B"].pen().color().name() == "#e0a300"

    panel.dtc_source.setCurrentIndex(
        panel.dtc_source.findData("quicktest")
    )
    assert panel.patterns == ()
    assert "0 überlappende ECU:DTC-Muster" in panel.pattern_note.text()
    assert not panel.plot.items_by_case
    panel.close()
    app.processEvents()
