"""Synthetische Datenschutz- und Funktionsregressionen fuer Export v3.

KEINE vertraulichen Daten und keine echten FINs im Repository.
"""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime

import pytest
from zipfile import ZipFile

from ntf_insight.domain.case import NTFCase
from ntf_insight.domain.enums import SupplierFindingResult
from ntf_insight.domain.events import (
    DiagnosticSession, PartReplacement, SupplierFinding,
)
from ntf_insight.domain.vehicle import Vehicle
from ntf_insight.ingestion.artifacts import SourceType
from ntf_insight.ingestion.service import SourceImportService
from ntf_insight.reporting.chatgpt_exchange import (
    ChatGPTAnalyseStore, ChatGPTBeleg,
)
from ntf_insight.reporting.ki_analysepaket import export_ki_analysepaket
from ntf_insight.storage.source_knowledge_store import SourceKnowledgeStore
from ntf_insight.storage.workflow_ai_chain import WorkflowAIChainStore


FIN = "WDD12345678901234"
OTHER_FIN = "WDB00000000012345"
PRIVATE = "VERTRAULICH NUR SYNTHETISCH MIT FIN " + FIN


def _csv(archive, path):
    return list(csv.DictReader(io.StringIO(
        archive.read(path).decode("utf-8-sig")
    )))


def _source(tmp_path):
    service = SourceImportService(tmp_path / "raw", tmp_path / "ntf.duckdb")
    knowledge = SourceKnowledgeStore(service.store)
    swap = PartReplacement(
        vin=FIN, component_type="Kühlmittelpumpe",
        occurred_at=datetime(2026, 2, 5, 12),
        time_precision="date", mileage_km=15000,
        old_part_number="PUMP-ALT-REAL", new_part_number="PUMP-NEU-REAL",
        supplier="SUPPLIER-REAL", serial_number="SERIAL-REAL", batch="BATCH-REAL",
    )
    case = NTFCase(
        case_id="FALL-REAL-PRIVAT", component_type="Kühlmittelpumpe",
        component_profile_id="coolant_pump",
        vehicle=Vehicle(vin=FIN, model_series="214"),
        replacements=[swap], investigated_replacement_id=swap.event_id,
        qec_reference="REF-REAL-PRIVAT",
        supplier_findings=[SupplierFinding(
            vin=FIN, occurred_at=datetime(2026, 3, 2),
            supplier="SUPPLIER-REAL", result=SupplierFindingResult.NTF,
            complaint_reproduced=False, failure_mode="Unauffällig",
            notes=PRIVATE,
        )],
        diagnostic_sessions=[
            DiagnosticSession(
                vin=FIN, occurred_at=datetime(2026, 2, 1, 10),
                dtc_count=1, ecu_count=12,
            ),
            DiagnosticSession(
                vin=FIN, occurred_at=datetime(2026, 2, 10, 10),
                dtc_count=0, ecu_count=12,
            ),
        ],
    )
    service.store.save_case(case)
    records = [
        {
            "category": "autoexport_dtc", "fin": FIN,
            "source_location": "csv:row:1",
            "data": {
                "Fin": FIN, "EcuNm": "CPC3", "EcuFaultNm": "P26F100",
                "EcuFaultStateTxt": "S", "FrequencyCounter": "3",
                "DiagStartTs": "2026-02-01T08:40:00Z",
                "KmReadingNum": "14500", "EcuSwVersionTxt": "SW-ALT",
                "EcuSuppHwVersionTxt": "HW-ALT", "EcuFaultTxt": PRIVATE,
            },
        },
        {
            "category": "autoexport_dtc", "fin": FIN,
            "source_location": "csv:row:2",
            "data": {
                "Fin": FIN, "EcuNm": "CPC3", "EcuFaultNm": "P26F100",
                "DiagStartDt": "2026-02-10", "KmReadingNum": "15100",
                "EcuSwVersionTxt": "SW-NEU",
            },
        },
        {
            "category": "autoexport_dtc", "fin": FIN,
            "source_location": "csv:row:3",
            "data": {
                "Fin": FIN, "EcuNm": "CPC3", "EcuFaultNm": "P26F100",
                "DiagStartTs": "2026-02-05T08:40:00Z",
            },
        },
        {
            "category": "autoexport_dtc", "fin": OTHER_FIN,
            "source_location": "csv:row:4",
            "data": {
                "Fin": OTHER_FIN, "EcuNm": "CPC3",
                "EcuFaultNm": "P00FA01", "DiagStartDt": "2026-02-01",
            },
        },
        {
            "category": "autoexport_repair", "fin": FIN,
            "source_location": "csv:row:5",
            "data": {
                "Fin": FIN, "RepairDt": "2026-02-05",
                "PartLetterCd": "PUMP-ALT-REAL", "KmReadingNum": "15000",
                "ComplDsc": PRIVATE, "RepairTypeNmGerman": "Pumpe getauscht",
            },
        },
        {
            "category": "autoexport_tips", "fin": FIN,
            "source_location": "csv:row:6",
            "data": {
                "Fin": FIN, "CaseId": "TIPS-ORIGINAL",
                "CreationDate": "2026-02-01",
                "InitialWorkshopMessageCustomerComplaint": PRIVATE,
            },
        },
    ]
    knowledge.save_records("a" * 64, "autoexport", records)
    attachment = tmp_path / "supplier-report.pdf"
    attachment.write_bytes(b"%PDF-1.7\nSynthetic supplier report\n")
    service.import_raw(attachment, SourceType.SUPPLIER_FINDING, case_id_hint=case.case_id)
    return service


