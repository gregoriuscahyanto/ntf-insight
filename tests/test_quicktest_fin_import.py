"""End-to-end FIN-scoped QuickTest import tests using synthetic PDFs only."""

from __future__ import annotations

import io
from datetime import datetime

from openpyxl import Workbook
from reportlab.pdfgen import canvas

from ntf_insight.app.bootstrap import load_application_data
from ntf_insight.app.settings import AppPaths
from ntf_insight.ingestion.batch_import import LocalBatchImporter
from ntf_insight.ingestion.service import SourceImportService
from ntf_insight.storage.quicktest_store import QuickTestStore


FIN = "W1TTEST0000000001"


def _pdf(*, fin: str = FIN, dtcs: int = 1, date: str = "2026-01-03 10:12:45") -> bytes:
    out = io.BytesIO()
    pdf = canvas.Canvas(out)
    lines = [
        f"FIN {fin}",
        "VIN W1TTEST0000000002",
        "DISTANCE 11980 km",
        f"DIAG START {date}",
        "VERSION 1",
        "LANGUAGE en",
        "SOURCE TD",
        "QuickTest 1",
        "ECU Count 2",
        "ECUS (2)",
        "CPC3-N127 - Controller",
        "Diagnostics ID 00AB13 ECU Variant CPC3_TEST",
        "Hardware",
        "Partnumber",
        "001 002 003 Hardware",
        "Version",
        "23/15 000",
        "Supplier Example Software",
        "Version",
        "25/04 002",
        "Software",
        "Partnumbers",
        "000001,000002",
        f"FAULT CODES ({dtcs})",
    ]
    if dtcs:
        lines += [
            "FC P26F100 - Coolant pump performance. S",
            "Name Value (first occurence or unknown) Value (last occurence)",
            "frequencyCounter 3 -",
            "originalOdometerValue Odometer value not available /",
            "Default -",
            "mostRecentOdometerValue 11980 km -",
            "Operating_Time 06 0F FE 3E A1 -",
        ]
    lines += [
        "MCM-N3/9 - Motor control unit",
        "Diagnostics ID 002001 ECU Variant MCM_TEST",
        "Hardware",
        "Partnumber",
        "004 005 006 Hardware",
        "Version",
        "22/01 000",
        "Supplier Example Software",
        "Version",
        "24/03 000",
        "FAULT CODES (0)",
        "No fault codes",
    ]
    for page_index, start in enumerate(range(0, len(lines), 30)):
        if page_index:
            pdf.showPage()
        for ix, line in enumerate(lines[start:start + 30]):
            pdf.drawString(35, 792 - 21 * ix, line)
    pdf.save()
    return out.getvalue()


def _qec() -> bytes:
    book = Workbook()
    sheet = book.active
    sheet.title = "Schadteile QEC"
    sheet.append(["Referenznr.", "FIN", "Benennung", "Rep.-Datum", "Laufleistung"])
    sheet.append([
        "QT-LATER", "MBC" + FIN, "KUEHLMITTELPUMPE",
        datetime(2026, 1, 5), 12000,
    ])
    target = io.BytesIO()
    book.save(target)
    return target.getvalue()


def _sources(tmp_path):
    data = tmp_path / "local"
    return SourceImportService(data / "raw", data / "ntf-insight.duckdb")


def test_pdf_only_is_persisted_by_fin_without_qec_case(tmp_path) -> None:
    service = _sources(tmp_path)
    path = tmp_path / "synthetic.pdf"
    path.write_bytes(_pdf())

    result = LocalBatchImporter(service).import_paths([path])
    quicktests = QuickTestStore(service.store)

    assert result.quicktests_saved == 1
    assert result.quicktests_without_case == 1
    assert result.cases_created == 0
    assert service.store.load_cases() == []
    assert quicktests.list_fins() == [FIN]
    reports = quicktests.list_reports(FIN)
    assert len(reports) == 1
    assert reports[0]["vin"] != FIN
    assert reports[0]["dtc_count"] == 1
    assert reports[0]["ecu_count"] == 2
    assert quicktests.statistics()["ecus"] == 2
    assert quicktests.statistics()["dtcs"] == 1
    assert quicktests.diagnostic_times_for_fins({FIN})[FIN] == [
        (datetime(2026, 1, 3, 10, 12, 45), 1)
    ]
    assert quicktests.statistics()["parameters"] == 4, quicktests.list_parameters(
        reports[0]["report_id"], 1, 1
    )
    ecus = quicktests.list_ecus(reports[0]["report_id"])
    assert ecus[0]["metadata"]["software_version"] == "25/04 002"
    faults = quicktests.list_dtcs(reports[0]["report_id"])
    assert faults[0]["dtc_code"] == "P26F100"
    parameters = quicktests.list_parameters(reports[0]["report_id"], 1, 1)
    assert any(p["name"] == "originalOdometerValue" for p in parameters)
    assert "Odometer value not available" in parameters[1]["first_value"]
    assert "FC P26F100" in quicktests.page_text(reports[0]["report_id"], 1)


