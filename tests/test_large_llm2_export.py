"""Regressionen fuer grosse LLM-2-Diagnoseexporte (synthetische Daten)."""
from __future__ import annotations

import csv
import io
from zipfile import ZipFile

import pytest

from ntf_insight.reporting import cluster_technical_data as technical
from ntf_insight.reporting.cluster_context_package import export_cluster_context
from ntf_insight.storage.duckdb_store import DuckDBStore
from test_cluster_technical_export import _create_test_data, _first


def _csv(archive: ZipFile, name: str) -> list[dict]:
    return list(csv.DictReader(io.StringIO(
        archive.read(name).decode("utf-8-sig")
    )))


def test_streamed_csv_splits_without_losing_or_duplicating_rows(
    tmp_path, monkeypatch,
):
    """Ein 1-Million-Zeilenlimit darf keine komplette zweite ZIP blockieren."""
    monkeypatch.setattr(technical, "MAX_ROWS_PER_CSV_PART", 2)
    store = DuckDBStore(tmp_path / "large.duckdb")
    with store.connect() as con:
        con.execute("CREATE TABLE messwerte (nummer INTEGER, wert VARCHAR)")
        con.executemany(
            "INSERT INTO messwerte VALUES (?,?)",
            [
                (1, "eins"), (2, "Hallo;ein, Test"),
                (3, 'mehr\n"zeiliger" Text'), (4, "vier"), (5, "fuenf"),
            ],
        )

    index: dict[str, list[dict]] = {}
    archive_path = tmp_path / "diagnose.zip"
    with ZipFile(archive_path, "w") as archive:
        count, size = technical._iter_query(
            store, "messwerte",
            "SELECT nummer, wert FROM messwerte ORDER BY nummer", [],
            lambda row: {"nummer": row[0], "wert": row[1]},
            ("nummer", "wert"), archive, "diagnose/parameter.csv",
            set(), table_files=index,
        )
    assert count == 5
    assert len(index["diagnose/parameter.csv"]) == 3
    with ZipFile(archive_path) as archive:
        assert archive.testzip() is None
        files = [
            "diagnose/parameter.csv", "diagnose/parameter_teil_0002.csv",
            "diagnose/parameter_teil_0003.csv",
        ]
        assert [p["datei"] for p in index["diagnose/parameter.csv"]] == files
        assert [p["zeilen"] for p in index["diagnose/parameter.csv"]] == [2, 2, 1]
        assert sum(p["bytes"] for p in index["diagnose/parameter.csv"]) == size
        assert all(archive.read(name).startswith(b"\xef\xbb\xbf") for name in files)
        rows = [item for name in files for item in _csv(archive, name)]
        assert [r["nummer"] for r in rows] == ["1", "2", "3", "4", "5"]
        assert rows[2]["wert"] == 'mehr\n"zeiliger" Text'


def test_csv_rolls_over_by_bytes_not_only_rows(tmp_path, monkeypatch):
    monkeypatch.setattr(technical, "MAX_ROWS_PER_CSV_PART", 100)
    monkeypatch.setattr(technical, "MAX_STRUCTURED_FILE_BYTES", 90)
    target = tmp_path / "byteparts.zip"
    with ZipFile(target, "w") as archive:
        with technical._PartitionedCsvWriter(
            archive, "diagnose/volltext.csv", ("id", "text"),
        ) as writer:
            for number in range(4):
                writer.writerow({"id": number, "text": "X" * 45})
    with ZipFile(target) as archive:
        assert len(writer.parts) == 4
        assert [len(_csv(archive, part["datei"])) for part in writer.parts] == [
            1, 1, 1, 1,
        ]
        assert all(part["bytes"] <= 90 for part in writer.parts)
    assert writer.total_rows == 4


def test_oversize_single_row_fails_explicitly_without_truncation(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr(technical, "MAX_STRUCTURED_FILE_BYTES", 90)
    with ZipFile(tmp_path / "single.zip", "w") as archive:
        with technical._PartitionedCsvWriter(
            archive, "diagnose/volltext.csv", ("id", "text"),
        ) as writer:
            with pytest.raises(ValueError, match="nicht gekuerzt"):
                writer.writerow({"id": 1, "text": "X" * 100})


def test_second_zip_manifest_lists_all_diagnosis_parts(tmp_path, monkeypatch):
    """Die erste Dateibenennung bleibt lesbar; Manifest nennt ALLE Teile."""
    monkeypatch.setattr(technical, "MAX_ROWS_PER_CSV_PART", 1)
    source, evidence, *_ = _create_test_data(tmp_path)
    first, result = _first(source, tmp_path / "first.zip")
    exported = export_cluster_context(
        evidence, "coolant_pump", "A-EXAMPLE-001", first.path,
        tmp_path / "second.zip", include_originals=False,
        first_result=result,
    )
    import json

    with ZipFile(exported.path) as archive:
        manifest = json.loads(archive.read("cluster_kontext_manifest.json"))
        files = manifest["diagnose_tabellen"]
        assert len(files["diagnose/quicktests.csv"]) == 2
        assert len(files["diagnose/dtc_beobachtungen.csv"]) == 2
        assert all(archive.getinfo(p["datei"]).file_size == p["bytes"]
                   for parts in files.values() for p in parts)
        assert sum(p["zeilen"] for p in files["diagnose/quicktests.csv"]) == 2
        assert sum(p["zeilen"] for p in files["diagnose/dtc_beobachtungen.csv"]) == 2
        assert manifest["diagnose_auszug"]["quicktests_geparst"] == 2
        assert manifest["diagnose_auszug"]["dtc_beobachtungen"] == 2
        assert "diagnose/quicktests.csv" in archive.namelist()
        assert "diagnose/quicktests_teil_0002.csv" in archive.namelist()
        assert b"_teil_0002.csv" in archive.read("CHATGPT_2_DURCHLAUF.txt")
        assert archive.testzip() is None
