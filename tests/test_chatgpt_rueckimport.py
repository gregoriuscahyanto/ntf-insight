"""Synthetischer bidirektionaler Austausch mit strenger lokaler Fallbindung."""
from __future__ import annotations

import csv
import io
import json
from zipfile import ZipFile

import pytest

from ntf_insight.domain.case import NTFCase
from ntf_insight.domain.vehicle import Vehicle
from ntf_insight.ingestion.artifacts import SourceType
from ntf_insight.ingestion.service import SourceImportService
from ntf_insight.reporting.chatgpt_exchange import (
    ChatGPTAnalyseStore, ergebnis_schema, ergebnis_vorlage,
)
from ntf_insight.reporting.ki_analysepaket import export_ki_analysepaket
from ntf_insight.storage.quicktest_store import QuickTestStore
from ntf_insight.storage.source_knowledge_store import SourceKnowledgeStore

FIN = "WDD12345678901234"
REF = "123456"


def make_data(tmp_path, *, qec: bool = True):
    source = SourceImportService(tmp_path / "raw", tmp_path / "ntf-insight.duckdb")
    QuickTestStore(source.store)
    knowledge = SourceKnowledgeStore(source.store)
    case = NTFCase(
        case_id="Original-interner-Fall-123",
        vehicle=Vehicle(vin=FIN, model_series="214"),
        component_type="Kühlmittelpumpe",
        component_profile_id="coolant_pump",
        qec_reference=REF,
        qec_part_number="A-EXAMPLE-001",
    )
    source.store.save_case(case)
    if qec:
        path = tmp_path / "qec" / FIN / ("ref_" + REF) / "qec.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 2, "fin": FIN, "referenznummer": REF,
            "sachnummer": "A-EXAMPLE-001",
            "abgerufen_am_utc": "2026-10-20T08:30:00+00:00",
            "vollstaendige_reiter": True, "abschnitte": [],
            "anhaenge": [{
                "anhang_id": "12", "dateiname": "Befund.pdf",
                "datei": "12_Befund.pdf",
            }],
        }
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        attachment = path.parent / "anhaenge" / "12_Befund.pdf"
        attachment.parent.mkdir()
        attachment.write_bytes(
            b"%PDF-1.4\n" + FIN.encode("ascii") + b"\nVertraulicher Testinhalt"
        )
        artifact = source.import_raw(path, SourceType.QEC_REPORT)
        knowledge.save_records(
            artifact.sha256, "qec_live_report",
            [{
                "category": "qec_field",
                "source_location": "QEC/01-WE-Daten/feld:1",
                "fin": FIN, "reference": REF,
                "label": "Vertrauliche Daten",
                "data": {
                    "bereich": "WE-Daten",
                    "name": "befund", "typ": "text",
                    "wert": "Korrosion mit FIN " + FIN,
                },
            }],
            metadata={
                "fin": FIN, "reference": REF,
                "part_number": "A-EXAMPLE-001",
                "fresh_complete": True, "sections": 5,
                "fresh_sections": 5, "fields": 1,
            },
        )
    return source


def read_package(path):
    with ZipFile(path) as archive:
        template = json.loads(archive.read("chatgpt_ergebnis_vorlage.json"))
        manifest = json.loads(archive.read("manifest.json"))
        cases = list(csv.DictReader(io.StringIO(
            archive.read("faelle.csv").decode("utf-8-sig")
        )))
        qecs = list(csv.DictReader(io.StringIO(
            archive.read("qec_berichte.csv").decode("utf-8-sig")
        )))
        return template, manifest, cases, qecs, archive.namelist()


def write_answer(path, template, case_alias, qec_alias=""):
    result = dict(template)
    result["clustermethode"] = "Jaccard für Vor-Tausch-DTCs"
    result["cluster"] = [{
        "cluster_id": "C01",
        "titel": "Anschlussumfeld – zu prüfen",
        "fall_ids": [case_alias],
        "technische_hypothese": "Unzureichende Daten zur Kausalität",
        "sicherheit": "Niedrig",
        "belege": [],
    }]
    result["faelle"] = [{
        "fall_id": case_alias, "cluster_id": "C01",
        "ntf_bewertung": "NTF fraglich",
        "prioritaet": "P1",
        "befund": "Originalbericht zeigt eine Prüfauffälligkeit",
        "verursachungsbereich": "Nicht zuordenbar",
        "sicherheit_zuordnung": "Offen",
        "begruendung_ntf": "Berichtsgrenzen prüfen",
        "ursachenhypothese": "Steckerumfeld könnte relevant sein",
        "sicherheit_bewertung": "Mittel",
        "naechster_schritt": "Originalbericht fachlich prüfen",
        "belege": [{
            "quelle": "qec_felder",
            "quelle_id": qec_alias,
            "fundstelle": "QF-GEPRUEFT",
            "aussage": "Im Original dokumentiert, unabhängig zu verifizieren",
            "belegstatus": "Nicht verifiziert",
        }] if qec_alias else [],
    }]
    path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    return result


