"""FIN-ZIP Importtests mit ausschließlich synthetischen Dokumenten."""
from __future__ import annotations

import json
from pathlib import Path
from zipfile import ZipFile

import pytest

from ntf_insight.ingestion.fin_zip_import import (
    is_fin_export, prepare_fin_export, install_fin_export,
)
from ntf_insight.reporting.fin_zip_export import export_fin_zip


FIN = "WDD12345678901234"
WRONG = "WDD12345678901235"
REF = "022301658"


def _write(root: Path, name: str, contents: bytes) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(contents)
    return path


def _export(tmp_path: Path) -> Path:
    origin = tmp_path / "source"
    _write(origin, f"quicktests/{FIN}/test.pdf", b"%PDF-1.4\nsynthetischer Platzhalter\n")
    _write(origin, f"qec/{FIN}/ref_{REF}/qec.json",
           json.dumps({"fin": FIN, "referenznummer": REF, "abschnitte": []}).encode())
    _write(origin, f"qec/{FIN}/ref_{REF}/anhaenge/befund.pdf", b"%PDF-1.4\nQEC\n")
    _write(origin, f"tips/{FIN}/tips.json", json.dumps({"fin": FIN}).encode())
    result = export_fin_zip(FIN, origin, tmp_path / "exports")
    assert result.zip_path is not None
    return result.zip_path


def test_export_import_roundtrip_and_idempotence(tmp_path):
    zip_path = _export(tmp_path)
    assert is_fin_export(zip_path)
    plan = prepare_fin_export(zip_path, tmp_path / "stage")
    assert plan.fin == FIN
    target = tmp_path / "other-pc"
    result = install_fin_export(plan, target)
    assert len(result.quicktest_paths) == 1
    assert len(result.attachments) == 1
    assert not result.conflicts
    assert (target / "qec" / FIN / f"ref_{REF}" / "qec.json").is_file()
    second = install_fin_export(plan, target)
    assert sum(second.counts.values()) == 0
    assert not second.conflicts


def test_different_qec_existing_file_remains_unchanged(tmp_path):
    plan = prepare_fin_export(_export(tmp_path), tmp_path / "stage")
    target = tmp_path / "other-pc"
    existing = _write(target, f"qec/{FIN}/ref_{REF}/qec.json", b'{"local": true}')
    result = install_fin_export(plan, target)
    assert existing.read_bytes() == b'{"local": true}'
    assert result.conflicts


def test_manifest_hash_tampering_rejected_before_install(tmp_path):
    exported = _export(tmp_path)
    corrupted = tmp_path / "damaged.zip"
    with ZipFile(exported) as src, ZipFile(corrupted, "w") as dest:
        for item in src.infolist():
            payload = src.read(item)
            if item.filename == "qec/ref_022301658/qec.json":
                payload = b'{"fin":"wrong"}'
            dest.writestr(item.filename, payload)
    with pytest.raises(ValueError, match="Prüfsumme"):
        prepare_fin_export(corrupted, tmp_path / "stage")
    assert not (tmp_path / "other-pc").exists()


def test_manifest_fin_cross_reference_rejected(tmp_path):
    exported = _export(tmp_path)
    damaged = tmp_path / "foreign.zip"
    with ZipFile(exported) as src, ZipFile(damaged, "w") as dest:
        for name in src.namelist():
            content = src.read(name)
            if name == "export_manifest.json":
                payload = json.loads(content)
                payload["fin"] = WRONG
                content = json.dumps(payload).encode()
            dest.writestr(name, content)
    with pytest.raises(ValueError, match="QEC-FIN"):
        prepare_fin_export(damaged, tmp_path / "stage")


def test_manifest_extra_file_rejected(tmp_path):
    exported = _export(tmp_path)
    damaged = tmp_path / "extra.zip"
    with ZipFile(exported) as src, ZipFile(damaged, "w") as dest:
        for name in src.namelist():
            dest.writestr(name, src.read(name))
        dest.writestr("browser/Cookies", b"credentials")
    with pytest.raises(ValueError, match="außerhalb"):
        prepare_fin_export(damaged, tmp_path / "stage")


def test_fleet_analysis_empty_database(tmp_path):
    from ntf_insight.analysis.quicktest_fleet import analyze_quicktest_fleet
    from ntf_insight.storage.duckdb_store import DuckDBStore
    from ntf_insight.storage.quicktest_store import QuickTestStore

    store = QuickTestStore(DuckDBStore(tmp_path / "ntf.duckdb"))
    result = analyze_quicktest_fleet(store)
    assert result.reports == 0
    assert result.fins == 0
    assert result.clean_reports == 0
    assert result.dtc_rows == ()


def test_local_quicktest_scan_does_not_infer_fin_or_follow_invalid_folders(tmp_path):
    from ntf_insight.ingestion.downloaded_quicktests import list_downloaded_quicktests

    first = _write(tmp_path, f"quicktests/{FIN}/first.pdf", b"%PDF-local")
    second = _write(tmp_path, f"quicktests/{FIN}/second.PDF", b"%PDF-local")
    _write(tmp_path, f"quicktests/{FIN}/abrufstatus.json", b"{}")
    _write(tmp_path, "quicktests/not-a-fin/wrong.pdf", b"%PDF-private")
    _write(tmp_path, f"quicktests/{FIN}/nested/not-scanned.pdf", b"%PDF-nested")
    assert list_downloaded_quicktests(tmp_path) == [first, second]


def test_fleet_dtc_counts_are_report_observations_not_new_cases(tmp_path):
    from datetime import datetime

    from ntf_insight.analysis.quicktest_fleet import analyze_quicktest_fleet
    from ntf_insight.storage.duckdb_store import DuckDBStore
    from ntf_insight.storage.quicktest_store import QuickTestStore

    other_fin = WRONG
    store = QuickTestStore(DuckDBStore(tmp_path / "fleet.duckdb"))
    with store.store.connect() as con:
        for report, fin, moment, dtcs in (
            ("report1", FIN, datetime(2026, 1, 1), 1),
            ("report2", FIN, datetime(2026, 1, 2), 0),
            ("report3", other_fin, datetime(2026, 1, 3), 1),
        ):
            con.execute(
                "INSERT INTO quicktest_reports VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [report, fin, fin, moment, 12345, 1, dtcs, "{}", "a" * 64, moment],
            )
            con.execute(
                "INSERT INTO quicktest_ecus VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [report, 1, "CPC3", "N127", "Control", json.dumps({
                    "software_version": "S1" if report != "report3" else "S2"
                }), dtcs, 1, 1, "synthetic"],
            )
            if dtcs:
                con.execute(
                    "INSERT INTO quicktest_dtcs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [report, 1, 1, "CPC3", "FC", "P260000", "Synthetic fault",
                     "S", 1, 12340, 12345, 1, 1, 1, "synthetic"],
                )
    full = analyze_quicktest_fleet(store)
    assert (full.reports, full.fins, full.ecus, full.dtc_observations, full.clean_reports) == (
        3, 2, 3, 2, 1,
    )
    assert full.dtc_rows[0][:5] == ("CPC3", "P260000", 2, 2, 2)
    assert len(full.software_rows) == 2
    assert sum(row[2] for row in full.software_rows) == 2
    assert analyze_quicktest_fleet(store, ecu_filter="SAM").dtc_rows == ()
    assert analyze_quicktest_fleet(store, dtc_filter="P999").dtc_rows == ()
    # Filtered DTCs never turn a report with a DTC into a clean test.
    assert analyze_quicktest_fleet(store, dtc_filter="P999").clean_reports == 1
