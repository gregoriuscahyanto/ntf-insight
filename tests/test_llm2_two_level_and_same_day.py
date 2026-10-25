"""Regressionen: taggleiche QEC-QuickTests und mehrdimensionale LLM2-Auswertung."""
from __future__ import annotations

import json
from datetime import datetime
from zipfile import ZipFile

import pytest
from pydantic import ValidationError

from ntf_insight.analysis.quicktest_swap_relation import compare_quicktest_to_swap
from ntf_insight.reporting.chatgpt_exchange import ChatGPTRueckgabe
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
        assert "fehlerbilder" in schema["$defs"]["ChatGPTFall"]["properties"]
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
