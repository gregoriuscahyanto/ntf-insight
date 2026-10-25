"""Synthetische Sicherheits-/Vollstaendigkeitstests fuer ChatGPT-Runde 2."""
from __future__ import annotations

import csv
import hashlib
import io
import json
from datetime import datetime
from pathlib import Path
from zipfile import ZipFile

import pytest

from ntf_insight.domain.case import NTFCase
from ntf_insight.domain.vehicle import Vehicle
from ntf_insight.ingestion.artifacts import SourceType
from ntf_insight.reporting.cluster_context_package import export_cluster_context
from ntf_insight.reporting.qec_first_package import export_qec_first_package
from ntf_insight.storage.cluster_evidence_store import ClusterEvidenceStore
from ntf_insight.storage.source_knowledge_store import SourceKnowledgeStore
from ntf_insight.storage.workflow_ai_chain import WorkflowAIChainStore
from ntf_insight.storage.workflow_projects import NTFProject, WorkflowProjectStore
from test_ki_analysepaket import FIN, PRIVATE_TEXT, _set_up

OTHER_FIN = "WDD12345678901245"
PART = "A-EXAMPLE-001"
CASE_ID = "QEC-FALL-VERTRAULICH"


def _csv(zipfile: ZipFile, name: str) -> list[dict]:
    return list(csv.DictReader(io.StringIO(
        zipfile.read(name).decode("utf-8-sig")
    )))


def _first(source, destination: Path, *, mit_freitext: bool = False):
    first = export_qec_first_package(
        source, destination, profile_id="coolant_pump",
        part_number=PART, selected_fins={FIN},
        selected_case_ids={CASE_ID}, mit_freitext=mit_freitext,
    )
    stored = WorkflowAIChainStore(source.store).register_first_export(
        "coolant_pump", PART, first.pfad,
    )
    with ZipFile(stored.path) as archive:
        template = json.loads(
            archive.read("chatgpt_ergebnis_vorlage.json")
        )
        template["faelle"] = [{
            "fall_id": _csv(archive, "faelle.csv")[0]["fall_id"],
            "ntf_bewertung": "NTF fraglich",
        }]
    return stored, template


