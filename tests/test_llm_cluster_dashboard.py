"""Regressionen: visualisierte LLM2-Cluster je Sachnummer statt LLM1-Labels."""
from __future__ import annotations

import json
from types import SimpleNamespace

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from ntf_insight.analysis.llm_cluster_overview import (
    build_llm_cluster_overview, evidence_lines,
)
from ntf_insight.app.widgets.llm_cluster_charts import LlmClusterBarChart
from test_workflow_page import _window


def _examples():
    clusters = [
        {
            "cluster_id": "C01", "titel": "Versorgungsunterbrechung",
            "fall_ids": ["F0001", "F0002"],
            "technische_hypothese": "Spannungseinbruch im Fahrzeugnetz",
            "sicherheit": "Mittel",
            "belege": [{
                "quelle": "technische_referenz",
                "quelle_id": "AE0001",
                "fundstelle": "diagnose/dtc_beobachtungen.csv/Zeile 17",
                "aussage": "Versorgungs-DTC",
                "belegstatus": "Originalbefund",
            }],
        },
        {
            "cluster_id": "C02", "titel": "Mechanisches Verhalten",
            "fall_ids": ["F0003"],
            "technische_hypothese": "Montageumfeld offen",
            "sicherheit": "Niedrig", "belege": [],
        },
        {
            "cluster_id": "C-FREMD", "titel": "Fremde Sachnummer",
            "fall_ids": ["F0099"], "technische_hypothese": "Darf nicht erscheinen",
        },
    ]
    def finding(case, pseudo, cluster, cause, confidence="Plausibel"):
        return (
            case, cluster,
            json.dumps({
                "fall_id": pseudo, "cluster_id": cluster,
                "ntf_bewertung": "NTF fraglich",
                "verursachungsbereich": cause,
                "sicherheit_zuordnung": confidence,
                "ursachenhypothese": "Möglicher Zusammenhang",
                "begruendung_zuordnung": "DTC-Muster kontrollieren",
                "fehlerwiederkehr": "Hinweise auf Wiederkehr",
                "begruendung_fehlerwiederkehr": "DTC nach dem Tausch",
                "belege": [],
                "fehlerbilder": (
                    [
                        {"kategorie": "Kurzschluss / Sicherung",
                         "nachweisstatus": "Werkstattangabe"},
                        {"kategorie": "Bus / Kommunikation",
                         "nachweisstatus": "Diagnostisch belegt"},
                    ] if case == "FALL-001" else
                    [{"kategorie": "Kurzschluss / Sicherung",
                      "nachweisstatus": "Werkstattangabe"}]
                    if case == "FALL-002" else
                    [{"kategorie": "Mechanik / Geräusch / Beschädigung",
                      "nachweisstatus": "Laborbefund"}]
                    if case == "FALL-003" else []
                ),
                "nachweisprofil": (
                    ["Werkstattangabe vorhanden", "Diagnose vor Tausch (Datum)"]
                    if case == "FALL-001" else
                    ["Werkstattangabe vorhanden"] if case == "FALL-002"
                    else ["Laborbefund optisch auffällig"] if case == "FALL-003"
                    else []
                ),
                "themen": (
                    ["Gleicher DTC nach Tausch: letzter Ereignis-km über Tauschstand"]
                    if case == "FALL-001" else []
                ),
            }),
            "Offen",
        )
    findings = [
        finding("FALL-001", "F0001", "C01", "Bordnetz / Versorgung"),
        finding("FALL-002", "F0002", "C01", "Bauteil / Lieferant", "Offen"),
        finding("FALL-003", "F0003", "C02", "Montage"),
        finding("FALL-004", "F0004", None, "Nicht zuordenbar", "Offen"),
        finding("FREMD-005", "F0099", "C-FREMD", "Lieferant"),
    ]
    scoped = {
        f"FALL-{i:03d}": {
            "case_id": f"FALL-{i:03d}",
            "fin": f"WDD1234567890{i:04d}", "part_number": "A 111",
        }
        for i in range(1, 5)
    }
    return clusters, findings, scoped


