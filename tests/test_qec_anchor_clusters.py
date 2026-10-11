"""Synthetische Regression fuer optionales QEC-Ankerverfahren.

Keine echten QEC-Kennungen, FINs oder DTCs gelangen ins Repository.
Die Checkbox darf bestehende HDBSCAN-/Complete-Link-Ergebnisse NICHT
veraendern oder bei Rueckwechsel erneut berechnen.
"""
from __future__ import annotations

import os

import numpy as np

from ntf_insight.analysis.autoexport_fin_patterns import (
    QEC_ANCHOR_MIN_SIMILARITY,
    _prepare,
    _qec_anchor_labels,
    cluster_fin_methods,
)


def _population():
    group_a = tuple(f"SYNTH-FIN-A-{i:03d}" for i in range(8))
    group_b = tuple(f"SYNTH-FIN-B-{i:03d}" for i in range(7))
    lonely = "SYNTH-FIN-LONELY"
    no_dtc = "SYNTH-FIN-WITHOUT-DTC"
    fins = (*group_a, *group_b, lonely, no_dtc)
    codes = {
        fin: [("CPC3", "TEST-A"), ("CTRL", "TEST-AUX-A")]
        for fin in group_a
    }
    codes.update({
        fin: [("CPC3", "TEST-B"), ("CTRL", "TEST-AUX-B")]
        for fin in group_b
    })
    codes[lonely] = [("CPC3", "ONLY-LONELY")]
    return fins, codes, group_a, group_b, lonely, no_dtc


def test_qec_seeds_form_actual_groups_only_with_matching_diagnoses():
    fins, codes, a, b, lonely, missing = _population()
    links = {
        a[0]: ("QEC-SYNTH-A",),
        a[1]: ("QEC-SYNTH-A2",),  # identical anchor signature, one group
        b[0]: ("QEC-SYNTH-B",),
        lonely: ("QEC-SYNTH-LONELY",),
    }
    runs = cluster_fin_methods(
        fins, codes, qec_links=links, min_cluster_size=5,
        include_qec_anchors=True,
    )
    assert set(runs) == {"leaf", "eom", "complete_cosine", "qec_anchor"}
    seeded = runs["qec_anchor"]
    assert seeded.method == "qec_anchor"
    assert seeded.total_fins == 17
    assert seeded.dtc_fins == 16
    assert seeded.no_dtc_fins == (missing,)
    assert seeded.assigned_fins == 15
    assert seeded.unassigned_fins == (lonely,)
    assert len(seeded.groups) == 2
    assert {
        frozenset(fin for fin, _ in group.members)
        for group in seeded.groups
    } == {frozenset(a), frozenset(b)}
    assert all(group.representative_is_fixed_anchor for group in seeded.groups)
    assert all(group.representative_has_qec for group in seeded.groups)
    assert all(group.representative_fin in links for group in seeded.groups)
    assert all(
        similarity + 1e-7 >= QEC_ANCHOR_MIN_SIMILARITY
        for group in seeded.groups for _fin, similarity in group.members
    )
    assert "KEIN HDBSCAN" in seeded.notes
    assert "NICHT zwischen jedem Fahrzeugpaar" in seeded.notes


def test_qec_anchor_mode_never_changes_existing_hdbscan_memberships():
    fins, codes, a, b, *_ = _population()
    qec_links = {a[0]: ("QEC-SYNTH-A",), b[0]: ("QEC-SYNTH-B",)}
    normal = cluster_fin_methods(
        fins, codes, qec_links=qec_links,
    )
    optional = cluster_fin_methods(
        fins, codes, qec_links=qec_links, include_qec_anchors=True,
    )
    assert set(normal) == {"leaf", "eom", "complete_cosine"}
    for method, before in normal.items():
        after = optional[method]
        assert before == after
    assert all(
        group.representative_has_qec
        for group in optional["qec_anchor"].groups
    )


def test_without_qec_dtc_anchors_no_vehicle_is_forced_into_group():
    fins, codes, *_ = _population()
    result = cluster_fin_methods(
        fins, codes, qec_links={}, include_qec_anchors=True,
    )["qec_anchor"]
    assert result.groups == ()
    assert result.assigned_fins == 0
    assert len(result.unassigned_fins) == result.dtc_fins
    assert result.total_fins == 17


