"""Small parser registry used to select source-specific adapters."""

from __future__ import annotations

from pathlib import Path

from ntf_insight.ingestion.base import ShortTestParser
from ntf_insight.ingestion.models import ParsedShortTest


class NoParserAvailableError(ValueError):
    pass


class ShortTestParserRegistry:
    def __init__(self, parsers: list[ShortTestParser] | None = None) -> None:
        self._parsers = list(parsers or [])

    def register(self, parser: ShortTestParser) -> None:
        self._parsers.append(parser)

    def select(self, path: Path) -> ShortTestParser:
        for parser in self._parsers:
            if parser.can_parse(path):
                return parser
        raise NoParserAvailableError(f"No short-test parser available for: {path.name}")

    def parse(self, path: Path) -> ParsedShortTest:
        return self.select(path).parse(path)
