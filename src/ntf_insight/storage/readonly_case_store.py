"""Strictly read-only access to an *existing* local NTF Insight DuckDB file.

The desktop DuckDBStore initializes/migrates tables on construction and is
therefore intentionally NOT suitable for unattended read-only runner jobs.
"""
from __future__ import annotations

from pathlib import Path

import duckdb

from ntf_insight.domain.case import NTFCase


class ReadOnlyCaseStore:
    def __init__(self, path: Path) -> None:
        source = Path(path).expanduser()
        if not source.is_file():
            raise FileNotFoundError("Die bestehende NTF-Datenbank wurde nicht gefunden.")
        self.path = source

    def connect(self) -> duckdb.DuckDBPyConnection:
        """A connection that rejects INSERT, DDL, and all database writes."""
        return duckdb.connect(str(self.path), read_only=True)

    def tables(self) -> frozenset[str]:
        with self.connect() as con:
            return frozenset(
                row[0] for row in con.execute(
                    """SELECT table_name FROM information_schema.tables
                       WHERE table_schema = 'main'"""
                ).fetchall()
            )

    def load_cases(self) -> list[NTFCase]:
        with self.connect() as con:
            rows = con.execute(
                "SELECT payload_json FROM case_snapshots ORDER BY case_id"
            ).fetchall()
        return [NTFCase.model_validate_json(value) for (value,) in rows]
