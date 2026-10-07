"""Parser contracts for source-specific ingestion adapters."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from ntf_insight.ingestion.models import (
    ParsedDTCTriggerCatalog,
    ParsedECUChangeCatalog,
    ParsedShortTest,
)


class ShortTestParser(Protocol):
    """Contract implemented by each concrete short-test export parser."""

    name: str

    def can_parse(self, path: Path) -> bool: ...

    def parse(self, path: Path) -> ParsedShortTest: ...


class DTCTriggerParser(Protocol):
    """Contract for SMR-D or other DTC trigger-definition sources."""

    name: str

    def can_parse(self, path: Path) -> bool: ...

    def parse(self, path: Path) -> ParsedDTCTriggerCatalog: ...


class ECUChangeHistoryParser(Protocol):
    """Contract for HW/SW/calibration release/change lists."""

    name: str

    def can_parse(self, path: Path) -> bool: ...

    def parse(self, path: Path) -> ParsedECUChangeCatalog: ...
