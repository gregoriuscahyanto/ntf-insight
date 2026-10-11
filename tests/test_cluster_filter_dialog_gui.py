"""Offscreen-GUI-Tests: drei Filterbereiche mit sechs Reiter-Listen.

Nur synthetische Steuergeräte, DTCs und SSL-Befunde.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialog, QFrame, QLineEdit

from ntf_insight.analysis.cluster_dtc_filters import ClusterDtcFilter
from ntf_insight.app.widgets.cluster_dtc_filter_dialog import (
    ClusterDtcFilterDialog,
)


def test_three_main_tabs_and_two_action_tabs_each():
    app = QApplication.instance() or QApplication([])
    dialog = ClusterDtcFilterDialog(
        {
            ("CPC3", "P100"): (8, 14, "Synthetische Pumpe"),
            ("BMS", "P200"): (3, 4, "Synthetische Batterie"),
        },
        ClusterDtcFilter(),
        findings={
            "Synthetischer Endbefund": (7, "SYNTH-SSL-A"),
            "(Ohne SSL-Endbefund)": (2, ""),
        },
    )
    dialog.show()
    app.processEvents()
    assert [dialog.tabs.tabText(i) for i in range(dialog.tabs.count())] == [
        "Steuergeräte", "ECU:DTC", "SSL-Endbefund",
    ]
    for name in ("ecus", "faults", "findings"):
        assert [dialog._subtabs[name].tabText(i) for i in range(2)] == [
            "Einschließen", "Ausschließen",
        ]
    assert len(dialog._views) == 6
    assert not dialog.selected_rules().active
    dialog.close()


def test_ssl_search_selection_removal_and_exclusion_precedence():
    app = QApplication.instance() or QApplication([])
    dialog = ClusterDtcFilterDialog(
        {("CPC3", "P100"): (3, 4, "Synthetischer Text")},
        ClusterDtcFilter(),
        findings={
            "Synthetischer Endbefund": (7, "SYNTH-SSL-A"),
            "Nicht reproduzierbar": (4, "SYNTH-SSL-B"),
        },
    )
    dialog.show()
    app.processEvents()
    included = dialog._subtabs["findings"].widget(0)
    search = included.findChild(QLineEdit)
    search.setText("synth-ssl-a")
    view, proxy, model, _status = dialog._views["include_findings"]
    assert proxy.rowCount() == 1
    view.selectRow(0)
    dialog._change("include_findings", True)
    assert dialog.selected_rules().include_findings == frozenset(
        ("synthetischer endbefund",)
    )
    assert model.rows[0][0] == "✓"

    dialog._subtabs["findings"].setCurrentIndex(1)
    excluded_view, excluded_proxy, _, _ = dialog._views["exclude_findings"]
    # Source sorting is not required; find the same label via search.
    exclude_search = dialog._subtabs["findings"].widget(1).findChild(QLineEdit)
    exclude_search.setText("synth-ssl-a")
    assert excluded_proxy.rowCount() == 1
    excluded_view.selectRow(0)
    dialog._change("exclude_findings", True)
    assert dialog.selected_rules().exclude_findings == frozenset(
        ("synthetischer endbefund",)
    )
    # The actual case filter gives exclusions priority.
    from ntf_insight.analysis.qec_end_finding_filter import selected_qec_cases
    from test_hdbscan_clustering import synthetic

    case = synthetic("QEC-SYNTH", "X", 1)
    case.qec_reference = case.case_id
    case.qec_ssl_end_finding = "Synthetischer Endbefund"
    rules = dialog.selected_rules()
    assert selected_qec_cases(
        (case,), exact_findings=rules.include_findings,
        excluded_findings=rules.exclude_findings,
    ) == ()

    excluded_view.selectRow(0)
    dialog._change("exclude_findings", False)
    assert not dialog.selected_rules().exclude_findings
    dialog._reset()
    assert not dialog.selected_rules().active
    # A text search can explicitly add all matching SSL findings.
    search.setText("SYNTH-SSL-B")
    assert proxy.rowCount() == 1
    dialog._add_matches("include_findings")
    assert dialog.selected_rules().include_findings == frozenset(
        ("nicht reproduzierbar",)
    )
    dialog.close()


def test_ecu_and_fault_lists_stay_separate():
    app = QApplication.instance() or QApplication([])
    dialog = ClusterDtcFilterDialog(
        {("CPC3", "P100"): (2, 5, "Pumpe")},
        ClusterDtcFilter(),
    )
    ecu_view, _, _, _ = dialog._views["include_ecus"]
    ecu_view.selectRow(0)
    dialog._change("include_ecus", True)
    fault_view, _, _, _ = dialog._views["exclude_faults"]
    fault_view.selectRow(0)
    dialog._change("exclude_faults", True)
    rules = dialog.selected_rules()
    assert rules.include_ecus == frozenset(("CPC3",))
    assert rules.exclude_faults == frozenset({("CPC3", "P100")})
    assert not rules.accepts("CPC3", "P100")
    dialog.close()


def test_cluster_workspace_uses_one_card_and_independent_qec_anchor():
    from ntf_insight.app.widgets.autoexport_fin_workspace import (
        AutoExportFinWorkspace,
    )

    app = QApplication.instance() or QApplication([])
    panel = AutoExportFinWorkspace(None, [])
    panel.show()
    app.processEvents()
    assert panel.filter_button.text() == "Filter"
    assert "Steuergeräte" in panel.filter_summary.text()
    assert "ECU:DTC" in panel.filter_summary.text()
    assert "SSL-Endbefund" in panel.filter_summary.text()
    assert panel.plot.mode == "3d"
    assert not hasattr(panel, "dimension")
    assert panel.overview_card.isVisible()
    # One compact overview Card + the separate 3D plot Card.
    cards = [
        frame for frame in panel.findChildren(QFrame)
        if frame.objectName() == "Card"
    ]
    assert len(cards) == 2
    assert panel.only_qec.isChecked()
    assert panel.qec_anchor_mode.isVisible()
    assert panel.qec_anchor_mode.isEnabled()
    panel.qec_anchor_mode.setChecked(True)
    assert panel.only_qec.isChecked()
    assert panel.qec_anchor_mode.isChecked()
    panel.only_qec.setChecked(False)
    assert panel.qec_anchor_mode.isVisible()
    assert panel.qec_anchor_mode.isChecked()
    panel.close()
    app.processEvents()


def test_filter_button_applies_ssl_exclusion_and_updates_main_overview(monkeypatch):
    from ntf_insight.app.widgets import autoexport_fin_workspace as workspace
    from test_hdbscan_clustering import synthetic

    app = QApplication.instance() or QApplication([])
    case = synthetic("SYNTH-QEC", "X", 1)
    case.qec_reference = case.case_id
    case.qec_ssl_end_finding = "Synthetischer SSL-Endbefund"
    panel = workspace.AutoExportFinWorkspace(None, [case])
    panel.show()
    app.processEvents()
    dialogs_opened = []

    class FakeDialog:
        DialogCode = QDialog.DialogCode

        def __init__(self, catalog, rules, parent, *, findings):
            assert parent is panel
            assert "Synthetischer SSL-Endbefund" in findings
            dialogs_opened.append(True)

        def exec(self):
            return self.DialogCode.Accepted

        def selected_rules(self):
            return ClusterDtcFilter(
                exclude_findings=frozenset(("Synthetischer SSL-Endbefund",))
            )

    monkeypatch.setattr(workspace, "ClusterDtcFilterDialog", FakeDialog)
    panel.filter_button.click()
    assert dialogs_opened
    assert not panel._matched_qec_cases()
    assert "Synthetischer SSL-Endbefund" in panel.filter_summary.text()
    assert "0 von 1 QEC-Fällen" in panel.finding_summary.text()
    assert panel.qec_anchor_mode.isVisible()
    assert panel.qec_anchor_mode.isEnabled()
    panel.close()
    app.processEvents()
