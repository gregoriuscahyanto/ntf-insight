"""Relational local storage for CDD, QEC, Part History and AutoExport data.

Original source files remain immutable; derived rows are keyed by source SHA256
and row number, so reparsing is idempotent and provenance stays traceable.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Iterable, Sequence

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

    def qec_report_for_case(
        self,
        fin: str,
        reference: str,
        *,
        part_number: str | None = None,
        limit: int = 750,
    ) -> dict[str, Any] | None:
        """Show one QEC JSON source by *both* FIN and reference.

        Never combine rows of two downloads. A duplicated latest timestamp,
        contradictory part number or failed download is flagged explicitly,
        not silently trusted as the current source of truth.
        """
        fin = str(fin or "").strip().upper()
        reference = str(reference or "").strip()
        if not fin or not reference:
            return None
        candidates = [
            document for document in self.documents()
            if (
                document["source_kind"] == "qec_live_report"
                and document["metadata"].get("fin") == fin
                and str(document["metadata"].get("reference") or "") == reference
            )
        ]
        if not candidates:
            return None

        def captured_at(document: dict) -> datetime:
            raw = str(document["metadata"].get("downloaded_at_utc") or "")
            try:
                parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
            except ValueError:
                return datetime.min.replace(tzinfo=timezone.utc)

        latest_time = max(captured_at(item) for item in candidates)
        latest = [item for item in candidates if captured_at(item) == latest_time]
        chosen = max(latest, key=lambda item: (item["updated_at"], item["source_sha256"]))
        metadata = chosen["metadata"]
        result: dict[str, Any] = {
            "source_sha256": chosen["source_sha256"],
            "metadata": metadata,
            "versions": len(candidates),
            "status": "Teilweise",
            "reason": "",
            "records": [],
            "truncated": False,
        }
        if len(latest) > 1:
            result["status"] = "Prüfbedarf"
            result["reason"] = (
                "Mehrere unterschiedliche QEC-Dateien mit derselben Abrufzeit. "
                "Bitte die Originaldateien prüfen; keine automatische Auswahl."
            )
            return result

        actual_part = str(metadata.get("part_number") or "").strip()
        expected_part = str(part_number or "").strip()
        def normalized(value: str) -> str:
            return value.upper().replace(" ", "").replace("-", "")
        if actual_part and expected_part and normalized(actual_part) != normalized(expected_part):
            result["status"] = "Prüfbedarf"
            result["reason"] = (
                "QEC-Sachnummer widerspricht der ausgewählten Fall-Sachnummer. "
                "Die QEC-Felder werden nicht als zugeordnet angezeigt."
            )
            return result

        if int(metadata.get("download_errors") or 0) > 0:
            result["status"] = "Prüfbedarf"
            result["reason"] = "Der QEC-Abruf enthält Fehler; Originalbericht prüfen."
        elif metadata.get("fresh_complete") is True:
            result["status"] = "Vollständig"
        else:
            result["reason"] = (
                "QEC-Reiter fehlen, sind älter oder der Abruf wurde nicht vollständig bestätigt."
            )

        max_rows = min(max(int(limit), 1), 2_500)
        with self.store.connect() as con:
            rows = con.execute(
                """
                SELECT category, source_location, label, payload_json
                FROM source_knowledge_rows
                WHERE source_sha256 = ?
                  AND category IN (
                      'qec_section', 'qec_field', 'qec_table_row', 'qec_attachment'
                  )
                ORDER BY record_number
                LIMIT ?
                """,
                [chosen["source_sha256"], max_rows + 1],
            ).fetchall()
        result["truncated"] = len(rows) > max_rows
        result["records"] = [
            {
                "source_sha256": chosen["source_sha256"],
                "category": category,
                "source_location": location,
                "label": label,
                "data": json.loads(payload),
            }
            for category, location, label, payload in rows[:max_rows]
        ]
        return result

    def qec_ssl_findings_by_reference(
        self,
    ) -> tuple[dict[str, dict[str, str]], frozenset[str]]:
        """Unique SSL findings keyed by real QEC reference, never by guessed FIN.

        Read previously archived QEC details as well as newly imported ones.
        A conflicting label/code/part for one reference is *ambiguous*: such a
        reference must not silently change any vehicle case.
        """
        with self.store.connect() as con:
            rows = con.execute(
                """
                SELECT reference, payload_json, source_sha256, source_location
                FROM source_knowledge_rows
                WHERE category = 'qec_row'
                  AND NULLIF(trim(reference), '') IS NOT NULL
                  AND source_location LIKE '%!%'
                ORDER BY reference, source_sha256, source_location
                """
            ).fetchall()
        candidates: dict[str, list[dict[str, str]]] = {}
        for reference, payload, sha, location in rows:
            data = json.loads(payload)
            finding = str(data.get("SSL-Endbefund Benennung") or "").strip()
            code = str(data.get("SSL Endbefund") or "").strip()
            if not finding and not code:
                continue
            candidate = {
                "finding": finding,
                "code": code,
                "part_number": str(data.get("Sachnr. Teil") or "").strip(),
                "end_date": str(data.get("Bef.abschl.datum") or "").strip(),
                "source_ref": f"{sha}:{location}",
            }
            candidates.setdefault(str(reference).strip(), []).append(candidate)
        unique: dict[str, dict[str, str]] = {}
        ambiguous: set[str] = set()
        for reference, entries in candidates.items():
            variants = {
                (item["finding"], item["code"], item["part_number"])
                for item in entries
            }
            if len(variants) != 1:
                ambiguous.add(reference)
                continue
            # Prefer the version with an explicit completion date, then
            # deterministic source provenance. Never fabricate a date.
            unique[reference] = sorted(
                entries,
                key=lambda item: (not bool(item["end_date"]), item["source_ref"]),
            )[0]
        return unique, frozenset(ambiguous)

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

    def autoexport_ecu_names(self) -> tuple[str, ...]:
        """ECUs actually present in the immutable local AutoExport DTC index."""
        with self.store.connect() as con:
            names = con.execute(
                """
                SELECT DISTINCT upper(trim(
                    json_extract_string(payload_json, '$.EcuNm')
                )) AS ecu
                FROM source_knowledge_rows
                WHERE category = 'autoexport_dtc'
                  AND NULLIF(trim(
                    json_extract_string(payload_json, '$.EcuNm')
                  ), '') IS NOT NULL
                ORDER BY ecu
                """
            ).fetchall()
        return tuple(row[0] for row in names)

    def ecu_software_rows_for_fins(
        self, fins: Sequence[str], ecu: str, *,
        per_fin_limit: int = 20000,
    ) -> dict[str, tuple[list[dict[str, Any]], bool]]:
        """Read EVERY distinct ECU diagnostic observation for a cohort.

        Aggregate repeated DTC export lines by actual FIN, source and ECU
        snapshot rather than silently showing only the first two SW versions.
        The original EcuSwVersionTxt is preserved verbatim; rows without SW
        also survive as *positive* DTC evidence, never as SW readings.
        Missing rows/quicktests are NOT evidence of no fault or no SW update.

        A single read-only SQL query is issued per 200 FINs. No raw FIN or
        document is transferred outside the local DuckDB connection.
        """
        from ntf_insight.ingestion.real_source_parsers import canonical_fin

        normalized = sorted({
            valid for raw in fins if (valid := canonical_fin(raw)) is not None
        })
        selected_ecu = str(ecu or "").strip().upper()
        if not selected_ecu or not normalized:
            return {}
        bound = max(1, min(int(per_fin_limit), 50000))
        result: dict[str, tuple[list[dict[str, Any]], bool]] = {
            fin: ([], False) for fin in normalized
        }
        normalized_fin = """
            CASE
                WHEN length(trim(fin)) = 20
                 AND left(upper(trim(fin)), 3) = 'MBC'
                THEN substr(upper(trim(fin)), 4)
                ELSE upper(trim(fin))
            END
        """
        with self.store.connect() as con:
            for offset in range(0, len(normalized), 200):
                group = normalized[offset:offset + 200]
                tokens = ", ".join("?" for _ in group)
                cursor = con.execute(
                    f"""
                    WITH matched AS (
                        SELECT {normalized_fin} AS case_fin,
                               source_sha256, source_location,
                               NULLIF(trim(json_extract_string(
                                   payload_json, '$.DiagStartTs'
                               )), '') AS diag_ts,
                               NULLIF(trim(json_extract_string(
                                   payload_json, '$.DiagStartDt'
                               )), '') AS diag_date,
                               NULLIF(trim(json_extract_string(
                                   payload_json, '$.EcuSwVersionTxt'
                               )), '') AS sw,
                               NULLIF(trim(json_extract_string(
                                   payload_json, '$.EcuSuppHwVersionTxt'
                               )), '') AS hw,
                               NULLIF(trim(json_extract_string(
                                   payload_json, '$.EcuHwPartnumberCd'
                               )), '') AS part,
                               NULLIF(trim(json_extract_string(
                                   payload_json, '$.EcuFaultNm'
                               )), '') AS dtc,
                               NULLIF(trim(json_extract_string(
                                   payload_json, '$.KmReadingNum'
                               )), '') AS km,
                               NULLIF(trim(json_extract_string(
                                   payload_json, '$.CntXDDiagnosisHeaderSid'
                               )), '') AS diagnosis_ref
                        FROM source_knowledge_rows
                        WHERE category = 'autoexport_dtc'
                          AND {normalized_fin} IN ({tokens})
                          AND upper(trim(json_extract_string(
                              payload_json, '$.EcuNm'
                          ))) = ?
                    )
                    SELECT case_fin, source_sha256,
                           min(source_location) AS first_location,
                           diag_ts, diag_date, sw, hw, part, km,
                           diagnosis_ref,
                           string_agg(
                               DISTINCT upper(dtc), ' | '
                               ORDER BY upper(dtc)
                           ) FILTER (WHERE dtc IS NOT NULL) AS fault_codes,
                           count(*) AS source_rows
                    FROM matched
                    GROUP BY case_fin, source_sha256,
                             diag_ts, diag_date, sw, hw, part, km,
                             diagnosis_ref
                    ORDER BY case_fin, coalesce(diag_ts, diag_date),
                             source_sha256, first_location
                    """,
                    [*group, selected_ecu],
                )
                while batch := cursor.fetchmany(5000):
                    for (fin, sha, location, ts, day, sw, hw, part,
                         km, diag_ref, codes, count) in batch:
                        gathered, was_truncated = result[fin]
                        if len(gathered) >= bound:
                            result[fin] = (gathered, True)
                            continue
                        gathered.append({
                            "source_ref": f"raw:{sha}#{location}",
                            "diag_timestamp": ts,
                            "diag_date": day,
                            "software_version": sw,
                            "hardware_version": hw,
                            "hardware_part_number": part,
                            "mileage_km": km,
                            "diagnosis_ref": diag_ref,
                            "dtc_codes": tuple(
                                code.strip() for code in (codes or "").split(" | ")
                                if code.strip()
                            ),
                            "raw_observation_count": int(count),
                        })
        return result

    def cpc3_software_rows_for_fin(
        self, fin: str, *, limit: int = 5000,
    ) -> tuple[list[dict[str, Any]], bool]:
        """Read CPC3 software evidence from locally archived AutoExport rows.

        Covers FINs without a QEC case and archived CSVs not attached to a
        case snapshot. A DTC export is an *incomplete* ECU test: absent fault
        codes must never be interpreted as healed or absent. The capped query
        cannot silently produce a false "no version changes" conclusion.
        """
        from ntf_insight.ingestion.real_source_parsers import canonical_fin

        normalized = canonical_fin(fin)
        if normalized is None:
            return [], False
        bound = min(max(limit, 1), 10000)
        with self.store.connect() as con:
            rows = con.execute(
                """
                SELECT source_sha256, source_location,
                       json_extract_string(payload_json, '$.DiagStartTs'),
                       json_extract_string(payload_json, '$.DiagStartDt'),
                       json_extract_string(payload_json, '$.EcuSwVersionTxt'),
                       json_extract_string(payload_json, '$.EcuSuppHwVersionTxt'),
                       json_extract_string(payload_json, '$.EcuHwPartnumberCd'),
                       json_extract_string(payload_json, '$.EcuFaultNm'),
                       json_extract_string(payload_json, '$.KmReadingNum')
                FROM source_knowledge_rows
                WHERE category = 'autoexport_dtc'
                  AND upper(trim(fin)) IN (?, ?)
                  AND upper(trim(
                      json_extract_string(payload_json, '$.EcuNm')
                  )) = 'CPC3'
                  AND NULLIF(trim(
                      json_extract_string(payload_json, '$.EcuSwVersionTxt')
                  ), '') IS NOT NULL
                ORDER BY
                    coalesce(
                        json_extract_string(payload_json, '$.DiagStartTs'),
                        json_extract_string(payload_json, '$.DiagStartDt')
                    ),
                    source_sha256, source_location
                LIMIT ?
                """,
                [normalized, "MBC" + normalized, bound + 1],
            ).fetchall()
        truncated = len(rows) > bound
        return [
            {
                "source_ref": f"raw:{sha}#{location}",
                "diag_timestamp": ts,
                "diag_date": day,
                "software_version": sw,
                "hardware_version": hw,
                "hardware_part_number": part,
                "dtc_code": dtc,
                "mileage_km": km,
            }
            for sha, location, ts, day, sw, hw, part, dtc, km
            in rows[:bound]
        ], truncated

    def autoexport_population(self) -> dict[str, int]:
        """Count rows and distinct FINs by source category, not QEC cases.

        This uses indexed metadata and does not materialize sensitive vehicle
        rows or customer text in Python. A TIPS record is a workshop case
        record; an AutoExport DTC row is not a failed-part case.
        """
        # Detect the primary sheet from the archived document's header metadata.
        # A second sheet containing copied FINs must not inflate QEC counts.
        required = {"Referenznr.", "FIN", "Rep.-Datum"}
        primary_pairs = []
        for document in self.documents():
            if document["source_kind"] != "qec_details":
                continue
            sheets = document["metadata"].get("sheets") or {}
            accepted = (
                [
                    name for name, info in sheets.items()
                    if required <= set(info.get("columns", ()))
                ]
                if sheets else ["Schadteile QEC"]
            )
            primary_pairs.extend(
                (document["source_sha256"], name) for name in accepted
            )

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
            qec_original = con.execute(
                "SELECT COUNT(*) FROM source_knowledge_rows WHERE category = 'qec_row'"
            ).fetchone()[0]
            if primary_pairs:
                placeholders = ", ".join("(?, ?)" for _ in primary_pairs)
                parameters = [
                    value for pair in primary_pairs for value in pair
                ]
                qec_primary = con.execute(
                    f"""
                    SELECT COUNT(*),
                           COUNT(DISTINCT NULLIF(trim(r.reference), '')),
                           COUNT(DISTINCT NULLIF(trim(r.fin), ''))
                    FROM source_knowledge_rows AS r
                    JOIN (VALUES {placeholders}) AS p(source_sha256, sheet_name)
                      ON r.source_sha256 = p.source_sha256
                     AND split_part(r.source_location, '!', 1) = p.sheet_name
                    WHERE r.category = 'qec_row'
                    """,
                    parameters,
                ).fetchone()
            else:
                qec_primary = (0, 0, 0)
        results: dict[str, int] = {
            "autoexport_unique_fins": int(overall_fins or 0),
            "autoexport_total_rows": sum(int(row_count) for _, row_count, _ in rows),
            "tips_distinct_case_ids": int(tips_ids or 0),
            "qec_original_rows": int(qec_original),
            "qec_primary_rows": int(qec_primary[0]),
            "qec_primary_references": int(qec_primary[1]),
            "qec_primary_fins": int(qec_primary[2]),
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

    def tp_dashboard_fins(self) -> frozenset[str]:
        """FINs evidenced by an imported TP-Dashboard CSV, not by QEC itself.

        Use source provenance to avoid claiming missing TP rows from unrelated
        AutoExport or QuickTest data; full FIN is normalized locally.
        """
        with self.store.connect() as con:
            rows = con.execute(
                """
                SELECT DISTINCT CASE
                    WHEN length(trim(r.fin)) = 20
                      AND left(upper(trim(r.fin)), 3) = 'MBC'
                    THEN substr(upper(trim(r.fin)), 4)
                    ELSE upper(trim(r.fin))
                END AS normalized_fin
                FROM source_knowledge_rows r
                JOIN source_knowledge_documents d
                  ON r.source_sha256 = d.source_sha256
                WHERE r.category = 'autoexport_dtc'
                  AND d.source_kind = 'autoexport_rows'
                  AND json_extract_string(d.metadata_json, '$.source_type') =
                      'tp_dashboard'
                  AND NULLIF(trim(r.fin), '') IS NOT NULL
                ORDER BY 1
                """
            ).fetchall()
        return frozenset(row[0] for row in rows)

    def autoexport_source_fins(self, category: str) -> frozenset[str]:
        """FIN membership for coverage metrics; only supported source types.

        No original DTCs, workshop free text or vehicle IDs are uploaded.
        SQL performs MBC-prefix normalization before distinct counting.
        """
        if category not in {"autoexport_dtc", "autoexport_tips"}:
            raise ValueError("Unbekannte AutoExport-Datenquelle.")
        tips_case_constraint = (
            "AND NULLIF(trim(json_extract_string("
            "payload_json, '$.CaseId')), '') IS NOT NULL"
            if category == "autoexport_tips" else ""
        )
        with self.store.connect() as con:
            rows = con.execute(
                f"""
                SELECT DISTINCT CASE
                    WHEN length(trim(fin)) = 20
                     AND left(upper(trim(fin)), 3) = 'MBC'
                    THEN substr(upper(trim(fin)), 4)
                    ELSE upper(trim(fin))
                END AS normalized_fin
                FROM source_knowledge_rows
                WHERE category = ?
                  AND NULLIF(trim(fin), '') IS NOT NULL
                  {tips_case_constraint}
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