def test_qec_anchor_uses_original_sparse_cosine_not_3d_plot_proximity():
    fins, codes, group_a, _group_b, lonely, _missing = _population()
    # The unique-DTC vehicle is a QEC seed but cannot join the
    # unrelated eight-vehicle group. Both remain exact ECU:DTC patterns.
    links = {group_a[0]: ("QEC-SYNTH-A",), lonely: ("QEC-SYNTH-L",)}
    prepared = _prepare(fins, codes, None, links)
    labels, strengths, anchors = _qec_anchor_labels(
        prepared, min_cluster_size=5, minimum_similarity=0.45,
    )
    assert len(anchors) == 2
    by_fin = {fin: labels[i] for i, fin in enumerate(prepared.eligible)}
    assert len({by_fin[fin] for fin in group_a}) == 1
    assert by_fin[group_a[0]] >= 0
    assert by_fin[lonely] == -1
    assert strengths.shape == (len(prepared.eligible),)
    assert strengths[prepared.eligible.index(lonely)] == 0.0
    assert np.all(np.isfinite(strengths))


def test_fin_checkbox_instantly_switches_cached_mode_and_back_to_eom():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from ntf_insight.app.widgets.autoexport_fin_workspace import (
        AutoExportFinWorkspace,
    )

    app = QApplication.instance() or QApplication([])
    fins, codes, a, b, *_ = _population()
    linked = {a[0]: ("QEC-SYNTH-A",), b[0]: ("QEC-SYNTH-B",)}
    runs = cluster_fin_methods(
        fins, codes, qec_links=linked, include_qec_anchors=True,
    )
    panel = AutoExportFinWorkspace(None, [])
    panel._run_results = runs
    panel._show_result(runs["leaf"])
    app.processEvents()
    assert not panel.qec_anchor_mode.isChecked()
    assert panel.method_combo.count() == 3
    panel.method_combo.setCurrentIndex(panel.method_combo.findData("eom"))
    assert panel.result is runs["eom"]

    panel.qec_anchor_mode.setChecked(True)
    app.processEvents()
    assert panel.method_combo.currentData() == "qec_anchor"
    assert not panel.method_combo.isEnabled()
    assert panel.result is runs["qec_anchor"]
    assert panel._task is None
    assert "QEC-Ankerverfahren" in panel.explanation.text()
    assert "QEC-FIN ist der feste Diagnose-Anker" in panel.explanation.text()
    assert "QEC-Ankergruppen" in panel.status.text()
    assert panel.number_labels["total"].text() == "17"
    assert panel.donut.values is not None
    assert sum(panel.donut.values) == 17

    panel.qec_anchor_mode.setChecked(False)
    app.processEvents()
    assert panel.method_combo.count() == 3
    assert panel.method_combo.currentData() == "eom"
    assert panel.method_combo.isEnabled()
    assert panel.result is runs["eom"]
    assert panel._task is None
    panel.qec_anchor_mode.setChecked(True)
    assert panel.result is runs["qec_anchor"]
    panel.close()
    app.processEvents()


def test_weak_autoexport_signature_is_not_assigned_to_qec_anchor():
    """SVD visual proximity must not override sparse-original threshold."""
    cluster = tuple(f"SYNTH-PUMP-{i:02d}" for i in range(6))
    weak = "SYNTH-PUMP-WEAK"
    codes = {
        fin: [("CPC3", "SHARED-A"), ("CTRL", "SHARED-B")]
        for fin in cluster
    }
    codes[weak] = [
        ("CPC3", "SHARED-A"),
        *[("CTRL", f"UNIQUE-{i:03d}") for i in range(30)],
    ]
    links = {cluster[0]: ("QEC-SYNTH",)}
    result = cluster_fin_methods(
        (*cluster, weak), codes, qec_links=links,
        min_cluster_size=5, include_qec_anchors=True,
    )["qec_anchor"]
    assert len(result.groups) == 1
    assert frozenset(fin for fin, _ in result.groups[0].members) == (
        frozenset(cluster)
    )
    assert result.groups[0].representative_fin == cluster[0]
    assert weak in result.unassigned_fins
    assert result.assigned_fins + len(result.unassigned_fins) == (
        result.dtc_fins
    )


def test_alternative_mode_available_through_explicit_single_method_api():
    from ntf_insight.analysis.autoexport_fin_patterns import (
        cluster_autoexport_fins,
    )

    fins, codes, a, b, *_ = _population()
    links = {
        a[0]: ("QEC-SYNTH-A",),
        b[0]: ("QEC-SYNTH-B",),
    }
    result = cluster_autoexport_fins(
        fins, codes, qec_links=links, method="qec_anchor",
    )
    assert result.method == "qec_anchor"
    assert len(result.groups) == 2
    assert all(group.representative_is_fixed_anchor for group in result.groups)
