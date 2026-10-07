"""Canonical ingestion results independent from source file formats."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from ntf_insight.domain.events import DiagnosticEvent, DiagnosticSession
from ntf_insight.domain.reference import DTCTriggerDefinition, ECUChangeRecord


class ImportSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class ImportIssue(BaseModel):
    model_config = ConfigDict(frozen=True)

    severity: ImportSeverity
    code: str
    message: str
    source_ref: str | None = None


class ParsedShortTest(BaseModel):
    """Normalized representation of one source short-test file/run."""

    session: DiagnosticSession
    diagnostics: list[DiagnosticEvent] = Field(default_factory=list)
    issues: list[ImportIssue] = Field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return not any(issue.severity == ImportSeverity.ERROR for issue in self.issues)


class ParsedDTCTriggerCatalog(BaseModel):
    """Normalized engineering DTC trigger definitions from one or more source files."""

    definitions: list[DTCTriggerDefinition] = Field(default_factory=list)
    issues: list[ImportIssue] = Field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return not any(issue.severity == ImportSeverity.ERROR for issue in self.issues)


class ParsedECUChangeCatalog(BaseModel):
    """Normalized HW/SW/calibration change history."""

    changes: list[ECUChangeRecord] = Field(default_factory=list)
    issues: list[ImportIssue] = Field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return not any(issue.severity == ImportSeverity.ERROR for issue in self.issues)