def test_contract_is_embedded_and_returned_analysis_is_reviewable(tmp_path):
    service = make_data(tmp_path)
    result = export_ki_analysepaket(service, tmp_path / "analyse.zip")
    template, manifest, cases, qecs, entries = read_package(result.pfad)
    assert "chatgpt_ergebnis_schema.json" in entries
    assert "CHATGPT_ANWEISUNG.txt" in entries
    assert manifest["paket_id"] == template["paket_id"]
    assert manifest["schema_version"] == 3
    assert manifest["qec_originaldateien_enthalten"] is False
    assert template["faelle"] == []
    assert ergebnis_vorlage(template["paket_id"])["paket_id"] == template["paket_id"]
    assert "properties" in ergebnis_schema()
    private_csv = result.private_zuordnung.read_text(encoding="utf-8-sig")
    assert FIN in private_csv
    assert template["paket_id"] in private_csv
    with ZipFile(result.pfad) as archive:
        assert all(FIN.encode() not in archive.read(p)
                   for p in entries if not p.endswith(".xlsx"))
    path = tmp_path / "chatgpt_ergebnis.json"
    write_answer(path, template, cases[0]["fall_id"], qecs[0]["qec_bericht_id"])

    review = ChatGPTAnalyseStore(service.store)
    imported = review.import_file(path)
    assert imported == {
        "analyse_id": template["analyse_id"], "faelle": 1,
        "cluster": 1, "bereits_importiert": False,
    }
    assert review.import_file(path)["bereits_importiert"]
    latest = review.latest_for_case("Original-interner-Fall-123")
    assert latest["cluster_id"] == "C01"
    assert latest["bewertung"]["ntf_bewertung"] == "NTF fraglich"
    assert latest["review_status"] == "Offen"
    assert service.store.get_case("Original-interner-Fall-123").assessment is None
    review.set_review_status(template["analyse_id"], "Original-interner-Fall-123",
                             "Bestätigt")
    assert review.latest_for_case("Original-interner-Fall-123")["review_status"] == "Bestätigt"
    assert service.store.get_case("Original-interner-Fall-123").assessment is None


def test_wrong_package_and_unknown_source_or_case_rejected(tmp_path):
    service = make_data(tmp_path)
    bundle = export_ki_analysepaket(service, tmp_path / "analyse.zip")
    template, _, cases, qecs, _ = read_package(bundle.pfad)
    answer_path = tmp_path / "antwort.json"
    data = write_answer(answer_path, template, cases[0]["fall_id"], qecs[0]["qec_bericht_id"])
    review = ChatGPTAnalyseStore(service.store)

    modified = json.loads(json.dumps(data))
    modified["paket_id"] = "f" * 32
    answer_path.write_text(json.dumps(modified), encoding="utf-8")
    with pytest.raises(ValueError, match="Paketzuordnung"):
        review.import_file(answer_path)

    modified = json.loads(json.dumps(data))
    modified["faelle"][0]["fall_id"] = "F9999"
    answer_path.write_text(json.dumps(modified), encoding="utf-8")
    with pytest.raises(ValueError, match="Fallkennung"):
        review.import_file(answer_path)

    modified = json.loads(json.dumps(data))
    modified["faelle"][0]["belege"][0]["quelle_id"] = "Q99999"
    answer_path.write_text(json.dumps(modified), encoding="utf-8")
    with pytest.raises(ValueError, match="Beleg referenziert"):
        review.import_file(answer_path)

    modified = json.loads(json.dumps(data))
    modified["faelle"][0]["cluster_id"] = "C02"
    answer_path.write_text(json.dumps(modified), encoding="utf-8")
    with pytest.raises(ValueError, match="Cluster"):
        review.import_file(answer_path)
    assert not review.list_case_findings()


def test_forged_case_mapping_and_duplicate_analysis_id_rejected(tmp_path):
    service = make_data(tmp_path)
    bundle = export_ki_analysepaket(service, tmp_path / "analyse.zip")
    template, _, cases, qecs, _ = read_package(bundle.pfad)
    answer_path = tmp_path / "antwort.json"
    data = write_answer(answer_path, template, cases[0]["fall_id"], qecs[0]["qec_bericht_id"])
    review = ChatGPTAnalyseStore(service.store)
    review.import_file(answer_path)
    data["faelle"][0]["befund"] = "Inhalt wurde später verändert"
    answer_path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="Analyse-ID"):
        review.import_file(answer_path)

    another = SourceImportService(tmp_path / "ziel" / "raw", tmp_path / "ziel" / "db.duckdb")
    QuickTestStore(another.store)
    SourceKnowledgeStore(another.store)
    other_case = NTFCase(
        case_id="Original-interner-Fall-123",
        vehicle=Vehicle(vin="WDD00000000000111"),
        component_type="Kühlmittelpumpe",
        qec_reference=REF,
    )
    another.store.save_case(other_case)
    with pytest.raises(ValueError, match="Paketzuordnung"):
        ChatGPTAnalyseStore(another.store).import_file(
            answer_path,
        )
    with pytest.raises(ValueError, match="veraltet"):
        ChatGPTAnalyseStore(another.store).import_file(
            answer_path, private_csv=bundle.private_zuordnung,
        )


