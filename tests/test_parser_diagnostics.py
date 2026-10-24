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


def test_parser_export_filters_only_selected_project_source(tmp_path):
    service, qt, qec = setup_bad_reports(tmp_path)
    found = find_parser_problems(
        service, tmp_path, category="qec", scope_paths=(qec,),
    )
    assert len(found) == 1
    assert found[0].kind == "qec"
    package = tmp_path / "projekt-qec.zip"
    result = export_parser_diagnostics(
        service, tmp_path, package, category="qec",
        scope_paths=(qec,),
    )
    assert result.problems_found == 1
    with ZipFile(package) as archive:
        manifest = json.loads(archive.read("diagnose.json"))
        assert len(manifest["dateien"]) == 1
        assert manifest["dateien"][0]["format"] == "qec_json"
        assert FIN not in archive.read("diagnose.json").decode("utf-8")


def test_parser_diagnostics_supports_tp_tips_and_cdd_without_originals(tmp_path):
    from ntf_insight.ingestion.artifacts import SourceType

    service = make_sources(tmp_path)
    paths = {}
    for name, kind, category in [
        ("dashboard.csv", SourceType.TP_DASHBOARD, "tp_dashboard"),
        ("tips.json", SourceType.TIPS_CASE, "tips_writer"),
        ("candela.cdd", SourceType.DIAGNOSTIC_DESCRIPTION, "cdd_smrd"),
    ]:
        path = tmp_path / name
        path.write_text(name + ": invalid synthetic parser test", encoding="utf-8")
        service.import_raw(path, kind)
        paths[category] = path
    for category, path in paths.items():
        problems = find_parser_problems(
            service, tmp_path, category=category, scope_paths=(path,),
        )
        assert len(problems) == 1
        assert problems[0].status == "nicht_erkannt_oder_nicht_gespeichert"
    package = tmp_path / "tp-fehler.zip"
    result = export_parser_diagnostics(
        service, tmp_path, package,
        category="tp_dashboard", scope_paths=(paths["tp_dashboard"],),
    )
    assert result.entries_documented == 1
    with ZipFile(package) as archive:
        assert set(archive.namelist()) == {"diagnose.json", "HINWEISE.txt"}
        manifest = json.loads(archive.read("diagnose.json"))
        assert manifest["dateien"][0]["format"] == "tp_dashboard_csv"


def test_existing_empty_zip_requires_consent_then_is_atomically_replaced(tmp_path):
    service, _, _ = setup_bad_reports(tmp_path)
    destination = tmp_path / "vorher-leeres-diagnosepaket.zip"
    destination.write_bytes(b"")
    with pytest.raises(FileExistsError):
        export_parser_diagnostics(service, tmp_path, destination)
    assert destination.stat().st_size == 0

    messages = []
    result = export_parser_diagnostics(
        service, tmp_path, destination,
        overwrite_existing=True, progress=messages.append,
    )
    assert result.path == destination
    assert destination.stat().st_size > 0
    assert any("ZIP-Dateien schreiben:" in message for message in messages)
    with ZipFile(destination) as archive:
        assert archive.testzip() is None
        assert "diagnose.json" in archive.namelist()


def test_failed_export_never_replaces_existing_zip(tmp_path):
    service, _, _ = setup_bad_reports(tmp_path)
    destination = tmp_path / "bereits-exportiert.zip"
    old_bytes = b"VORHERIGES-PAKET"
    destination.write_bytes(old_bytes)
    source = service.list_artifacts()[0]
    import pathlib
    original = pathlib.Path(source.archived_path)
    original.write_bytes(original.read_bytes() + b"geaendert")
    with pytest.raises(ValueError, match="Archivprüfsumme"):
        export_parser_diagnostics(
            service, tmp_path, destination,
            overwrite_existing=True, include_originals=True,
        )
    assert destination.read_bytes() == old_bytes
    assert not list(tmp_path.glob(".ntf-parser-diagnose-*.zip"))


def test_project_diagnostics_avoids_unrelated_global_pdf_scan(
    tmp_path, monkeypatch,
):
    import ntf_insight.ingestion.parser_diagnostics as diagnostics

    service, quicktest, _qec = setup_bad_reports(tmp_path)
    monkeypatch.setattr(
        diagnostics, "list_downloaded_quicktests",
        lambda _root: (_ for _ in ()).throw(
            AssertionError("Unrelated vehicle archives must not be scanned")
        ),
    )
    monkeypatch.setattr(
        diagnostics, "list_downloaded_qec_reports",
        lambda _root: (_ for _ in ()).throw(
            AssertionError("Unrelated QEC archives must not be scanned")
        ),
    )
    progress = []
    found = find_parser_problems(
        service, tmp_path, progress=progress.append,
        category="diagnosis_viewer", scope_paths=(quicktest,),
    )
    assert len(found) == 1
    assert found[0].kind == "quicktests"
    assert any("Projektdateien prüfen: 1/1" in msg for msg in progress)
