"""Source-specific import adapters and canonical ingestion results."""

from ntf_insight.ingestion.base import DTCTriggerParser, ECUChangeHistoryParser, ShortTestParser
from ntf_insight.ingestion.models import (
    ImportIssue,
    ImportSeverity,
    ParsedDTCTriggerCatalog,
    ParsedECUChangeCatalog,
    ParsedShortTest,
)
from ntf_insight.ingestion.registry import NoParserAvailableError, ShortTestParserRegistry

__all__ = [
    "DTCTriggerParser",
    "ECUChangeHistoryParser",
    "ImportIssue",
    "ImportSeverity",
    "NoParserAvailableError",
    "ParsedDTCTriggerCatalog",
    "ParsedECUChangeCatalog",
    "ParsedShortTest",
    "ShortTestParser",
    "ShortTestParserRegistry",
]
