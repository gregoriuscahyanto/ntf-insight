"""All-pump CPC3 SW table: synthetic cases, no real FIN or OEM SW data."""
from __future__ import annotations

import os
from datetime import datetime, timedelta

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from openpyxl import load_workbook
from PySide6.QtWidgets import QApplication

from ntf_insight.analysis.cpc3_pump_overview import (
    build_cpc3_pump_overview, ecu_software_frequencies,
    evaluate_cpc3_pump_case, is_pump_case,
)
from ntf_insight.app.widgets.cpc3_pump_overview_panel import (
    CPC3PumpOverviewPanel,
)
from ntf_insight.domain.case import NTFCase
from ntf_insight.domain.events import (
    DiagnosticEvent, DiagnosticSession, ECUStateObservation,
    PartReplacement, SoftwareEvent,
)
from ntf_insight.domain.vehicle import Vehicle
from ntf_insight.reporting.cpc3_pump_excel import export_cpc3_pump_overview
from ntf_insight.ingestion.reference_source_parsers import iter_autoexport_rows
from ntf_insight.storage.duckdb_store import DuckDBStore
from ntf_insight.storage.source_knowledge_store import SourceKnowledgeStore


BASE = datetime(2026, 3, 1, 12)
FIN = "W1TTEST0000000001"


def _pump(
    number: int, *, vin: str = FIN, anchor: int | None = 7,
    before_sw: str = "SW-A", after_sw: str = "SW-B",
    update: int | None = None, update_action: str = "SW programmiert",
    after_codes: tuple[str, ...] = (),
    extra_post_codes: tuple[str, ...] = (),
    with_quicktests: bool = True,
    same_day_test: bool = False,
    component: str = "Coolant Pump",
) -> NTFCase:
    events = ()
    if anchor is not None:
        events = (PartReplacement(
            vin=vin, occurred_at=BASE + timedelta(days=anchor),
            time_precision="date", component_type=component,
        ),)
    states = [
        ECUStateObservation(
            vin=vin, ecu="CPC3", software_version=before_sw,
            occurred_at=BASE + timedelta(days=0),
            session_id="PRE-" + str(number),
        ),
        ECUStateObservation(
            vin=vin, ecu="CPC3", software_version=after_sw,
            occurred_at=BASE + timedelta(days=10),
            session_id="POST-" + str(number),
        ),
    ]
    sessions = []
    faults = []
    if with_quicktests:
        for name, day, codes in (
            ("PRE", 0, ("PUMP-1",)),
            ("POST", 10, after_codes),
            ("POST2", 18, extra_post_codes),
        ):
            session_id = f"{name}-{number}"
            sessions.append(DiagnosticSession(
                vin=vin, occurred_at=BASE + timedelta(days=day),
                session_id=session_id, source_is_complete_quicktest=True,
            ))
            # For a truly complete CPC3 0-DTC session, the ECU must exist
            # in the session even when there are no DiagnosticEvent rows.
            if name == "POST2":
                states.append(ECUStateObservation(
                    vin=vin, ecu="CPC3", occurred_at=BASE + timedelta(days=day),
                    software_version=after_sw, session_id=session_id,
                ))
            for code in codes:
                faults.append(DiagnosticEvent(
                    vin=vin, ecu="CPC3", dtc_code=code,
                    occurred_at=BASE + timedelta(days=day),
                    session_id=session_id,
                ))
        if same_day_test:
            sessions.append(DiagnosticSession(
                vin=vin, occurred_at=BASE + timedelta(days=anchor),
                session_id=f"SAME-{number}",
                source_is_complete_quicktest=True,
            ))
            states.append(ECUStateObservation(
                vin=vin, ecu="CPC3", software_version="SW-MIDDLE",
                occurred_at=BASE + timedelta(days=anchor),
                session_id=f"SAME-{number}",
                time_precision="date",
            ))
            faults.append(DiagnosticEvent(
                vin=vin, ecu="CPC3", dtc_code="PUMP-ON-SAME-DAY",
                session_id=f"SAME-{number}",
                occurred_at=BASE + timedelta(days=anchor),
            ))
    software_events = ()
    if update is not None:
        software_events = (SoftwareEvent(
            vin=vin, ecu="CPC3",
            occurred_at=BASE + timedelta(days=update),
            action=update_action, software_version=after_sw,
            source_ref="raw:synthetic#workshop-update",
        ),)
    return NTFCase(
        case_id=f"QEC-SYNTH-{number}",
        vehicle=Vehicle(vin=vin),
        component_type=component,
        component_profile_id="coolant_pump" if component == "Coolant Pump" else None,
        replacements=list(events), ecu_states=states,
        diagnostic_sessions=sessions, diagnostics=faults,
        software_events=list(software_events),
    )


