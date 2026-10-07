"""Source-specific import adapters and canonical ingestion results."""

from ntf_insight.ingestion.assembly import AssemblyResult, CaseAssembler
from ntf_insight.ingestion.artifacts import ParseRun, ParseStatus, RawArchive, SourceArtifact, SourceType, sha256_file
from ntf_insight.ingestion.base import (
    DTCTriggerParser,
    ECUChangeHistoryParser,
    PopulationExposureParser,
    ReplacementParser,
    ShortTestParser,
    SupplierFindingParser,
    VehicleListParser,
    VehicleSoftwareHistoryParser,
    WorkshopHistoryParser,
)
from ntf_insight.ingestion.models import (
    ImportIssue,
    ImportResult,
    ImportSeverity,
    ParsedDTCTriggerCatalog,
    ParsedECUChangeCatalog,
    ParsedPopulationData,
    ParsedReplacementData,
    ParsedShortTest,
    ParsedSupplierFindingData,
    ParsedVehicleList,
    ParsedVehicleSoftwareData,
    ParsedWorkshopData,
)
from ntf_insight.ingestion.parser_execution import ParserExecutionService
from ntf_insight.ingestion.registry import NoParserAvailableError, ShortTestParserRegistry
from ntf_insight.ingestion.service import SourceImportService

__all__ = [
    "AssemblyResult",
    "CaseAssembler",
    "DTCTriggerParser",
    "ECUChangeHistoryParser",
    "ImportIssue",
    "ImportResult",
    "ImportSeverity",
    "NoParserAvailableError",
    "ParsedDTCTriggerCatalog",
    "ParsedECUChangeCatalog",
    "ParsedPopulationData",
    "ParsedReplacementData",
    "ParsedShortTest",
    "ParsedSupplierFindingData",
    "ParsedVehicleList",
    "ParsedVehicleSoftwareData",
    "ParsedWorkshopData",
    "ParseRun",
    "ParseStatus",
    "ParserExecutionService",
    "PopulationExposureParser",
    "RawArchive",
    "ReplacementParser",
    "ShortTestParser",
    "ShortTestParserRegistry",
    "SourceArtifact",
    "SourceImportService",
    "SourceType",
    "SupplierFindingParser",
    "VehicleListParser",
    "VehicleSoftwareHistoryParser",
    "WorkshopHistoryParser",
    "sha256_file",
]