def test_quicktest_pdf_becomes_local_not_demo_without_qec(tmp_path) -> None:
    data_root = tmp_path / "local"
    service = _sources(tmp_path)
    path = tmp_path / "standalone.pdf"
    path.write_bytes(_pdf(dtcs=0))
    result = LocalBatchImporter(service).import_paths([path])
    paths = AppPaths(
        data_dir=data_root,
        raw_dir=data_root / "raw",
        database_path=data_root / "ntf-insight.duckdb",
    )
    app_data = load_application_data(paths)

    assert result.quicktests_saved == 1
    assert app_data.mode == "local"
    assert app_data.cases.list_cases() == []
    reports = QuickTestStore(service.store).list_reports(FIN)
    assert reports[0]["dtc_count"] == 0
    assert QuickTestStore(service.store).statistics()["ecus"] == 2


def test_later_qec_import_links_previously_stored_quicktest(tmp_path) -> None:
    service = _sources(tmp_path)
    importer = LocalBatchImporter(service)
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(_pdf())
    first = importer.import_paths([pdf])
    assert first.quicktests_saved == 1
    assert not service.store.load_cases()

    qec = tmp_path / "list.xlsx"
    qec.write_bytes(_qec())
    second = importer.import_paths([qec])
    assert second.cases_created == 1
    case = service.store.get_case("QEC-QT-LATER")
    assert case is not None
    assert case.vin == FIN
    assert len(case.diagnostic_sessions) == 1
    assert len(case.ecu_states) == 2
    assert len(case.diagnostics) == 1
    assert case.diagnostics[0].freeze_frame["parameters"]
    assert case.diagnostic_sessions[0].report_id == QuickTestStore(
        service.store
    ).list_reports(FIN)[0]["report_id"]

    again = importer.import_paths([qec, pdf])
    assert again.quicktests_saved == 0
    assert len(service.store.get_case("QEC-QT-LATER").diagnostics) == 1
    assert len(QuickTestStore(service.store).list_reports(FIN)) == 1


def test_pdf_changed_metadata_does_not_create_second_diagnosis(tmp_path) -> None:
    service = _sources(tmp_path)
    original = _pdf()
    first = tmp_path / "report_a.pdf"
    second = tmp_path / "report_b.pdf"
    first.write_bytes(original)
    second.write_bytes(original + b"\n% synthetic PDF file-level metadata change\n")

    result = LocalBatchImporter(service).import_paths([first, second])
    store = QuickTestStore(service.store)
    assert result.quicktests_saved == 1
    assert result.duplicates >= 1
    assert len(store.list_reports(FIN)) == 1
    with service.store.connect() as con:
        assert con.execute("SELECT COUNT(*) FROM quicktest_sources").fetchone()[0] == 2


def test_pdf_parser_rejects_missing_fin_without_guessing_from_filename(tmp_path) -> None:
    service = _sources(tmp_path)
    path = tmp_path / f"QuickTest_{FIN}.pdf"
    path.write_bytes(_pdf(fin="INVALID"))
    summary = LocalBatchImporter(service).import_paths([path])
    assert summary.quicktests_saved == 0
    assert not QuickTestStore(service.store).list_reports()
    assert service.list_artifacts()  # The unmodified raw file remains traceable.
    assert any("ValueError" in issue for issue in summary.issues)


def test_different_fins_remain_separate_without_a_fall(tmp_path) -> None:
    service = _sources(tmp_path)
    a = tmp_path / "first.pdf"
    b = tmp_path / "second.pdf"
    a.write_bytes(_pdf(fin=FIN))
    b.write_bytes(_pdf(fin="W1TTEST0000000003"))
    LocalBatchImporter(service).import_paths([a, b])
    store = QuickTestStore(service.store)
    assert len(store.list_fins()) == 2
    assert all(len(store.list_reports(fin)) == 1 for fin in store.list_fins())


def test_pdf_drag_drop_opens_fin_browser_without_qec_case(tmp_path, monkeypatch) -> None:
    import time

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("NTF_INSIGHT_DATA_DIR", str(tmp_path / "gui-data"))
    from PySide6.QtWidgets import QApplication

    from ntf_insight.app.windows.main_window import MainWindow

    pdf = tmp_path / "from-explorer.pdf"
    pdf.write_bytes(_pdf())
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    assert window.application_data.mode == "demo"

    source_page = window.pages["sources"]
    source_page._archive_paths([pdf])
    deadline = time.monotonic() + 20
    while window.application_data.mode != "local" and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.025)
    app.processEvents()

    assert window.application_data.mode == "local"
    assert not window.repository.list_cases()
    case_page = window.pages["cases"]
    assert case_page.quicktest_browser is not None
    assert case_page.detail_tabs.currentWidget() is case_page.quicktest_browser
    assert case_page.quicktest_browser.fin_selector.currentText() == FIN
    assert case_page.quicktest_browser.report_model.rowCount() == 1
    assert case_page.quicktest_browser.ecu_model.rowCount() == 2
    assert case_page.quicktest_browser.dtc_model.rowCount() == 1

    window.close()
    app.processEvents()


