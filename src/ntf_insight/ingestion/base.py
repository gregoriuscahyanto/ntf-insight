"""Parser contracts for source-specific ingestion adapters."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from ntf_insight.ingestion.models import ParsedShortTest


class ShortTestParser(Protocol):
    """Contract implemented by each concrete short-test export parser."""

    name: str

    def can_parse(self, path: Path) -> bool: ...

    def parse(self, path: Path) -> ParsedShortTest: ...
