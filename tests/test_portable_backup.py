"""Offline-Transfer eines vollständigen, bereits ausgewerteten Datenbestands.

Ausschließlich synthetische FINs und Quelldateien; nie Unternehmensdaten
in CI, GitHub-Artefakte oder Test-Logs übernehmen.
"""
from __future__ import annotations

import json
import os

import duckdb
from datetime import datetime
from pathlib import Path
from zipfile import ZipFile

import pytest

from ntf_insight.domain.case import NTFCase
from ntf_insight.domain.manual import ManualAction, ManualChange
from ntf_insight.domain.vehicle import Vehicle
from ntf_insight.ingestion.artifacts import SourceType
from ntf_insight.ingestion.portable_backup import (
    DATABASE_NAME, export_portable_backup, has_local_dataset,
    restore_portable_backup,
)
from ntf_insight.ingestion.service import SourceImportService
from ntf_insight.storage.duckdb_store import DuckDBStore
from ntf_insight.storage.quicktest_store import QuickTestStore


FIN = "WDD12345678901234"
REFERENCE = "022301658"


def _make_data(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "pc-a"
    root.mkdir()
    incoming = tmp_path / "local_report.pdf"
    incoming.write_bytes(b"%PDF-1.4\nSYNTHETIC-REPORT\n")
    source = SourceImportService(root / "raw", root / DATABASE_NAME)
    source.import_raw(incoming, SourceType.SHORT_TEST, source_system="synthetic")
    QuickTestStore(source.store)
    case = NTFCase(
        case_id="QEC-SYNTHETISCH-001",
        vehicle=Vehicle(vin=FIN),
        component_type="Coolant Pump",
        component_profile_id="coolant_pump",
    )
    source.store.save_case(case)
    source.store.save_manual_revision(
        case, ManualChange(
            case_id=case.case_id, action=ManualAction.ADD_EVENT,
            entity_type="diagnostics", after_json="{}", actor="local_user",
        ),
    )
    with source.store.connect() as con:
        con.execute(
            "INSERT INTO quicktest_reports VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                "synthetic-logical-report", FIN, FIN, datetime(2026, 1, 1),
                12345, 1, 0, "{}", "a" * 64, datetime(2026, 1, 1),
            ],
        )
    qt = root / "quicktests" / FIN / "test.pdf"
    qt.parent.mkdir(parents=True)
    qt.write_bytes(incoming.read_bytes())
    qec = root / "qec" / FIN / ("ref_" + REFERENCE)
    (qec / "anhaenge").mkdir(parents=True)
    (qec / "qec.json").write_text(json.dumps({
        "fin": FIN, "referenznummer": REFERENCE,
        "abschnitte": [{"bereich": "Stellungnahme Lieferant", "sichtbarer_text": "NTF"}],
    }), encoding="utf-8")
    (qec / "ansicht.html").write_text(
        "<html><body>Historische QEC-Ansicht (synthetisch)</body></html>",
        encoding="utf-8",
    )
    (qec / "anhaenge" / "bericht.pdf").write_bytes(b"%PDF-1.4\nQEC SYNTHETIC\n")
    tips = root / "tips" / FIN / "fall_12345678"
    tips.mkdir(parents=True)
    (tips / "tips.json").write_text(
        json.dumps({"fin": FIN, "fallnummer": "12345678"}), encoding="utf-8",
    )
    # These are explicitly NEVER part of the transfer.
    private = root / "edge-qec-profile" / "Cookies"
    private.parent.mkdir()
    private.write_bytes(b"DO-NOT-TRANSFER")
    return root, incoming


def _backup(tmp_path: Path) -> tuple[Path, Path]:
    origin, _ = _make_data(tmp_path)
    file = tmp_path / "transport.ntfbackup"
    export_portable_backup(origin, file)
    return file, origin