def test_fin_case_overview_shows_readonly_quicktest_timeline_without_qec(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("NTF_INSIGHT_DATA_DIR", str(tmp_path / "local"))
    from PySide6.QtWidgets import QApplication

    from ntf_insight.app.windows.main_window import MainWindow

    source = _sources(tmp_path)
    pdf = tmp_path / "diagnosis.pdf"
    pdf.write_bytes(_pdf())
    LocalBatchImporter(source).import_paths([pdf])
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    page = window.pages["cases"]

    assert not window.repository.list_cases()
    assert page.case_model.rowCount() == 1
    assert page.case_model.data(page.case_model.index(0, 0)) == "Nur QuickTests (kein Fall)"
    assert page.case_model.data(page.case_model.index(0, 1)) == FIN
    assert len(page.fin_only_previews) == 1
    assert page.selector.currentData() == "FIN-QUICKTEST:" + FIN
    assert page.timeline_model.rowCount() == 4  # 1 session, 1 DTC, 2 ECU states
    assert page.time_plot._entries
    assert page.recurrence_value.text() == "Nicht beurteilbar"
    assert page.root_cause_value.text() == "Nicht bestimmbar"
    assert page.evidence_model.rowCount() == 0
    assert page._selected_case() is None
    assert not page.add_event_button.isEnabled()
    assert not page.correct_button.isEnabled()
    assert not page.export_button.isEnabled()
    assert not page.history_button.isEnabled()

    from PySide6.QtWidgets import QLabel

    from ntf_insight.app.widgets.status_card import StatusCard

    cards = window.pages["dashboard"].findChildren(StatusCard)
    totals = {}
    for card in cards:
        labels = card.findChildren(QLabel)
        totals[labels[0].text()] = labels[1].text()
    assert totals["Fahrzeuge"] == "1"
    assert totals["NTF-Fälle"] == "0"
    assert totals["QuickTests"] == "1"

    page.case_search.setText("NOT-A-FIN")
    assert page.case_proxy.rowCount() == 0
    assert page.selector.currentIndex() == -1
    assert not page.time_plot._entries
    page.case_search.setText(FIN)
    assert page.case_proxy.rowCount() == 1
    assert page.timeline_model.rowCount() == 4

    window.close()
    app.processEvents()


def test_archived_quicktest_can_be_reclassified_without_losing_provenance(
    tmp_path,
) -> None:
    from ntf_insight.ingestion.artifacts import SourceType

    service = _sources(tmp_path)
    source = tmp_path / "original-quicktest.pdf"
    source.write_bytes(_pdf())
    artifact = service.import_raw(source, SourceType.OTHER)

    result = LocalBatchImporter(service).import_paths(
        [type(source)(artifact.archived_path)]
    )

    assert result.quicktests_saved == 1
    assert result.files_archived == 0
    saved = service.store.load_artifacts()
    assert len(saved) == 1
    assert saved[0].source_type == SourceType.SHORT_TEST
    assert saved[0].original_name == "original-quicktest.pdf"
    assert saved[0].archived_path == artifact.archived_path
    assert saved[0].imported_at == artifact.imported_at


def test_archived_old_sources_can_be_filtered_without_deleting_them(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("NTF_INSIGHT_DATA_DIR", str(tmp_path / "local"))
    from PySide6.QtWidgets import QApplication

    from ntf_insight.app.windows.main_window import MainWindow
    from ntf_insight.ingestion.artifacts import SourceType

    service = _sources(tmp_path)
    old = tmp_path / "old-format.dat"
    old.write_text("Synthetischer, noch nicht unterstützter Inhalt")
    service.import_raw(old, SourceType.OTHER)
    pdf = tmp_path / "report.pdf"
    pdf.write_bytes(_pdf())
    LocalBatchImporter(service).import_paths([pdf])

    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    page = window.pages["sources"]
    assert page.archive_view.currentData() == "processed"
    assert page.artifact_model.rowCount() == 1
    assert "1 verarbeitet" in page.archive_counts.text()

    page.archive_view.setCurrentIndex(page.archive_view.findData("all"))
    assert page.artifact_model.rowCount() == 2
    page.archive_view.setCurrentIndex(page.archive_view.findData("pending"))
    assert page.artifact_model.rowCount() == 1
    assert page._visible_artifacts[0].original_name == "old-format.dat"
    page.artifact_table.selectRow(0)
    assert page.retry_button.isEnabled()
    assert len(service.store.load_artifacts()) == 2

    window.close()
    app.processEvents()
