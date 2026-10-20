"""Synthetic end-to-end test of the generated QEC + TP dashboard cohort.

No original user FINs, DTCs or supplier reports are committed.
"""
from __future__ import annotations

import csv
from datetime import datetime

import pytest
from openpyxl import Workbook

from ntf_insight.analysis.combined_fin_evidence import (
    merge_fin_evidence, qec_fin_evidence,
)
from ntf_insight.app.bootstrap import load_application_data
from ntf_insight.app.settings import AppPaths
from ntf_insight.ingestion.artifacts import SourceType
from ntf_insight.ingestion.batch_import import LocalBatchImporter
from ntf_insight.ingestion.service import SourceImportService
from ntf_insight.ingestion.source_detection import detect_source_type
from ntf_insight.storage.qec_workflow_store import QecWorkflowStore
from ntf_insight.storage.source_knowledge_store import SourceKnowledgeStore


def _fin(index: int) -> str:
    return f"W1TTEST000000{index:04d}"


def _qec_file(path) -> None:
    book = Workbook()
    pivot = book.active
    pivot.title = "Pivot Fehlerarten"
    pivot.append(["Status", "5"])
    pivot.append(["Sachnr. Teil", "SYNTH-PART"])
    sheet = book.create_sheet("NTF_Elektischer Fehler")
    sheet.append([
        "Referenznr.", "FIN", "Rep.-Datum", "Benennung",
        "Sachnr. Teil", "SSL Endbefund", "SSL-Endbefund Benennung",
    ])
    for n in range(1, 174):
        # 173 real-looking QEC references, but only 171 unique FINs.
        fin_index = min(n, 171)
        sheet.append([
            str(900000 + n), _fin(fin_index), datetime(2026, 5, 15),
            "KUEHLMITTELPUMPE 100-140W", "SYNTH-PART",
            "SYNTH-NO-ASSIGN", "Synthetischer Endbefund - NTF",
        ])
    book.save(path)
    book.close()


def _tp_file(path) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow([
            "DiagStartDt", "EcuNm", "EcuFaultNm", "EcuFaultTxt",
            "DiagStartTs", "Fin", "CntXDDiagnosisHeaderSid",
            "LastRepairDt", "C1",
        ])
        for index in range(1, 162):
            writer.writerow([
                "2026-03-05", "CPC3", "P000001", "Synthetischer DTC",
                "2026-03-05T12:00:00", _fin(index),
                "SYNTHETIC", "2026-05-15", "1",
            ])


@pytest.mark.parametrize("order", ("qec_first", "tp_first", "together"))
def test_generated_qec_is_full_population_even_when_tp_has_fewer_fins(
    tmp_path, order,
):
    qec = tmp_path / "generated.xlsx"
    tp = tmp_path / "synthetic_tp.csv"
    _qec_file(qec)
    _tp_file(tp)
    assert detect_source_type(qec) == SourceType.VEHICLE_CASE_LIST
    assert detect_source_type(tp) == SourceType.TP_DASHBOARD
    service = SourceImportService(tmp_path / "raw", tmp_path / "db.duckdb")
    importer = LocalBatchImporter(service)
    if order == "qec_first":
        importer.import_paths([qec])
        importer.import_paths([tp])
    elif order == "tp_first":
        importer.import_paths([tp])
        importer.import_paths([qec])
    else:
        importer.import_paths([tp, qec])

    cases = service.store.load_cases()
    assert len(cases) == 173
    assert len({case.vin for case in cases}) == 171
    assert {case.component_profile_id for case in cases} == {"coolant_pump"}
    assert all(case.investigated_replacement() for case in cases)

    knowledge = SourceKnowledgeStore(service.store)
    tp_fins = knowledge.tp_dashboard_fins()
    assert len(tp_fins) == 161
    assert len({case.vin for case in cases} - tp_fins) == 10

    workflow = QecWorkflowStore(service.store)
    overview = workflow.overview(tmp_path / "qec")
    assert overview["fins"] == 171
    assert overview["cases"] == 173
    assert overview["with_tp"] == 161
    assert overview["without_tp"] == 10
    assert overview["open"] == 173
    assert workflow.active_source().original_name == qec.name

    qec_evidence = qec_fin_evidence(cases)
    auto_fins, auto_faults, labels = knowledge.autoexport_fin_dtc_signatures(
        pump_swap_dates=qec_evidence.pump_swap_dates, include_all_fins=True,
        fin_filter=tuple(qec_evidence.case_links),
    )
    combined = merge_fin_evidence(
        auto_fins, auto_faults, labels, qec_evidence, only_qec=True,
    )
    assert len(combined.fins) == 171
    assert len(combined.case_links) == 171
    assert all(fin in combined.fins and not combined.faults[fin]
               for fin in {_fin(n) for n in range(162, 172)})

    exported = tmp_path / "qec_fins.csv"
    assert workflow.export_csv(exported, tmp_path / "qec") == 173
    with exported.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter=";"))
    assert len(rows) == 173
    missing = [row for row in rows
               if row["TP-Dashboard"] == "Kein TP-Dashboard-Eintrag"]
    assert len({row["FIN"] for row in missing}) == 10


def test_already_archived_qec_and_tp_are_recovered_on_boot(tmp_path):
    qec = tmp_path / "generated.xlsx"
    tp = tmp_path / "synthetic_tp.csv"
    _qec_file(qec)
    _tp_file(tp)
    paths = AppPaths(
        data_dir=tmp_path / "data", raw_dir=tmp_path / "data" / "raw",
        database_path=tmp_path / "data" / "db.duckdb",
    )
    service = SourceImportService(paths.raw_dir, paths.database_path)
    service.import_raw(qec, SourceType.OTHER)
    service.import_raw(tp, SourceType.SHORT_TEST)
    assert not service.store.load_cases()
    recovered = load_application_data(paths)
    assert recovered.mode == "local"
    assert len(recovered.cases.list_cases()) == 173
    assert len(SourceKnowledgeStore(service.store).tp_dashboard_fins()) == 161
    assert len(QecWorkflowStore(service.store).rows(paths.data_dir / "qec")) == 173
    reloaded = load_application_data(paths)
    assert len(reloaded.cases.list_cases()) == 173
    assert len(service.list_artifacts()) == 2
