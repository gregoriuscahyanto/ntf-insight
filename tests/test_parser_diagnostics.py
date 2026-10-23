"""Nur synthetische lokale Parser-Proben; kein Upload realer Berichte."""
from __future__ import annotations

import json
from zipfile import ZipFile

import pytest

from ntf_insight.ingestion.batch_import import LocalBatchImporter
from ntf_insight.ingestion.parser_diagnostics import (
    export_parser_diagnostics, find_parser_problems,
)
from ntf_insight.ingestion.service import SourceImportService


FIN = "W1TTEST0000000001"


def make_sources(tmp_path):
    return SourceImportService(tmp_path / "raw", tmp_path / "local.duckdb")


def setup_bad_reports(tmp_path):
    qt = tmp_path / "quicktests" / FIN / "roher_quicktest.pdf"
    qt.parent.mkdir(parents=True)
    qt.write_bytes(b"KEINE GUELTIGE PDF-DATEI")
    qec = tmp_path / "qec" / FIN / "ref_123456" / "qec.json"
    qec.parent.mkdir(parents=True)
    # Valid UTF-8 JSON, but not a supported QEC report.
    qec.write_text(json.dumps({
        "schema_version": 999,
        "fin": FIN,
        "referenznummer": "123456",
        "geheim": "Nur synthetischer Inhalt",
    }), encoding="utf-8")
    service = make_sources(tmp_path)
    importer = LocalBatchImporter(service)
    importer.import_paths([qt], only_new=True, local_kind="quicktests")
    importer.import_paths([qec], only_new=True, local_kind="qec")
    return service, qt, qec


def test_diagnose_zip_ohne_originale_hat_keine_fin_und_keine_dateinamen(tmp_path):
    service, qt, qec = setup_bad_reports(tmp_path)
    problems = find_parser_problems(service, tmp_path)
    assert len(problems) == 2
    assert {item.kind for item in problems} == {"quicktests", "qec"}
    package = tmp_path / "diagnose-sicher.zip"
    result = export_parser_diagnostics(service, tmp_path, package)
    assert result.problems_found == 2
    assert result.original_files == 0
    with ZipFile(package) as archive:
        assert set(archive.namelist()) == {"diagnose.json", "HINWEISE.txt"}
        data = archive.read("diagnose.json").decode("utf-8")
        assert FIN not in data
        assert qt.name not in data and qec.name not in data
        assert "raw/" not in data and "qec/" not in data
        manifest = json.loads(data)
        assert manifest["dateien_dokumentiert"] == 2
        assert all(not item["originaldatei_enthalten"] for item in manifest["dateien"])


def test_originale_nur_nach_expliziter_option_und_bytegetreu(tmp_path):
    service, qt, qec = setup_bad_reports(tmp_path)
    package = tmp_path / "diagnose-vertraulich.zip"
    result = export_parser_diagnostics(
        service, tmp_path, package, include_originals=True,
    )
    assert result.original_files == 2
    with ZipFile(package) as archive:
        manifest = json.loads(archive.read("diagnose.json"))
        for item in manifest["dateien"]:
            assert item["originaldatei_enthalten"]
            src = qt if item["format"] == "quicktest_pdf" else qec
            assert archive.read(item["datei_im_paket"]) == src.read_bytes()
            assert item["datei_im_paket"].startswith("originale/")
            assert src.name not in item["datei_im_paket"]
        assert FIN not in archive.read("diagnose.json").decode("utf-8")
        assert FIN.encode() in archive.read(
            next(item["datei_im_paket"] for item in manifest["dateien"]
                 if item["format"] == "qec_json")
        )


def test_problemdiagnose_erkennt_auch_unvollstaendig_lesbares_qec(tmp_path):
    qec = tmp_path / "qec" / FIN / "ref_987654" / "qec.json"
    qec.parent.mkdir(parents=True)
    qec.write_text(json.dumps({
        "schema_version": 2,
        "fin": FIN,
        "referenznummer": "987654",
        "vollstaendige_reiter": False,
        "abschnitte": [{"bereich": "WE-Daten", "felder": [], "tabellen": []}],
        "anhaenge": [],
    }), encoding="utf-8")
    service = make_sources(tmp_path)
    LocalBatchImporter(service).import_paths([qec], only_new=True, local_kind="qec")
    found = find_parser_problems(service, tmp_path)
    assert len(found) == 1
    assert found[0].status == "teilweise"


def test_diagnosepaket_nicht_ueberschreiben(tmp_path):
    service, _, _ = setup_bad_reports(tmp_path)
    destination = tmp_path / "diagnose.zip"
    destination.write_bytes(b"VORHER")
    with pytest.raises(FileExistsError):
        export_parser_diagnostics(service, tmp_path, destination)
    assert destination.read_bytes() == b"VORHER"


def test_archivquelle_nach_manipulation_nicht_unbemerkt_exportieren(tmp_path):
    service, _, _ = setup_bad_reports(tmp_path)
    artifact = service.list_artifacts()[0]
    path = __import__("pathlib").Path(artifact.archived_path)
    path.write_bytes(path.read_bytes() + b"veraendert")
    with pytest.raises(ValueError, match="Archivprüfsumme"):
        export_parser_diagnostics(
            service, tmp_path, tmp_path / "diagnose-ungueltig.zip",
            include_originals=True,
        )
    assert not (tmp_path / "diagnose-ungueltig.zip").exists()
