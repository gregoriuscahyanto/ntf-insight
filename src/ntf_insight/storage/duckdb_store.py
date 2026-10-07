"""Local DuckDB persistence for normalized case and reference snapshots."""

from __future__ import annotations

from pathlib import Path

import duckdb

from ntf_insight.domain.case import NTFCase
from ntf_insight.domain.reference import DTCTriggerDefinition, ECUChangeRecord
from ntf_insight.ingestion.artifacts import SourceArtifact


class DuckDBStore:
    """Small local persistence layer suitable for the desktop prototype.

    Canonical Pydantic objects are persisted as JSON snapshots with indexed identity columns.
    Analytical/materialized tables can be added later without changing the domain API.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def connect(self):
        return duckdb.connect(str(self.path))

    def initialize(self) -> None:
        with self.connect() as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS source_artifacts (
                    sha256 VARCHAR PRIMARY KEY,
                    source_type VARCHAR NOT NULL,
                    original_name VARCHAR NOT NULL,
                    payload_json VARCHAR NOT NULL
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS case_snapshots (
                    case_id VARCHAR PRIMARY KEY,
                    vin VARCHAR NOT NULL,
                    component_type VARCHAR NOT NULL,
                    payload_json VARCHAR NOT NULL
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS dtc_trigger_definitions (
                    definition_id VARCHAR PRIMARY KEY,
                    ecu VARCHAR NOT NULL,
                    dtc_code VARCHAR NOT NULL,
                    payload_json VARCHAR NOT NULL
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS ecu_change_records (
                    change_id VARCHAR PRIMARY KEY,
                    ecu VARCHAR NOT NULL,
                    payload_json VARCHAR NOT NULL
                )
                """
            )

    def save_artifact(self, artifact: SourceArtifact) -> None:
        with self.connect() as con:
            con.execute(
                """
                INSERT INTO source_artifacts VALUES (?, ?, ?, ?)
                ON CONFLICT(sha256) DO UPDATE SET
                    source_type = excluded.source_type,
                    original_name = excluded.original_name,
                    payload_json = excluded.payload_json
                """,
                [
                    artifact.sha256,
                    str(artifact.source_type),
                    artifact.original_name,
                    artifact.model_dump_json(),
                ],
            )

    def load_artifacts(self) -> list[SourceArtifact]:
        with self.connect() as con:
            rows = con.execute(
                "SELECT payload_json FROM source_artifacts ORDER BY original_name"
            ).fetchall()
        return [SourceArtifact.model_validate_json(row[0]) for row in rows]

    def save_case(self, case: NTFCase) -> None:
        with self.connect() as con:
            con.execute(
                """
                INSERT INTO case_snapshots VALUES (?, ?, ?, ?)
                ON CONFLICT(case_id) DO UPDATE SET
                    vin = excluded.vin,
                    component_type = excluded.component_type,
                    payload_json = excluded.payload_json
                """,
                [case.case_id, case.vin, case.component_type, case.model_dump_json()],
            )

    def save_cases(self, cases: list[NTFCase]) -> None:
        for case in cases:
            self.save_case(case)

    def load_cases(self) -> list[NTFCase]:
        with self.connect() as con:
            rows = con.execute(
                "SELECT payload_json FROM case_snapshots ORDER BY case_id"
            ).fetchall()
        return [NTFCase.model_validate_json(row[0]) for row in rows]

    def save_trigger(self, trigger: DTCTriggerDefinition) -> None:
        with self.connect() as con:
            con.execute(
                """
                INSERT INTO dtc_trigger_definitions VALUES (?, ?, ?, ?)
                ON CONFLICT(definition_id) DO UPDATE SET
                    ecu = excluded.ecu,
                    dtc_code = excluded.dtc_code,
                    payload_json = excluded.payload_json
                """,
                [trigger.definition_id, trigger.ecu, trigger.dtc_code, trigger.model_dump_json()],
            )

    def save_change(self, change: ECUChangeRecord) -> None:
        with self.connect() as con:
            con.execute(
                """
                INSERT INTO ecu_change_records VALUES (?, ?, ?)
                ON CONFLICT(change_id) DO UPDATE SET
                    ecu = excluded.ecu,
                    payload_json = excluded.payload_json
                """,
                [change.change_id, change.ecu, change.model_dump_json()],
            )

    def save_reference_data(
        self,
        triggers: list[DTCTriggerDefinition],
        changes: list[ECUChangeRecord],
    ) -> None:
        for trigger in triggers:
            self.save_trigger(trigger)
        for change in changes:
            self.save_change(change)

    def load_triggers(self) -> list[DTCTriggerDefinition]:
        with self.connect() as con:
            rows = con.execute(
                "SELECT payload_json FROM dtc_trigger_definitions ORDER BY definition_id"
            ).fetchall()
        return [DTCTriggerDefinition.model_validate_json(row[0]) for row in rows]

    def load_changes(self) -> list[ECUChangeRecord]:
        with self.connect() as con:
            rows = con.execute(
                "SELECT payload_json FROM ecu_change_records ORDER BY change_id"
            ).fetchall()
        return [ECUChangeRecord.model_validate_json(row[0]) for row in rows]