def test_overview_keeps_multiple_qec_cases_per_fin_and_loads_source_once():
    first = _pump(1, anchor=7, update=7)
    second = _pump(2, anchor=25, update=None, after_sw="SW-A")
    other = _pump(3, vin="W1TTEST0000000002", anchor=None)
    loading = []

    def source(fin):
        loading.append(fin)
        return [], False

    report = build_cpc3_pump_overview(
        (second, first, other), load_autoexport=source,
    )
    assert report.total_pump_cases == 3
    assert report.unique_fins == 2
    assert len(loading) == 2
    assert {row.case_id for row in report.cases} == {
        "QEC-SYNTH-1", "QEC-SYNTH-2", "QEC-SYNTH-3",
    }
    assert report.documented_swap_day_updates == 1
    assert report.not_assessable >= 1


def test_documented_update_same_day_not_inferred_from_sw_version_only():
    actual = evaluate_cpc3_pump_case(_pump(1, update=7))
    assert actual.update_group == "documented_same_day"
    assert "am Tauschtag dokumentiert" in actual.update_status
    assert "SW-A" == actual.before_sw
    assert "SW-B" == actual.after_sw
    assert actual.update_events
    inferred = evaluate_cpc3_pump_case(_pump(2))
    assert inferred.update_group == "observed_change"
    assert "Updatezeit unbekannt" in inferred.update_status
    assert "dokumentiert" not in inferred.update_status


def test_same_sw_observed_is_not_claimed_as_no_update():
    row = evaluate_cpc3_pump_case(_pump(1, before_sw="SW-A", after_sw="SW-A"))
    assert row.update_group == "observed_same"
    assert "beobachtet" in row.update_status
    assert "kein Update" not in row.update_status.casefold()


def test_non_update_software_note_is_not_a_flash_document():
    row = evaluate_cpc3_pump_case(_pump(
        1, update=7, update_action="SW-Stand abgelesen",
    ))
    assert row.update_group == "observed_change"
    near = evaluate_cpc3_pump_case(_pump(2, update=10))
    assert near.update_group == "documented_nearby"
    too_far = evaluate_cpc3_pump_case(_pump(3, update=40))
    assert too_far.update_group == "observed_change"


def test_dtc_recurs_in_later_complete_qt_even_if_first_post_is_clear():
    row = evaluate_cpc3_pump_case(_pump(
        1, update=7, after_codes=(), extra_post_codes=("PUMP-1",),
        same_day_test=True,
    ))
    assert row.pre_complete_tests == 1
    assert row.post_complete_tests == 2
    assert row.returned_dtcs == ("PUMP-1",)
    assert "erneut" in row.dtc_status
    assert "keine SW-Lösung belegt" in row.sw_effect
    assert row.sw_pre_complete_tests == 1
    assert row.sw_post_complete_tests == 2
    assert row.sw_post_returned_dtcs == ("PUMP-1",)
    assert "PUMP-ON-SAME-DAY" not in row.post_cpc3_dtcs


def test_complete_cpc3_qt_without_post_dtc_is_observation_not_sw_cure():
    row = evaluate_cpc3_pump_case(_pump(
        1, update=7, after_codes=(), extra_post_codes=(),
    ))
    assert row.returned_dtcs == ()
    assert row.post_complete_tests == 2
    assert "nicht erneut" in row.dtc_status
    assert "nicht isolierbar" in row.sw_effect



def test_no_documented_update_is_not_counted_as_sw_cure():
    row = evaluate_cpc3_pump_case(_pump(
        1, update=None, after_codes=(), extra_post_codes=(),
    ))
    assert row.update_group == "observed_change"
    assert row.sw_pre_complete_tests == 0
    assert row.sw_post_complete_tests == 0
    assert "Updatedatum nicht dokumentiert" in row.sw_effect


