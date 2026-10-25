"""Regressionen: taggleiche QEC-QuickTests und mehrdimensionale LLM2-Auswertung."""
from __future__ import annotations

import json
from datetime import datetime
from zipfile import ZipFile

import pytest
from pydantic import ValidationError

from ntf_insight.analysis.quicktest_swap_relation import compare_quicktest_to_swap
from ntf_insight.reporting.chatgpt_exchange import (
    ChatGPTAnalyseStore, ChatGPTRueckgabe, ergebnis_schema,
)
from ntf_insight.reporting.cluster_context_package import export_cluster_context
from test_cluster_technical_export import CASE_ID, PART, _create_test_data, _csv, _first


def test_same_day_qt_is_a_possible_before_swap_evidence_not_false_absence():
    swap = datetime(2024, 1, 5, 0, 0)
    for clock in [(9, 52, 1), (10, 24, 12)]:
        qt = datetime(2024, 1, 5, *clock)
        relation = compare_quicktest_to_swap(qt, 15808, swap, 15890)
        assert relation.phase == "gleicher_tag_km_vor_tausch_indiz"
        assert relation.days == 0
        assert relation.km_difference == -82
        assert relation.confidence == "Kilometer-Indiz"
        assert "NICHT sicher" in relation.explanation


@pytest.mark.parametrize(
    ("day_shift", "qt_km", "swap_km", "phase"),
    [
        (-1, 990, 1000, "vor_tausch"),
        (1, 1010, 1000, "nach_tausch"),
        (0, 1020, 1000, "gleicher_tag_km_nach_tausch_indiz"),
        (0, 1000, 1000, "zeitlich_unklar_gleicher_tag"),
        (0, None, 1000, "zeitlich_unklar_gleicher_tag"),
        (-1, 1010, 1000, "datum_km_widerspruch"),
        (1, 990, 1000, "datum_km_widerspruch"),
    ],
)
def test_quicktest_date_and_km_are_both_considered(
    day_shift, qt_km, swap_km, phase,
):
    from datetime import timedelta
    swap = datetime(2026, 4, 8, 0)
    checked = swap + timedelta(days=day_shift, hours=9)
    result = compare_quicktest_to_swap(checked, qt_km, swap, swap_km)
    assert result.phase == phase


def test_second_package_preserves_same_day_qt_and_km_detail(tmp_path):
    """Vollstaendiger, pseudonymisierter ZIP-Test mit zwei taggleichen QT."""
    source, evidence, *_ = _create_test_data(tmp_path)
    case = source.store.get_case(CASE_ID)
    assert case is not None
    # Ein von der QEC-Rohquelle bestaetigter Tauschanker, kein FIN-Raten.
    case.source_ref = "raw:synthetic-qec"
    case.replacements[0].source_ref = "raw:synthetic-qec"
    source.store.save_case(case)
    same_date = datetime(2026, 1, 5, 9, 52, 1)
    with source.store.connect() as con:
        con.executemany(
            "INSERT INTO quicktest_reports VALUES (?,?,?,?,?,?,?,?,?,?)",
            [
                ("QTSAME1", case.vin, case.vin, same_date, 11918, 1, 1,
                 "{}", "d" * 64, same_date),
                ("QTSAME2", case.vin, case.vin,
                 datetime(2026, 1, 5, 10, 24, 12), 11918, 1, 1,
                 "{}", "e" * 64, same_date),
            ],
        )
    first, result = _first(source, tmp_path / "first.zip")
    exported = export_cluster_context(
        evidence, "coolant_pump", PART, first.path,
        tmp_path / "second.zip", include_originals=False,
        first_result=result,
    )
    with ZipFile(exported.path) as archive:
        relation = _csv(archive, "diagnose/quicktest_fallbezug.csv")
        close = [row for row in relation
                 if row["lage_zum_tausch"] == "gleicher_tag_km_vor_tausch_indiz"]
        assert len(close) == 2
        assert {row["km_quicktest"] for row in close} == {"11918"}
        assert {row["km_tausch"] for row in close} == {"12000"}
        assert {row["km_differenz_zum_tausch"] for row in close} == {"-82"}
        assert {row["zeitliche_sicherheit"] for row in close} == {
            "Kilometer-Indiz",
        }
        assert not any(row["lage_zum_tausch"] == "zeitlich_unklar_gleicher_tag"
                       for row in close)
        prompt = archive.read("CHATGPT_2_DURCHLAUF.txt").decode("utf-8")
        assert "QUICKTESTS AM TAUSCHTAG" in prompt
        assert "mehrere Fehlerbild-Kategorien" in prompt
        assert "fehlerbilder[]" in prompt
        schema = json.loads(archive.read("chatgpt_ergebnis_schema.json"))
        assert schema == ergebnis_schema()
        assert "fehlerbilder" in schema["$defs"]["ChatGPTFall"]["properties"]
        assert "nachweisprofil" in schema["$defs"]["ChatGPTFall"]["properties"]
        assert "fehlerwiederkehr" in schema["$defs"]["ChatGPTFall"]["properties"]
        assert "fehlerbild_methodik" in schema["properties"]
        assert schema["$defs"]["LLMFehlerbild"]["additionalProperties"] is False
        template = json.loads(archive.read("chatgpt_ergebnis_vorlage.json"))
        assert template["fehlerbild_methodik"] == "multilabel_symptom_nachweis_v2"
        manifest = json.loads(archive.read("cluster_kontext_manifest.json"))
        assert manifest["fehlerbild_methodik"] == "multilabel_symptom_nachweis_v2"


