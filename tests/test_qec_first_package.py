"""Regressionen fuer die neue QEC-Erstanalyse in Workflow-Schritt 03.

Ausschliesslich synthetische Testdaten, keinerlei echte FINs oder QEC-Originale.
"""
from __future__ import annotations

import csv
import io
import json
from zipfile import ZipFile

import pytest

from ntf_insight.domain.case import NTFCase
from ntf_insight.domain.vehicle import Vehicle
from ntf_insight.reporting.chatgpt_exchange import ChatGPTAnalyseStore
from ntf_insight.reporting.cluster_context_package import export_cluster_context
from ntf_insight.reporting.qec_first_package import export_qec_first_package
from ntf_insight.storage.cluster_evidence_store import ClusterEvidenceStore
from ntf_insight.storage.source_knowledge_store import SourceKnowledgeStore
from ntf_insight.storage.workflow_ai_chain import WorkflowAIChainStore
from ntf_insight.storage.workflow_projects import NTFProject, WorkflowProjectStore
from ntf_insight.storage.qec_project_scope import qec_case_matches_project
from ntf_insight.ingestion.service import SourceImportService
from test_ki_analysepaket import (
    FIN, PRIVATE_TEXT, SECRET_QEC_TEXT, _set_up,
)

CASE_ID = "QEC-FALL-VERTRAULICH"
PART = "A-EXAMPLE-001"


def _rows(archive: ZipFile, name: str) -> list[dict]:
    return list(csv.DictReader(io.StringIO(
        archive.read(name).decode("utf-8-sig")
    )))


def _export(source, path, **options):
    return export_qec_first_package(
        source, path,
        profile_id="coolant_pump",
        part_number=PART,
        selected_fins={FIN},
        selected_case_ids={CASE_ID},
        **options,
    )


def test_step03_exports_only_qec_01_02_and_preserves_privacy(tmp_path):
    source = _set_up(tmp_path)
    messages = []
    result = _export(
        source, tmp_path / "qec-erstanalyse.zip", progress=messages.append
    )
    assert (result.faelle, result.fahrzeuge, result.qec_berichte) == (1, 1, 1)
    assert (result.quicktests, result.dtcs) == (0, 0)
    assert messages

    with ZipFile(result.pfad) as archive:
        files = set(archive.namelist())
        assert {
            "faelle.csv", "fahrzeuge.csv", "cluster_input.csv",
            "fallmerkmale.csv", "qec_felder.csv", "qec_berichte.csv",
            "qec_datenluecken.csv", "bewertungen_NICHT_CLUSTER.csv",
            "manifest.json", "methodik.csv", "README.txt",
            "Auswertung.xlsx", "chatgpt_ergebnis_vorlage.json",
            "chatgpt_ergebnis_schema.json",
        } <= files
        assert not any(name.startswith("qec_originale/") for name in files)
        assert not any(name in files for name in (
            "quicktests.csv", "quicktest_fallbezug.csv",
            "dtc_beobachtungen.csv", "ecu_staende.csv",
            "autoexport_diagnosen.csv", "autoexport_fallbezug.csv",
            "werkstatt_historie.csv", "autoexport_tips.csv",
            "tips.csv", "lieferantenbefunde_NICHT_CLUSTER.csv",
            "smrd_bestand.csv",
        ))
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["schema_version"] == 3
        assert manifest["analyseumfang"] == "workflow_01_02_qec"
        assert manifest["pseudonymisiert"]
        assert manifest["datenreihen"]["quicktests"] == 0
        faelle = _rows(archive, "faelle.csv")
        fields = _rows(archive, "qec_felder.csv")
        assert faelle[0]["fall_id"].startswith("F")
        assert faelle[0]["qec_bericht_id"].startswith("Q")
        assert len(fields) == 2
        assert any(row["wert_strukturiert"] == "ja" for row in fields)
        assert all(not row["original_wert_opt_in"] for row in fields)
        assert all(not row["original_beschriftung_opt_in"] for row in fields)
        assert _rows(archive, "qec_datenluecken.csv")[0][
            "fachtexte_ausgeblendet"
        ] == "1"
        assert FIN.encode() not in archive.read("faelle.csv")
        for name in files:
            if name.endswith((".csv", ".json", ".txt")):
                payload = archive.read(name).decode("utf-8-sig")
                assert FIN not in payload
                assert CASE_ID not in payload
                assert SECRET_QEC_TEXT not in payload
                assert PRIVATE_TEXT not in payload

    private = result.private_zuordnung.read_text(encoding="utf-8-sig")
    assert FIN in private
    assert CASE_ID in private
    assert "_NICHT_HOCHLADEN_" in result.private_zuordnung.name