def test_v3_enthaelt_autoexport_und_trennt_lieferantenbefunde(tmp_path):
    service = _source(tmp_path)
    result = export_ki_analysepaket(service, tmp_path / "paket.zip")
    assert result.fahrzeuge == 2  # inklusive reiner AutoExport-FIN ohne QEC-Fall
    assert result.faelle == 1

    with ZipFile(result.pfad) as archive:
        names = set(archive.namelist())
        assert {
            "autoexport_diagnosen.csv", "autoexport_fallbezug.csv",
            "werkstatt_historie.csv", "autoexport_tips.csv",
            "pumpentausch_historie.csv", "fall_ereignisse.csv",
            "ecu_versionshistorie.csv", "diagnose_qualitaet.csv",
            "lieferantenbefunde_NICHT_CLUSTER.csv",
            "lieferantenquellen_bestand_NICHT_CLUSTER.csv",
        } <= names
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["schema_version"] == 3
        assert manifest["datenreihen"]["autoexport_dtc_zeilen"] == 4

        ae = _csv(archive, "autoexport_diagnosen.csv")
        assert len(ae) == 4
        assert {r["dtc_code"] for r in ae} == {"P26F100", "P00FA01"}
        assert all(r["fahrzeug_id"].startswith("V") for r in ae)
        assert all(not r["dtc_text_opt_in"] for r in ae)

        rel = _csv(archive, "autoexport_fallbezug.csv")
        assert len(rel) == 3
        assert {r["lage_zum_pumpentausch"] for r in rel} == {
            "vor_tausch", "nach_tausch", "zeitlich_unklar",
        }
        assert _csv(archive, "diagnose_qualitaet.csv")[0]["autoexport_dtc_vor_positiv"] == "1"
        assert _csv(archive, "pumpentausch_historie.csv")[0]["alte_teilegruppe"].startswith("T")
        assert _csv(archive, "lieferantenbefunde_NICHT_CLUSTER.csv")[0]["ergebnis_nachtraeglich"] == "NTF"
        lieferantenquellen = _csv(archive, "lieferantenquellen_bestand_NICHT_CLUSTER.csv")
        assert len(lieferantenquellen) == 1
        assert lieferantenquellen[0]["original_im_zip"] == "0"
        assert not any(name.endswith(".pdf") for name in names)
        cluster = archive.read("cluster_input.csv").decode("utf-8-sig")
        assert "supplier" not in cluster.lower()
        assert "lieferant" not in cluster.lower()
        assert "autoexport_diagnosen" not in cluster  # separater sicherer Join

        for name in names:
            if name.endswith((".csv", ".json", ".txt")):
                body = archive.read(name).decode("utf-8-sig")
                for sensitive in (
                    FIN, OTHER_FIN, PRIVATE, "FALL-REAL-PRIVAT",
                    "PUMP-ALT-REAL", "SUPPLIER-REAL", "TIPS-ORIGINAL",
                ):
                    assert sensitive not in body, (name, sensitive)

        aliases = _csv(archive, "autoexport_diagnosen.csv")
        source_alias = aliases[0]["quelle_id"]
        mapping = ChatGPTAnalyseStore(service.store)._mapping(manifest["paket_id"], None)
        assert ("quelle", source_alias) in mapping
        assert any(art == "lieferant" for art, _ in mapping)
        ChatGPTAnalyseStore._validate_belege([
            ChatGPTBeleg(
                quelle="autoexport_diagnosen",
                quelle_id=source_alias,
                fundstelle="csv:row:1",
            ),
        ], mapping)

    private = result.private_zuordnung.read_text(encoding="utf-8-sig")
    assert FIN in private
    assert "SUPPLIER-REAL" in private
    assert "PUMP-ALT-REAL" in private


