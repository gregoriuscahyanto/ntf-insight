"""T/S/H-Gesamtclusterung: ZIP-Vertrag und regressionssicherer Import.

Nur synthetische Fahrzeuge/Fallpseudonyme, keine Nutzer-/QEC-Rohdaten.
"""
from __future__ import annotations

import json

import pytest

from ntf_insight.reporting.chatgpt_exchange import ChatGPTAnalyseStore
from test_llm2_ts_one_button import _prepared


def _hypothesis():
    return {
        "cluster_id": "H01",
        "ebene": "H",
        "titel": "Fehlende technische Zuordnung / Diagnose-Arbeitshypothese",
        "fall_ids": ["F0001"],
        "technische_hypothese": (
            "Nur ein synthetischer Prozess-/Datenlueckenzusammenhang; "
            "keine bewiesene Ursache"
        ),
        "sicherheit": "Niedrig",
        "hypothese_von": "ChatGPT",
        "hypothese_bestaetigt": False,
        "cluster_typ": "KI-Hypothese (unbestätigt)",
        "abgrenzung": "Keine echte Messung am Bauteil vorhanden",
        "empfohlene_pruefung": "Originalmesswerte nachfordern",
        "belege": [{
            "quelle": "technische_referenz",
            "quelle_id": "D00001",
            "fundstelle": "unterlagen/demo.txt/Zeile 1",
            "aussage": "Synthetischer Ausgangspunkt, keine bestätigte Ursache",
            "belegstatus": "Abgeleitet",
        }],
    }


def _finding(cluster: str = "H01"):
    return {
        "fall_id": "F0001",
        "cluster_id": cluster,
        "ntf_bewertung": "NTF fraglich",
        "prioritaet": "P2",
        "verursachungsbereich": "Nicht zuordenbar",
        "sicherheit_zuordnung": "Offen",
        "sicherheit_bewertung": "Niedrig",
        "fehlerbilder": [{
            "kategorie": "Unbekannt",
            "nachweisstatus": "Hypothese / unbestätigt",
        }],
        "nachweisprofil": ["Datenlage unzureichend"],
        "hypothese_von": "ChatGPT",
        "hypothese_bestaetigt": False,
    }


def _file(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def test_hypothesis_cluster_is_validated_and_imported_with_one_button(tmp_path):
    source, first, _second, chain, template, *_ = _prepared(tmp_path)
    importer = ChatGPTAnalyseStore(source.store)
    reply = dict(template)
    reply["cluster"] = [_hypothesis()]
    reply["faelle"] = [_finding()]
    path = tmp_path / "tsh-response.json"
    _file(path, reply)
    result = importer.import_file(path)
    assert result["cluster"] == 1 and result["faelle"] == 1
    assert chain.record_import(result["analyse_id"], round_number=2)

    with source.store.connect() as con:
        assert con.execute(
            "SELECT cluster_id FROM chatgpt_fallanalysen "
            "WHERE analyse_id=?",
            [reply["analyse_id"]],
        ).fetchone()[0] == "H01"

    # Die Versionierung und derselbe Button gelten auch fuer geaenderte
    # H-Hypothesen. Nie bestehende Ergebniszeilen ueberschreiben.
    changed = json.loads(json.dumps(reply))
    changed["analyse_id"] = "ClusterTSH-synthetic-Revision01"
    changed["analyse_id_vorher"] = reply["analyse_id"]
    assert chain.is_authorized_second_result(
        "coolant_pump", "A-EXAMPLE-001", first.paket_id,
        changed["analyse_id"], reply["analyse_id"],
    )
    _file(path, changed)
    newer = importer.import_file(path)
    assert newer["faelle"] == 1
    assert chain.record_import(newer["analyse_id"], round_number=2)
    with source.store.connect() as con:
        assert con.execute(
            "SELECT COUNT(*) FROM chatgpt_imports WHERE paket_id=?",
            [first.paket_id],
        ).fetchone()[0] == 2


def test_hypothesis_must_be_unconfirmed_and_source_based(tmp_path):
    source, _first, _second, _chain, template, *_ = _prepared(tmp_path)
    importer = ChatGPTAnalyseStore(source.store)
    reply = dict(template)
    reply["cluster"] = [_hypothesis()]
    reply["faelle"] = [_finding()]
    path = tmp_path / "hypothese.json"
    reply["cluster"][0]["hypothese_bestaetigt"] = True
    _file(path, reply)
    with pytest.raises(ValueError, match="H-Cluster"):
        importer.import_file(path)
    reply["cluster"][0]["hypothese_bestaetigt"] = False
    reply["faelle"][0]["hypothese_von"] = None
    _file(path, reply)
    with pytest.raises(ValueError, match="H-Fall"):
        importer.import_file(path)
    reply["faelle"][0]["hypothese_von"] = "ChatGPT"
    reply["cluster"][0]["belege"] = []
    _file(path, reply)
    with pytest.raises(ValueError, match="H-Cluster"):
        importer.import_file(path)


def test_reclassification_never_demotes_previous_technical_cluster(tmp_path):
    source, _first, second, chain, template, *_ = _prepared(tmp_path)
    importer = ChatGPTAnalyseStore(source.store)
    parent = dict(template)
    tech = {
        "cluster_id": "T01", "ebene": "T", "titel": "Elektrisches Messmuster",
        "fall_ids": ["F0001"], "sicherheit": "Niedrig",
        "belege": [{
            "quelle": "technische_referenz", "quelle_id": "D00001",
            "fundstelle": "unterlagen/messung.csv/Zeile 1",
            "aussage": "Synthetischer technischer Messwert",
            "belegstatus": "Originalbefund",
        }],
    }
    parent["cluster"] = [tech]
    parent["faelle"] = [{
        **_finding("T01"), "hypothese_von": None,
        "hypothese_bestaetigt": None,
    }]
    p = tmp_path / "t-vorher.json"
    _file(p, parent)
    imported = importer.import_file(p)
    assert imported["analyse_id"] == second.analysis_id
    assert chain.record_import(imported["analyse_id"], round_number=2)
    new = json.loads(json.dumps(parent))
    new["analyse_id"] = "ClusterTSH-synthetic-NoDemotion"
    new["analyse_id_vorher"] = parent["analyse_id"]
    new["cluster"] = [_hypothesis()]
    new["faelle"] = [_finding()]
    _file(p, new)
    with pytest.raises(ValueError, match="technische T-Gruppen"):
        importer.import_file(p)
    with source.store.connect() as con:
        assert con.execute(
            "SELECT COUNT(*) FROM chatgpt_imports WHERE paket_id=?",
            [parent["paket_id"]],
        ).fetchone()[0] == 1


def test_new_tsh_prefix_does_not_allow_missing_cluster_abdeckung(tmp_path):
    source, _first, _second, _chain, template, *_ = _prepared(tmp_path)
    importer = ChatGPTAnalyseStore(source.store)
    candidate = dict(template)
    candidate["cluster"] = [_hypothesis()]
    candidate["faelle"] = [_finding()]
    candidate.pop("cluster_abdeckung")
    path = _file(tmp_path / "missing-contract.json", candidate)
    with pytest.raises(ValueError, match="cluster_abdeckung=T_S_H_v1"):
        importer.import_file(path)
