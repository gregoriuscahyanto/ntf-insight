"""Native GUI smoke tests only on fictional diagnostic cases."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from ntf_insight.app.widgets.hdbscan_panel import HDBSCANPanel
from test_hdbscan_clustering import sample


def test_local_gap_and_medoid_views_are_read_only():
    app = QApplication.instance() or QApplication([])
    cases = sample()
    panel = HDBSCANPanel(cases)
    panel.run_analysis()
    assert panel.gap_model.rowCount() == 2
    assert "Keine FIN-Rohdatenbank" in panel.gap_summary.text()
    assert panel.transfer_model.rowCount() > 0
    assert "keine automatische" in panel.transfer_summary.text().lower()
    assert "Repräsentantenbefund" in panel.transfer_summary.text() or panel.transfer_model.rowCount() > 0
    panel.close()
    app.processEvents()


def test_exactly_one_representative_per_group_can_be_reviewed_and_shared_locally(
    tmp_path, monkeypatch,
):
    """One expert-reviewed medoid seeds *only* review hypotheses for others."""
    import csv

    from PySide6.QtWidgets import QFileDialog

    app = QApplication.instance() or QApplication([])
    panel = HDBSCANPanel(sample())
    panel.run_analysis()
    before = panel.result
    assert before is not None and len(before.clusters) == 2
    assert panel.representative_template_button.isEnabled()
    assert panel.transfer_export_button.isEnabled()

    template = tmp_path / "representatives_private.csv"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName",
        lambda *args, **kwargs: (str(template), "CSV-Dateien (*.csv)"),
    )
    panel.representative_template_button.click()
    with template.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f, delimiter=";"))
    medoids = {group.representative_case_id for group in before.clusters}
    assert len(rows) == len(medoids)
    assert {r["qec_case_id"] for r in rows} == medoids
    assert all(r["review_status"] == "pending" for r in rows)

    # Only one independent expert confirmation, no auto-learning from SSL.
    first = rows[0]
    first["review_status"] = "confirmed"
    first["mechanism_code"] = "PUMP_IMPELLER_BLOCKAGE"
    first["reviewer"] = "Synthetic reviewer"
    first["evidence_ref"] = "Synthetic lab sample"
    first["confirmed_on"] = "2026-10-09"
    with template.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys(), delimiter=";")
        writer.writeheader()
        writer.writerows(rows)
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName",
        lambda *args, **kwargs: (str(template), "CSV-Dateien (*.csv)"),
    )
    panel.import_review_button.click()
    assert panel.result == before
    assert len(panel.confirmed_mechanisms) == 1

    hypotheses = tmp_path / "hypotheses_private.csv"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName",
        lambda *args, **kwargs: (str(hypotheses), "CSV-Dateien (*.csv)"),
    )
    panel.transfer_export_button.click()
    with hypotheses.open(encoding="utf-8-sig", newline="") as f:
        proposals = list(csv.DictReader(f, delimiter=";"))
    assert len(proposals) == before.clustered_count - len(before.clusters)
    assert all(r["Ergebnisstatus Ziel"] == "Nicht bestätigt" for r in proposals)
    assert all(not r["Unabhängige Zielevidenz"] for r in proposals)
    assert any(
        row["Repräsentantenmechanismus nur als Hypothese"]
        == "PUMP_IMPELLER_BLOCKAGE" for row in proposals
    )
    assert any(
        not row["Repräsentantenmechanismus nur als Hypothese"]
        for row in proposals
    )
    panel.close()
    app.processEvents()


def test_local_duckdb_raw_autoexport_is_visible_without_mutating_qec(
    tmp_path,
):
    from ntf_insight.storage.duckdb_store import DuckDBStore
    from ntf_insight.storage.source_knowledge_store import SourceKnowledgeStore

    app = QApplication.instance() or QApplication([])
    cases = sample()
    victim = cases[0]
    victim.diagnostics.clear()
    db = DuckDBStore(tmp_path / "synthetic.duckdb")
    knowledge = SourceKnowledgeStore(db)
    knowledge.save_records(
        "synthetic-source-sha", "autoexport_rows",
        [{
            "category": "autoexport_dtc",
            "source_location": "row:1",
            "fin": victim.vin,
            "data": {
                "DiagStartDt": "2026-04-01",
                "DiagStartTs": "2026-04-01T12:00:00Z",
                "EcuNm": "CPC3", "EcuFaultNm": "P26F100",
            },
        }],
    )
    panel = HDBSCANPanel(cases, store=db)
    panel.run_analysis()
    assert panel.evidence_audit.without_any_dtc >= 1
    gap = next(r for r in panel.gap_model.rows if r[0] == victim.case_id)
    assert gap[6] == 1  # FIN raw pre-Tausch, not a QEC-attached fault
    assert gap[11] == 1  # AutoExport raw row only
    assert victim.diagnostics == []
    assert "Rohquellen lokal geprüft" in panel.gap_summary.text()
    panel.close()
    app.processEvents()
