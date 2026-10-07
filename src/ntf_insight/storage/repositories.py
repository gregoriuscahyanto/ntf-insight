"""Repository abstractions used by the application layer."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from ntf_insight.domain.case import NTFCase


class CaseRepository(Protocol):
    def list_cases(self) -> list[NTFCase]: ...

    def get_case(self, case_id: str) -> NTFCase | None: ...


class InMemoryCaseRepository:
    """Simple repository used for synthetic/demo cases and tests."""

    def __init__(self, cases: Iterable[NTFCase] = ()) -> None:
        self._cases = {case.case_id: case for case in cases}

    def list_cases(self) -> list[NTFCase]:
        return sorted(self._cases.values(), key=lambda case: case.case_id)

    def get_case(self, case_id: str) -> NTFCase | None:
        return self._cases.get(case_id)

    def replace_all(self, cases: Iterable[NTFCase]) -> None:
        self._cases = {case.case_id: case for case in cases}