def test_separate_software_intervention_has_observational_followup_only():
    row = evaluate_cpc3_pump_case(_pump(
        1, update=12, after_codes=("PUMP-1",),
        extra_post_codes=(),
    ))
    assert row.update_group == "documented_nearby"
    assert row.sw_pre_complete_tests == 2
    assert row.sw_post_complete_tests == 1
    assert row.sw_post_returned_dtcs == ()
    assert "zeitlicher Hinweis" in row.sw_effect
    assert "keine kausal bestätigte SW-Heilung" in row.sw_effect


def test_sw_intervention_and_pump_swap_in_same_diagnosis_window_confounded():
    row = evaluate_cpc3_pump_case(_pump(
        1, update=7, after_codes=(), extra_post_codes=(),
    ))
    assert "Pumpentausch im Messfenster" in row.sw_effect
    assert "nicht isolierbar" in row.sw_effect


def test_multiple_sw_updates_cannot_be_summarized_as_one_cure():
    case = _pump(1, update=7)
    case.software_events.append(SoftwareEvent(
        vin=FIN, ecu="CPC3", occurred_at=BASE + timedelta(days=8),
        software_version="SW-NEWER", action="SW geflasht",
    ))
    row = evaluate_cpc3_pump_case(case)
    assert "Mehrere SW-Maßnahmen" in row.sw_effect


def test_without_complete_quicktests_sw_effect_stays_unknown():
    row = evaluate_cpc3_pump_case(_pump(1, update=7, with_quicktests=False))
    assert row.pre_complete_tests == 0 and row.post_complete_tests == 0
    assert "nicht beurteilbar" in row.sw_effect
    assert "Vollständige" in row.dtc_status


def test_missing_swap_and_missing_sw_produce_explicit_data_gap():
    case = _pump(1, anchor=None, with_quicktests=False)
    case.ecu_states = []
    row = evaluate_cpc3_pump_case(case)
    assert row.update_group == "no_swap"
    assert row.swap_day is None
    assert row.before_sw is None and row.after_sw is None
    assert "nicht beurteilbar" in row.sw_effect
    assert "Pumpentauschdatum fehlt" in row.note


def test_non_pump_case_is_not_mixed_into_pump_population():
    battery = _pump(1, component="Battery")
    assert not is_pump_case(battery)
    assert build_cpc3_pump_overview([battery]).total_pump_cases == 0


def test_gui_search_filter_navigation_and_visible_excel(tmp_path):
    app = QApplication.instance() or QApplication([])
    first = _pump(1, update=7)
    second = _pump(2, update=None)
    report = build_cpc3_pump_overview([first, second])
    panel = CPC3PumpOverviewPanel([first, second], None)
    panel.show()
    app.processEvents()
    panel.set_report(report)
    assert panel.model.rowCount() == 2
    assert "2 Pumpenfälle" in panel.summary.text()
    assert panel.ecu_selector.currentText() == "CPC3"
    assert sum(n for _, n in panel.donut_pre.donut.entries) == 2
    assert sum(n for _, n in panel.donut_sw.donut.entries) == 2
    assert sum(n for _, n in panel.donut_post.donut.entries) == 2
    assert panel.sw_detail_model.rowCount() >= 1
    panel.update_filter.setCurrentIndex(
        panel.update_filter.findData("documented_same_day")
    )
    assert panel.proxy.rowCount() == 1
    assert sum(n for _, n in panel.donut_pre.donut.entries) == 1
    selected = []
    panel.case_requested.connect(selected.append)
    panel._open_case(panel.proxy.index(0, 0))
    assert selected == ["QEC-SYNTH-1"]
    filename = tmp_path / "cpc3-pumpen.xlsx"
    visible = tuple(
        panel.report.cases[
            panel.proxy.mapToSource(panel.proxy.index(i, 0)).row()
        ]
        for i in range(panel.proxy.rowCount())
    )
    assert export_cpc3_pump_overview(filename, visible) == 1
    wb = load_workbook(filename, read_only=True)
    try:
        ws = wb["ECU-Pumpenfälle"]
        assert ws.max_row == 2
        assert ws["A2"].value == "QEC-SYNTH-1"
        assert "Bewertungsregeln" in wb.sheetnames
        assert "SW-Messhistorie" in wb.sheetnames
        assert ws["AB2"].value == "CPC3"
        assert "SW-A" in ws["AC2"].value
    finally:
        wb.close()
    panel.search.setText("does-not-exist")
    assert panel.proxy.rowCount() == 0
    panel.search.clear()
    assert panel.proxy.rowCount() == 1
    panel.close()