def test_step03_qec_fachtexte_only_after_explicit_opt_in(tmp_path):
    source = _set_up(tmp_path)
    result = _export(
        source, tmp_path / "qec-vertraulich.zip", mit_freitext=True,
    )
    with ZipFile(result.pfad) as archive:
        assert SECRET_QEC_TEXT in archive.read("qec_felder.csv").decode("utf-8")
        assert json.loads(archive.read("manifest.json"))["pseudonymisiert"] is False
        assert not any(
            name in archive.namelist()
            for name in ("quicktests.csv", "tips.csv", "autoexport_diagnosen.csv")
        )


def test_step03_never_uses_other_component_or_part_on_same_fin(tmp_path):
    source = _set_up(tmp_path)
    other = NTFCase(
        case_id="QEC-FREMD-TEIL",
        vehicle=Vehicle(vin=FIN, model_series="214"),
        component_type="Kuehlmittelpumpe",
        component_profile_id="coolant_pump",
        qec_reference="999999",
        qec_part_number="B-OTHER-123",
    )
    source.store.save_case(other)
    extra = [{
        "category": "qec_field", "source_location": "QEC/01-WE-Daten/feld:1",
        "fin": FIN, "reference": "999999", "label": "Fremdteil",
        "data": {"bereich": "WE-Daten", "typ": "text", "wert": "FREMDTEIL"},
    }]
    SourceKnowledgeStore(source.store).save_records(
        "c" * 64, "qec_live_report", extra,
        metadata={
            "fin": FIN, "reference": "999999", "part_number": "B-OTHER-123",
            "fresh_complete": True, "sections": 5, "fresh_sections": 5,
        },
    )
    result = _export(source, tmp_path / "qec-scoped.zip", mit_freitext=True)
    with ZipFile(result.pfad) as archive:
        assert len(_rows(archive, "faelle.csv")) == 1
        assert len(_rows(archive, "qec_berichte.csv")) == 1
        assert "FREMDTEIL" not in archive.read("qec_felder.csv").decode("utf-8")
        assert "999999" not in archive.read("README.txt").decode("utf-8")
    with pytest.raises(ValueError, match="Sachnummernprojekt"):
        export_qec_first_package(
            source, tmp_path / "wrong-case.zip",
            profile_id="coolant_pump", part_number=PART,
            selected_fins={FIN},
            selected_case_ids={CASE_ID, "QEC-FREMD-TEIL"},
        )


def test_step03_keeps_all_cases_when_no_qec_documents_exist(tmp_path):
    """QEC-Berichte duerfen vollständig fehlen; die Fallliste bleibt exportierbar."""
    source = _set_up(tmp_path)
    with source.store.connect() as con:
        con.execute(
            "DELETE FROM source_knowledge_rows WHERE source_sha256=?",
            ["a" * 64],
        )
        con.execute(
            "DELETE FROM source_knowledge_documents WHERE source_sha256=?",
            ["a" * 64],
        )
    result = _export(source, tmp_path / "missing-qec.zip")
    assert result.pfad.exists()
    assert result.faelle == 1
    assert result.qec_berichte == 0
    with ZipFile(result.pfad) as archive:
        gaps = _rows(archive, "qec_datenluecken.csv")
        cases = _rows(archive, "faelle.csv")
        assert len(cases) == len(gaps) == 1
        assert cases[0]["qec_bericht_status"] == "Nicht vorhanden"
        assert cases[0]["qec_bericht_id"] == ""
        assert gaps[0]["qec_bericht_status"] == "Nicht vorhanden"
        assert _rows(archive, "qec_felder.csv") == []
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["datenreihen"]["qec_berichte_nicht_vorhanden"] == 1
        assert "Nicht bewertbar" in archive.read(
            "CHATGPT_ANWEISUNG.txt"
        ).decode("utf-8")