def test_overview_uses_only_current_project_and_does_not_infer_causality():
    clusters, findings, scoped = _examples()
    overview = build_llm_cluster_overview(clusters, findings, scoped)
    assert overview.total_cases == 4
    assert [(g.cluster_id, g.count) for g in overview.groups] == [
        ("C01", 2), ("C02", 1),
    ]
    assert overview.ungrouped == 1
    assert overview.supplier_hypotheses == 1
    assert overview.unknown_causes == 2
    assert overview.recurrence_signals == 4
    assert "FREMD-005" not in {case.case_id for case in overview.cases}
    assert overview.cases[0].recurrence == "Hinweise auf Wiederkehr"
    assert overview.structurally_classified == 3
    assert overview.legacy_without_symptom_fields == 1
    assert dict(overview.symptoms)["Kurzschluss / Sicherung"] == 2
    assert dict(overview.proof_profiles)["Werkstattangabe vorhanden"] == 2
    assert overview.causes[0][0] in {
        "Bauteil / Lieferant", "Bordnetz / Versorgung",
        "Montage", "Nicht zuordenbar",
    }
    assert "diagnose/dtc_beobachtungen.csv/Zeile 17" in evidence_lines(
        overview.groups[0].evidence,
    )
    assert "Keine konkreten Belege" in evidence_lines([])


def test_bars_render_and_emit_selection_with_keyboard(tmp_path):
    app = QApplication.instance() or QApplication([])
    chart = LlmClusterBarChart("Clustergrößen")
    try:
        chart.show()
        app.processEvents()
        chart.set_items([
            ("C01", "Versorgung", 10),
            ("C02", "Mechanik", 4),
        ])
        chart.resize(500, chart.sizeHint().height())
        got = []
        chart.selected.connect(got.append)
        assert chart.grab().width() == 500
        chart.setFocus()
        QTest.keyClick(chart, Qt.Key.Key_Down)
        assert got == ["C01"]
        QTest.keyClick(chart, Qt.Key.Key_Down)
        assert got[-1] == "C02"
        assert "Versorgung: 10 Fälle" in chart.accessibleDescription()
    finally:
        chart.close()
        app.processEvents()


def test_workflow_llm_dashboard_is_interactive_and_project_scoped(
    tmp_path, monkeypatch,
):
    app, window = _window(tmp_path, monkeypatch)
    try:
        page = window.pages["workflow"]
        clusters, findings, scoped = _examples()
        package_id = "a" * 32
        analysis_id = "Cluster-Synthetic-02"
        with page.progress_store.store.connect() as con:
            con.execute(
                "INSERT INTO workflow_ai_rounds "
                "(paket_id,analyse_id,round_number) VALUES (?,?,2)",
                [package_id, analysis_id],
            )
            con.execute(
                "INSERT INTO chatgpt_imports VALUES (?,?,?,now(),?)",
                [analysis_id, package_id, "b" * 64, "{}"],
            )
            con.executemany(
                "INSERT INTO chatgpt_cluster VALUES (?,?,?)",
                [
                    (analysis_id, item["cluster_id"], json.dumps(item))
                    for item in clusters
                ],
            )
            con.executemany(
                "INSERT INTO chatgpt_fallanalysen "
                "(analyse_id,case_id,fall_pseudonym,cluster_id,"
                "payload_json,review_status) VALUES (?,?,?,?,?,?)",
                [
                    (analysis_id, case, json.loads(raw)["fall_id"],
                     cluster, raw, review)
                    for case, cluster, raw, review in findings
                ],
            )

        page.first_package = SimpleNamespace(
            paket_id=package_id, analysis_id="Analyse-Runde-1",
        )
        page._scoped_rows = list(scoped.values())
        page._refresh_chatgpt_cluster_view()
        assert page.llm_metric_labels["cases"].text() == "4"
        assert page.llm_metric_labels["clusters"].text() == "2"
        assert page.llm_metric_labels["ungrouped"].text() == "1"
        assert page.llm_metric_labels["supplier"].text() == "1"
        assert page.llm_metric_labels["recurrence"].text() == "4"
        assert page.chatgpt_cluster_model.rowCount() == 2
        assert page.chatgpt_case_model.rowCount() == 4
        assert len(page.llm_cluster_chart.items) == 3
        assert len(page.llm_symptom_chart.items) >= 3
        assert len(page.llm_proof_chart.items) >= 3

        page.llm_symptom_chart.selected.emit("Kurzschluss / Sicherung")
        assert page.llm_symptom_filter.currentData() == "Kurzschluss / Sicherung"
        assert page.chatgpt_case_proxy.rowCount() == 2
        page.llm_proof_chart.selected.emit("Diagnose vor Tausch (Datum)")
        assert page.chatgpt_case_proxy.rowCount() == 1
        page.llm_clear_filters.click()
        assert page.chatgpt_case_proxy.rowCount() == 4

        page.llm_cluster_chart.selected.emit("C01")
        assert page.llm_cluster_filter.currentData() == "C01"
        assert page.chatgpt_case_proxy.rowCount() == 2
        assert "Spannungseinbruch" in page.chatgpt_cluster_details.toPlainText()
        page.llm_cause_chart.selected.emit("Bauteil / Lieferant")
        assert page.chatgpt_case_proxy.rowCount() == 1
        page.llm_clear_filters.click()
        assert page.chatgpt_case_proxy.rowCount() == 4
        page.llm_cluster_filter.setCurrentIndex(
            page.llm_cluster_filter.findData("__nicht_gruppiert__")
        )
        assert page.chatgpt_case_proxy.rowCount() == 1

        # Projektwechsel MUSS das neue Paket verwenden. Globale
        # Ergebniszeilen der ersten Sachnummer duerfen nicht erscheinen.
        page._scoped_rows = [{
            "case_id": "FREMD-005", "fin": "WDD12345678909999",
            "part_number": "B 222",
        }]
        page.first_package = SimpleNamespace(
            paket_id="c" * 32, analysis_id=None,
        )
        page._refresh_chatgpt_cluster_view()
        assert page.chatgpt_case_model.rowCount() == 0
        assert not page.llm_symptom_chart.items
        # Ohne erstes Paket bleiben alle Altwerte ebenfalls leer.
        page.first_package = None
        page._refresh_chatgpt_cluster_view()
        assert page.chatgpt_case_model.rowCount() == 0
        assert page.llm_metric_labels["cases"].text() == "0"
        assert not page.llm_cluster_chart.items
        assert not page.llm_symptom_chart.items
        assert not page.llm_proof_chart.items
    finally:
        window.close()
        app.processEvents()



