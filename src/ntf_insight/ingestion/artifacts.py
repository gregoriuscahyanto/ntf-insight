"""Immutable source-artifact metadata and raw-file archiving."""

from __future__ import annotations

import hashlib
import shutil
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict


class SourceType(StrEnum):
    SHORT_TEST = "short_test"
    REPLACEMENT_LIST = "replacement_list"
    SUPPLIER_FINDING = "supplier_finding"
    WORKSHOP_HISTORY = "workshop_history"
    SMR_D = "smr_d"
    HW_SW_CHANGE_HISTORY = "hw_sw_change_history"
    VEHICLE_SOFTWARE_HISTORY = "vehicle_software_history"
    OTHER = "other"


class SourceArtifact(BaseModel):
    model_config = ConfigDict(frozen=True)

    sha256: str
    source_type: SourceType
    original_name: str
    archived_path: str
    size_bytes: int
    imported_at: datetime
    parser_name: str | None = None
    parser_version: str | None = None


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
        parser_name: str | None = None,
        parser_version: str | None = None,
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
            parser_name=parser_name,
            parser_version=parser_version,
        )