def test_v3_freitext_zusaetzliche_quellen_nur_opt_in(tmp_path):
    service = _source(tmp_path)
    output = export_ki_analysepaket(service, tmp_path / "freitext.zip", mit_freitext=True)
    with ZipFile(output.pfad) as archive:
        assert PRIVATE in archive.read("autoexport_diagnosen.csv").decode("utf-8-sig")
        assert PRIVATE in archive.read("werkstatt_historie.csv").decode("utf-8-sig")
        assert PRIVATE in archive.read("autoexport_tips.csv").decode("utf-8-sig")
        assert PRIVATE in archive.read("lieferantenbefunde_NICHT_CLUSTER.csv").decode("utf-8-sig")
        assert json.loads(archive.read("manifest.json"))["pseudonymisiert"] is False


def test_chatgpt_row_evidence_uses_archived_export_not_private_alias(tmp_path):
    """AE-/LB-Zeilen des v3-Exports müssen zum ursprünglichen ZIP gehören."""
    service = _source(tmp_path)
    exported = export_ki_analysepaket(service, tmp_path / "row-source.zip")
    WorkflowAIChainStore(service.store).register_first_export(
        "coolant_pump", "PUMP-ALT-REAL", exported.pfad,
    )
    with ZipFile(exported.pfad) as archive:
        template = json.loads(archive.read("chatgpt_ergebnis_vorlage.json"))
        case_alias = _csv(archive, "faelle.csv")[0]["fall_id"]
        auto_alias = _csv(archive, "autoexport_diagnosen.csv")[0]["beobachtung_id"]
        supplier_alias = _csv(
            archive, "lieferantenbefunde_NICHT_CLUSTER.csv"
        )[0]["befund_id"]

    template["cluster"] = [{
        "cluster_id": "C01", "titel": "Vor-Tausch-DTC", "fall_ids": [case_alias],
        "technische_hypothese": "Elektrik prüfen", "sicherheit": "Niedrig",
        "belege": [{"quelle": "autoexport_diagnosen", "quelle_id": auto_alias}],
    }]
    template["faelle"] = [{
        "fall_id": case_alias, "cluster_id": "C01",
        "ntf_bewertung": "NTF fraglich", "prioritaet": "P2",
        "belege": [
            {"quelle": "autoexport_diagnosen", "quelle_id": auto_alias},
            {"quelle": "lieferantenbefunde_NICHT_CLUSTER",
             "quelle_id": supplier_alias},
        ],
    }]
    result_path = tmp_path / "chatgpt.json"
    records = []
    template["analyse_id"] = "Analyse-Test-Zeilenbelege"
    result_path.write_text(json.dumps(template), encoding="utf-8")

    store = ChatGPTAnalyseStore(service.store)
    result = store.import_file(result_path, progress=records.append)
    assert (result["faelle"], result["cluster"]) == (1, 1)
    assert records and any("Fallbewertungen prüfen" in msg for msg in records)
    assert store.latest_for_case("FALL-REAL-PRIVAT") is not None

    # Auch mit passender Paket-ID dürfen erfundene Zeilen nicht durchgehen.
    template["analyse_id"] = "Analyse-Test-Manipulation"
    template["faelle"][0]["belege"][1]["quelle_id"] = "LB999999"
    result_path.write_text(json.dumps(template), encoding="utf-8")
    with pytest.raises(ValueError, match="nicht vorhanden"):
        store.import_file(result_path)
    assert store.latest_for_case("FALL-REAL-PRIVAT")["analyse_id"] == (
        "Analyse-Test-Zeilenbelege"
    )


def test_chatgpt_row_evidence_without_archived_package_is_rejected(tmp_path):
    """Fehlende Originalquelle wird nicht als validierter Lieferantenbeleg geraten."""
    service = _source(tmp_path)
    exported = export_ki_analysepaket(service, tmp_path / "row-no-zip.zip")
    with ZipFile(exported.pfad) as archive:
        template = json.loads(archive.read("chatgpt_ergebnis_vorlage.json"))
        case_alias = _csv(archive, "faelle.csv")[0]["fall_id"]
        auto_alias = _csv(archive, "autoexport_diagnosen.csv")[0]["beobachtung_id"]
    template["faelle"] = [{
        "fall_id": case_alias,
        "belege": [{"quelle": "autoexport_diagnosen", "quelle_id": auto_alias}],
    }]
    path = tmp_path / "rueckgabe.json"
    path.write_text(json.dumps(template), encoding="utf-8")
    with pytest.raises(ValueError, match="Analyse-ZIP"):
        ChatGPTAnalyseStore(service.store).import_file(path)