def test_single_file_roundtrip_preserves_parsed_state_and_raw_paths(tmp_path):
    archive, origin = _backup(tmp_path)
    with ZipFile(archive) as package:
        members = package.namelist()
        assert "database/ntf-insight.duckdb" in members
        assert "manifest.json" in members
        assert any(name.startswith("files/raw/") for name in members)
        assert f"files/quicktests/{FIN}/test.pdf" in members
        assert f"files/qec/{FIN}/ref_{REFERENCE}/qec.json" in members
        assert f"files/qec/{FIN}/ref_{REFERENCE}/ansicht.html" in members
        assert f"files/tips/{FIN}/fall_12345678/tips.json" in members
        assert not any("edge-" in item or "Cookies" in item for item in members)

    dest = tmp_path / "pc-b"
    dest.mkdir()
    DuckDBStore(dest / DATABASE_NAME)  # GUI's newly created, empty DB
    (dest / "raw").mkdir()
    assert not has_local_dataset(dest)
    result = restore_portable_backup(archive, dest)
    assert result.case_count == 1
    assert result.quicktest_count == 1
    assert has_local_dataset(dest)
    transferred = DuckDBStore(dest / DATABASE_NAME)
    assert transferred.load_cases()[0].case_id == "QEC-SYNTHETISCH-001"
    assert len(transferred.load_manual_changes()) == 1
    assert transferred.load_manual_changes()[0].actor == "local_user"
    with transferred.connect() as con:
        assert con.execute("SELECT COUNT(*) FROM quicktest_reports").fetchone()[0] == 1
    restored_artifact = transferred.load_artifacts()[0]
    assert Path(restored_artifact.archived_path).is_relative_to(dest)
    assert Path(restored_artifact.archived_path).is_file()
    assert not Path(restored_artifact.archived_path).is_relative_to(origin)
    assert (dest / "qec" / FIN / f"ref_{REFERENCE}" / "qec.json").is_file()
    assert (dest / "tips" / FIN / "fall_12345678" / "tips.json").is_file()
    assert not (dest / "edge-qec-profile").exists()

    # A restored machine can become the exporter for a third machine as well.
    second_package = tmp_path / "second-transfer.ntfbackup"
    export_portable_backup(dest, second_package)
    third = tmp_path / "pc-c"
    restored = restore_portable_backup(second_package, third)
    assert restored.quicktest_count == 1
    assert Path(
        DuckDBStore(third / DATABASE_NAME).load_artifacts()[0].archived_path
    ).is_relative_to(third)


def test_import_does_not_rerun_any_source_parser(tmp_path, monkeypatch):
    archive, _ = _backup(tmp_path)
    from ntf_insight.ingestion import real_source_parsers

    def forbidden(*_args, **_kwargs):
        raise AssertionError("Transfer must not parse anything")
    monkeypatch.setattr(real_source_parsers.QuickTestPdfParser, "parse", forbidden)
    dest = tmp_path / "new-pc"
    result = restore_portable_backup(archive, dest)
    assert result.quicktest_count == 1


def test_existing_data_not_overwritten_implicitly(tmp_path):
    package, _ = _backup(tmp_path)
    dest = tmp_path / "pc-b"
    dest.mkdir()
    source = SourceImportService(dest / "raw", dest / DATABASE_NAME)
    (dest / "original.txt").write_text("do not touch", encoding="utf-8")
    existing = source.store.load_cases()
    source.store.save_case(NTFCase(
        case_id="LOCAL-ONLY", vehicle=Vehicle(vin=FIN),
        component_type="Coolant Pump",
    ))
    assert not existing
    with pytest.raises(ValueError, match="bereits Daten"):
        restore_portable_backup(package, dest)
    assert source.store.load_cases()[0].case_id == "LOCAL-ONLY"
    assert (dest / "original.txt").is_file()
    # Explicit replacement is possible, and never merges old case IDs.
    result = restore_portable_backup(package, dest, replace_existing=True)
    assert result.case_count == 1
    assert DuckDBStore(dest / DATABASE_NAME).load_cases()[0].case_id == (
        "QEC-SYNTHETISCH-001"
    )


def test_changed_bytes_are_rejected_before_touching_the_destination(tmp_path):
    package, _ = _backup(tmp_path)
    bad = tmp_path / "corrupted.ntfbackup"
    with ZipFile(package) as source, ZipFile(bad, "w") as destination:
        for name in source.namelist():
            data = source.read(name)
            if name.startswith("files/qec/") and name.endswith(".pdf"):
                data = bytes([data[0] ^ 1]) + data[1:]
            destination.writestr(name, data)
    dest = tmp_path / "pc-b"
    dest.mkdir()
    DuckDBStore(dest / DATABASE_NAME)
    with pytest.raises(ValueError, match="Prüfsumme"):
        restore_portable_backup(bad, dest)
    assert not (dest / "qec").exists()


