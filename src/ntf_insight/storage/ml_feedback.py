"""Local expert feedback: separately versioned from provisional case assessments."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import duckdb

from ntf_insight.analysis.root_cause_ml import ConfirmedCause
from ntf_insight.domain.enums import RootCauseCategory


class MLFeedbackStore:
    def __init__(self, database_path: Path) -> None:
        self.path = Path(database_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with duckdb.connect(str(self.path)) as con:
            con.execute("""
                CREATE TABLE IF NOT EXISTS confirmed_root_causes (
                    case_id VARCHAR PRIMARY KEY,
                    cause VARCHAR NOT NULL,
                    reviewer VARCHAR NOT NULL,
                    evidence_ref VARCHAR NOT NULL,
                    confirmed_at TIMESTAMP NOT NULL
                )
            """)

    def save(self, record: ConfirmedCause) -> None:
        with duckdb.connect(str(self.path)) as con:
            con.execute(
                """INSERT INTO confirmed_root_causes VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(case_id) DO UPDATE SET
                    cause=excluded.cause, reviewer=excluded.reviewer,
                    evidence_ref=excluded.evidence_ref, confirmed_at=excluded.confirmed_at""",
                [record.case_id, record.cause.value, record.reviewer,
                 record.evidence_ref, record.confirmed_at],
            )

    def confirm(
        self, case_id: str, cause: RootCauseCategory, reviewer: str, evidence_ref: str
    ) -> ConfirmedCause:
        label = ConfirmedCause(
            case_id=case_id, cause=cause, reviewer=reviewer,
            evidence_ref=evidence_ref, confirmed_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        self.save(label)
        return label

    def list_confirmed(self) -> list[ConfirmedCause]:
        with duckdb.connect(str(self.path)) as con:
            rows = con.execute(
                """SELECT case_id, cause, reviewer, evidence_ref, confirmed_at
                FROM confirmed_root_causes ORDER BY case_id"""
            ).fetchall()
        return [
            ConfirmedCause(case_id=row[0], cause=RootCauseCategory(row[1]),
                           reviewer=row[2], evidence_ref=row[3], confirmed_at=row[4])
            for row in rows
        ]