def test_excel_escapes_untrusted_formula_like_software_event(tmp_path):
    case = _pump(
        1, update=7, update_action="=WEBSERVICE(1)",
        before_sw="=HYPERLINK(1)", after_sw="+CMD",
    )
    row = evaluate_cpc3_pump_case(case)
    path = tmp_path / "safe.xlsx"
    export_cpc3_pump_overview(path, (row,))
    wb = load_workbook(path)
    try:
        ws = wb["ECU-Pumpenfälle"]
        assert ws["E2"].data_type == "s"
        assert ws["E2"].value.startswith("'=")
        assert ws["F2"].data_type == "s"
        assert ws["F2"].value.startswith("'+")
    finally:
        wb.close()


def test_full_ecu_history_from_archived_csv_and_fast_ecu_switch(tmp_path):
    """Synthetic copy of AutoExport header, no customer VINs or OEM SW."""
    path = tmp_path / "synthetic-autoexport.csv"
    header = (
        "DiagStartDt;SourceSystemNm;EcuNm;EcuHwPartnumberCd;"
        "EcuSuppHwVersionTxt;EcuSwVersionTxt;KmReadingNum;"
        "EcuFaultNm;DiagStartTs;Fin;CntXDDiagnosisHeaderSid"
    )
    data = [
        ("2026-03-01", "CPC3", "22/36 000", "PUMP-1", "OLD"),
        ("2026-03-01", "CPC3", "22/36 000", "PUMP-2", "OLD"),
        ("2026-03-04", "CPC3", "23/38 000", "PUMP-3", "MID"),
        ("2026-03-15", "CPC3", "24/28 000", "PUMP-4", "NEW"),
        ("2026-03-25", "CPC3", "", "POST-NO-SW", "LATE"),
        ("2026-03-01", "MCM", "MCM-8", "MCM-FAULT", "MC1"),
    ]
    csv_rows = [
        ";".join((
            day, "XD", ecu, "000 901 23 45", "20/01 000",
            sw, "42000", dtc, "", FIN, reference,
        ))
        for day, ecu, sw, dtc, reference in data
    ]
    path.write_text(
        "\n".join([
            "Original query: synthetic",
            "Query Id: synthetic",
            "",
            header,
            *csv_rows,
            "",
        ]), encoding="utf-8",
    )
    store = SourceKnowledgeStore(DuckDBStore(tmp_path / "data.duckdb"))
    store.save_records(
        "a" * 64, "autoexport_rows", iter_autoexport_rows(path),
    )
    assert "CPC3" in store.autoexport_ecu_names()
    assert "MCM" in store.autoexport_ecu_names()
    rows, capped = store.ecu_software_rows_for_fins([FIN], "CPC3")[FIN]
    assert not capped
    assert len(rows) == 4  # two DTC lines are one ECU snapshot
    assert rows[0]["dtc_codes"] == ("PUMP-1", "PUMP-2")
    assert rows[-1]["software_version"] is None
    case = _pump(31, with_quicktests=False)
    case.ecu_states = []
    report = build_cpc3_pump_overview(
        [case], ecu="CPC3",
        load_ecu_history=store.ecu_software_rows_for_fins,
    )
    row = report.cases[0]
    assert row.ecu == "CPC3"
    assert row.sw_versions == ("22/36 000", "23/38 000", "24/28 000")
    assert len(row.sw_history) == 3
    assert row.before_sw == "23/38 000"
    assert row.after_sw == "24/28 000"
    assert row.pre_dtc_evidence == "present"
    assert row.post_dtc_evidence == "present"
    assert "POST-NO-SW" in row.post_dtc_observed
    assert row.post_complete_tests == 0
    mcm = build_cpc3_pump_overview(
        [case], ecu="MCM",
        load_ecu_history=store.ecu_software_rows_for_fins,
    ).cases[0]
    assert mcm.ecu == "MCM"
    assert mcm.sw_versions == ("MCM-8",)
    assert mcm.pre_dtc_observed == ("MCM-FAULT",)
    assert mcm.post_dtc_evidence == "unknown"