def test_cluster_chart_displays_all_22_t_and_s_groups_and_last_is_filterable(
    tmp_path, monkeypatch,
):
    """Keine stille Top-10-Begrenzung bei vollstaendiger T/S-Clusterung."""
    app, window = _window(tmp_path, monkeypatch)
    try:
        page = window.pages["workflow"]
        package_id = "d" * 32
        analysis_id = "ClusterTS-Test-All-22"
        clusters = []
        findings = []
        scoped = []

        # Acht technische T-Gruppen und 14 symptom-/datenbasierte S-Gruppen.
        ids = [
            *(f"T{n:02d}" for n in range(1, 9)),
            *(f"S{n:02d}" for n in range(11, 25)),
        ]
        for index, cluster_id in enumerate(ids, 1):
            case_id = f"QEC-TEST-{index:03d}"
            alias = f"F{index:04d}"
            clusters.append({
                "cluster_id": cluster_id,
                "titel": f"Synthetisches Muster {cluster_id}",
                "fall_ids": [alias],
                "sicherheit": "Niedrig",
                "technische_hypothese": "",
                "belege": [],
                "ebene": cluster_id[0],
            })
            findings.append((
                case_id, cluster_id, json.dumps({
                    "fall_id": alias,
                    "cluster_id": cluster_id,
                    "ntf_bewertung": "NTF fraglich",
                    "verursachungsbereich": "Nicht zuordenbar",
                    "sicherheit_zuordnung": "Offen",
                    "fehlerbilder": [{"kategorie": "Unbekannt",
                                      "nachweisstatus": "Werkstattangabe"}],
                    "nachweisprofil": ["Datenlage unzureichend"],
                }), "Offen",
            ))
            scoped.append({
                "case_id": case_id,
                "fin": f"WDD1234567890{index:04d}",
                "part_number": "A 111",
            })

        with page.progress_store.store.connect() as con:
            con.execute(
                "INSERT INTO workflow_ai_rounds "
                "(paket_id,analyse_id,round_number) VALUES (?,?,2)",
                [package_id, analysis_id],
            )
            con.execute(
                "INSERT INTO chatgpt_imports VALUES (?,?,?,now(),?)",
                [analysis_id, package_id, "e" * 64, "{}"],
            )
            con.executemany(
                "INSERT INTO chatgpt_cluster VALUES (?,?,?)",
                [(analysis_id, group["cluster_id"], json.dumps(group))
                 for group in clusters],
            )
            con.executemany(
                "INSERT INTO chatgpt_fallanalysen "
                "(analyse_id,case_id,fall_pseudonym,cluster_id,"
                "payload_json,review_status) VALUES (?,?,?,?,?,?)",
                [(analysis_id, case_id, json.loads(payload)["fall_id"],
                  cluster_id, payload, review)
                 for case_id, cluster_id, payload, review in findings],
            )

        page.first_package = SimpleNamespace(
            paket_id=package_id, analysis_id="Analyse-Runde-1",
        )
        page._scoped_rows = scoped
        page._refresh_chatgpt_cluster_view()

        items = page.llm_cluster_chart.items
        assert len(items) == 22
        assert {code for code, _title, _count in items} == set(ids)
        assert page.chatgpt_cluster_model.rowCount() == 22
        assert page.llm_cluster_chart.height() == (
            page.llm_cluster_chart.sizeHint().height()
        )
        assert page.chatgpt_cluster_scroll.isWidgetResizable()

        # Auch ein Cluster jenseits der frueheren Top 10 bleibt anwaehlbar.
        assert "T08" in [code for code, _title, _count in items[10:]]
        page.llm_cluster_chart.selected.emit("T08")
        assert page.llm_cluster_filter.currentData() == "T08"
        assert page.chatgpt_case_proxy.rowCount() == 1
    finally:
        window.close()
        app.processEvents()


