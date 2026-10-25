"""Regressionen: ein T/S-JSON pro Runde 2, alle Fälle genau einmal.

Ausschliesslich synthetische QEC-Fall- und Quellenpseudonyme.
"""
from __future__ import annotations

import json
from zipfile import ZipFile

import pytest
from pydantic import ValidationError

from ntf_insight.reporting.chatgpt_exchange import (
    ChatGPTAnalyseStore, ChatGPTRueckgabe,
)
from ntf_insight.reporting.cluster_context_package import export_cluster_context
from ntf_insight.storage.workflow_ai_chain import WorkflowAIChainStore
from test_cluster_technical_export import (
    CASE_ID, PART, _create_test_data, _first,
)


def _prepared(tmp_path):
    source, evidence, *_ = _create_test_data(tmp_path)
    first, initial = _first(source, tmp_path / "first.zip")
    second = export_cluster_context(
        evidence, "coolant_pump", PART, first.path,
        tmp_path / "second.zip", include_originals=False,
        first_result=initial,
    )
    chain = WorkflowAIChainStore(source.store)
    chain.register_second_export(
        "coolant_pump", PART, first.paket_id, second.analysis_id,
    )
    with ZipFile(second.path) as archive:
        template = json.loads(
            archive.read("chatgpt_ergebnis_vorlage.json")
        )
        prompt = archive.read("CHATGPT_2_DURCHLAUF.txt").decode("utf-8")
        manifest = json.loads(archive.read("cluster_kontext_manifest.json"))
        schema = json.loads(archive.read("chatgpt_ergebnis_schema.json"))
    return source, first, second, chain, template, prompt, manifest, schema


def test_second_zip_requires_exact_one_T_S_or_H_per_case(tmp_path):
    _source, _first, _second, _chain, template, prompt, manifest, schema = (
        _prepared(tmp_path)
    )
    assert template["cluster_abdeckung"] == "T_S_H_v1"
    assert template["analyse_id"].startswith("ClusterTSH-")
    assert manifest["cluster_abdeckung"] == "T_S_H_v1"
    assert "JEDER" in prompt
    assert "Txx" in prompt and "Sxx" in prompt and "Hxx" in prompt
    assert "T -> S -> H" in prompt
    assert "hypothese_von='ChatGPT'" in prompt
    assert "hypothese_bestaetigt=false" in prompt
    assert "cluster_id=null" not in prompt
    assert "ebene" in schema["$defs"]["ChatGPTCluster"]["properties"]
    assert "cluster_abdeckung" in schema["properties"]
    assert "analyse_id_vorher" in schema["properties"]
    assert "hypothese_von" in schema["$defs"]["ChatGPTCluster"]["properties"]
    assert "hypothese_bestaetigt" in schema["$defs"]["ChatGPTFall"]["properties"]


def test_ts_schema_keeps_ambiguous_current_as_noncausal_symptom():
    valid = ChatGPTRueckgabe.model_validate({
        "paket_id": "a" * 32,
        "analyse_id": "ClusterTS-synthetic",
        "cluster_abdeckung": "T_S_v1",
        "faelle": [{
            "fall_id": "F0001", "cluster_id": "S01",
            "fehlerbilder": [{
                "kategorie": "Stromaufnahme unplausibel (hoch/niedrig)",
                "nachweisstatus": "Werkstattangabe",
            }],
            "nachweisprofil": ["Werkstattangabe vorhanden"],
        }],
        "cluster": [{
            "cluster_id": "S01", "ebene": "S", "titel": "Nur Werkstattmeldung",
            "fall_ids": ["F0001"], "sicherheit": "Niedrig",
        }],
    })
    assert valid.cluster[0].ebene == "S"
    with pytest.raises(ValidationError):
        ChatGPTRueckgabe.model_validate({
            **valid.model_dump(mode="json"),
            "unbekannter_import_modus": True,
        })


