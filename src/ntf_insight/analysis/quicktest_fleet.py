"""FIN-übergreifende Analyse sämtlicher importierter PDF-QuickTests.

Berichtszahlen sind Beobachtungszahlen, keine Ausfallquoten oder Ursachenbelege.
Die aggregierten Abfragen arbeiten direkt auf der bestehenden lokalen DuckDB.
"""
from __future__ import annotations

from dataclasses import dataclass

from ntf_insight.storage.quicktest_store import QuickTestStore


@dataclass(frozen=True)
class FleetQuickTestAnalysis:
    reports: int
    fins: int
    ecus: int
    dtc_observations: int
    clean_reports: int
    report_rows: tuple[tuple, ...]
    dtc_rows: tuple[tuple, ...]
    ecu_rows: tuple[tuple, ...]
    software_rows: tuple[tuple, ...]


def analyze_quicktest_fleet(
    store: QuickTestStore, ecu_filter: str = "", dtc_filter: str = ""
) -> FleetQuickTestAnalysis:
    """Count each logical QuickTest once; never infer failure from its DTCs.

    ECU and DTC filters apply to the event tables. The totals always describe
    the entire imported fleet; filtering cannot manufacture clean sessions.
    """
    ecu_filter = ecu_filter.strip().upper()
    dtc_filter = dtc_filter.strip().upper()
    with store.store.connect() as con:
        reports, fins, clean = con.execute("""
            SELECT COUNT(*), COUNT(DISTINCT fin),
                   COUNT(*) FILTER (WHERE dtc_count = 0)
            FROM quicktest_reports
        """).fetchone()
        ecus = con.execute("SELECT COUNT(*) FROM quicktest_ecus").fetchone()[0]
        observations = con.execute("SELECT COUNT(*) FROM quicktest_dtcs").fetchone()[0]
        # A report with no matching filter is not a clean report.
        report_rows = con.execute("""
            SELECT r.fin, COUNT(DISTINCT r.report_id) AS berichte,
                   MIN(r.diagnosed_at), MAX(r.diagnosed_at),
                   SUM(r.dtc_count) AS dtc_beobachtungen,
                   SUM(CASE WHEN r.dtc_count = 0 THEN 1 ELSE 0 END)
            FROM quicktest_reports r
            GROUP BY r.fin
            ORDER BY berichte DESC, r.fin
        """).fetchall()
        dtc_rows = con.execute("""
            SELECT d.ecu_code, d.dtc_code, COUNT(*) AS beobachtungen,
                   COUNT(DISTINCT r.fin) AS fahrzeuge,
                   COUNT(DISTINCT d.report_id) AS berichte,
                   MIN(r.diagnosed_at), MAX(r.diagnosed_at)
            FROM quicktest_dtcs d
            JOIN quicktest_reports r ON r.report_id = d.report_id
            WHERE (? = '' OR UPPER(d.ecu_code) LIKE '%' || ? || '%')
              AND (? = '' OR UPPER(d.dtc_code) LIKE '%' || ? || '%')
            GROUP BY d.ecu_code, d.dtc_code
            ORDER BY fahrzeuge DESC, beobachtungen DESC, d.ecu_code, d.dtc_code
        """, [ecu_filter, ecu_filter, dtc_filter, dtc_filter]).fetchall()
        ecu_rows = con.execute("""
            SELECT e.ecu_code, COUNT(DISTINCT r.fin), COUNT(DISTINCT e.report_id),
                   SUM(e.reported_fault_count)
            FROM quicktest_ecus e
            JOIN quicktest_reports r ON r.report_id = e.report_id
            WHERE (? = '' OR UPPER(e.ecu_code) LIKE '%' || ? || '%')
            GROUP BY e.ecu_code
            ORDER BY COUNT(DISTINCT r.fin) DESC, e.ecu_code
        """, [ecu_filter, ecu_filter]).fetchall()
        software_rows = con.execute("""
            SELECT e.ecu_code,
                   COALESCE(NULLIF(json_extract_string(e.metadata_json, '$.software_version'), ''), 'k. A.'),
                   COUNT(DISTINCT r.fin), COUNT(DISTINCT e.report_id)
            FROM quicktest_ecus e
            JOIN quicktest_reports r ON r.report_id = e.report_id
            WHERE (? = '' OR UPPER(e.ecu_code) LIKE '%' || ? || '%')
            GROUP BY 1, 2
            ORDER BY 1, 3 DESC, 2
        """, [ecu_filter, ecu_filter]).fetchall()
    return FleetQuickTestAnalysis(
        reports=int(reports), fins=int(fins), ecus=int(ecus),
        dtc_observations=int(observations), clean_reports=int(clean),
        report_rows=tuple(tuple(row) for row in report_rows),
        dtc_rows=tuple(tuple(row) for row in dtc_rows),
        ecu_rows=tuple(tuple(row) for row in ecu_rows),
        software_rows=tuple(tuple(row) for row in software_rows),
    )
