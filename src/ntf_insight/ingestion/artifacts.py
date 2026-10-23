"""Immutable source-artifact metadata, parsing provenance and raw-file archiving."""

from __future__ import annotations

import hashlib
import shutil
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class SourceType(StrEnum):
    VEHICLE_CASE_LIST = "vehicle_case_list"
    QEC_REPORT = "qec_report"
    SHORT_TEST = "short_test"
    TP_DASHBOARD = "tp_dashboard"
    REPLACEMENT_LIST = "replacement_list"
    SUPPLIER_FINDING = "supplier_finding"
    WORKSHOP_HISTORY = "workshop_history"
    SMR_D = "smr_d"
    DIAGNOSTIC_DESCRIPTION = "diagnostic_description"
    PART_HISTORY = "part_history"
    AUTOEXPORT_SUMMARY = "autoexport_summary"
    TIPS_CASE = "tips_case"
    HW_SW_CHANGE_HISTORY = "hw_sw_change_history"
    VEHICLE_SOFTWARE_HISTORY = "vehicle_software_history"
    INSTALLED_POPULATION = "installed_population"
    COMPONENT_MASTER_DATA = "component_master_data"
    OTHER = "other"


class ParseStatus(StrEnum):
    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"


class SourceArtifact(BaseModel):
    """Immutable identity/provenance of one original source file."""

    model_config = ConfigDict(frozen=True)

    sha256: str
    source_type: SourceType
    original_name: str
    archived_path: str
    size_bytes: int
    imported_at: datetime
    source_system: str | None = None
    vin_hint: str | None = None
    case_id_hint: str | None = None
    remote_ref: str | None = None
    report_date: datetime | None = None


class ParseRun(BaseModel):
    """Versioned record of one parser execution against an immutable artifact."""

    model_config = ConfigDict(frozen=True)

    run_id: str = Field(default_factory=lambda: uuid4().hex)
    artifact_sha256: str
    parser_name: str
    parser_version: str
    status: ParseStatus
    started_at: datetime
    completed_at: datetime | None = None
    records_emitted: int = Field(default=0, ge=0)
    issue_count: int = Field(default=0, ge=0)
    error_message: str | None = None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class RawArchive:
    """Content-addressed immutable archive for original input files."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def archive(
        self,
        source: Path,
        source_type: SourceType,
        *,
        source_system: str | None = None,
        vin_hint: str | None = None,
        case_id_hint: str | None = None,
        remote_ref: str | None = None,
        report_date: datetime | None = None,
    ) -> SourceArtifact:
        source = source.expanduser().resolve()
        if not source.is_file():
            raise FileNotFoundError(source)

        digest = sha256_file(source)
        target_dir = self.root / digest[:2]
        target_dir.mkdir(parents=True, exist_ok=True)
        suffix = "".join(source.suffixes) or ".bin"
        target = target_dir / f"{digest}{suffix}"
        if not target.exists():
            shutil.copy2(source, target)

        return SourceArtifact(
            sha256=digest,
            source_type=source_type,
            original_name=source.name,
            archived_path=str(target),
            size_bytes=source.stat().st_size,
            imported_at=datetime.now(timezone.utc),
            source_system=source_system,
            vin_hint=vin_hint,
            case_id_hint=case_id_hint,
            remote_ref=remote_ref,
            report_date=report_date,
        )
