"""Synthetischer Projekttest: zwei KI-Runden mit stabiler Paket-/Fallzuordnung."""
from __future__ import annotations

import json
from zipfile import ZipFile

import pytest

from ntf_insight.reporting.chatgpt_exchange import ChatGPTAnalyseStore
from ntf_insight.reporting.cluster_context_package import export_cluster_context
from ntf_insight.reporting.ki_analysepaket import export_ki_analysepaket
from ntf_insight.storage.cluster_evidence_store import ClusterEvidenceStore
from ntf_insight.storage.workflow_ai_chain import WorkflowAIChainStore
from ntf_insight.storage.workflow_projects import NTFProject, WorkflowProjectStore
from test_chatgpt_rueckimport import make_data, read_package, write_answer


def test_project_settings_are_isolated_and_persist(tmp_path):
    from ntf_insight.storage.duckdb_store import DuckDBStore

    path = tmp_path / "ntf-insight.duckdb"
    store = WorkflowProjectStore(DuckDBStore(path))
    first = store.save(
        NTFProject("coolant_pump", " A 123-456 ", "Kühlmittelpumpe", ("CPC3", "MCM"))
    )
    assert first.title == "Kühlmittelpumpe [A 123-456]"
    assert first.ecu_names == ("CPC3", "MCM")
    with pytest.raises(ValueError, match="existiert"):
        store.save(
            NTFProject("coolant_pump", "A123456", "Kühlmittelpumpe", ()),
            create_only=True,
        )
    second = store.save(
        NTFProject("coolant_pump", "B 987 654", "Kühlmittelpumpe", ("CPC",))
    )
    assert second.ecu_names == ("CPC",)
    store.save(NTFProject("coolant_pump", first.part_number, "Pumpe", ("CPC3",)))
    reopened = WorkflowProjectStore(DuckDBStore(path))
    assert len(reopened.list_projects()) == 2
    assert reopened.get("coolant_pump", "A123456").title == "Pumpe [A 123-456]"
    assert reopened.get("coolant_pump", "B987654").ecu_names == ("CPC",)
    assert reopened.get("coolant_pump", "C000") is None


def test_automatic_first_package_links_second_result_and_survives_backup(tmp_path):
    from ntf_insight.ingestion.portable_backup import (
        export_portable_backup, restore_portable_backup,
    )
    from ntf_insight.storage.duckdb_store import DuckDBStore

    base = tmp_path / "working"
    base.mkdir()
    service = make_data(base, qec=False)
    pkg = export_ki_analysepaket(service, tmp_path / "erstes-paket.zip")
    template, manifest, cases, _qecs, _ = read_package(pkg.pfad)
    chain = WorkflowAIChainStore(service.store)
    stored = chain.register_first_export("coolant_pump", "A-EXAMPLE-001", pkg.pfad)
    assert stored.paket_id == manifest["paket_id"]
    assert stored.analysis_id is None
    assert stored.path.exists()
    assert stored.path != pkg.pfad
    assert chain.latest_first_export("coolant_pump", "B-OTHER") is None
    chain.validate_cached_zip(stored)

    answer = tmp_path / "erstes-ergebnis.json"
    write_answer(answer, template, cases[0]["fall_id"])
    result = ChatGPTAnalyseStore(service.store).import_file(answer)
    assert chain.record_import(result["analyse_id"], round_number=1)
    first_payload = chain.first_result(stored.paket_id)
    assert first_payload["paket_id"] == stored.paket_id
    assert first_payload["faelle"][0]["fall_id"] == cases[0]["fall_id"]

    context = ClusterEvidenceStore(service.store)
    technical = tmp_path / "pump.txt"
    technical.write_text("Synthetisches Bauteildatenblatt", encoding="utf-8")
    context.add_files("coolant_pump", "A-EXAMPLE-001", "additional", [technical])
    second = export_cluster_context(
        context, "coolant_pump", "A-EXAMPLE-001", stored.path,
        tmp_path / "zweiter-durchlauf.zip",
        first_result=first_payload,
    )
    with ZipFile(second.path) as archive:
        names = set(archive.namelist())
        assert "voranalyse/erstes_chatgpt_ergebnis.json" in names
        previous = json.loads(archive.read("voranalyse/erstes_chatgpt_ergebnis.json"))
        assert previous["analyse_id"] == result["analyse_id"]
        second_template = json.loads(archive.read("chatgpt_ergebnis_vorlage.json"))
        assert second_template["paket_id"] == template["paket_id"]
        assert second_template["analyse_id"] != template["analyse_id"]
        assert second_template["analyse_id"] == second.analysis_id
        assert not any(name.startswith("unterlagen/") for name in names)
    chain.register_second_export(
        "coolant_pump", "A-EXAMPLE-001",
        second.parent_package_id, second.analysis_id,
    )
    assert chain.is_prepared_second(
        "coolant_pump", "A-EXAMPLE-001", stored.paket_id, second.analysis_id
    )
    assert not chain.is_prepared_second(
        "coolant_pump", "B-OTHER", stored.paket_id, second.analysis_id
    )
    # Ein zweites Ergebnis unter falscher/neuer Kennung wird nicht zugeordnet.
    with pytest.raises(ValueError, match="keinem zuvor"):
        chain.record_import(result["analyse_id"], round_number=2)

    backup = tmp_path / "projekt.ntfbackup"
    export_portable_backup(base, backup)
    restored_root = tmp_path / "recovered"
    restore_portable_backup(backup, restored_root)
    restored = WorkflowAIChainStore(DuckDBStore(restored_root / "ntf-insight.duckdb"))
    restored_pkg = restored.latest_first_export("coolant_pump", "A-EXAMPLE-001")
    assert restored_pkg is not None
    assert restored_pkg.path.is_file()
    restored.validate_cached_zip(restored_pkg)
    assert restored_pkg.analysis_id == result["analyse_id"]
    assert restored.is_prepared_second(
        "coolant_pump", "A-EXAMPLE-001", stored.paket_id, second.analysis_id
    )


def test_project_page_opens_new_project_and_configures_ecus(tmp_path, monkeypatch):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from ntf_insight.app.windows.main_window import MainWindow

    monkeypatch.setenv("NTF_INSIGHT_DATA_DIR", str(tmp_path / "app-data"))
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    workflow = window.pages["workflow"]
    settings = window.pages["project_settings"]
    assert len(workflow.cards) == 5
    assert window.pages["cases"].detail_tabs.indexOf(
        window.pages["cases"].cluster_workspace
    ) == -1
    assert workflow.local_cluster_widget is window.pages["cases"].cluster_workspace
    assert not hasattr(workflow, "context_base_button")
    assert not hasattr(workflow, "context_export_button")
    workflow.new_project_button.click()
    assert window.stack.currentWidget() is settings
    settings.part_edit.setText("A 123 456")
    settings.ecus_edit.setPlainText("CPC3\nMCM")
    settings.save_button.click()
    assert window.stack.currentWidget() is workflow
    assert "Kühlmittelpumpe [A 123 456]" in workflow.project_title.text()
    assert "CPC3" in workflow.project_ecus_label.text()
    assert "MCM" in workflow.project_ecus_label.text()
    assert workflow.part_number.text() == "A 123 456"
    assert not workflow.cluster_export_button.isEnabled()
    assert workflow.project_export_button.parent() is workflow
    assert workflow.project_import_button.parent() is workflow
    window.close()
    app.processEvents()