def test_step03_new_package_keeps_prior_analysis_and_round_two_works(tmp_path):
    source = _set_up(tmp_path)
    first = _export(source, tmp_path / "runde1-alt.zip")
    chain = WorkflowAIChainStore(source.store)
    first_pkg = chain.register_first_export("coolant_pump", PART, first.pfad)
    with ZipFile(first.pfad) as archive:
        template = json.loads(archive.read("chatgpt_ergebnis_vorlage.json"))
        fall_id = _rows(archive, "faelle.csv")[0]["fall_id"]
        qec_id = _rows(archive, "qec_berichte.csv")[0]["qec_bericht_id"]
        fundstelle = _rows(archive, "qec_felder.csv")[0]["fundstelle"]
    template["faelle"] = [{
        "fall_id": fall_id,
        "ntf_bewertung": "NTF fraglich",
        "belege": [{
            "quelle": "qec_felder", "quelle_id": qec_id,
            "fundstelle": fundstelle,
            "belegstatus": "Originalbefund",
        }],
    }]
    answer = tmp_path / "erste-neuauswertung.json"
    answer.write_text(json.dumps(template), encoding="utf-8")
    result = ChatGPTAnalyseStore(source.store).import_file(answer)
    assert result["faelle"] == 1
    assert chain.record_import(result["analyse_id"], round_number=1)
    assert chain.first_result(first_pkg.paket_id) is not None

    second = _export(source, tmp_path / "runde1-neu.zip")
    second_pkg = chain.register_first_export("coolant_pump", PART, second.pfad)
    assert second_pkg.paket_id != first_pkg.paket_id
    # Die alte Analyse bleibt verifizierbar, aber der neue Export ist neu/ungeprueft.
    assert chain.first_result(first_pkg.paket_id) is not None
    assert chain.first_result(second_pkg.paket_id) is None
    with source.store.connect() as con:
        assert con.execute(
            "SELECT COUNT(*) FROM chatgpt_export_mapping "
            "WHERE paket_id IN (?,?) AND art='fall'",
            [first_pkg.paket_id, second_pkg.paket_id],
        ).fetchone()[0] == 2

    technical = ClusterEvidenceStore(source.store)
    (tmp_path / "werkstatt.txt").write_text(
        "Synthetische technische Unterlage", encoding="utf-8",
    )
    technical.add_files(
        "coolant_pump", PART, "additional", [tmp_path / "werkstatt.txt"],
    )
    round_two = export_cluster_context(
        technical, "coolant_pump", PART,
        first_pkg.path, tmp_path / "runde2.zip",
        first_result=chain.first_result(first_pkg.paket_id),
    )
    with ZipFile(round_two.path) as archive:
        assert "basis/qec_berichte.csv" in archive.namelist()
        assert "basis/qec_felder.csv" in archive.namelist()
        assert "voranalyse/erstes_chatgpt_ergebnis.json" in archive.namelist()
        assert "basis/quicktests.csv" not in archive.namelist()


def test_only_qec_excel_replacement_anchor_is_exported(tmp_path):
    """Tauschereignisse aus fremden Quellen sind kein Schritt-01-Beweis."""
    source = _set_up(tmp_path)
    without = _export(source, tmp_path / "ohne-qec-anker.zip")
    with ZipFile(without.pfad) as archive:
        row = _rows(archive, "faelle.csv")[0]
        assert row["tauschanker_vorhanden"] == "0"
        assert row["tausch_km"] == ""
        assert _rows(archive, "qec_datenluecken.csv")[0][
            "qec_tauschanker_fehlend"
        ] == "1"

    case = source.store.get_case(CASE_ID)
    case.source_ref = "raw:" + "d" * 64 + "#Schadteile QEC!2"
    case.replacements[0].source_ref = case.source_ref
    source.store.save_case(case)
    with_qec = _export(source, tmp_path / "mit-qec-anker.zip")
    with ZipFile(with_qec.pfad) as archive:
        row = _rows(archive, "faelle.csv")[0]
        assert row["tauschanker_vorhanden"] == "1"
        assert row["tausch_km"] == "12000"
        assert _rows(archive, "qec_datenluecken.csv")[0][
            "qec_tauschanker_fehlend"
        ] == "0"


