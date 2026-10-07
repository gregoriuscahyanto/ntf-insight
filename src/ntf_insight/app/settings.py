"""Local desktop application settings."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class AppPaths:
    data_dir: Path
    raw_dir: Path
    database_path: Path

    @classmethod
    def default(cls) -> "AppPaths":
        configured = os.environ.get("NTF_INSIGHT_DATA_DIR")
        data_dir = Path(configured).expanduser() if configured else Path.home() / ".ntf-insight"
        return cls(
            data_dir=data_dir,
            raw_dir=data_dir / "raw",
            database_path=data_dir / "ntf-insight.duckdb",
        )

    def ensure(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.raw_dir.mkdir(parents=True, exist_ok=True)