def test_autoexport_without_full_post_qt_never_counts_as_dtc_free():
    case = _pump(9, with_quicktests=False)
    case.ecu_states = []
    rows = [
        {
            "diag_date": "2026-03-01", "software_version": "SW-1",
            "dtc_codes": ("PUMP-1",), "source_ref": "raw:synthetic#row:1",
        },
        {
            "diag_date": "2026-03-15", "software_version": "SW-2",
            "dtc_codes": (), "source_ref": "raw:synthetic#row:2",
        },
    ]
    item = evaluate_cpc3_pump_case(case, autoexport_rows=rows)
    assert item.pre_dtc_evidence == "present"
    assert item.post_dtc_evidence == "unknown"
    assert item.returned_dtcs == ()
    assert "nicht beurteilbar" in item.sw_effect


def test_sw_frequency_counts_cases_not_csv_dtc_rows():
    cases = [
        _pump(i, with_quicktests=True, before_sw="SW-CASE-A")
        for i in range(50, 56)
    ]
    report = build_cpc3_pump_overview(cases)
    stats = ecu_software_frequencies(report.cases)
    assert len(stats) == 1
    assert stats[0].cases == 6
    assert stats[0].fins == 1  # 6 real cases can share one VIN
    assert stats[0].with_pre_dtc == 6
    assert stats[0].with_pre_complete_comparison == 6
    assert stats[0].recurrence_percent == 0.0
    assert ecu_software_frequencies(report.cases[:1])[0].recurrence_percent is None


def test_gui_renders_selected_other_ecu_sw_and_all_observations():
    app = QApplication.instance() or QApplication([])
    case = _pump(99, with_quicktests=False)
    case.ecu_states = [
        ECUStateObservation(
            vin=FIN, ecu="MCM", occurred_at=BASE,
            software_version="MCM-SW-1",
        ),
        ECUStateObservation(
            vin=FIN, ecu="MCM",
            occurred_at=BASE + timedelta(days=12),
            software_version="MCM-SW-2",
        ),
    ]
    report = build_cpc3_pump_overview([case], ecu="MCM")
    panel = CPC3PumpOverviewPanel([case], None)
    app.processEvents()
    panel.set_report(report)
    assert "MCM" in panel.heading.text()
    assert panel.model.rows[0][4] == "MCM"
    assert panel.model.rows[0][9] == "MCM-SW-1; MCM-SW-2"
    assert panel.sw_detail_model.rowCount() == 2
    assert sum(n for _, n in panel.donut_sw.donut.entries) == 1
    panel.close()