def test_qec_originals_are_opt_in_not_silently_uploaded(tmp_path):
    service = make_data(tmp_path)
    without = export_ki_analysepaket(service, tmp_path / "standard.zip")
    with ZipFile(without.pfad) as z:
        assert not any(name.startswith("qec_originale/") for name in z.namelist())
        assert not json.loads(z.read("manifest.json"))["qec_originaldateien_enthalten"]

    original = export_ki_analysepaket(
        service, tmp_path / "vertrauliche-originale.zip",
        mit_qec_originalen=True,
    )
    assert original.qec_originale == 2
    with ZipFile(original.pfad) as z:
        names = z.namelist()
        raw_reports = [name for name in names if name.endswith("/qec.json")]
        pdf_files = [name for name in names if name.endswith(".pdf")]
        assert len(raw_reports) == 1
        assert len(pdf_files) == 1
        raw_content = z.read(raw_reports[0])
        assert FIN.encode() in raw_content  # Original content NOT anonymized.
        assert b"Korrosion" not in raw_content
        assert FIN.encode() in z.read(pdf_files[0])
        assert "Befund.pdf" not in pdf_files[0]  # neutral ZIP path
        assert not json.loads(z.read("manifest.json"))["pseudonymisiert"]
        info = json.loads(z.read("qec_originale/vollstaendigkeit.json"))
        assert info["belegdateien"] == 2
        assert not info["fehlende_qec_berichte"]
        assert not info["fehlende_qec_anhaenge"]


def test_qec_attachment_with_traversal_never_exported(tmp_path):
    service = make_data(tmp_path, qec=False)
    folder = tmp_path / "qec" / FIN / ("ref_" + REF)
    folder.mkdir(parents=True)
    report_path = folder / "qec.json"
    report_path.write_text(json.dumps({
        "schema_version": 2, "fin": FIN, "referenznummer": REF,
        "anhaenge": [{"datei": "../../private.pdf"}],
    }), encoding="utf-8")
    artifact = service.import_raw(report_path, SourceType.QEC_REPORT)
    SourceKnowledgeStore(service.store).save_records(
        artifact.sha256, "qec_live_report", [],
        metadata={"fin": FIN, "reference": REF, "part_number": "A-EXAMPLE-001"},
    )
    exported = export_ki_analysepaket(
        service, tmp_path / "restricted.zip", mit_qec_originalen=True,
    )
    with ZipFile(exported.pfad) as zip_file:
        assert all(not name.endswith(".pdf") for name in zip_file.namelist())
        findings = json.loads(zip_file.read("qec_originale/vollstaendigkeit.json"))
        assert findings["fehlende_qec_anhaenge"]



def test_unparsed_but_valid_downloaded_qec_is_not_lost_from_opt_in_zip(tmp_path):
    service = make_data(tmp_path, qec=False)
    path = tmp_path / "qec" / FIN / ("ref_" + REF) / "qec.json"
    path.parent.mkdir(parents=True)
    raw = {
        "schema_version": 2, "fin": FIN, "referenznummer": REF,
        "sachnummer": "A-EXAMPLE-001",
        "abgerufen_am_utc": "2026-10-20T08:30:00+00:00",
        "abschnitte": [{"bereich": "WE-Daten", "sichtbarer_text": "Noch nicht geparst"}],
        "anhaenge": [],
    }
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    result = export_ki_analysepaket(
        service, tmp_path / "unparsed-originals.zip", mit_qec_originalen=True,
    )
    assert result.qec_berichte == 1
    assert result.qec_originale == 1
    with ZipFile(result.pfad) as package:
        assert "qec_originale/Q00001/qec.json" in package.namelist()
        qec = list(csv.DictReader(io.StringIO(
            package.read("qec_berichte.csv").decode("utf-8-sig")
        )))
        assert qec[0]["erfassungsstand"] == "nicht_geparst"
        assert json.loads(package.read("manifest.json"))[
            "datenreihen"
        ]["qec_nur_original_nicht_geparst"] == 1
    assert service.store.get_case("Original-interner-Fall-123") is not None


def test_unidentifiable_qec_json_blocks_incomplete_original_export(tmp_path):
    service = make_data(tmp_path, qec=False)
    path = tmp_path / "qec" / FIN / ("ref_" + REF) / "qec.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps({"schema_version": 2, "fin": "FALSCH", "referenznummer": REF}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="keinem gültigen Fall zugeordnet"):
        export_ki_analysepaket(
            service, tmp_path / "unsafe.zip", mit_qec_originalen=True,
        )
    assert not (tmp_path / "unsafe.zip").exists()