def test_import_same_button_revisions_parent_while_preserving_old(tmp_path):
    source, first, second, chain, template, *_rest = _prepared(tmp_path)
    importer = ChatGPTAnalyseStore(source.store)
    # Die zweite Basisanalyse ist bereits importiert, aber technisch
    # ungeclustert. Die neue Datei ordnet diesen Fall als S ein.
    parent = dict(template)
    # Regression zum historischen, tatsaechlich noch importierbaren
    # T/S-Vorgaengerformat; der heutige ZIP-Export verlangt T/S/H.
    # Test-Legacy-ID wird nur in der synthetischen DB als zweiter
    # Export registriert, niemals als reales Benutzerpaket ausgegeben.
    parent["analyse_id"] = "ClusterLegacy-synthetic-second"
    chain.register_second_export(
        "coolant_pump", PART, first.paket_id, parent["analyse_id"],
    )
    parent["cluster"] = []
    parent["faelle"] = [{
        "fall_id": "F0001", "cluster_id": None,
        "ntf_bewertung": "NTF fraglich", "prioritaet": "P2",
        "verursachungsbereich": "Nicht zuordenbar",
        "sicherheit_bewertung": "Niedrig",
        "fehlerbilder": [{
            "kategorie": "Unbekannt", "nachweisstatus": "Werkstattangabe",
            "sicherheit": "Niedrig",
        }],
        "nachweisprofil": ["Datenlage unzureichend"],
    }]
    parent["cluster_abdeckung"] = None  # Alter LLM2-Vertrag
    parent_file = tmp_path / "alte-zweite.json"
    parent_file.write_text(json.dumps(parent), encoding="utf-8")
    imported = importer.import_file(parent_file)
    assert imported["faelle"] == 1
    assert chain.record_import(imported["analyse_id"], round_number=2)

    revision = json.loads(json.dumps(parent))
    revision["analyse_id_vorher"] = parent["analyse_id"]
    revision["analyse_id"] = "ClusterTS-synthetic-revision-01"
    revision["cluster_abdeckung"] = "T_S_v1"
    revision["cluster"] = [{
        "cluster_id": "S11", "ebene": "S",
        "titel": "Meldebild unklar / Datenlage unzureichend",
        "fall_ids": ["F0001"],
        "technische_hypothese": "Kein technischer Pumpendefekt bewiesen",
        "sicherheit": "Niedrig",
        "cluster_typ": "Symptom / Datenlage",
        "abgrenzung": "Keine gemeinsamen technischen Ursachen belegt",
    }]
    revision["faelle"][0]["cluster_id"] = "S11"
    revision_file = tmp_path / "ts-zweite.json"

    def save():
        revision_file.write_text(
            json.dumps(revision, ensure_ascii=False), encoding="utf-8",
        )

    save()
    assert chain.is_authorized_second_result(
        "coolant_pump", PART, first.paket_id,
        revision["analyse_id"], parent["analyse_id"],
    )
    assert not chain.is_authorized_second_result(
        "coolant_pump", "FREMDE-SACHNUMMER", first.paket_id,
        revision["analyse_id"], parent["analyse_id"],
    )
    # NTF- und Verursacherbewertung dürfen nicht mit der S-Gruppe umgedeutet werden.
    revision["faelle"][0]["ntf_bewertung"] = "Kein reiner NTF"
    save()
    with pytest.raises(ValueError, match="NTF-/Verursacher-/Wiederkehrwert"):
        importer.import_file(revision_file)
    revision["faelle"][0]["ntf_bewertung"] = parent["faelle"][0]["ntf_bewertung"]

    revision["cluster"][0]["ebene"] = "T"
    save()
    with pytest.raises(ValueError, match="Kennung und Ebene"):
        importer.import_file(revision_file)
    revision["cluster"][0]["ebene"] = "S"
    revision["faelle"][0]["cluster_id"] = None
    save()
    with pytest.raises(ValueError, match="Clusterzuordnung fehlt|nicht alle Fälle"):
        importer.import_file(revision_file)
    revision["faelle"][0]["cluster_id"] = "S11"

    save()
    imported_new = importer.import_file(revision_file)
    assert imported_new["faelle"] == 1
    assert imported_new["cluster"] == 1
    assert chain.record_import(imported_new["analyse_id"], round_number=2)
    assert importer.import_file(revision_file)["bereits_importiert"]
    assert importer.latest_for_case(CASE_ID)["cluster_id"] == "S11"
    with source.store.connect() as con:
        assert con.execute(
            "SELECT COUNT(*) FROM chatgpt_imports WHERE paket_id=?",
            [first.paket_id],
        ).fetchone()[0] == 2
        assert con.execute(
            "SELECT cluster_id FROM chatgpt_fallanalysen "
            "WHERE analyse_id=?",
            [parent["analyse_id"]],
        ).fetchone()[0] is None
        assert con.execute(
            "SELECT COUNT(*) FROM workflow_ai_rounds "
            "WHERE paket_id=? AND round_number=2",
            [first.paket_id],
        ).fetchone()[0] == 2