def test_unclustered_and_legacy_answers_are_readable_without_fabricated_causes():
    from ntf_insight.reporting.chatgpt_exchange import ChatGPTRueckgabe

    _clusters, findings, scoped = _examples()
    no_clusters = [
        (case_id, None, json.dumps({
            **json.loads(payload), "cluster_id": None,
            "verursachungsbereich": "Nicht zuordenbar",
        }), review)
        for case_id, _cluster_id, payload, review in findings
    ]
    overview = build_llm_cluster_overview([], no_clusters, scoped)
    assert not overview.groups
    assert overview.ungrouped == 4
    assert overview.supplier_hypotheses == 0
    assert overview.unknown_causes == 4

    # Neue Angaben zur Fehlerwiederkehr sind optional, damit die bisherige
    # Runde-1-/Runde-2-JSON nach einem App-Update lesbar bleibt.
    data = ChatGPTRueckgabe.model_validate({
        "format": "ntf-insight-chatgpt-rueckgabe",
        "schema_version": 1,
        "paket_id": "a" * 32,
        "analyse_id": "Analyse-Old",
        "faelle": [{"fall_id": "F0001", "ntf_bewertung": "NTF fraglich"}],
    })
    assert data.faelle[0].fehlerwiederkehr == "Nicht beurteilbar"
    assert data.faelle[0].begruendung_fehlerwiederkehr == ""
    data = ChatGPTRueckgabe.model_validate({
        "format": "ntf-insight-chatgpt-rueckgabe",
        "schema_version": 1,
        "paket_id": "a" * 32,
        "analyse_id": "Analyse-Second",
        "faelle": [{
            "fall_id": "F0001",
            "fehlerwiederkehr": "Nach Tausch erneut nachgewiesen",
            "begruendung_fehlerwiederkehr": "QT vor und nach dem Tausch",
        }],
    })
    assert data.faelle[0].fehlerwiederkehr == "Nach Tausch erneut nachgewiesen"



def test_old_result_distinguishes_new_dtc_from_historical_memory():
    """Gleicher DTC nach Tausch ist nicht automatisch ein erneuter Fehler."""
    from ntf_insight.analysis.llm_cluster_overview import (
        _recurrence_for_display,
    )

    label, note, counted = _recurrence_for_display({
        "themen": [
            "Gleicher DTC nach Tausch: letzter Ereignis-km über Tauschstand",
        ],
    })
    assert counted and "LLM-Hinweis" in label
    assert "unbewiesen" in note

    label, note, counted = _recurrence_for_display({
        "themen": [
            "Gleicher Code nach Tausch gespeichert: Wiederauftreten unbewiesen",
        ],
    })
    assert not counted
    assert "nicht belegt" in label

    label, note, counted = _recurrence_for_display({
        "themen": [
            "Neuer Auftretens-km pumpenbezogener DTC nach Tausch",
        ],
    })
    assert not counted and "Vergleich offen" in label

    label, note, counted = _recurrence_for_display({})
    assert not counted and label == "Nicht strukturiert ausgewertet"

    # Explizite neue Struktur hat Vorrang vor alten Themenkennzeichen.
    label, note, counted = _recurrence_for_display({
        "fehlerwiederkehr": "Nicht beurteilbar",
        "themen": [
            "Gleicher DTC nach Tausch: letzter Ereignis-km über Tauschstand",
        ],
    })
    assert label == "Nicht beurteilbar" and not counted
