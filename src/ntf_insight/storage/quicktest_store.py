"""Query-friendly local DuckDB storage of complete QuickTest observations.

Vehicle diagnostics belong to their FIN even when no QEC repair case exists.
The QuickTest tables are therefore independent from the case_snapshots table.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from ntf_insight.storage.duckdb_store import DuckDBStore


class QuickTestStore:
    """Normalized report / ECU / DTC / parameter / PDF-text persistence."""

    def __init__(self, store: DuckDBStore, *, initialize: bool = True) -> None:
        self.store = store
        # On a self-hosted analysis runner, a ReadOnlyCaseStore is passed
        # with initialize=False. Never emit CREATE TABLE/INDEX in that mode.
        if not initialize:
            return
        with self.store.connect() as con:
            con.execute("""
                CREATE TABLE IF NOT EXISTS quicktest_reports (
                    report_id VARCHAR PRIMARY KEY,
                    fin VARCHAR NOT NULL,
                    vin VARCHAR,
                    diagnosed_at TIMESTAMP NOT NULL,
                    mileage_km BIGINT,
                    ecu_count INTEGER NOT NULL,
                    dtc_count INTEGER NOT NULL,
                    header_json VARCHAR NOT NULL,
                    first_source_sha256 VARCHAR NOT NULL,
                    imported_at TIMESTAMP NOT NULL
                )
            """)
            con.execute("""
                CREATE TABLE IF NOT EXISTS quicktest_sources (
                    artifact_sha256 VARCHAR PRIMARY KEY,
                    report_id VARCHAR NOT NULL
                )
            """)
            con.execute("""
                CREATE TABLE IF NOT EXISTS quicktest_pages (
                    report_id VARCHAR NOT NULL,
                    page_number INTEGER NOT NULL,
                    text_content VARCHAR NOT NULL,
                    PRIMARY KEY(report_id, page_number)
                )
            """)
            con.execute("""
                CREATE TABLE IF NOT EXISTS quicktest_ecus (
                    report_id VARCHAR NOT NULL,
                    ecu_index INTEGER NOT NULL,
                    ecu_code VARCHAR NOT NULL,
                    location VARCHAR,
                    ecu_name VARCHAR,
                    metadata_json VARCHAR NOT NULL,
                    reported_fault_count INTEGER NOT NULL,
                    page_start INTEGER,
                    page_end INTEGER,
                    raw_block_text VARCHAR NOT NULL,
                    PRIMARY KEY(report_id, ecu_index)
                )
            """)
            con.execute("""
                CREATE TABLE IF NOT EXISTS quicktest_dtcs (
                    report_id VARCHAR NOT NULL,
                    ecu_index INTEGER NOT NULL,
                    dtc_index INTEGER NOT NULL,
                    ecu_code VARCHAR NOT NULL,
                    kind VARCHAR,
                    dtc_code VARCHAR NOT NULL,
                    description VARCHAR,
                    status VARCHAR,
                    frequency_counter INTEGER,
                    original_odometer_km BIGINT,
                    most_recent_odometer_km BIGINT,
                    ignition_cycle_counter INTEGER,
                    page_start INTEGER,
                    page_end INTEGER,
                    raw_block_text VARCHAR NOT NULL,
                    PRIMARY KEY(report_id, ecu_index, dtc_index)
                )
            """)
            con.execute("""
                CREATE TABLE IF NOT EXISTS quicktest_parameters (
                    report_id VARCHAR NOT NULL,
                    ecu_index INTEGER NOT NULL,
                    dtc_index INTEGER NOT NULL,
                    parameter_index INTEGER NOT NULL,
                    parameter_name VARCHAR NOT NULL,
                    first_value VARCHAR,
                    last_value VARCHAR,
                    page_number INTEGER,
                    PRIMARY KEY(report_id, ecu_index, dtc_index, parameter_index)
                )
            """)

    def save_report(self, report: dict[str, Any], artifact_sha256: str) -> bool:
        """Persist a full report once, link every source PDF independently.

        Returns True if a new logical report was inserted; false for a reimport.
        The transaction ensures users never see partial ECU/DTC pages.
        """
        report_id = report["report_id"]
        with self.store.connect() as con:
            con.execute("BEGIN TRANSACTION")
            try:
                found = con.execute(
                    "SELECT fin FROM quicktest_reports WHERE report_id = ?",
                    [report_id],
                ).fetchone()
                if found:
                    if found[0] != report["fin"]:
                        raise ValueError("QuickTest-Duplikat mit widersprüchlicher FIN.")
                else:
                    con.execute(
                        """
                        INSERT INTO quicktest_reports VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        [
                            report_id,
                            report["fin"],
                            report.get("vin"),
                            datetime.fromisoformat(report["diag_start"]),
                            report.get("distance_km"),
                            report["reported_ecu_count"],
                            report["observed_dtc_count"],
                            json.dumps(report["header"], ensure_ascii=False),
                            artifact_sha256,
                            datetime.now(),
                        ],
                    )
                    for index, page_text in enumerate(report["page_texts"], start=1):
                        con.execute(
                            "INSERT INTO quicktest_pages VALUES (?, ?, ?)",
                            [report_id, index, page_text],
                        )
                    for ecu in report["ecus"]:
                        ecu_index = ecu["ecu_index"]
                        con.execute(
                            "INSERT INTO quicktest_ecus VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            [
                                report_id, ecu_index, ecu["ecu_code"],
                                ecu.get("location"), ecu.get("name"),
                                json.dumps(ecu["metadata"], ensure_ascii=False),
                                ecu["reported_fault_count"],
                                ecu["page_start"], ecu["page_end"], ecu["raw_block_text"],
                            ],
                        )
                        for dtc_index, fault in enumerate(ecu["faults"], start=1):
                            con.execute(
                                """
                                INSERT INTO quicktest_dtcs
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                """,
                                [
                                    report_id, ecu_index, dtc_index, ecu["ecu_code"],
                                    fault["kind"], fault["code"], fault["description"],
                                    fault["status"], fault["frequency_counter"],
                                    fault["original_odometer_km"],
                                    fault["most_recent_odometer_km"],
                                    fault["ignition_cycle_counter"],
                                    fault["page_start"], fault["page_end"],
                                    fault["raw_block_text"],
                                ],
                            )
                            for parameter_index, param in enumerate(
                                fault["parameters"], start=1
                            ):
                                con.execute(
                                    """
                                    INSERT INTO quicktest_parameters
                                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                                    """,
                                    [
                                        report_id, ecu_index, dtc_index, parameter_index,
                                        param["name"], param["first_value"],
                                        param["last_value"], param["page"],
                                    ],
                                )
                con.execute(
                    """
                    INSERT INTO quicktest_sources VALUES (?, ?)
                    ON CONFLICT(artifact_sha256) DO NOTHING
                    """,
                    [artifact_sha256, report_id],
                )
                con.execute("COMMIT")
            except Exception:
                con.execute("ROLLBACK")
                raise
        return found is None

    def report_summaries_for_fins(
        self, fins: set[str]
    ) -> dict[str, list[tuple[datetime, int]]]:
        """All original FIN QuickTest report timestamps, including zero-DTC tests.

        No QEC assignment is inferred and no source PDF is materialized.
        The count is the reported DTC count, not an independent fault event.
        """
        if not fins:
            return {}
        summaries: dict[str, list[tuple[datetime, int]]] = {}
        with self.store.connect() as con:
            for fin in sorted(fins):
                rows = con.execute(
                    """SELECT diagnosed_at, dtc_count
                       FROM quicktest_reports
                       WHERE fin = ?
                       ORDER BY diagnosed_at, report_id""",
                    [fin],
                ).fetchall()
                summaries[fin] = [
                    (observed_at, int(count)) for observed_at, count in rows
                ]
        return summaries

    def diagnostic_times_for_fins(
        self, fins: set[str]
    ) -> dict[str, list[tuple[datetime, int]]]:
        """Count source-reported QuickTest DTCs by FIN/session, not by QEC."""
        if not fins:
            return {}
        output: dict[str, list[tuple[datetime, int]]] = {}
        with self.store.connect() as con:
            for fin in sorted(fins):
                rows = con.execute(
                    """SELECT r.diagnosed_at, COUNT(d.dtc_index)
                       FROM quicktest_reports AS r
                       JOIN quicktest_dtcs AS d ON d.report_id = r.report_id
                       WHERE r.fin = ?
                       GROUP BY r.report_id, r.diagnosed_at
                       ORDER BY r.diagnosed_at""",
                    [fin],
                ).fetchall()
                output[fin] = [(when, int(count)) for when, count in rows]
        return output

    def list_fins(self) -> list[str]:
        with self.store.connect() as con:
            return [
                row[0] for row in con.execute(
                    "SELECT DISTINCT fin FROM quicktest_reports ORDER BY fin"
                ).fetchall()
            ]

    def list_reports(self, fin: str | None = None) -> list[dict]:
        query = (
            "SELECT report_id, fin, vin, diagnosed_at, mileage_km, ecu_count, dtc_count, "
            "header_json FROM quicktest_reports"
        )
        args: list[str] = []
        if fin is not None:
            query += " WHERE fin = ?"
            args.append(fin)
        query += " ORDER BY diagnosed_at DESC, report_id"
        with self.store.connect() as con:
            rows = con.execute(query, args).fetchall()
        return [
            {
                "report_id": row[0],
                "fin": row[1],
                "vin": row[2],
                "diagnosed_at": row[3],
                "mileage_km": row[4],
                "ecu_count": row[5],
                "dtc_count": row[6],
                "header": json.loads(row[7]),
            }
            for row in rows
        ]

    def list_ecus(self, report_id: str) -> list[dict]:
        with self.store.connect() as con:
            rows = con.execute(
                """
                SELECT ecu_index, ecu_code, location, ecu_name, metadata_json,
                       reported_fault_count, page_start, page_end, raw_block_text
                FROM quicktest_ecus WHERE report_id = ? ORDER BY ecu_index
                """,
                [report_id],
            ).fetchall()
        return [
            {
                "ecu_index": row[0], "ecu_code": row[1],
                "location": row[2], "name": row[3],
                "metadata": json.loads(row[4]),
                "dtc_count": row[5], "page_start": row[6],
                "page_end": row[7], "raw_block_text": row[8],
            }
            for row in rows
        ]

    def list_dtcs(self, report_id: str, ecu_index: int | None = None) -> list[dict]:
        query = (
            "SELECT ecu_index, dtc_index, ecu_code, kind, dtc_code, description,"
            " status, frequency_counter, original_odometer_km, most_recent_odometer_km,"
            " ignition_cycle_counter, page_start, page_end, raw_block_text"
            " FROM quicktest_dtcs WHERE report_id = ?"
        )
        args: list[Any] = [report_id]
        if ecu_index is not None:
            query += " AND ecu_index = ?"
            args.append(ecu_index)
        query += " ORDER BY ecu_index, dtc_index"
        with self.store.connect() as con:
            rows = con.execute(query, args).fetchall()
        return [
            {
                "ecu_index": row[0], "dtc_index": row[1],
                "ecu_code": row[2], "kind": row[3],
                "dtc_code": row[4], "description": row[5],
                "status": row[6], "frequency_counter": row[7],
                "original_odometer_km": row[8],
                "most_recent_odometer_km": row[9],
                "ignition_cycle_counter": row[10],
                "page_start": row[11], "page_end": row[12],
                "raw_block_text": row[13],
            }
            for row in rows
        ]

    def list_parameters(
        self, report_id: str, ecu_index: int, dtc_index: int
    ) -> list[dict]:
        with self.store.connect() as con:
            rows = con.execute(
                """
                SELECT parameter_name, first_value, last_value, page_number
                FROM quicktest_parameters
                WHERE report_id = ? AND ecu_index = ? AND dtc_index = ?
                ORDER BY parameter_index
                """,
                [report_id, ecu_index, dtc_index],
            ).fetchall()
        return [
            {
                "name": row[0], "first_value": row[1],
                "last_value": row[2], "page": row[3],
            }
            for row in rows
        ]

    def page_text(self, report_id: str, page: int) -> str | None:
        with self.store.connect() as con:
            row = con.execute(
                """
                SELECT text_content FROM quicktest_pages
                WHERE report_id = ? AND page_number = ?
                """,
                [report_id, page],
            ).fetchone()
        return row[0] if row else None

    def case_projection(self, report_id: str):
        """Recreate canonical events after a QEC case arrives later.

        The independently saved PDF remains the source of truth. A case only
        receives a projection when FIN and repair time permit safe matching.
        """
        from ntf_insight.domain.events import (
            DiagnosticEvent, DiagnosticSession, ECUStateObservation,
        )
        from ntf_insight.ingestion.quicktest_detailed import _identifier

        with self.store.connect() as con:
            report = con.execute(
                """
                SELECT fin, vin, diagnosed_at, mileage_km, ecu_count, dtc_count,
                       first_source_sha256
                FROM quicktest_reports WHERE report_id = ?
                """,
                [report_id],
            ).fetchone()
            if not report:
                return [], [], []
            ecu_rows = con.execute(
                """
                SELECT ecu_index, ecu_code, metadata_json
                FROM quicktest_ecus WHERE report_id = ? ORDER BY ecu_index
                """,
                [report_id],
            ).fetchall()
            dtc_rows = con.execute(
                """
                SELECT ecu_index, dtc_index, ecu_code, kind, dtc_code,
                       description, status, frequency_counter,
                       original_odometer_km, most_recent_odometer_km,
                       ignition_cycle_counter
                FROM quicktest_dtcs WHERE report_id = ?
                ORDER BY ecu_index, dtc_index
                """,
                [report_id],
            ).fetchall()
            parameter_rows = con.execute(
                """
                SELECT ecu_index, dtc_index, parameter_name, first_value,
                       last_value, page_number
                FROM quicktest_parameters WHERE report_id = ?
                ORDER BY ecu_index, dtc_index, parameter_index
                """,
                [report_id],
            ).fetchall()

        fin, vehicle_vin, when, km, ecu_count, dtc_count, source_sha = report
        session_id = _identifier(report_id, "session")
        reference = f"raw:{source_sha}"
        sessions = [DiagnosticSession(
            event_id=_identifier(report_id, "session:event"),
            session_id=session_id, vin=fin, occurred_at=when, mileage_km=km,
            label="QuickTest PDF", ecu_count=ecu_count, dtc_count=dtc_count,
            source_ref=f"{reference}#session", report_id=report_id,
            report_vin_usa=vehicle_vin, source_is_complete_quicktest=True,
        )]
        states = []
        for ecu_index, code, metadata_json in ecu_rows:
            metadata = json.loads(metadata_json)
            states.append(ECUStateObservation(
                event_id=_identifier(report_id, f"ecu:{ecu_index}:state"),
                vin=fin, occurred_at=when, mileage_km=km,
                session_id=session_id, ecu=code,
                software_version=metadata.get("software_version"),
                hardware_version=metadata.get("hardware_version"),
                source_ref=f"{reference}#ecu:{ecu_index}",
                hardware_part_number=metadata.get("hardware_partnumber"),
                supplier=metadata.get("supplier"),
                ecu_variant=metadata.get("ecu_variant"),
            ))
        params: dict[tuple[int, int], list[dict]] = {}
        for ecu_index, dtc_index, name, first, last, page in parameter_rows:
            params.setdefault((ecu_index, dtc_index), []).append({
                "name": name, "first_value": first,
                "last_value": last, "page": page,
            })
        diagnostics = []
        for (
            ecu_index, dtc_index, code, kind, dtc_code, description,
            status, frequency, original_km, recent_km, cycles,
        ) in dtc_rows:
            diagnostics.append(DiagnosticEvent(
                event_id=_identifier(report_id, f"ecu:{ecu_index}:dtc:{dtc_index}"),
                vin=fin, occurred_at=when, mileage_km=km,
                session_id=session_id, ecu=code, dtc_code=dtc_code,
                dtc_text=description, status=status,
                occurrence_count=frequency,
                freeze_frame={
                    "kind": kind, "original_odometer_km": original_km,
                    "most_recent_odometer_km": recent_km,
                    "ignition_cycle_counter": cycles,
                    "parameters": params.get((ecu_index, dtc_index), []),
                    "observed_at_diagnostic_test": True,
                },
                source_ref=f"{reference}#ecu:{ecu_index}:dtc:{dtc_index}",
            ))
        return sessions, diagnostics, states

    def statistics(self) -> dict[str, int]:
        with self.store.connect() as con:
            return {
                "reports": con.execute("SELECT COUNT(*) FROM quicktest_reports").fetchone()[0],
                "ecus": con.execute("SELECT COUNT(*) FROM quicktest_ecus").fetchone()[0],
                "dtcs": con.execute("SELECT COUNT(*) FROM quicktest_dtcs").fetchone()[0],
                "parameters": con.execute(
                    "SELECT COUNT(*) FROM quicktest_parameters"
                ).fetchone()[0],
            }