def test_sw_measured_on_pump_swap_day_is_visible_but_not_ordered(tmp_path):
    """Screenshot-like date-only QEC anchor + AutoExport 06:32 on that day."""
    case = _pump(321, with_quicktests=False)
    case.ecu_states = []
    diagnosis_day = (BASE + timedelta(days=7)).date().isoformat()
    observations = [
        {
            "source_ref": f"raw:synthetic-source-{index}#csv:{index}",
            "diag_timestamp": f"{diagnosis_day}T06:32:00",
            "diag_date": diagnosis_day,
            "software_version": "SW-SYNTH-42",
            "dtc_codes": ("SYNTH-FAULT",),
        }
        for index in (1, 2)
    ]
    row = evaluate_cpc3_pump_case(
        case, autoexport_rows=observations,
    )
    assert row.before_sw is None and row.after_sw is None
    assert row.sw_versions == ("SW-SYNTH-42",)
    assert row.swap_day_sw == ("SW-SYNTH-42",)
    assert len(row.swap_day_sources) == 2
    assert row.swap_context_sw == "SW-SYNTH-42"
    assert row.swap_context_kind == "on_day_only"
    assert row.update_group == "unknown"
    assert row.pre_dtc_evidence == "unknown"
    assert row.post_dtc_evidence == "unknown"
    assert "Tauschtag" in row.note
    assert len(row.sw_observations) == 2

    report = build_cpc3_pump_overview(
        [case], load_autoexport=lambda fin: (observations, False),
    )
    app = QApplication.instance() or QApplication([])
    panel = CPC3PumpOverviewPanel([case], None)
    panel.show()
    app.processEvents()
    panel.set_report(report)
    assert panel.model.rowCount() == 1
    assert panel.model.rows[0][5] == "Nicht vor Tausch belegt"
    assert panel.model.rows[0][6] == "Nicht nach Tausch belegt"
    assert panel.model.rows[0][7] == "SW-SYNTH-42"
    assert "Zeitfolge offen" in panel.model.rows[0][8]
    assert "SW am Tauschtag: 1" in panel.summary.text()
    assert panel.donut_time.donut.entries[1] == ("Nur am Tauschtag", 1)
    assert sum(value for _, value in panel.donut_sw.donut.entries) == 1
    assert panel.donut_sw.donut.entries[0] == (
        "SW-SYNTH-42 (Tauschtag)", 1,
    )
    panel.sw_time_filter.setCurrentIndex(
        panel.sw_time_filter.findData("on_day_only")
    )
    assert panel.proxy.rowCount() == 1
    panel.sw_time_filter.setCurrentIndex(
        panel.sw_time_filter.findData("before")
    )
    assert panel.proxy.rowCount() == 0
    panel.sw_time_filter.setCurrentIndex(0)

    filename = tmp_path / "all-sw-same-day.xlsx"
    export_cpc3_pump_overview(filename, report.cases)
    workbook = load_workbook(filename, read_only=True)
    try:
        sheet = workbook["ECU-Pumpenfälle"]
        fields = tuple(cell.value for cell in sheet[1])
        swap_sw_col = fields.index("SW-Beobachtungen am Tauschtag") + 1
        swap_kind_col = fields.index("SW-Zeitlage zum Pumpentausch") + 1
        assert sheet.cell(2, swap_sw_col).value == "SW-SYNTH-42"
        assert sheet.cell(2, swap_kind_col).value == "on_day_only"
        assert workbook["SW-Messhistorie"].max_row == 3
    finally:
        workbook.close()
    panel.close()


def test_sw_on_swap_day_conflicts_and_earlier_sw_remain_distinct():
    case = _pump(325, with_quicktests=False)
    case.ecu_states = []
    day = (BASE + timedelta(days=7)).date().isoformat()
    raw = [
        {
            "source_ref": "raw:synthetic#1",
            "diag_date": day,
            "software_version": "SW-1",
        },
        {
            "source_ref": "raw:synthetic#2",
            "diag_date": day,
            "software_version": "SW-2",
        },
    ]
    conflict = evaluate_cpc3_pump_case(case, autoexport_rows=raw)
    assert conflict.swap_day_sw == ("SW-1", "SW-2")
    assert conflict.swap_context_kind == "on_day_conflict"
    assert conflict.swap_context_sw is None
    assert conflict.before_sw is None
    assert conflict.after_sw is None

    raw.append({
        "source_ref": "raw:synthetic#3",
        "diag_date": (BASE + timedelta(days=3)).date().isoformat(),
        "software_version": "SW-0",
    })
    with_prior = evaluate_cpc3_pump_case(case, autoexport_rows=raw)
    assert with_prior.swap_context_kind == "before"
    assert with_prior.swap_context_sw == "SW-0"
    assert with_prior.before_sw == "SW-0"
    assert with_prior.swap_day_sw == ("SW-1", "SW-2")


def test_software_only_after_swap_not_classified_as_missing():
    case = _pump(326, with_quicktests=False)
    case.ecu_states = []
    raw = [{
        "source_ref": "raw:synthetic#post",
        "diag_date": (BASE + timedelta(days=10)).date().isoformat(),
        "software_version": "SW-AFTER",
    }]
    result = evaluate_cpc3_pump_case(case, autoexport_rows=raw)
    assert result.sw_versions == ("SW-AFTER",)
    assert result.swap_context_kind == "after_only"
    assert result.swap_day_sw == ()
    assert result.before_sw is None
    assert result.after_sw == "SW-AFTER"
