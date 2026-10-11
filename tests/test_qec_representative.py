"""Synthetische Tests: QEC-FIN als repraesentativer, nicht erzwungener Medoid."""
from __future__ import annotations

import os

import numpy as np
import pytest

from ntf_insight.analysis.autoexport_fin_patterns import (
    QEC_REPRESENTATIVE_MIN_CENTRALITY_RATIO,
    _make_result,
    _prepare,
    _representative_position,
    cluster_fin_methods,
)
from test_autoexport_fin_patterns import _synthetic_population


@pytest.mark.parametrize(
    ("scores", "qec_indices", "selected"),
    [
        ((0.95, 0.92, 0.41), (1,), 1),  # QEC almost as typical as best FIN
        ((0.95, 0.72, 0.41), (1,), 0),  # atypical QEC must NOT be forced
        ((0.95, 0.92, 0.41), (), 0),   # no QEC: ordinary optimum
        ((0.80, 0.80, 0.41), (1,), 1),  # ties favour QEC
        ((0.98, 0.91, 0.97), (1, 2), 2),  # best qualifying QEC
        ((0.95, 0.80, 0.94), (1,), 0),  # QEC below 90% of optimum
    ],
)
def test_prefer_qec_only_when_representative(scores, qec_indices, selected):
    fins = tuple(f"SYNTH-FIN-{number}" for number in range(len(scores)))
    links = {
        fins[index]: ("QEC-SYNTHETIC",)
        for index in qec_indices
    }
    index, relative_centrality = _representative_position(
        fins, np.array(scores), links,
    )
    assert index == selected
    assert relative_centrality == pytest.approx(
        scores[selected] / max(scores), abs=0.0001,
    )


def test_representative_qec_tie_breaker_is_independent_of_fin_input_order():
    scores = np.array([0.8, 0.8, 0.8])
    fins = ("SYNTH-C", "SYNTH-B", "SYNTH-A")
    links = {
        "SYNTH-A": ("QEC-SYNTH",),
        "SYNTH-B": ("QEC-SYNTH",),
    }
    index, similarity = _representative_position(fins, scores, links)
    assert fins[index] == "SYNTH-A"
    assert similarity == 1.0
    assert QEC_REPRESENTATIVE_MIN_CENTRALITY_RATIO == 0.9


def test_qec_rep_changes_no_memberships_and_no_cluster_ids():
    fins, dtcs, *_ = _synthetic_population()
    baseline = cluster_fin_methods(fins, dtcs, min_cluster_size=5)
    # Link original most central FIN in each HDBSCAN Leaf group.
    qec = {
        group.representative_fin: (f"QEC-SYNTH-{i}",)
        for i, group in enumerate(baseline["leaf"].groups, start=1)
    }
    linked = cluster_fin_methods(fins, dtcs, qec_links=qec, min_cluster_size=5)
    assert set(linked) == {"leaf", "eom", "complete_cosine"}
    for method in baseline:
        before, after = baseline[method], linked[method]
        assert before.total_fins == after.total_fins == 23
        assert before.unassigned_fins == after.unassigned_fins
        assert before.no_dtc_fins == after.no_dtc_fins
        assert [
            (group.group_id, frozenset(fin for fin, _ in group.members))
            for group in before.groups
        ] == [
            (group.group_id, frozenset(fin for fin, _ in group.members))
            for group in after.groups
        ]
        for group in after.groups:
            assert group.representative_fin in dict(group.members)
            assert group.representative_has_qec == (
                group.representative_fin in qec
            )
            assert 0 < group.representative_centrality_ratio <= 1.0
            if group.representative_has_qec:
                assert group.representative_centrality_ratio >= 0.9

    assert all(group.representative_has_qec for group in linked["leaf"].groups)


def test_gui_identifies_qec_representative_and_explains_selection():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from ntf_insight.app.widgets.autoexport_fin_workspace import (
        AutoExportFinWorkspace,
    )

    app = QApplication.instance() or QApplication([])
    fins, dtcs, *_ = _synthetic_population()
    previous = cluster_fin_methods(fins, dtcs)["leaf"]
    qec = {
        group.representative_fin: ("QEC-SYNTH",)
        for group in previous.groups
    }
    current = cluster_fin_methods(
        fins, dtcs, qec_links=qec,
    )["leaf"]
    panel = AutoExportFinWorkspace(None, [])
    panel.show()
    panel._show_result(current)
    app.processEvents()

    assert panel.group_model.rowCount() == len(current.groups)
    assert all(row[6] == "Ja" for row in panel.group_model.rows)
    assert "Repräsentant:" in panel.explanation.text()
    assert "FIN mit QEC-Fall" in panel.explanation.text()
    assert "mittlerer Diagnose-Cosinuswert" in panel.explanation.text()
    assert panel.result is current
    panel.close()
    app.processEvents()


def _one_diagnostic_group(qec_indices: tuple[int, ...]):
    """Force the SAME assigned group: A-D typical, E has many rare DTCs."""
    fins = tuple(f"SYNTH-VEHICLE-{i}" for i in range(5))
    faults = {fin: [("CPC3", "SHARED")] for fin in fins}
    faults[fins[-1]] += [
        ("CPC3", f"RARE-{i}") for i in range(15)
    ]
    qec = {
        fins[index]: (f"QEC-SYNTH-{index}",)
        for index in qec_indices
    }
    prepared = _prepare(fins, faults, None, qec)
    result = _make_result(
        prepared, "leaf", np.zeros(5, dtype=int),
        np.ones(5, dtype=float), min_cluster_size=3,
        notes="Synthetische Gruppenbewertung",
    )
    assert len(result.groups) == 1
    return result.groups[0], result


def test_real_sparse_cosine_keeps_best_when_only_qec_member_is_atypical():
    group, result = _one_diagnostic_group((4,))
    assert group.fin_count == 5
    assert group.qec_fin_count == 1
    assert not group.representative_has_qec
    assert group.representative_fin != "SYNTH-VEHICLE-4"
    assert group.representative_centrality_ratio == 1.0
    assert dict(group.members)[group.representative_fin] == 1.0
    assert result.assigned_fins == 5


def test_real_sparse_cosine_prefers_typical_qec_over_an_atypical_qec():
    group, _ = _one_diagnostic_group((1, 4))
    assert group.qec_fin_count == 2
    assert group.representative_fin == "SYNTH-VEHICLE-1"
    assert group.representative_has_qec
    assert group.unconstrained_representative_fin == "SYNTH-VEHICLE-0"
    assert group.representative_centrality_ratio == 1.0


def test_gui_explains_fallback_if_qec_in_cluster_is_atypical():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from ntf_insight.app.widgets.autoexport_fin_workspace import (
        AutoExportFinWorkspace,
    )

    app = QApplication.instance() or QApplication([])
    _group, result = _one_diagnostic_group((4,))
    panel = AutoExportFinWorkspace(None, [])
    panel._show_result(result)
    app.processEvents()
    assert panel.group_model.rows[0][6] == "Nein"
    assert "Diese sind jedoch diagnostisch weniger typisch" in (
        panel.explanation.text()
    )
    assert "Repräsentant:" in panel.explanation.text()
    panel.close()
    app.processEvents()
