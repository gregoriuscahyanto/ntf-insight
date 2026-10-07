"""Source-format contracts and canonical ingestion models.

Storage-dependent services are intentionally not imported here. Keeping this package
initializer lightweight prevents circular imports when the storage layer references
ingestion artifact models.
"""

from ntf_insight.ingestion.assembly import AssemblyResult, CaseAssembler
from ntf_insight.ingestion.artifacts import (
    ParseRun,
    ParseStatus,
    RawArchive,
    SourceArtifact,
    SourceType,
    sha256_file,
)
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
from ntf_insight.ingestion.registry import NoParserAvailableError, ShortTestParserRegistry

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
    "PopulationExposureParser",
    "RawArchive",
    "ReplacementParser",
    "ShortTestParser",
    "ShortTestParserRegistry",
    "SourceArtifact",
    "SourceType",
    "SupplierFindingParser",
    "VehicleListParser",
    "VehicleSoftwareHistoryParser",
    "WorkshopHistoryParser",
    "sha256_file",
]
