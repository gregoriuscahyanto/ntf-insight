"""Unterlagenkategorien und zweiter ChatGPT-Durchlauf mit synthetischen Dateien."""
from __future__ import annotations

import json
from pathlib import Path
from zipfile import ZipFile

import pytest

from ntf_insight.reporting.cluster_context_package import (
    export_cluster_context, validate_first_package,
)
from ntf_insight.storage.cluster_evidence_store import (
    CATEGORY_LABELS, ClusterEvidenceStore,
)
from ntf_insight.storage.duckdb_store import DuckDBStore


def _store(tmp_path: Path) -> ClusterEvidenceStore:
    root = tmp_path / "ntf-data"
    return ClusterEvidenceStore(
        DuckDBStore(root / "ntf-insight.duckdb"),
    )


def _basis(tmp_path: Path, *, originals: bool = False) -> Path:
    name = tmp_path / "erste-analyse.zip"
    package_id = "a" * 32
    with ZipFile(name, "w") as archive:
        archive.writestr("manifest.json", json.dumps({
            "schema_version": 3,
            "paket_id": package_id,
            "pseudonymisiert": not originals,
        }))
        archive.writestr(
            "chatgpt_ergebnis_vorlage.json",
            json.dumps({"paket_id": package_id, "analyse_id": "neu"}),
        )
        archive.writestr("chatgpt_ergebnis_schema.json", "{}")
        archive.writestr("cluster_input.csv", "fall_id,daten\nF0001,test\n")
    return name


def test_evidence_files_are_scoped_deduplicated_and_archived(tmp_path):
    store = _store(tmp_path)
    cdd = tmp_path / "candela.cdd"
    cdd.write_text("synthetische ECU-Testdaten", encoding="utf-8")
    assert store.add_files("coolant_pump", "A 123 456", "cdd_smrd", [cdd]) == 1
    assert store.add_files("coolant_pump", "A-123456", "cdd_smrd", [cdd]) == 0
    assert store.add_files("coolant_pump", "B 555 666", "cdd_smrd", [cdd]) == 1
    assert store.add_files("hv_battery", "A 123 456", "cdd_smrd", [cdd]) == 1
    assert len(store.list_files("coolant_pump", "A123456")) == 1
    assert len(store.list_files("coolant_pump", "B555666")) == 1
    assert len(store.list_files("hv_battery", "A123456")) == 1
    assert len(store.store.load_artifacts()) == 1  # Ein SHA/Original.
    entry = store.list_files("coolant_pump", "A123456")[0]
    assert entry.source_path.is_file()
    assert entry.source_path.read_bytes() == cdd.read_bytes()
    assert entry.source_path.is_relative_to(store.archive.root)
    assert len(store.counts("coolant_pump", "A123456")) == len(CATEGORY_LABELS)
    assert store.remove_file("coolant_pump", "A123456", "cdd_smrd", entry.sha256)
    assert store.list_files("coolant_pump", "A123456") == []
    assert store.list_files("coolant_pump", "B555666")
    assert entry.source_path.exists()  # Keine Löschung fremder Archivverweise.


def test_evidence_picker_rejects_scripts_and_unknown_categories(tmp_path):
    store = _store(tmp_path)
    unsafe = tmp_path / "start.ps1"
    unsafe.write_text("not executed", encoding="utf-8")
    with pytest.raises(ValueError, match="Dateityp"):
        store.add_files("coolant_pump", "", "additional", [unsafe])
    with pytest.raises(ValueError, match="Unbekannte"):
        store.add_files("coolant_pump", "", "undefined", [unsafe])


def test_context_package_contains_originals_only_after_opt_in(tmp_path):
    store = _store(tmp_path)
    file = tmp_path / "setzbedingungen.xlsx"
    file.write_bytes(b"synthetic Excel bytes, not parsed by context collection")
    assert store.add_files(
        "coolant_pump", "A 123 456", "trigger_conditions", [file],
    ) == 1
    basis = _basis(tmp_path)
    first = export_cluster_context(
        store, "coolant_pump", "A123456", basis,
        tmp_path / "kontext-ohne-originale.zip",
    )
    assert first.file_count == 1
    assert first.included_files == 0
    assert first.parent_package_id == "a" * 32
    with ZipFile(first.path) as archive:
        names = set(archive.namelist())
        assert "basis/cluster_input.csv" in names
        assert "chatgpt_ergebnis_vorlage.json" in names
        assert "chatgpt_ergebnis_schema.json" in names
        assert "CHATGPT_2_DURCHLAUF.txt" in names
        assert not any(x.startswith("unterlagen/") for x in names)
        manifest = json.loads(archive.read("cluster_kontext_manifest.json"))
        assert manifest["basis_paket_id"] == "a" * 32
        assert manifest["sachnummer_wurde_lokal_gefiltert"]
        assert "A123456" not in archive.read("cluster_kontext_manifest.json").decode()
        assert not manifest["inhalt_originaldateien"]
    second = export_cluster_context(
        store, "coolant_pump", "A123456", basis,
        tmp_path / "kontext-mit-originalen.zip", include_originals=True,
    )
    assert second.included_files == 1
    with ZipFile(second.path) as archive:
        assert archive.read(
            "unterlagen/trigger_conditions/D0001.xlsx"
        ) == file.read_bytes()


def test_context_package_rejects_unsafe_first_package(tmp_path):
    store = _store(tmp_path)
    basis = _basis(tmp_path)
    with ZipFile(basis, "a") as archive:
        archive.writestr("../escape.txt", "untrusted")
    with pytest.raises(ValueError, match="unsichere"):
        validate_first_package(basis)
    with pytest.raises(ValueError, match="unsichere"):
        export_cluster_context(
            store, "coolant_pump", "", basis, tmp_path / "soll-nicht-existieren.zip",
        )
    assert not (tmp_path / "soll-nicht-existieren.zip").exists()


def test_context_package_rejects_unredacted_first_zip_without_opt_in(tmp_path):
    store = _store(tmp_path)
    basis = _basis(tmp_path, originals=True)
    with pytest.raises(ValueError, match="Freitext/Originaldaten"):
        export_cluster_context(
            store, "coolant_pump", "", basis,
            tmp_path / "nur-metadaten.zip",
            include_originals=False,
        )
    assert not (tmp_path / "nur-metadaten.zip").exists()



def test_context_files_survive_pc_backup_and_restore(tmp_path):
    from ntf_insight.ingestion.portable_backup import (
        export_portable_backup, restore_portable_backup,
    )

    store = _store(tmp_path)
    doc = tmp_path / "ecu_net.xml"
    doc.write_text("<synthetic>test</synthetic>", encoding="utf-8")
    store.add_files("coolant_pump", "A 123 456", "network_topology", [doc])
    archive = tmp_path / "transfer.ntfbackup"
    export_portable_backup(store.store.path.parent, archive)
    destination = tmp_path / "pc2"
    restore_portable_backup(archive, destination)
    migrated = ClusterEvidenceStore(
        DuckDBStore(destination / "ntf-insight.duckdb"),
    )
    files = migrated.list_files("coolant_pump", "A123456")
    assert len(files) == 1
    assert files[0].source_path.is_file()
    assert files[0].source_path.read_bytes() == doc.read_bytes()
    assert files[0].source_path.is_relative_to(destination)
