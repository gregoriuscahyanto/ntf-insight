"""Projektlöschung: identitätsgenaue Grenzen, Quellenschutz und GUI-Bestätigung."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from ntf_insight.ingestion.artifacts import RawArchive, SourceType
from ntf_insight.storage.cluster_evidence_store import ClusterEvidenceStore
from ntf_insight.storage.duckdb_store import DuckDBStore
from ntf_insight.storage.qec_workflow_store import QecWorkflowStore
from ntf_insight.storage.workflow_progress import (
    WorkflowProgress, WorkflowProgressStore,
)
from ntf_insight.storage.workflow_project_deletion import (
    fully_delete_project, remove_project_assignment,
)
from ntf_insight.storage.workflow_projects import NTFProject, WorkflowProjectStore


FIN_A = "WDD12345678901234"
FIN_B = "WDD12345678901235"


def _storage(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    store = DuckDBStore(root / "ntf-insight.duckdb")
    projects = WorkflowProjectStore(store)
    WorkflowProgressStore(store)
    ClusterEvidenceStore(store)
    QecWorkflowStore(store)
    projects.save(
        NTFProject("coolant_pump", "A 111 222", "Kühlmittelpumpe", ("CPC3",))
    )
    projects.save(
        NTFProject("coolant_pump", "B 333 444", "Kühlmittelpumpe", ("MCM",))
    )
    with store.connect() as con:
        for case_id, fin, part in (
            ("CASE-A", FIN_A, "A 111 222"),
            ("CASE-B", FIN_B, "B 333 444"),
        ):
            con.execute(
                "INSERT INTO case_snapshots VALUES (?,?,?,?)",
                [
                    case_id, fin, "Kühlmittelpumpe",
                    json.dumps({
                        "case_id": case_id, "qec_part_number": part,
                        "component_profile_id": "coolant_pump",
                    }),
                ],
            )
    return store, projects


def _archive(store: DuckDBStore, root: Path, tmp_path: Path, fin: str):
    original = tmp_path / f"{fin}.txt"
    original.write_text(f"Synthetischer Nachweis {fin}", encoding="utf-8")
    artifact = RawArchive(root / "raw").archive(
        original, SourceType.OTHER, vin_hint=fin,
    )
    store.save_artifact(artifact)
    return artifact


def test_remove_assignment_preserves_every_case_and_archive(tmp_path):
    root = tmp_path / "data"
    store, projects = _storage(root)
    artifact = _archive(store, root, tmp_path, FIN_A)
    WorkflowProgressStore(store).select_context("coolant_pump", "A 111 222")
    result = remove_project_assignment(store, "coolant_pump", "A111222")
    assert not result.complete
    assert projects.get("coolant_pump", "A111222") is None
    assert projects.get("coolant_pump", "B333444") is not None
    with store.connect() as con:
        assert con.execute("SELECT COUNT(*) FROM case_snapshots").fetchone()[0] == 2
        assert con.execute(
            "SELECT COUNT(*) FROM source_artifacts WHERE sha256=?",
            [artifact.sha256],
        ).fetchone()[0] == 1
    assert Path(artifact.archived_path).is_file()
    assert WorkflowProgressStore(store).current_context() == ("coolant_pump", "")
    # Nach dem Entfernen kann derselbe Bestand als neues Projekt übernommen werden.
    projects.save(
        NTFProject("coolant_pump", "A111222", "Kühlmittelpumpe", ("CPC3",)),
        create_only=True,
    )
    assert projects.get("coolant_pump", "A111222") is not None


def test_fully_delete_only_exclusive_files_and_keep_other_project(tmp_path):
    root = tmp_path / "data"
    store, projects = _storage(root)
    original_a = _archive(store, root, tmp_path, FIN_A)
    original_b = _archive(store, root, tmp_path, FIN_B)
    for folder, fin, text in (
        ("quicktests", FIN_A, "A QuickTest"),
        ("qec", FIN_A, "A QEC report"),
        ("tips", FIN_A, "A TIPS"),
        ("quicktests", FIN_B, "B QuickTest"),
    ):
        path = root / folder / fin
        path.mkdir(parents=True, exist_ok=True)
        (path / "test.txt").write_text(text, encoding="utf-8")
    evidence = tmp_path / "technical.txt"
    evidence.write_text("Nur Projekt A", encoding="utf-8")
    ClusterEvidenceStore(store).add_files(
        "coolant_pump", "A111222", "additional", [evidence],
    )
    WorkflowProgressStore(store).save(
        "coolant_pump", "A111222",
        WorkflowProgress(step=3, reviewed_steps=(3,)),
    )
    result = fully_delete_project(store, root, "coolant_pump", "A 111 222")
    assert result.complete
    assert result.cases_deleted == 1
    assert not (root / "quicktests" / FIN_A).exists()
    assert not (root / "qec" / FIN_A).exists()
    assert not (root / "tips" / FIN_A).exists()
    assert not Path(original_a.archived_path).exists()
    assert Path(original_b.archived_path).exists()
    assert (root / "quicktests" / FIN_B / "test.txt").is_file()
    assert projects.get("coolant_pump", "A111222") is None
    assert projects.get("coolant_pump", "B333444") is not None
    with store.connect() as con:
        assert con.execute(
            "SELECT case_id FROM case_snapshots ORDER BY case_id"
        ).fetchall() == [("CASE-B",)]
        assert con.execute(
            "SELECT COUNT(*) FROM cluster_evidence_files "
            "WHERE profile_id='coolant_pump'"
        ).fetchone()[0] == 0
        assert con.execute(
            "SELECT COUNT(*) FROM workflow_progress "
            "WHERE part_number='A111222'"
        ).fetchone()[0] == 0


def test_full_delete_refuses_shared_qec_excel_and_preserves_all(tmp_path, monkeypatch):
    root = tmp_path / "data"
    store, projects = _storage(root)
    artifact = _archive(store, root, tmp_path, FIN_A)
    shared_sha = "a" * 64
    monkeypatch.setattr(
        QecWorkflowStore, "rows",
        lambda _self, _dir: [
            {
                "fin": FIN_A, "case_id": "CASE-A", "part_number": "A111222",
                "source_sha256": shared_sha,
            },
            {
                "fin": FIN_B, "case_id": "CASE-B", "part_number": "B333444",
                "source_sha256": shared_sha,
            },
        ],
    )
    with pytest.raises(ValueError, match="QEC-Excel"):
        fully_delete_project(store, root, "coolant_pump", "A111222")
    assert projects.get("coolant_pump", "A111222") is not None
    assert projects.get("coolant_pump", "B333444") is not None
    assert Path(artifact.archived_path).exists()
    with store.connect() as con:
        assert con.execute("SELECT COUNT(*) FROM case_snapshots").fetchone()[0] == 2


def test_full_delete_refuses_fin_shared_between_projects(tmp_path):
    root = tmp_path / "data"
    store, projects = _storage(root)
    with store.connect() as con:
        con.execute(
            "UPDATE case_snapshots SET vin=? WHERE case_id='CASE-B'", [FIN_A],
        )
    with pytest.raises(ValueError, match="FIN"):
        fully_delete_project(store, root, "coolant_pump", "A111222")
    assert projects.get("coolant_pump", "A111222") is not None


def test_project_settings_confirmation_requires_exact_part_number(tmp_path, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QMessageBox, QInputDialog

    from ntf_insight.app.pages.project_settings_page import ProjectSettingsPage

    app = QApplication.instance() or QApplication([])
    _store, projects = _storage(tmp_path / "data")
    widget = ProjectSettingsPage(projects)
    widget.select_project("coolant_pump", "A 111 222")
    assert widget.project_selector.currentData() == (
        "coolant_pump", "A 111 222",
    )
    assert widget.part_edit.text() == "A 111 222"
    assert not widget._is_new
    requested = []
    widget.project_delete_requested.connect(
        lambda p, n, full: requested.append((p, n, full))
    )
    monkeypatch.setattr(
        QMessageBox, "question",
        lambda *_a, **_k: QMessageBox.StandardButton.Yes,
    )
    monkeypatch.setattr(
        QMessageBox, "warning",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        QInputDialog, "getText", lambda *_a, **_k: ("A111222", True),
    )
    widget.delete_button.click()
    assert not requested
    assert projects.get("coolant_pump", "A111222") is not None
    monkeypatch.setattr(
        QInputDialog, "getText", lambda *_a, **_k: ("A 111 222", True),
    )
    assert widget.remove_button.isEnabled()
    assert widget.delete_button.isEnabled()
    widget._confirm_project_deletion(False)
    widget._confirm_project_deletion(True)
    assert requested == [
        ("coolant_pump", "A 111 222", False),
        ("coolant_pump", "A 111 222", True),
    ]
    widget.close()
    app.processEvents()



def test_full_delete_preserves_same_sha_evidence_used_by_another_project(tmp_path):
    root = tmp_path / "data"
    store, projects = _storage(root)
    doc = tmp_path / "shared.txt"
    doc.write_text("Für beide Projekte relevante Setzbedingungen", encoding="utf-8")
    evidence = ClusterEvidenceStore(store)
    evidence.add_files("coolant_pump", "A111222", "additional", [doc])
    evidence.add_files("coolant_pump", "B333444", "additional", [doc])
    sha = evidence.list_files("coolant_pump", "A111222")[0].sha256
    target = evidence.list_files("coolant_pump", "B333444")[0].source_path
    assert target.exists()

    result = fully_delete_project(store, root, "coolant_pump", "A111222")
    assert result.complete
    assert result.shared_files_retained >= 1
    assert target.is_file()
    assert not evidence.list_files("coolant_pump", "A111222")
    assert evidence.list_files("coolant_pump", "B333444")[0].sha256 == sha
    assert projects.get("coolant_pump", "B333444") is not None
