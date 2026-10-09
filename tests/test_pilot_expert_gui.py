"""Synthetic Qt roundtrip: selected pilot CSV -> expert -> audited comparison."""
from __future__ import annotations

import csv

from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from ntf_insight.app.widgets.hdbscan_panel import HDBSCANPanel
from test_hdbscan_clustering import sample


def _write_rows(path, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, delimiter=";", fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _confirm(row, cause, evidence):
    row["review_status"] = "confirmed"
    row["mechanism_code"] = cause
    row["reviewer"] = "Synthetic reviewer"
    row["evidence_ref"] = evidence
    row["confirmed_on"] = "2026-10-09"


def test_pilot_local_review_imports_verified_rep_and_target_and_preserves_prior_labels(
    tmp_path, monkeypatch,
):
    app = QApplication.instance() or QApplication([])
    panel = HDBSCANPanel(sample())
    panel.run_analysis()
    original = panel.result
    assert original is not None
    assert panel.pilot_review_button.isEnabled()
    assert panel.latest_pilot_validation.reviewed_representatives == 0
    assert panel.latest_pilot_validation.comparable_target_fins == 0

    target = tmp_path / "pilot_private_NICHT_HOCHLADEN.csv"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName",
        lambda *args, **kwargs: (str(target), "CSV-Dateien (*.csv)"),
    )
    panel.pilot_review_button.click()
    with target.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream, delimiter=";"))
    assert len(rows) == len(panel.latest_pilot_plan.inspections)
    group = original.clusters[0]
    first = next(r for r in rows if r["qec_case_id"] == group.representative_case_id)
    second = next(
        r for r in rows if r["pilot_group"] == f"H{group.cluster_id}"
        and r["qec_case_id"] != group.representative_case_id
    )
    _confirm(first, "PUMP_SYNTHETIC_WINDING", "EVIDENCE-1")
    _confirm(second, "PUMP_SYNTHETIC_WINDING", "EVIDENCE-2")
    _write_rows(target, rows)

    monkeypatch.setattr(
        QFileDialog, "getOpenFileName",
        lambda *args, **kwargs: (str(target), "CSV-Dateien (*.csv)"),
    )
    panel.import_review_button.click()
    assert panel.result == original
    assert len(panel.confirmed_mechanisms) == 2
    assert panel.latest_pilot_validation.concordant_target_fins == 1
    assert panel.latest_pilot_validation.comparable_target_fins == 1
    assert any(
        "Getrennte Evidenz" in row[8]
        for row in panel.pilot_validation_target_model.rows
    )

    # Importing a *different subset* must not delete previous confirmations.
    # Use a new review template with just the other cluster medoid.
    alternate = next(
        r for r in rows if r["pilot_group"] != f"H{group.cluster_id}"
        and "Repräsentant" in r["pilot_role"]
    )
    other_path = tmp_path / "new_synthetic_reviewer.csv"
    partial = dict(alternate)
    _confirm(partial, "PUMP_SYNTHETIC_HOSE", "EVIDENCE-3")
    _write_rows(other_path, [partial])
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName",
        lambda *args, **kwargs: (str(other_path), "CSV-Dateien (*.csv)"),
    )
    panel.import_review_button.click()
    assert len(panel.confirmed_mechanisms) == 3
    assert panel.latest_pilot_validation.reviewed_representatives == 2
    assert panel.latest_pilot_validation.concordant_target_fins == 1

    previous = panel.confirmed_mechanisms
    conflicting = dict(first)
    _confirm(conflicting, "PUMP_SYNTHETIC_DIFFERENT", "EVIDENCE-CHANGED")
    _write_rows(other_path, [conflicting])
    messages = []
    monkeypatch.setattr(
        QMessageBox, "warning",
        lambda _parent, title, message: messages.append((title, message)),
    )
    panel.import_review_button.click()
    assert messages and "Widersprechende" in messages[0][0]
    assert panel.confirmed_mechanisms == previous
    panel.close()
    app.processEvents()
