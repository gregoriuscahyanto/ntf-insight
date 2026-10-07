"""Models for batch report acquisition."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ntf_insight.ingestion.artifacts import SourceArtifact, SourceType


@dataclass(frozen=True, slots=True)
class DownloadedSource:
    path: Path
    source_type: SourceType
    remote_ref: str | None = None


@dataclass(frozen=True, slots=True)
class AcquisitionIssue:
    vin: str
    provider: str
    message: str


@dataclass(slots=True)
class AcquisitionResult:
    artifacts: list[SourceArtifact] = field(default_factory=list)
    issues: list[AcquisitionIssue] = field(default_factory=list)
