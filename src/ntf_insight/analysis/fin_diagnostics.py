"""Read-only FIN diagnosis preview used when no QEC/NTF case exists.

These previews are never saved as QEC cases and never enter supplier, cluster
or root-cause analysis. They only make vehicle observations visible in the
combined FIN/Fall workspace while the true case relationship is unknown.
"""
from __future__ import annotations

from ntf_insight.domain.case import NTFCase
from ntf_insight.domain.vehicle import Vehicle
from ntf_insight.storage.quicktest_store import QuickTestStore


FIN_ONLY_PREFIX = "FIN-QUICKTEST:"


def build_fin_only_previews(
    quicktests: QuickTestStore,
    case_fins: set[str],
) -> dict[str, NTFCase]:
    previews: dict[str, NTFCase] = {}
    for fin in quicktests.list_fins():
        if fin in case_fins:
            continue
        case_id = FIN_ONLY_PREFIX + fin
        preview = NTFCase(
            case_id=case_id,
            vehicle=Vehicle(vin=fin),
            component_type="Nicht festgelegt (nur QuickTests)",
        )
        for report in quicktests.list_reports(fin):
            sessions, diagnostics, ecu_states = quicktests.case_projection(
                report["report_id"]
            )
            preview.diagnostic_sessions.extend(sessions)
            preview.diagnostics.extend(diagnostics)
            preview.ecu_states.extend(ecu_states)
        previews[case_id] = preview
    return previews