def test_extra_zip_member_is_rejected_without_extracting_it(tmp_path):
    package, _ = _backup(tmp_path)
    bad = tmp_path / "extra.ntfbackup"
    with ZipFile(package) as source, ZipFile(bad, "w") as destination:
        for name in source.namelist():
            destination.writestr(name, source.read(name))
        destination.writestr("files/../../outside.txt", "NOT A SAFE PATH")
    dest = tmp_path / "pc-b"
    with pytest.raises(ValueError, match="Unsicherer Paketpfad"):
        restore_portable_backup(bad, dest)
    assert not (tmp_path / "outside.txt").exists()


def test_export_will_not_overwrite_an_existing_package(tmp_path):
    package, original = _backup(tmp_path)
    before = package.read_bytes()
    with pytest.raises(FileExistsError):
        export_portable_backup(original, package)
    assert package.read_bytes() == before


@pytest.mark.skipif(os.name == "nt", reason="Symlinks ohne Windows-Developer-Modus")
def test_symlinked_source_documents_are_not_exported(tmp_path):
    root, _ = _make_data(tmp_path)
    outside = tmp_path / "private.pdf"
    outside.write_bytes(b"%PDF-PRIVATE")
    link = root / "quicktests" / FIN / "external.pdf"
    link.symlink_to(outside)
    with pytest.raises(ValueError, match="Symbolischer Link"):
        export_portable_backup(root, tmp_path / "bad.ntfbackup")
    assert not (tmp_path / "bad.ntfbackup").exists()


def test_rollback_if_installation_fails_after_previous_data_moved(tmp_path, monkeypatch):
    import ntf_insight.ingestion.portable_backup as module

    package, _ = _backup(tmp_path)
    dest = tmp_path / "pc-b"
    dest.mkdir()
    store = DuckDBStore(dest / DATABASE_NAME)
    case = NTFCase(
        case_id="OLD-LOCAL-CASE", vehicle=Vehicle(vin=FIN),
        component_type="Coolant Pump",
    )
    store.save_case(case)
    before = (dest / DATABASE_NAME).read_bytes()
    original_replace = module.os.replace
    failed = False

    def fail_once(src, target):
        nonlocal failed
        if not failed and str(target) == str(dest / "quicktests"):
            failed = True
            raise OSError("simulated Windows file lock")
        return original_replace(src, target)

    monkeypatch.setattr(module.os, "replace", fail_once)
    with pytest.raises(OSError, match="simulated"):
        restore_portable_backup(package, dest, replace_existing=True)
    assert DuckDBStore(dest / DATABASE_NAME).load_cases()[0].case_id == "OLD-LOCAL-CASE"
    assert (dest / DATABASE_NAME).read_bytes() == before


def test_failed_rollback_preserves_original_database_for_recovery(tmp_path, monkeypatch):
    import ntf_insight.ingestion.portable_backup as module

    package, _ = _backup(tmp_path)
    dest = tmp_path / "pc-b"
    dest.mkdir()
    store = DuckDBStore(dest / DATABASE_NAME)
    store.save_case(NTFCase(
        case_id="PRESERVE-ME", vehicle=Vehicle(vin=FIN),
        component_type="Coolant Pump",
    ))
    real_replace = module.os.replace

    def fail_install_and_rollback(src, dst):
        if Path(dst) == dest / "quicktests":
            raise OSError("synthetic failed installation")
        if Path(dst) == dest / DATABASE_NAME and Path(src).parent.name == "_vorher":
            raise OSError("synthetic locked destination")
        return real_replace(src, dst)

    monkeypatch.setattr(module.os, "replace", fail_install_and_rollback)
    with pytest.raises(RuntimeError, match="manuellen Wiederherstellung"):
        restore_portable_backup(package, dest, replace_existing=True)
    recovered = list(tmp_path.glob(".ntf-restore-*/_vorher/ntf-insight.duckdb"))
    assert len(recovered) == 1
    assert recovered[0].is_file()
    with duckdb.connect(str(recovered[0]), read_only=True) as con:
        assert con.execute(
            "SELECT COUNT(*) FROM case_snapshots WHERE case_id='PRESERVE-ME'"
        ).fetchone()[0] == 1
