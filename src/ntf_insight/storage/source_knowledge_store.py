"""Relational local storage for CDD, QEC, Part History and AutoExport data.

Original source files remain immutable; derived rows are keyed by source SHA256
and row number, so reparsing is idempotent and provenance stays traceable.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Iterable

from ntf_insight.storage.duckdb_store import DuckDBStore


class SourceKnowledgeStore:
    def __init__(self, store: DuckDBStore, *, initialize: bool = True) -> None:
        self.store = store
        # On a self-hosted analysis runner, a ReadOnlyCaseStore is passed
        # with initialize=False. Never emit CREATE TABLE/INDEX in that mode.
        if not initialize:
            return
        with self.store.connect() as con:
            con.execute("""
                CREATE TABLE IF NOT EXISTS source_knowledge_documents (
                    source_sha256 VARCHAR PRIMARY KEY,
                    source_kind VARCHAR NOT NULL,
                    metadata_json VARCHAR NOT NULL,
                    row_count INTEGER NOT NULL,
                    updated_at TIMESTAMP NOT NULL
                )
            """)
            con.execute("""
                CREATE TABLE IF NOT EXISTS source_knowledge_rows (
                    source_sha256 VARCHAR NOT NULL,
                    record_number INTEGER NOT NULL,
                    category VARCHAR NOT NULL,
                    source_location VARCHAR NOT NULL,
                    fin VARCHAR,
                    reference VARCHAR,
                    label VARCHAR,
                    payload_json VARCHAR NOT NULL,
                    PRIMARY KEY(source_sha256, record_number)
                )
            """)
            con.execute("""
                CREATE INDEX IF NOT EXISTS idx_knowledge_fin
                ON source_knowledge_rows(fin)
            """)
            con.execute("""
                CREATE INDEX IF NOT EXISTS idx_knowledge_category
                ON source_knowledge_rows(category)
            """)

    def save_records(
        self,
        source_sha: str,
        source_kind: str,
        records: Iterable[dict],
        *,
        metadata: dict | None = None,
        maximum_rows: int = 250_000,
    ) -> int:
        """Replace one source's derived rows atomically, preserving the original.

        Supports generators to avoid loading large AutoExport files into RAM.
        """
        count = 0
        with self.store.connect() as con:
            con.execute("BEGIN TRANSACTION")
            try:
                con.execute(
                    "DELETE FROM source_knowledge_rows WHERE source_sha256 = ?",
                    [source_sha],
                )
                batch = []
                for row in records:
                    count += 1
                    if count > maximum_rows:
                        raise ValueError("Quelldatei enthält mehr Datenzeilen als erlaubt.")
                    batch.append((
                        source_sha,
                        count,
                        str(row["category"]),
                        str(row.get("source_location") or f"row:{count}"),
                        str(row["fin"]) if row.get("fin") else None,
                        str(row["reference"]) if row.get("reference") else None,
                        str(row.get("label") or ""),
                        json.dumps(row.get("data", {}), ensure_ascii=False, default=str),
                    ))
                    if len(batch) >= 500:
                        con.executemany(
                            """
                            INSERT INTO source_knowledge_rows VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            batch,
                        )
                        batch.clear()
                if batch:
                    con.executemany(
                        "INSERT INTO source_knowledge_rows VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        batch,
                    )
                con.execute(
                    """
                    INSERT INTO source_knowledge_documents
                        (source_sha256, source_kind, metadata_json, row_count, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT (source_sha256) DO UPDATE SET
                        source_kind = excluded.source_kind,
                        metadata_json = excluded.metadata_json,
                        row_count = excluded.row_count,
                        updated_at = excluded.updated_at
                    """,
                    [
                        source_sha,
                        source_kind,
                        json.dumps(metadata or {}, ensure_ascii=False, default=str),
                        count,
                        datetime.now(),
                    ],
                )
                con.execute("COMMIT")
            except Exception:
                con.execute("ROLLBACK")
                raise
        return count

    def summary(self) -> dict[str, int]:
        with self.store.connect() as con:
            rows = con.execute(
                """
                SELECT source_kind, SUM(row_count)
                FROM source_knowledge_documents
                GROUP BY source_kind
                """
            ).fetchall()
        return {key: int(value) for key, value in rows}

    def documents(self) -> list[dict]:
        with self.store.connect() as con:
            rows = con.execute(
                """
                SELECT source_sha256, source_kind, metadata_json, row_count, updated_at
                FROM source_knowledge_documents
                ORDER BY updated_at DESC, source_sha256
                """
            ).fetchall()
        return [
            {
                "source_sha256": row[0],
                "source_kind": row[1],
                "metadata": json.loads(row[2]),
                "row_count": row[3],
                "updated_at": row[4],
            }
            for row in rows
        ]

    def list_rows(
        self,
        *,
        category: str | None = None,
        fin: str | None = None,
        search: str | None = None,
        limit: int = 500,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Return bounded, searchable source rows (no raw repository data)."""
        filters = []
        args: list[Any] = []
        if category:
            filters.append("category = ?")
            args.append(category)
        if fin:
            filters.append("fin = ?")
            args.append(fin)
        if search:
            filters.append(
                "(lower(coalesce(reference,'')) LIKE ? OR lower(coalesce(label,'')) LIKE ? "
                "OR lower(coalesce(fin,'')) LIKE ? OR lower(payload_json) LIKE ?)"
            )
            pattern = f"%{search.lower()}%"
            args.extend([pattern] * 4)
        sql = (
            "SELECT source_sha256, category, source_location, fin, reference, label, "
            "payload_json FROM source_knowledge_rows"
        )
        if filters:
            sql += " WHERE " + " AND ".join(filters)
        sql += " ORDER BY source_sha256, record_number LIMIT ? OFFSET ?"
        args.extend([min(max(limit, 1), 1000), max(offset, 0)])
        with self.store.connect() as con:
            rows = con.execute(sql, args).fetchall()
        return [
            {
                "source_sha256": row[0], "category": row[1],
                "source_location": row[2], "fin": row[3],
                "reference": row[4], "label": row[5],
                "data": json.loads(row[6]),
            }
            for row in rows
        ]

    def diagnostic_times_for_fins(
        self, fins: set[str]
    ) -> dict[str, list[tuple[str | None, str | None, int]]]:
        """Read only timestamps of original AutoExport DTCs for scoped FINs.

        Source rows are not deduplicated and are never directly attached
        to QEC cases by this read-only audit.
        """
        if not fins:
            return {}
        result: dict[str, list[tuple[str | None, str | None, int]]] = {}
        with self.store.connect() as con:
            for fin in sorted(fins):
                rows = con.execute(
                    """SELECT json_extract_string(payload_json, '$.DiagStartTs'),
                              json_extract_string(payload_json, '$.DiagStartDt'),
                              COUNT(*)
                       FROM source_knowledge_rows
                       WHERE category = 'autoexport_dtc' AND fin = ?
                       GROUP BY 1, 2""", [fin],
                ).fetchall()
                result[fin] = [(a, b, int(n)) for a, b, n in rows]
        return result

    def autoexport_population(self) -> dict[str, int]:
        """Count rows and distinct FINs by source category, not QEC cases.

        This uses indexed metadata and does not materialize sensitive vehicle
        rows or customer text in Python. A TIPS record is a workshop case
        record; an AutoExport DTC row is not a failed-part case.
        """
        with self.store.connect() as con:
            rows = con.execute(
                """
                SELECT category, COUNT(*) AS row_count,
                       COUNT(DISTINCT fin) AS fin_count
                FROM source_knowledge_rows
                WHERE category IN (
                    'autoexport_dtc', 'autoexport_repair', 'autoexport_tips'
                )
                GROUP BY category
                """
            ).fetchall()
            overall_fins = con.execute(
                """
                SELECT COUNT(DISTINCT NULLIF(trim(fin), ''))
                FROM source_knowledge_rows
                WHERE category IN (
                    'autoexport_dtc', 'autoexport_repair', 'autoexport_tips'
                )
                """
            ).fetchone()[0]
            tips_ids = con.execute(
                """
                SELECT COUNT(DISTINCT NULLIF(
                    json_extract_string(payload_json, '$.CaseId'), ''
                ))
                FROM source_knowledge_rows
                WHERE category = 'autoexport_tips'
                """
            ).fetchone()[0]
            qec = con.execute(
                """
                SELECT
                    COUNT(*) AS all_rows,
                    COUNT(*) FILTER (
                        WHERE source_location LIKE 'Schadteile QEC!%'
                    ) AS primary_rows,
                    COUNT(DISTINCT reference) FILTER (
                        WHERE source_location LIKE 'Schadteile QEC!%'
                    ) AS primary_references,
                    COUNT(DISTINCT fin) FILTER (
                        WHERE source_location LIKE 'Schadteile QEC!%'
                    ) AS primary_fins
                FROM source_knowledge_rows
                WHERE category = 'qec_row'
                """
            ).fetchone()
        results: dict[str, int] = {
            "autoexport_unique_fins": int(overall_fins or 0),
            "autoexport_total_rows": sum(int(row_count) for _, row_count, _ in rows),
            "tips_distinct_case_ids": int(tips_ids or 0),
            "qec_original_rows": int(qec[0]),
            "qec_primary_rows": int(qec[1]),
            "qec_primary_references": int(qec[2]),
            "qec_primary_fins": int(qec[3]),
        }
        for category, row_count, fin_count in rows:
            results[f"{category}_rows"] = int(row_count)
            results[f"{category}_fins"] = int(fin_count)
        return results

    def autoexport_dtc_overview(
        self,
    ) -> dict[tuple[str, str], tuple[int, int, str]]:
        """Aggregated DTC Explorer catalog: no raw FINs leave this query.

        Values are (distinct vehicles, raw observations, imported description).
        This includes DTCs from AutoExport FINs with no QEC case.
        """
        with self.store.connect() as con:
            rows = con.execute(
                """
                SELECT
                    upper(trim(json_extract_string(payload_json, '$.EcuNm'))) AS ecu,
                    upper(trim(json_extract_string(payload_json, '$.EcuFaultNm'))) AS dtc,
                    COUNT(DISTINCT CASE
                        WHEN length(trim(fin)) = 20
                         AND left(upper(trim(fin)), 3) = 'MBC'
                        THEN substr(upper(trim(fin)), 4)
                        ELSE upper(trim(fin))
                    END) AS vehicle_count,
                    COUNT(*) AS observation_count,
                    MAX(NULLIF(trim(
                        json_extract_string(payload_json, '$.EcuFaultTxt')
                    ), '')) AS description
                FROM source_knowledge_rows
                WHERE category = 'autoexport_dtc'
                  AND NULLIF(trim(
                      json_extract_string(payload_json, '$.EcuNm')
                  ), '') IS NOT NULL
                  AND NULLIF(trim(
                      json_extract_string(payload_json, '$.EcuFaultNm')
                  ), '') IS NOT NULL
                GROUP BY 1, 2
                ORDER BY 1, 2
                """
            ).fetchall()
        return {
            (ecu, dtc): (int(vehicles), int(events), description or "")
            for ecu, dtc, vehicles, events, description in rows
        }

    def autoexport_source_fins(self, category: str) -> frozenset[str]:
        """FIN membership for coverage metrics; only supported source types.

        No original DTCs, workshop free text or vehicle IDs are uploaded.
        SQL performs MBC-prefix normalization before distinct counting.
        """
        if category not in {"autoexport_dtc", "autoexport_tips"}:
            raise ValueError("Unbekannte AutoExport-Datenquelle.")
        with self.store.connect() as con:
            rows = con.execute(
                """
                SELECT DISTINCT CASE
                    WHEN length(trim(fin)) = 20
                     AND left(upper(trim(fin)), 3) = 'MBC'
                    THEN substr(upper(trim(fin)), 4)
                    ELSE upper(trim(fin))
                END AS normalized_fin
                FROM source_knowledge_rows
                WHERE category = ?
                  AND NULLIF(trim(fin), '') IS NOT NULL
                """,
                [category],
            ).fetchall()
        return frozenset(row[0] for row in rows)

    def autoexport_fin_dtc_signatures(
        self, *,
        pump_swap_dates: dict[str, str] | None = None,
        include_all_fins: bool = False,
        fin_filter: Sequence[str] | None = None,
    ) -> tuple[
        tuple[str, ...],
        dict[str, tuple[tuple[str, str], ...]],
        dict[tuple[str, str], str],
    ]:
        """Read unique AutoExport ECU:DTC keys for all or pump-anchored FINs.

        If pump_swap_dates is set, it is an explicit QEC-backed FIN -> ISO
        date mapping. DTCs of anchored FINs must be dated STRICTLY BEFORE
        their earliest documented pump swap. Same-day/undated are unknown.
        With include_all_fins=True, unanchored FINs keep their full DTC
        history as general diagnostic patterns; both sets share one
        FIN-level comparison space. Workshop RepairDt is not a pump anchor.
        """
        from datetime import date

        anchors: dict[str, date] | None = None
        if pump_swap_dates is not None:
            anchors = {
                fin.strip().upper(): date.fromisoformat(value)
                for fin, value in pump_swap_dates.items()
            }

        # QEC canonical_fin strips the known 20-character MBC sales
        # prefix. Apply EXACTLY the same safe normalization to AutoExport
        # source FINs so an identical vehicle cannot become two clusters.
        fin_expression = """
            CASE
                WHEN length(trim(fin)) = 20
                 AND left(upper(trim(fin)), 3) = 'MBC'
                THEN substr(upper(trim(fin)), 4)
                ELSE upper(trim(fin))
            END
        """
        with self.store.connect() as con:
            all_fins = tuple(
                row[0] for row in con.execute(
                    f"""
                    SELECT DISTINCT {fin_expression} AS normalized_fin
                    FROM source_knowledge_rows
                    WHERE category IN (
                        'autoexport_dtc', 'autoexport_repair', 'autoexport_tips'
                    )
                      AND NULLIF(trim(fin), '') IS NOT NULL
                    ORDER BY 1
                    """
                ).fetchall()
            )
            if anchors is not None and not include_all_fins:
                all_fins = tuple(fin for fin in all_fins if fin in anchors)
            if fin_filter is not None:
                target = {fin.strip().upper() for fin in fin_filter}
                all_fins = tuple(fin for fin in all_fins if fin in target)
            if not all_fins:
                return (), {}, {}

            parameters: list[str] = []
            where = ""
            date_field = "NULL::VARCHAR AS event_date"
            group_date = ""
            if fin_filter is not None or (
                anchors is not None and not include_all_fins
            ):
                where = (
                    f"AND ({fin_expression}) IN ("
                    + ", ".join("?" for _ in all_fins) + ")"
                )
                parameters.extend(all_fins)
            if anchors is not None:
                # The original ISO AutoExport fields may represent a date
                # or precise timestamp. Only its calendar day is safe
                # against day-only QEC replacement precision.
                date_field = """
                    CAST(COALESCE(
                        TRY_CAST(left(
                            json_extract_string(payload_json, '$.DiagStartTs'), 10
                        ) AS DATE),
                        TRY_CAST(left(
                            json_extract_string(payload_json, '$.DiagStartDt'), 10
                        ) AS DATE)
                    ) AS VARCHAR) AS event_date
                """
                group_date = ", 5"
            sql = f"""
                SELECT
                    {fin_expression} AS fin,
                    upper(trim(json_extract_string(payload_json, '$.EcuNm'))) AS ecu,
                    upper(trim(json_extract_string(payload_json, '$.EcuFaultNm'))) AS dtc,
                    max(nullif(trim(
                        json_extract_string(payload_json, '$.EcuFaultTxt')
                    ), '')) AS dtc_text,
                    {date_field}
                FROM source_knowledge_rows
                WHERE category = 'autoexport_dtc'
                  AND NULLIF(trim(fin), '') IS NOT NULL
                  AND NULLIF(trim(
                      json_extract_string(payload_json, '$.EcuNm')
                  ), '') IS NOT NULL
                  AND NULLIF(trim(
                      json_extract_string(payload_json, '$.EcuFaultNm')
                  ), '') IS NOT NULL
                  {where}
                GROUP BY 1, 2, 3{group_date}
                ORDER BY 1, 2, 3
            """
            cursor = con.execute(sql, parameters)
            groups: dict[str, set[tuple[str, str]]] = {}
            labels: dict[tuple[str, str], str] = {}
            while batch := cursor.fetchmany(5000):
                for fin, ecu, dtc, dtc_text, event_date in batch:
                    if anchors is not None and fin in anchors:
                        if not event_date:
                            continue
                        try:
                            event_day = date.fromisoformat(str(event_date)[:10])
                        except ValueError:
                            continue
                        if event_day >= anchors[fin]:
                            # QEC Rep.-Datum usually only has day precision.
                            # A diagnostic taken the same day cannot be
                            # proven to predate the actual replacement.
                            continue
                    key = (ecu, dtc)
                    groups.setdefault(fin, set()).add(key)
                    if dtc_text and key not in labels:
                        labels[key] = dtc_text

        return (
            all_fins,
            {fin: tuple(sorted(faults)) for fin, faults in groups.items()},
            labels,
        )

    def fin_history_counts(self, fin: str) -> dict[str, int]:
        """Counts of immutable original AutoExport rows for a FIN (not DTC rates)."""
        with self.store.connect() as con:
            rows = con.execute(
                """
                SELECT category, COUNT(*)
                FROM source_knowledge_rows
                WHERE fin = ?
                  AND category IN (
                    'autoexport_dtc', 'autoexport_repair', 'autoexport_tips'
                  )
                GROUP BY category
                """,
                [fin],
            ).fetchall()
        return {kind: int(count) for kind, count in rows}

    def list_fin_history(
        self, fin: str, *, limit: int = 200, offset: int = 0
    ) -> list[dict[str, Any]]:
        """Bounded, newest-first VIN/FIN history without requiring a QEC case.

        The source label is DiagStartTs if available, otherwise a date. Both
        source SHA and CSV record positions remain available for audit. These
        are individual raw source rows, *not* de-duplicated diagnostic sessions.
        """
        with self.store.connect() as con:
            rows = con.execute(
                """
                SELECT source_sha256, category, source_location,
                       fin, reference, label, payload_json
                FROM source_knowledge_rows
                WHERE fin = ?
                  AND category IN (
                    'autoexport_dtc', 'autoexport_repair', 'autoexport_tips'
                  )
                ORDER BY label DESC, source_sha256, record_number DESC
                LIMIT ? OFFSET ?
                """,
                [fin, min(max(limit, 1), 500), max(offset, 0)],
            ).fetchall()
        return [
            {
                "source_sha256": row[0], "category": row[1],
                "source_location": row[2], "fin": row[3],
                "reference": row[4], "label": row[5],
                "data": json.loads(row[6]),
            }
            for row in rows
        ]

    def count_rows(self, category: str | None = None) -> int:
        with self.store.connect() as con:
            if category is None:
                return con.execute(
                    "SELECT COUNT(*) FROM source_knowledge_rows"
                ).fetchone()[0]
            return con.execute(
                "SELECT COUNT(*) FROM source_knowledge_rows WHERE category = ?",
                [category],
            ).fetchone()[0]
