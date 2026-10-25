"""LLM2: fehlende QT-Vergleiche und zweistufige Clustermethodik absichern."""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from zipfile import ZipFile

import pytest
from pydantic import ValidationError

from ntf_insight.reporting.chatgpt_exchange import ChatGPTRueckgabe
from ntf_insight.reporting.cluster_context_package import export_cluster_context
from ntf_insight.reporting.cluster_technical_data import _csv_safe
from ntf_insight.reporting.quicktest_swap_timing import (
    classify_quicktest_swap_timing,
)
from test_cluster_technical_export import PART, _create_test_data, _first
from test_ki_analysepaket import FIN


def test_same_day_quicktest_below_swap_km_is_plausible_not_proven_before():
    qt = datetime(2024, 1, 5, 9, 52, 1)
    swap = datetime(2024, 1, 5, 12, 0)
    result = classify_quicktest_swap_timing(
        qt, 15808, swap, 15890, verified_swap=True,
    )
    assert result.phase == "zeitlich_unklar_gleicher_tag"
    assert result.days == 0
    assert result.km_difference == -82
    assert result.hint == "gleicher_tag_qt_km_kleiner"
    assert "Indiz" in result.rule and "NICHT bewiesen" in result.rule
    assert _csv_safe(result.km_difference) == "-82"
    assert _csv_safe(0) == "0"
    assert _csv_safe("-HYPERLINK('bad')").startswith("'")


@pytest.mark.parametrize(
    ("offset_days", "qt_km", "expected_phase", "expected_hint"),
    [
        (-1, 15808, "vor_tausch", "datum_vor_tausch"),
        (1, 15900, "nach_tausch", "datum_nach_tausch"),
        (0, 15900, "zeitlich_unklar_gleicher_tag",
         "gleicher_tag_qt_km_groesser"),
        (0, 15890, "zeitlich_unklar_gleicher_tag",
         "gleicher_tag_qt_km_gleich"),
        (0, None, "zeitlich_unklar_gleicher_tag",
         "gleicher_tag_km_vergleich_fehlt"),
        (-1, 15900, "vor_tausch", "datum_vor_tausch_km_widerspruch"),
    ],
)
def test_quicktest_swap_timing_remains_auditable(
    offset_days, qt_km, expected_phase, expected_hint,
):
    from datetime import timedelta

    swap = datetime(2024, 1, 5)
    result = classify_quicktest_swap_timing(
        swap + timedelta(days=offset_days), qt_km,
        swap, 15890, verified_swap=True,
    )
    assert result.phase == expected_phase
    assert result.hint == expected_hint
    if offset_days == 0:
        assert result.days == 0
    if "widerspruch" in expected_hint:
        assert "Widerspruch" in result.rule


def test_unknown_swap_not_silently_classified():
    result = classify_quicktest_swap_timing(
        datetime(2024, 1, 5), 100, datetime(2024, 1, 5),
        200, verified_swap=False,
    )
    assert result.phase == "tauschdatum_nicht_belegt"
    assert result.km_difference is None


def test_new_multilabel_contract_and_legacy_json_are_compatible():
    base = {
        "format": "ntf-insight-chatgpt-rueckgabe",
        "schema_version": 1,
        "paket_id": "a" * 32,
        "analyse_id": "LLM-Second-Test",
        "faelle": [{"fall_id": "F0001", "ntf_bewertung": "NTF fraglich"}],
    }
    old = ChatGPTRueckgabe.model_validate(base)
    assert old.faelle[0].fehlerbilder == []
    assert old.faelle[0].nachweisprofil == []

    extended = {
        **base,
        "faelle": [{
            **base["faelle"][0],
            "fehlerbilder": [
                {
                    "kategorie": "Stromaufnahme zu hoch",
                    "nachweisstatus": "Werkstattangabe",
                    "sicherheit": "Niedrig",
                    "begruendung": "Werkstattmeldung, keine Messkurve",
                },
                {
                    "kategorie": "Kurzschluss / Sicherung",
                    "nachweisstatus": "Diagnostisch belegt",
                    "sicherheit": "Mittel",
                    "begruendung": "Gesicherter DTC",
                },
            ],
            "nachweisprofil": [
                "Werkstattangabe vorhanden",
                "Diagnose am Tauschtag, km niedriger (Indiz)",
                "Labor nicht reproduziert",
            ],
        }],
    }
    parsed = ChatGPTRueckgabe.model_validate(extended)
    assert len(parsed.faelle[0].fehlerbilder) == 2
    assert len(parsed.faelle[0].nachweisprofil) == 3
    assert parsed.faelle[0].cluster_id is None
    invalid = json.loads(json.dumps(extended))
    invalid["faelle"][0]["fehlerbilder"][0]["kategorie"] = "Lieferant schuld"
    with pytest.raises(ValidationError):
        ChatGPTRueckgabe.model_validate(invalid)


def test_second_export_includes_same_day_qt_and_new_analysis_instructions(tmp_path):
    source, evidence, *_ = _create_test_data(tmp_path)
    # Exportlogik vertraut nur einem explizit am QEC-Rohfall verankerten
    # Tausch. Die im Test verwendeten Referenzen sind synthetisch.
    case = source.store.get_case("QEC-FALL-VERTRAULICH")
    assert case is not None
    case.source_ref = "raw:synthetic-qec-anchor"
    case.replacements[0].source_ref = case.source_ref
    source.store.save_case(case)
    same_day = datetime(2026, 1, 5, 9, 52)
    with source.store.connect() as con:
        con.execute(
            "INSERT INTO quicktest_reports VALUES (?,?,?,?,?,?,?,?,?,?)",
            ["QT-SAME-DAY", FIN, FIN, same_day, 11918,
             1, 0, "{}", "1" * 64, same_day],
        )
    first, first_json = _first(source, tmp_path / "first.zip")
    out = export_cluster_context(
        evidence, "coolant_pump", PART, first.path,
        tmp_path / "second.zip", include_originals=False,
        first_result=first_json,
    )
    with ZipFile(out.path) as archive:
        relevant = []
        manifest = json.loads(archive.read("cluster_kontext_manifest.json"))
        for part in manifest["diagnose_tabellen"][
            "diagnose/quicktest_fallbezug.csv"
        ]:
            relevant.extend(csv.DictReader(io.StringIO(
                archive.read(part["datei"]).decode("utf-8-sig")
            )))
        same = next(row for row in relevant if row["zeitindiz"] ==
                    "gleicher_tag_qt_km_kleiner")
        assert same["lage_zum_tausch"] == "zeitlich_unklar_gleicher_tag"
        assert same["qt_km"] == "11918"
        assert same["tausch_km"] == "12000"
        assert same["km_relativ_zum_tausch"] == "-82"
        assert same["tage_relativ_zum_tausch"] == "0"
        assert "NICHT bewiesen" in same["belegregel"]
        instructions = archive.read("CHATGPT_2_DURCHLAUF.txt").decode("utf-8")
        assert "FEHLERBILD" in instructions
        assert "NACHWEISPROFIL" in instructions
        assert "QUICKTEST AM TAUSCHTAG" in instructions
        assert "Auch Werkstattbeschreibungen" in instructions
        assert "cluster_id=null" in instructions
        assert archive.testzip() is None
