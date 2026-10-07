"""Parser contracts for source-specific ingestion adapters."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, TypeVar

from ntf_insight.ingestion.models import (
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


class ShortTestParser(Protocol):
    name: str
    def can_parse(self, path: Path) -> bool: ...
    def parse(self, path: Path) -> ParsedShortTest: ...


class VehicleListParser(Protocol):
    name: str
    def can_parse(self, path: Path) -> bool: ...
    def parse(self, path: Path) -> ParsedVehicleList: ...


class ReplacementParser(Protocol):
    name: str
    def can_parse(self, path: Path) -> bool: ...
    def parse(self, path: Path) -> ParsedReplacementData: ...


class SupplierFindingParser(Protocol):
    name: str
    def can_parse(self, path: Path) -> bool: ...
    def parse(self, path: Path) -> ParsedSupplierFindingData: ...


class WorkshopHistoryParser(Protocol):
    name: str
    def can_parse(self, path: Path) -> bool: ...
    def parse(self, path: Path) -> ParsedWorkshopData: ...


class VehicleSoftwareHistoryParser(Protocol):
    name: str
    def can_parse(self, path: Path) -> bool: ...
    def parse(self, path: Path) -> ParsedVehicleSoftwareData: ...


class DTCTriggerParser(Protocol):
    name: str
    def can_parse(self, path: Path) -> bool: ...
    def parse(self, path: Path) -> ParsedDTCTriggerCatalog: ...


class ECUChangeHistoryParser(Protocol):
    name: str
    def can_parse(self, path: Path) -> bool: ...
    def parse(self, path: Path) -> ParsedECUChangeCatalog: ...


class PopulationExposureParser(Protocol):
    name: str
    def can_parse(self, path: Path) -> bool: ...
    def parse(self, path: Path) -> ParsedPopulationData: ...
