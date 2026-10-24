"""Project-scoped acquisition attempt timestamps, distinct from file import dates."""
from __future__ import annotations

from datetime import datetime, timezone

from ntf_insight.storage.cluster_evidence_store import part_key
from ntf_insight.storage.duckdb_store import DuckDBStore

CATEGORIES = frozenset({
    "tp_dashboard", "diagnosis_viewer", "tips_writer", "celonis", "cdd_smrd",
})


class WorkflowSourceActivity:
    def __init__(self, store: DuckDBStore) -> None:
        self.store = store
        with store.connect() as con:
            con.execute("""
                CREATE TABLE IF NOT EXISTS workflow_source_activity (
                    profile_id VARCHAR NOT NULL,
                    part_key VARCHAR NOT NULL,
                    category VARCHAR NOT NULL,
                    attempted_at TIMESTAMP NOT NULL,
                    result VARCHAR NOT NULL,
                    PRIMARY KEY(profile_id,part_key,category)
                )
            """)
            con.execute("""
                CREATE TABLE IF NOT EXISTS workflow_source_log (
                    profile_id VARCHAR NOT NULL,
                    part_key VARCHAR NOT NULL,
                    category VARCHAR NOT NULL,
                    event_type VARCHAR NOT NULL,
                    attempted_at TIMESTAMP NOT NULL,
                    result VARCHAR NOT NULL,
                    PRIMARY KEY(profile_id,part_key,category,event_type)
                )
            """)

    def record(self, profile: str, part: str, category: str, result: str) -> None:
        if category not in CATEGORIES or result not in {
            "Gestartet", "Abgeschlossen", "Fehlgeschlagen", "Abgebrochen",
            "Einlesen gestartet", "Eingelesen", "Archiviert",
        }:
            raise ValueError("Ungültiger Quellenabrufstatus.")
        with self.store.connect() as con:
            event_type = (
                "Einlesen" if result in {
                    "Einlesen gestartet", "Eingelesen", "Archiviert",
                } else "Abruf"
            )
            con.execute(
                "INSERT INTO workflow_source_log VALUES (?,?,?,?,?,?) "
                "ON CONFLICT (profile_id,part_key,category,event_type) "
                "DO UPDATE SET attempted_at=excluded.attempted_at,"
                "result=excluded.result",
                [
                    profile, part_key(part), category, event_type,
                    datetime.now(timezone.utc).replace(tzinfo=None), result,
                ],
            )
            con.execute(
                "INSERT INTO workflow_source_activity VALUES (?,?,?,?,?) "
                "ON CONFLICT (profile_id,part_key,category) DO UPDATE "
                "SET attempted_at=excluded.attempted_at,result=excluded.result",
                [
                    profile, part_key(part), category,
                    datetime.now(timezone.utc).replace(tzinfo=None), result,
                ],
            )

    def get(self, profile: str, part: str) -> dict[str, tuple[datetime, str]]:
        with self.store.connect() as con:
            rows = con.execute(
                "SELECT category,attempted_at,result FROM workflow_source_activity "
                "WHERE profile_id=? AND part_key=?",
                [profile, part_key(part)],
            ).fetchall()
        return {category: (at, result) for category, at, result in rows}


    def get_details(
        self, profile: str, part: str,
    ) -> dict[str, dict[str, tuple[datetime, str]]]:
        """Abrufdatum und Einlesedatum bleiben unabhängig voneinander erhalten."""
        with self.store.connect() as con:
            rows = con.execute(
                "SELECT category,event_type,attempted_at,result "
                "FROM workflow_source_log WHERE profile_id=? AND part_key=?",
                [profile, part_key(part)],
            ).fetchall()
        output: dict[str, dict[str, tuple[datetime, str]]] = {}
        for category, event_type, at, result in rows:
            output.setdefault(category, {})[event_type] = (at, result)
        return output