def test_multilabel_fields_are_optional_in_old_json_and_strict_in_new():
    legacy = ChatGPTRueckgabe.model_validate({
        "paket_id": "a" * 32, "analyse_id": "Cluster-Old-01",
        "faelle": [{"fall_id": "F0001", "ntf_bewertung": "NTF fraglich"}],
    })
    assert legacy.faelle[0].fehlerbilder == []
    assert legacy.faelle[0].nachweisprofil == []

    payload = legacy.model_dump(mode="json")
    payload["faelle"][0]["fehlerbilder"] = [
        {
            "kategorie": "Kurzschluss / Sicherung",
            "nachweisstatus": "Werkstattangabe",
            "sicherheit": "Niedrig",
            "begruendung": "Nur als Beanstandung berichtet.",
        },
        {
            "kategorie": "Bus / Kommunikation",
            "nachweisstatus": "Diagnostisch belegt",
            "sicherheit": "Mittel",
            "begruendung": "Originaler DTC im QEC-Kontext.",
        },
    ]
    payload["faelle"][0]["nachweisprofil"] = [
        "Werkstattangabe vorhanden",
        "Diagnose am Tauschtag (km-Indiz vor)",
        "Laborfehler nicht reproduziert",
    ]
    result = ChatGPTRueckgabe.model_validate(payload)
    assert len(result.faelle[0].fehlerbilder) == 2
    assert result.faelle[0].cluster_id is None  # multimodal != Kausalcluster
    assert len(result.faelle[0].nachweisprofil) == 3

    payload["faelle"][0]["fehlerbilder"][0]["kategorie"] = "Lieferant schuld"
    with pytest.raises(ValidationError):
        ChatGPTRueckgabe.model_validate(payload)



def test_csv_injection_protection_preserves_real_negative_measurements():
    from ntf_insight.reporting.cluster_technical_data import _csv_safe

    assert _csv_safe("-82") == "-82"
    assert _csv_safe("-1.25") == "-1.25"
    assert _csv_safe("-A1") == "'-A1"
    assert _csv_safe("=HYPERLINK(1,2)") == "'=HYPERLINK(1,2)"
    assert _csv_safe("+A1") == "'+A1"


def test_qec_field_display_label_must_match_original_zip(tmp_path):
    """Beschriftete Belege sind nur bei exaktem Original-Label zulaessig."""
    source, evidence, *_ = _create_test_data(tmp_path)
    first, result = _first(
        source, tmp_path / "first-labeled.zip", mit_freitext=True,
    )
    with ZipFile(first.path) as archive:
        fields = _csv(archive, "qec_felder.csv")
    row = next(
        item for item in fields
        if item["original_beschriftung_opt_in"]
        and item["fundstelle"].startswith("QEC/")
    )
    alias = row["qec_bericht_id"]
    location = row["fundstelle"]
    label = row["original_beschriftung_opt_in"]
    importer = ChatGPTAnalyseStore(source.store)

    importer._verify_qec_field_locations(
        first.paket_id,
        {(alias, location), (alias, f"{location} [{label}]")},
    )
    with pytest.raises(ValueError, match="nicht im exportierten Original"):
        importer._verify_qec_field_locations(
            first.paket_id, {(alias, f"{location} [frei erfunden]")},
        )
    with pytest.raises(ValueError, match="nicht im exportierten Original"):
        importer._verify_qec_field_locations(
            first.paket_id, {("Q99999", f"{location} [{label}]")},
        )
    with pytest.raises(ValueError, match="nicht im exportierten Original"):
        importer._verify_qec_field_locations(
            first.paket_id, {(alias, f"{location}/feld:999 [{label}]")},
        )