def _create_test_data(tmp_path: Path):
    data = tmp_path / "daten"
    data.mkdir()
    source = _set_up(data)
    WorkflowProjectStore(source.store).save(
        NTFProject("coolant_pump", PART, "Kuehlmittelpumpe", ("CPC3",))
    )
    other = NTFCase(
        case_id="FREMD-BAUTEIL-FALL",
        vehicle=Vehicle(vin=OTHER_FIN, model_series="999"),
        component_type="HV-Batterie",
        component_profile_id="hv_battery",
        qec_part_number="B-FREMD-002",
        qec_reference="654320",
    )
    source.store.save_case(other)
    with source.store.connect() as con:
        con.execute(
            "INSERT INTO quicktest_reports VALUES (?,?,?,?,?,?,?,?,?,?)",
            ["OTHER-QT", OTHER_FIN, OTHER_FIN, datetime(2026, 1, 11, 10),
             30000, 1, 1, "{}", "c" * 64, datetime(2026, 1, 12)],
        )
        con.execute(
            "INSERT INTO quicktest_dtcs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ["OTHER-QT", 1, 1, "BMS", "FC", "PFOREIGN",
             "DTC fremdes Fahrzeug", "S", 1, 30000, 30000, 1, 1, 1, ""],
        )
        con.execute(
            "INSERT INTO quicktest_pages VALUES (?,?,?)",
            ["QTPRE", 1, "Synthetisches PDF " + FIN + " mit DTC P26F100"],
        )

    # Geparste PDF (gleiches SHA wie quicktest_sources) niemals als Raw-PDF
    # duplizieren; neues PDF derselben FIN muss als Fallback rein.
    folder = data / "quicktests" / FIN
    folder.mkdir(parents=True)
    parsed = folder / "bereits-geparst.pdf"
    parsed.write_bytes(b"%PDF-1.5\nPARSED\n%%EOF")
    parsed_sha = hashlib.sha256(parsed.read_bytes()).hexdigest()
    with source.store.connect() as con:
        con.execute(
            "INSERT INTO quicktest_sources VALUES (?,?)",
            [parsed_sha, "QTPRE"],
        )
    pending = folder / "noch-ungeparst.pdf"
    pending.write_bytes(b"%PDF-1.5\nUNPARSED\n%%EOF")

    knowledge = SourceKnowledgeStore(source.store)
    knowledge.save_records(
        "d" * 64, "autoexport_rows",
        [
            {"category": "autoexport_dtc",
             "source_location": "csv:1", "fin": FIN, "reference": "",
             "label": "CPC3",
             "data": {
                 "Fin": FIN, "DiagStartTs": "2026-01-04 10:00:00",
                 "EcuNm": "CPC3", "EcuFaultNm": "P26F100",
                 "EcuFaultStateTxt": "S", "KmReadingNum": "11900",
             }},
            {"category": "autoexport_dtc",
             "source_location": "csv:2", "fin": OTHER_FIN, "reference": "",
             "label": "BMS",
             "data": {
                 "Fin": OTHER_FIN, "DiagStartTs": "2026-01-04 10:00:00",
                 "EcuNm": "BMS", "EcuFaultNm": "PFOREIGN",
             }},
        ],
        metadata={"source_type": "tp_dashboard"},
    )
    knowledge.save_records(
        "e" * 64, "autoexport_rows",
        [{"category": "autoexport_dtc",
          "source_location": "csv:1", "fin": FIN, "reference": "",
          "label": "Fremdquelle",
          "data": {"Fin": FIN, "EcuNm": "MISC", "EcuFaultNm": "POTHER"}}],
        metadata={"source_type": "autoexport"},
    )
    evidence = ClusterEvidenceStore(source.store)
    tech = tmp_path / "schaltplan.txt"
    tech.write_text("Projekt Kuehlmittelpumpe, technische Pinbelegung", encoding="utf-8")
    evidence.add_files("coolant_pump", PART, "additional", [tech])
    foreign = tmp_path / "fremder_fall.txt"
    foreign.write_text("FREMDFINFILE", encoding="utf-8")
    source.import_raw(foreign, SourceType.OTHER, vin_hint=OTHER_FIN)
    evidence.add_files("coolant_pump", PART, "additional", [foreign])
    separate = tmp_path / "fremdprojekt.txt"
    separate.write_text("FREMDES_PROJEKT_FINGERPRINT", encoding="utf-8")
    evidence.add_files("hv_battery", "B-FREMD-002", "additional", [separate])
    return source, evidence, pending, parsed, tech, foreign