def test_some_cases_without_qec_report_remain_in_export(tmp_path):
    source = _set_up(tmp_path)
    extra = NTFCase(
        case_id="QEC-KEIN-BERICHT",
        vehicle=Vehicle(vin="WDD12345678901235", model_series="214"),
        component_type="Kühlmittelpumpe",
        component_profile_id="coolant_pump",
        qec_reference="654321",
        qec_part_number=PART,
    )
    source.store.save_case(extra)
    result = export_qec_first_package(
        source, tmp_path / "teilweise-berichte.zip",
        profile_id="coolant_pump", part_number=PART,
        selected_fins={FIN, extra.vin},
        selected_case_ids={CASE_ID, extra.case_id},
    )
    assert result.faelle == 2
    assert result.qec_berichte == 1
    with ZipFile(result.pfad) as archive:
        cases = _rows(archive, "faelle.csv")
        gaps = _rows(archive, "qec_datenluecken.csv")
        assert len(cases) == len(gaps) == 2
        assert sum(row["qec_bericht_status"] == "Nicht vorhanden" for row in cases) == 1
        assert sum(row["qec_bericht_status"] == "Vollstaendig" for row in cases) == 1
        assert len(_rows(archive, "qec_felder.csv")) == 2
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["datenreihen"]["qec_berichte_nicht_vorhanden"] == 1


@pytest.mark.parametrize(
    ("profile", "component_name"),
    [
        ("hv_battery", "HV-Batterie"),
        ("dcdc_converter", "DC/DC-Wandler"),
        ("other_component", "Sensor / Ventil"),
    ],
)
def test_generic_first_and_second_round_without_documents(
    tmp_path, profile, component_name,
):
    """Beide ChatGPT-Exporte gehen auch ohne Diagnoseunterlagen und CPC3."""
    service = SourceImportService(tmp_path / "raw", tmp_path / "ntf.duckdb")
    project = WorkflowProjectStore(service.store)
    project.save(
        NTFProject(profile, "A 678 910", component_name, ("BMS",))
    )
    vehicle = "WDD12345678901239"
    case = NTFCase(
        case_id="QEC-FREMDPROFIL-123",
        vehicle=Vehicle(vin=vehicle, model_series="X"),
        component_type=component_name,
        component_profile_id=None,  # Generischer QEC-Parser.
        qec_reference="777788",
        qec_part_number="A678910",
    )
    service.store.save_case(case)
    output = export_qec_first_package(
        service, tmp_path / "erstes-qec.zip",
        profile_id=profile, part_number="A 678 910",
        selected_fins={vehicle}, selected_case_ids={case.case_id},
    )
    assert output.faelle == 1
    assert output.qec_berichte == 0
    with ZipFile(output.pfad) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["projektprofil"] == profile
        assert manifest["datenreihen"]["qec_berichte_nicht_vorhanden"] == 1
        assert archive.read("CHATGPT_ANWEISUNG.txt").decode(
            "utf-8"
        ).count("Nicht bewertbar") >= 1
        template = json.loads(archive.read("chatgpt_ergebnis_vorlage.json"))
        alias = _rows(archive, "faelle.csv")[0]["fall_id"]
    chain = WorkflowAIChainStore(service.store)
    first = chain.register_first_export(profile, "A 678 910", output.pfad)
    template["faelle"] = [{
        "fall_id": alias,
        "ntf_bewertung": "Nicht bewertbar",
        "pruefungen_grenzen": "QEC-Dokumente fuer diesen Fall fehlen.",
        "belege": [],
    }]
    answer = tmp_path / "qec-antwort.json"
    answer.write_text(json.dumps(template), encoding="utf-8")
    result = ChatGPTAnalyseStore(service.store).import_file(answer)
    assert result["faelle"] == 1
    assert chain.record_import(result["analyse_id"], round_number=1)
    technical = ClusterEvidenceStore(service.store)
    second = export_cluster_context(
        technical, profile, "A 678 910", first.path,
        tmp_path / "zweiter-kontext.zip",
        first_result=chain.first_result(first.paket_id),
    )
    with ZipFile(second.path) as archive:
        manifest = json.loads(archive.read("cluster_kontext_manifest.json"))
        assert manifest["profil"] == profile
        assert manifest["basis_nicht_nach_sachnummer_gefiltert"] is False
        assert manifest["sachnummer_wurde_lokal_gefiltert"] is True
        assert manifest["bestand"] is not None
        prompt = archive.read("CHATGPT_2_DURCHLAUF.txt").decode("utf-8")
        assert component_name in prompt
        assert "CPC3" not in prompt
        assert "Pumpe" not in prompt
        assert "Fehlende QEC-Berichte" in prompt
        assert "voranalyse/erstes_chatgpt_ergebnis.json" in archive.namelist()

    with pytest.raises(ValueError, match="Sachnummernprojekt"):
        export_cluster_context(
            technical, profile, "A 000 001", first.path,
            tmp_path / "falsche-sachnummer.zip",
        )
    with pytest.raises(ValueError, match="Bauteilprofil"):
        export_cluster_context(
            technical, "coolant_pump", "A 678 910", first.path,
            tmp_path / "falsches-profil.zip",
        )


