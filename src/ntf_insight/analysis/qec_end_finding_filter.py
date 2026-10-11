"""QEC-Endbefund-Selektion und nachvollziehbare Quellenabdeckung je FIN.

Keine Befundtexte oder FINs verlassen den lokalen Prozess. Ein Endbefund ist
nur ein Filterkriterium / Nachprüfattribut, NIE ein DTC-Clustermerkmal.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Iterable, Sequence

from ntf_insight.domain.case import NTFCase

MISSING_END_FINDING = "(Ohne SSL-Endbefund)"


def _text(value: object) -> str:
    return " ".join(str(value or "").strip().split())


def qec_pump_cases(cases: Iterable[NTFCase]) -> tuple[NTFCase, ...]:
    return tuple(
        case for case in cases
        if case.component_profile_id == "coolant_pump"
        and getattr(case, "qec_reference", None)
        and case.vin.strip()
    )


def finding_for(case: NTFCase) -> str:
    return _text(getattr(case, "qec_ssl_end_finding", None)) or MISSING_END_FINDING


def finding_counts(cases: Sequence[NTFCase]) -> dict[str, int]:
    return dict(sorted(Counter(
        finding_for(case) for case in qec_pump_cases(cases)
    ).items(), key=lambda entry: (-entry[1], entry[0].casefold())))


def selected_qec_cases(
    cases: Sequence[NTFCase],
    *,
    exact_findings: Iterable[str] = (),
    search: str = "",
) -> tuple[NTFCase, ...]:
    """Empty exact choices and empty search each mean no restriction.

    When both are present, they are combined with logical AND, never OR.
    No code guesses an NTF/supplier judgment based on a keyword.
    """
    normalized_exact = {value.casefold() for value in exact_findings}
    needle = _text(search).casefold()
    return tuple(
        case for case in qec_pump_cases(cases)
        if (
            not normalized_exact
            or finding_for(case).casefold() in normalized_exact
        )
        and (
            not needle
            or needle in finding_for(case).casefold()
        )
    )


def part_numbers(cases: Sequence[NTFCase]) -> tuple[str, ...]:
    counts = Counter(
        _text(getattr(case, "qec_part_number", None))
        for case in qec_pump_cases(cases)
        if _text(getattr(case, "qec_part_number", None))
    )
    return tuple(sorted(counts, key=lambda key: (-counts[key], key)))


@dataclass(frozen=True, slots=True)
class FinSourceCoverage:
    """Each count is independent: overlaps are EXPECTED and deliberate."""

    total_fins: int
    part_number_fins: int
    qec_fins: int
    tips_fins: int
    quicktest_fins: int
    part_number: str
    qec_case_count: int


def source_coverage(
    fins: Sequence[str],
    qec_cases: Sequence[NTFCase],
    *,
    part_number: str,
    tips_fins: Iterable[str] = (),
    quicktest_fins: Iterable[str] = (),
) -> FinSourceCoverage:
    universe = {fin.strip().upper() for fin in fins}
    scoped_qec = [
        case for case in qec_pump_cases(qec_cases)
        if case.vin.strip().upper() in universe
    ]
    def normalized(items: Iterable[str]) -> set[str]:
        return {fin.strip().upper() for fin in items}
    part = _text(part_number)
    part_fins = {
        case.vin.strip().upper() for case in scoped_qec
        if part and _text(getattr(case, "qec_part_number", None)) == part
    }
    return FinSourceCoverage(
        total_fins=len(universe),
        part_number_fins=len(part_fins),
        qec_fins=len({case.vin.strip().upper() for case in scoped_qec}),
        tips_fins=len(universe & normalized(tips_fins)),
        quicktest_fins=len(universe & normalized(quicktest_fins)),
        part_number=part,
        qec_case_count=len(scoped_qec),
    )