def test_comprehensive_second_export_contains_parsed_diagnosis_and_unparsed_fallback(
    tmp_path,
):
    source, evidence, _pending, _parsed, _tech, _foreign = _create_test_data(tmp_path)
    first, first_result = _first(source, tmp_path / "first.zip")
    exported = export_cluster_context(
        evidence, "coolant_pump", PART, first.path,
        tmp_path / "second.zip", include_originals=True,
        first_result=first_result,
    )
    assert exported.parent_package_id == first.paket_id
    with ZipFile(exported.path) as archive:
        names = archive.namelist()
        assert "basis/faelle.csv" in names
        assert "basis/qec_felder.csv" in names
        assert "voranalyse/erstes_chatgpt_ergebnis.json" in names
        required = {
            "diagnose/quicktests.csv", "diagnose/ecu_staende.csv",
            "diagnose/dtc_beobachtungen.csv", "diagnose/dtc_parameter.csv",
            "diagnose/quicktest_seitentexte.csv", "diagnose/quicktest_fallbezug.csv",
            "diagnose/tp_dashboard_dtc.csv", "diagnose/tips_writer.csv",
        }
        assert required <= set(names)
        reports = _csv(archive, "diagnose/quicktests.csv")
        assert len(reports) == 2
        assert {r["quicktest_id"] for r in reports} == {
            "QT000001", "QT000002",
        }
        assert all(r["fahrzeug_id"].startswith("V") for r in reports)
        dtcs = _csv(archive, "diagnose/dtc_beobachtungen.csv")
        assert len(dtcs) == 2
        assert all(d["dtc_code"] == "P26F100" for d in dtcs)
        assert all("PFOREIGN" not in str(row) for row in dtcs)
        assert len(_csv(archive, "diagnose/ecu_staende.csv")) == 2
        assert len(_csv(archive, "diagnose/quicktest_fallbezug.csv")) == 2
        tp = _csv(archive, "diagnose/tp_dashboard_dtc.csv")
        assert len(tp) == 1 and tp[0]["dtc_code"] == "P26F100"
        fulltext = _csv(archive, "diagnose/quicktest_seitentexte.csv")
        assert "<FIN>" in fulltext[0]["geparster_text"]
        assert FIN not in fulltext[0]["geparster_text"]
        assert len([n for n in names if n.startswith(
            "unterlagen/diagnosis_viewer_fallback/"
        )]) == 1
        assert b"UNPARSED" in archive.read(
            next(n for n in names if n.startswith(
                "unterlagen/diagnosis_viewer_fallback/"
            ))
        )
        assert b"\nPARSED\n" not in b"".join(
            archive.read(n) for n in names if n.startswith("unterlagen/")
        )
        manifest = json.loads(
            archive.read("cluster_kontext_manifest.json")
        )
        assert manifest["diagnose_auszug"]["quicktests_geparst"] == 2
        assert manifest["diagnose_auszug"]["dtc_beobachtungen"] == 2
        assert manifest["diagnose_auszug"]["autoexport_dtc"] == 1
        assert manifest["unterlagen_nach_sachnummer_zugeordnet"]
        assert any(entry["auslassungsgrund"].startswith(
            "Dokument ist einem anderen Fahrzeug"
        ) for entry in manifest["belege"])
        assert any(entry["zuordnung"].startswith(
            "Explizit dem Projekt"
        ) for entry in manifest["belege"])
        assert any(n.startswith("unterlagen/additional/") for n in names)
        assert b"FREMDFINFILE" not in b"".join(
            archive.read(n) for n in names if n.startswith("unterlagen/")
        )
        assert b"FREMDES_PROJEKT_FINGERPRINT" not in b"".join(
            archive.read(n) for n in names if n.startswith("unterlagen/")
        )
        assert "Sammeldateien" in archive.read(
            "CHATGPT_2_DURCHLAUF.txt"
        ).decode("utf-8") or "andere Sachnummern" in archive.read(
            "CHATGPT_2_DURCHLAUF.txt"
        ).decode("utf-8")


def test_second_export_without_originals_still_has_structured_data(tmp_path):
    source, evidence, _pending, _parsed, _tech, _foreign = _create_test_data(tmp_path)
    first, first_result = _first(source, tmp_path / "first.zip")
    out = export_cluster_context(
        evidence, "coolant_pump", PART, first.path,
        tmp_path / "second-no-originals.zip", include_originals=False,
        first_result=first_result,
    )
    with ZipFile(out.path) as archive:
        assert "diagnose/quicktests.csv" in archive.namelist()
        assert len(_csv(archive, "diagnose/quicktests.csv")) == 2
        assert "diagnose/quicktest_seitentexte.csv" not in archive.namelist()
        assert not any(name.startswith("unterlagen/") for name in archive.namelist())
        manifest = json.loads(
            archive.read("cluster_kontext_manifest.json")
        )
        assert manifest["diagnose_auszug"]["originale_projektdateien"] == 0
        assert any(not row["original_aufgenommen"] for row in manifest["belege"])


def test_confidential_first_basis_requires_separate_permission(tmp_path):
    source, evidence, _pending, _parsed, _tech, _foreign = _create_test_data(tmp_path)
    first, first_result = _first(source, tmp_path / "first-sensitive.zip", mit_freitext=True)
    with pytest.raises(ValueError, match="getrennte Freigabe"):
        export_cluster_context(
            evidence, "coolant_pump", PART, first.path,
            tmp_path / "should-fail.zip", include_originals=True,
            include_confidential_basis=False, first_result=first_result,
        )
    result = export_cluster_context(
        evidence, "coolant_pump", PART, first.path,
        tmp_path / "with-freitext.zip", include_originals=False,
        include_confidential_basis=True, first_result=first_result,
    )
    with ZipFile(result.path) as archive:
        assert "basis/qec_felder.csv" in archive.namelist()
        assert "unterlagen/additional/D" not in "".join(archive.namelist())
        manifest = json.loads(
            archive.read("cluster_kontext_manifest.json")
        )
        assert manifest["vertrauliche_basis_gesondert_freigegeben"]
