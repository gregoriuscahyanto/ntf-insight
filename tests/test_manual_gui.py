import os
from datetime import datetime

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from ntf_insight.app.dialogs.manual_entry_dialogs import ManualEventDialog, NewCaseDialog
from ntf_insight.app.windows.main_window import MainWindow
from ntf_insight.domain.events import DiagnosticEvent, DiagnosticSession, PartReplacement


def test_new_case_dialog_builds_component_agnostic_case() -> None:
    app = QApplication.instance() or QApplication([])
    dialog = NewCaseDialog()
    dialog.case_id.setText("FIELD-001")
    dialog.vin.setText("W1TTEST0000000001")
    dialog.model_series.setText("Test series")
    case = dialog.build_case()

    assert case.case_id == "FIELD-001"
    assert case.vin == "W1TTEST0000000001"
    assert case.component_profile_id == "coolant_pump"
    assert case.vehicle.model_series == "Test series"
    dialog.close()
    app.processEvents()


def test_manual_event_dialog_generates_typed_events_and_optional_mileage() -> None:
    app = QApplication.instance() or QApplication([])
    from ntf_insight.domain.case import NTFCase
    from ntf_insight.domain.vehicle import Vehicle

    case = NTFCase(
        case_id="FIELD-001",
        vehicle=Vehicle(vin="W1TTEST0000000001"),
        component_type="Coolant Pump",
    )
    dialog = ManualEventDialog(case)
    dialog.kind_combo.setCurrentIndex(dialog.kind_combo.findData("diagnostic_session"))
    dialog.fields["diagnostic_session"]["dtc_count"].setText("0")
    session = dialog.build_event()
    assert isinstance(session, DiagnosticSession)
    assert session.dtc_count == 0
    assert session.mileage_km is None
    dialog.close()

    case.diagnostic_sessions = [session]
    dialog = ManualEventDialog(case)
    dialog.kind_combo.setCurrentIndex(dialog.kind_combo.findData("diagnostic"))
    dialog.fields["diagnostic"]["ecu"].setText("CPC3")
    dialog.fields["diagnostic"]["dtc_code"].setText("P26F100")
    dialog.fields["diagnostic"]["session_id"].setCurrentIndex(1)
    event = dialog.build_event()

    assert isinstance(event, DiagnosticEvent)
    assert event.session_id == session.session_id
    assert event.dtc_code == "P26F100"
    dialog.close()
    app.processEvents()


def test_main_window_reloads_real_case_and_manual_events(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("NTF_INSIGHT_DATA_DIR", str(tmp_path / "app-data"))
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    assert window.application_data.mode == "demo"
    assert window.pages["cases"].manual_service is not None

    from ntf_insight.domain.case import NTFCase
    from ntf_insight.domain.vehicle import Vehicle

    case = NTFCase(
        case_id="FIELD-001",
        vehicle=Vehicle(vin="W1TTEST0000000001"),
        component_type="Coolant Pump",
    )
    window.manual_service.create_case(case)
    window._reload_after_manual_change("FIELD-001")

    assert window.application_data.mode == "local"
    assert [case.case_id for case in window.repository.list_cases()] == ["FIELD-001"]
    assert window.pages["cases"].selector.currentData() == "FIELD-001"
    assert window.pages["cases"].case_table.model().rowCount() == 1

    window.manual_service.add_event(
        "FIELD-001", "replacement",
        PartReplacement(
            vin=case.vin,
            occurred_at=datetime(2026, 1, 2, 12),
            mileage_km=1000,
            component_type="Coolant Pump",
        ),
    )
    window._reload_after_manual_change("FIELD-001")
    assert window.pages["cases"].timeline_model.rowCount() == 1
    assert window.repository.get_case("FIELD-001").replacements
    window.close()
    app.processEvents()
