"""Sicherheits- und Trennungsprüfungen für den einzelnen .ntfproject-Transfer."""
from __future__ import annotations

import json
from pathlib import Path
from zipfile import ZipFile

import duckdb
import pytest

from ntf_insight.ingestion.artifacts import RawArchive, SourceType
from ntf_insight.ingestion.project_portable import (
    PROJECT_EXTENSION, export_project, import_project,
)
from ntf_insight.storage.duckdb_store import DuckDBStore
from ntf_insight.storage.workflow_progress import WorkflowProgressStore
from ntf_insight.storage.workflow_projects import NTFProject, WorkflowProjectStore


FIN_A = "WDD12345678901234"
FIN_B = "WDD12345678901235"


def _setup(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    store = DuckDBStore(root / "ntf-insight.duckdb")
    projects = WorkflowProjectStore(store)
    WorkflowProgressStore(store)
    from ntf_insight.storage.cluster_evidence_store import ClusterEvidenceStore
    ClusterEvidenceStore(store)
    from ntf_insight.storage.workflow_ai_chain import WorkflowAIChainStore
    WorkflowAIChainStore(store)
    from ntf_insight.storage.qec_workflow_store import QecWorkflowStore
    QecWorkflowStore(store)
    return store, projects


def _case(store, part, fin, number):
    # A transfer test reads raw canonical snapshots, without requiring the
    # much larger application-data bootstrap or any real FIN.
    with store.connect() as con:
        con.execute(
            "INSERT INTO case_snapshots VALUES (?,?,?,?)",
            [
                f"CASE-{number}", fin, "coolant_pump",
                json.dumps({
                    "case_id": f"CASE-{number}", "qec_part_number": part,
                    "vehicle": {"vin": fin},
                }),
            ],
        )


def _raw(store, root: Path, name: str, content: bytes, fin: str):
    original = root.parent / name
    original.write_bytes(content)
    raw = RawArchive(root / "raw")
    artifact = raw.archive(original, SourceType.OTHER, vin_hint=fin)
    store.save_artifact(artifact)
    return artifact


def test_project_package_imports_only_selected_part_and_preserves_other_projects(tmp_path):
    origin = tmp_path / "pc1"
    source, projects = _setup(origin)
    projects.save(NTFProject("coolant_pump", "A 100 200", "Kühlmittelpumpe", ("CPC3",)))
    projects.save(NTFProject("coolant_pump", "B 900 800", "Pumpe 2", ("SAM",)))
    _case(source, "A100200", FIN_A, "A")
    _case(source, "B900800", FIN_B, "B")
    art_a = _raw(source, origin, "a-doc.txt", b"CPC3 Project A", FIN_A)
    art_b = _raw(source, origin, "b-doc.txt", b"SAM Project B", FIN_B)
    (origin / "quicktests" / FIN_A).mkdir(parents=True)
    (origin / "quicktests" / FIN_A / "test.pdf").write_bytes(b"A QuickTest")
    (origin / "quicktests" / FIN_B).mkdir(parents=True)
    (origin / "quicktests" / FIN_B / "test.pdf").write_bytes(b"B QuickTest")

    package = tmp_path / ("pumpe" + PROJECT_EXTENSION)
    export_steps = []
    result = export_project(
        origin, package, "coolant_pump", "A100200",
        progress=lambda percent, message: export_steps.append((percent, message)),
    )
    assert export_steps[0][0] >= 0
    assert export_steps[-1][0] == 100
    assert any("Projektarchiv" in label for _, label in export_steps)
    assert result.case_count == 1
    assert result.fin_count == 1
    assert package.is_file()
    assert package.suffix == ".ntfproject"
    assert art_a.sha256 != art_b.sha256

    # A different existing project on PC2 must not be deleted or overwritten.
    target = tmp_path / "pc2"
    other, other_projects = _setup(target)
    other_projects.save(NTFProject("coolant_pump", "Z 777 777", "Altprojekt", ("MCM",)))
    _case(other, "Z777777", FIN_B, "LOCAL")
    import_steps = []
    imported = import_project(
        package, target,
        progress=lambda percent, message: import_steps.append((percent, message)),
    )
    assert import_steps[0][0] >= 0
    assert import_steps[-1][0] == 100
    assert any("Projekttabellen" in label for _, label in import_steps)
    assert imported.part_number == "A 100 200"
    reopened = WorkflowProjectStore(DuckDBStore(target / "ntf-insight.duckdb"))
    assert {p.part_number for p in reopened.list_projects()} == {
        "A 100 200", "Z 777 777",
    }
    with duckdb.connect(str(target / "ntf-insight.duckdb"), read_only=True) as con:
        rows = con.execute(
            "SELECT case_id FROM case_snapshots ORDER BY case_id"
        ).fetchall()
        shas = {
            r[0] for r in con.execute(
                "SELECT sha256 FROM source_artifacts"
            ).fetchall()
        }
    assert rows == [("CASE-A",), ("CASE-LOCAL",)]
    assert art_a.sha256 in shas
    assert art_b.sha256 not in shas
    assert (target / "quicktests" / FIN_A / "test.pdf").read_bytes() == b"A QuickTest"
    assert not (target / "quicktests" / FIN_B / "test.pdf").exists()

    # Identically named projects may NOT be silently overwritten.
    with pytest.raises(ValueError, match="existiert"):
        import_project(package, target)


def test_project_package_requires_registered_project_and_detects_tampering(tmp_path):
    source = tmp_path / "data"
    store, projects = _setup(source)
    _case(store, "A100200", FIN_A, "A")
    package = tmp_path / "first.ntfproject"
    with pytest.raises(ValueError, match="noch nicht angelegt"):
        export_project(source, package, "coolant_pump", "A100200")
    projects.save(NTFProject("coolant_pump", "A100200", "Kühlmittelpumpe", ()))
    export_project(source, package, "coolant_pump", "A100200")
    with ZipFile(package, "a") as archive:
        archive.writestr("../evasion.txt", b"bad")
    with pytest.raises(ValueError, match="unerwartete"):
        import_project(package, tmp_path / "unmodified")
    assert not (tmp_path / "unmodified" / "ntf-insight.duckdb").exists()


def test_project_import_does_not_confuse_global_backup(tmp_path):
    from ntf_insight.ingestion.portable_backup import export_portable_backup

    store, projects = _setup(tmp_path / "source")
    projects.save(NTFProject("coolant_pump", "A100200", "Kühlmittelpumpe", ()))
    export_portable_backup(tmp_path / "source", tmp_path / "all.ntfbackup")
    with pytest.raises(ValueError, match="reguläres"):
        import_project(tmp_path / "all.ntfbackup", tmp_path / "target")



def test_two_independent_qec_excel_projects_survive_transfer_on_one_pc(tmp_path):
    """Both QEC masters remain usable after transferring A onto PC B."""
    from test_qec_workflow import _primary
    from ntf_insight.ingestion.batch_import import LocalBatchImporter
    from ntf_insight.ingestion.service import SourceImportService
    from ntf_insight.storage.qec_workflow_store import QecWorkflowStore

    left = tmp_path / "pc_a"
    right = tmp_path / "pc_b"
    left_store, left_projects = _setup(left)
    right_store, right_projects = _setup(right)
    left_projects.save(NTFProject(
        "coolant_pump", "SYNTH-PART-A", "Pumpe A", ("CPC3",),
    ))
    right_projects.save(NTFProject(
        "coolant_pump", "SYNTH-PART-B", "Pumpe B", ("SAM",),
    ))
    xlsx_a = tmp_path / "a.xlsx"
    xlsx_b = tmp_path / "b.xlsx"
    _primary(
        xlsx_a, "11111", fin=FIN_A, part="SYNTH-PART-A",
    )
    _primary(
        xlsx_b, "22222", fin=FIN_B, part="SYNTH-PART-B",
    )
    LocalBatchImporter(SourceImportService(
        left / "raw", left / "ntf-insight.duckdb",
    )).import_paths([xlsx_a])
    LocalBatchImporter(SourceImportService(
        right / "raw", right / "ntf-insight.duckdb",
    )).import_paths([xlsx_b])
    package = tmp_path / "A.ntfproject"
    exported = export_project(
        left, package, "coolant_pump", "SYNTH-PART-A",
    )
    assert exported.case_count == 1
    assert exported.fin_count == 1
    imported = import_project(package, right)
    assert imported.case_count == 1
    rows = QecWorkflowStore(right_store).rows(right / "qec")
    assert len(rows) == 2
    assert {r["part_number"] for r in rows} == {
        "SYNTH-PART-A", "SYNTH-PART-B",
    }
    assert len(QecWorkflowStore(right_store).active_sources()) == 2
    assert WorkflowProjectStore(right_store).get(
        "coolant_pump", "SYNTH-PART-B"
    ) is not None