def test_unknown_qec_component_cannot_cross_ambiguous_project_boundaries(tmp_path):
    source = SourceImportService(tmp_path / "raw", tmp_path / "db.duckdb")
    projects = WorkflowProjectStore(source.store)
    pump = projects.save(NTFProject("coolant_pump", "A-ONE", "Pumpe", ()))
    battery = projects.save(NTFProject("hv_battery", "A ONE", "Batterie", ()))
    assert not qec_case_matches_project(
        case_part_number="AONE",
        source_profile_id=None,
        project_profile_id="hv_battery",
        project_part_number="A ONE",
        projects=[pump, battery],
    )
    assert qec_case_matches_project(
        case_part_number="AONE",
        source_profile_id="hv_battery",
        project_profile_id="hv_battery",
        project_part_number="A ONE",
        projects=[pump, battery],
    )
    assert not qec_case_matches_project(
        case_part_number="AONE",
        source_profile_id="coolant_pump",
        project_profile_id="hv_battery",
        project_part_number="A ONE",
        projects=[pump, battery],
    )


def test_existing_qec_report_with_inconsistent_tab_counts_is_only_partial(tmp_path):
    """Vorhandene Dokumente pruefen, aber bei Inkonsistenz nicht abbrechen."""
    source = _set_up(tmp_path)
    with source.store.connect() as con:
        old = con.execute(
            "SELECT metadata_json FROM source_knowledge_documents "
            "WHERE source_sha256=?",
            ["a" * 64],
        ).fetchone()
        meta = json.loads(old[0])
        meta.update({
            "fresh_complete": True,
            "sections": 5,
            "fresh_sections": 3,
            "missing_sections": ["Historie", "Ergebnis + Nachanalyse"],
        })
        con.execute(
            "UPDATE source_knowledge_documents SET metadata_json=? "
            "WHERE source_sha256=?",
            [json.dumps(meta), "a" * 64],
        )
    out = _export(source, tmp_path / "nicht-alle-reiter.zip")
    assert out.faelle == 1 and out.qec_berichte == 1
    with ZipFile(out.pfad) as archive:
        row = _rows(archive, "faelle.csv")[0]
        assert row["qec_bericht_status"] == "Teilweise"
        gap = _rows(archive, "qec_datenluecken.csv")[0]
        assert "Historie" in gap["fehlende_reiter"]
        assert "Abruf ist unvollstaendig" in gap["datenluecke"]
