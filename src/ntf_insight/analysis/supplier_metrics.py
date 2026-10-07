"""Supplier/population summaries with denominator-aware rates."""

from __future__ import annotations

from dataclasses import dataclass

from ntf_insight.analysis.recurrence import analyze_recurrence
from ntf_insight.domain.case import NTFCase
from ntf_insight.domain.enums import SupplierFindingResult
from ntf_insight.domain.population import PopulationExposure


@dataclass(frozen=True, slots=True)
class SupplierSummary:
    supplier: str
    case_count: int
    return_ntf_count: int
    return_fault_found_count: int
    recurrence_count: int
    installed_units: int | None
    ntf_per_1000_installed: float | None


def build_supplier_summaries(
    cases: list[NTFCase],
    exposures: list[PopulationExposure] | None = None,
) -> list[SupplierSummary]:
    exposures = exposures or []
    suppliers = sorted(
        {
            replacement.supplier
            for case in cases
            for replacement in case.replacements
            if replacement.supplier
        }
    )

    summaries: list[SupplierSummary] = []
    for supplier in suppliers:
        supplier_cases = [
            case
            for case in cases
            if any(replacement.supplier == supplier for replacement in case.replacements)
        ]
        return_ntf = sum(
            any(finding.result == SupplierFindingResult.NTF for finding in case.supplier_findings)
            for case in supplier_cases
        )
        fault_found = sum(
            any(
                finding.result == SupplierFindingResult.FAULT_FOUND
                for finding in case.supplier_findings
            )
            for case in supplier_cases
        )
        recurrence_count = sum(
            (result := analyze_recurrence(case)).assessable and result.has_recurrence
            for case in supplier_cases
        )

        matching_exposures = [item for item in exposures if item.supplier == supplier]
        installed_units = (
            sum(item.installed_units for item in matching_exposures)
            if matching_exposures
            else None
        )
        rate = (
            return_ntf / installed_units * 1000
            if installed_units and installed_units > 0
            else None
        )
        summaries.append(
            SupplierSummary(
                supplier=supplier,
                case_count=len(supplier_cases),
                return_ntf_count=return_ntf,
                return_fault_found_count=fault_found,
                recurrence_count=recurrence_count,
                installed_units=installed_units,
                ntf_per_1000_installed=rate,
            )
        )
    return summaries