def test_legacy_detail_json_imports_without_editing_file(tmp_path):
    """Die bisherige Detail-JSON wird nur appintern kanonisiert.

    Originaltext bleibt gespeichert; auch Nachweisprofil-Belege werden geprueft.
    Keine echten Kunden- oder Produktionsdaten in den Testdaten.
    """
    source, evidence, *_ = _create_test_data(tmp_path)
    first, first_result = _first(
        source, tmp_path / "first-legacy.zip", mit_freitext=True,
    )
    with ZipFile(first.path) as archive:
        row = next(
            item for item in _csv(archive, "qec_felder.csv")
            if item["original_beschriftung_opt_in"]
        )
        case_info = _csv(archive, "faelle.csv")[0]
    proof = {
        "quelle": "qec_felder",
        "quelle_id": row["qec_bericht_id"],
        "fundstelle": (
            f"{row['fundstelle']} [{row['original_beschriftung_opt_in']}]"
        ),
        "aussage": "Synthetische QEC-Fundstelle.",
        "belegstatus": "Originalbefund",
    }
    answer = dict(first_result)
    answer["analyse_id"] = "Cluster-Synthetic-Legacy-Detail"
    answer["fehlerbild_methodik"] = "multilabel_symptom_nachweis_v2"
    answer["erklaerung_zusatzfelder"] = "Altes Detailformat."
    answer["faelle"][0].update({
        "fahrzeug_id": case_info["fahrzeug_id"],
        "qec_bericht_id": row["qec_bericht_id"],
        "baureihe": "214",
        "sachnummer_pseudonym": "A-EXAMPLE-001",
        "tausch_monat": "2026-01",
        "tausch_km": 12000,
        "cluster_alt": None,
        "ntf_bewertung_alt": "NTF fraglich",
        "aenderung_gegenueber_erstlauf": "Neue Diagnosequelle",
        "fehlerbilder": [
            {
                "kategorie": "Bus/Kommunikation",
                "nachweisstatus": "Werkstattangabe",
                "sicherheit": "Niedrig",
                "begruendung": "Nur Werkstattbehauptung.",
                "belege": [proof],
            },
            {
                "kategorie": "Bus/Kommunikation",
                "nachweisstatus": "Diagnosehinweis",
                "sicherheit": "Mittel",
                "begruendung": "Diagnoseereignis, kein Kausalbeweis.",
                "belege": [proof],
            },
        ],
        "nachweisprofil": [{
            "quelle": "QEC-Lieferantenbericht (Erstrunde)",
            "nachweisstatus": "Optischer Sichtbefund NOK",
            "sicherheit": "Mittel",
            "begruendung": "Synthetischer Befund.",
            "belege": [proof],
        }],
        "fehlerwiederkehr": "Nicht beurteilbar",
        "begruendung_fehlerwiederkehr": "Kein echter Nachtest.",
        "qt_anzahl": 2,
        "qt_zeitkategorien": {"vor_tausch": 1, "nach_tausch": 1},
        "vortausch_dtc_codes": "P26F100/CPC3",
        "vortausch_ecu_versionen": [],
        "datumsbezogen_vor_tausch_qt": 1,
        "gleicher_tag_km_vor_tausch_indiz_qt": 0,
        "dato_km_widerspruch_qt": 0,
        "nach_tausch_neuer_ereigniskm_dtc": 0,
        "fall_duplikat_pruefen": [],
    })
    path = tmp_path / "legacy-llm2.json"
    importer = ChatGPTAnalyseStore(source.store)
    answer["faelle"][0]["nicht_erlaubt"] = "keine unkontrollierten Extras"
    path.write_text(json.dumps(answer), encoding="utf-8")
    with pytest.raises(ValueError, match="Unbekannte LLM2-Zusatzfelder"):
        importer.import_file(path)
    del answer["faelle"][0]["nicht_erlaubt"]

    answer["faelle"][0]["nachweisprofil"][0]["belege"][0] = {
        **proof, "fundstelle": f"{row['fundstelle']} [erfundene Beschriftung]",
    }
    path.write_text(json.dumps(answer), encoding="utf-8")
    with pytest.raises(ValueError, match="nicht im exportierten Original"):
        importer.import_file(path)
    answer["faelle"][0]["nachweisprofil"][0]["belege"][0] = proof
    path.write_text(json.dumps(answer), encoding="utf-8")
    original = path.read_bytes()

    result = importer.import_file(path)
    assert result["faelle"] == 1
    assert path.read_bytes() == original
    finding = importer.latest_for_case(CASE_ID)["bewertung"]
    assert len(finding["fehlerbilder"]) == 1
    assert finding["fehlerbilder"][0]["kategorie"] == "Bus / Kommunikation"
    # Zwei Statusbehauptungen mit derselben Fundstelle sind noch keine
    # voneinander unabhaengigen Mehrfachbelege.
    assert finding["fehlerbilder"][0]["nachweisstatus"] == (
        "Hypothese / unbestätigt"
    )
    assert finding["nachweisprofil"] == ["Laborbefund optisch auffällig"]
    assert any(e["fundstelle"] == proof["fundstelle"] for e in finding["belege"])
    with source.store.connect() as con:
        archived = con.execute(
            "SELECT payload_json FROM chatgpt_imports WHERE analyse_id=?",
            [answer["analyse_id"]],
        ).fetchone()[0]
    assert archived == original.decode("utf-8")
