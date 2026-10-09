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
    def __init__(self, store: DuckDBStore) -> None:
        self.store = store
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
            tips_ids = con.execute(
                """
                SELECT COUNT(DISTINCT NULLIF(
                    json_extract_string(payload_json, '$.CaseId'), ''
                ))
                FROM source_knowledge_rows
                WHERE category = 'autoexport_tips'
                """
            ).fetchone()[0]
        results: dict[str, int] = {"tips_distinct_case_ids": int(tips_ids or 0)}
        for category, row_count, fin_count in rows:
            results[f"{category}_rows"] = int(row_count)
            results[f"{category}_fins"] = int(fin_count)
        return results

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
