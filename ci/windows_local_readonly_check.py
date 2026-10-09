"""Aggregate, read-only integrity checks against the locally configured NTF database.

No VIN/FIN, source path, serialized record, or exception detail may reach Actions logs.
This command never initializes/migrates the database and never writes to it.
"""

from __future__ import annotations

import os
from collections import Counter
from pathlib import Path


def main() -> int:
    local_dir = os.environ.get("NTF_INSIGHT_DATA_DIR", "").strip()
    if not local_dir:
        print("NICHT BEREIT: NTF_INSIGHT_DATA_DIR fehlt im lokalen Runner-Konto.")
        return 2

    database = Path(local_dir).expanduser() / "ntf-insight.duckdb"
    if not database.is_file():
        print("NICHT BEREIT: Keine bereits importierte lokale NTF-Datenbank vorhanden.")
        return 2

    try:
        import duckdb

        from ntf_insight.analysis.integrity import (
            IntegritySeverity,
            validate_case_integrity,
        )
        from ntf_insight.domain.case import NTFCase

        connection = duckdb.connect(str(database), read_only=True)
        try:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'main'"
                ).fetchall()
            }
            if "case_snapshots" not in tables:
                print("NICHT BEREIT: Erwartete Falltabelle fehlt.")
                return 2

            errors: Counter[str] = Counter()
            checked_cases = 0
            cursor = connection.execute("SELECT payload_json FROM case_snapshots")
            while True:
                batch = cursor.fetchmany(200)
                if not batch:
                    break
                for (payload,) in batch:
                    checked_cases += 1
                    try:
                        case = NTFCase.model_validate_json(payload)
                        report = validate_case_integrity(case)
                        for issue in report.issues:
                            if issue.severity == IntegritySeverity.ERROR:
                                errors[issue.code] += 1
                    except Exception:
                        errors["CASE_FORMAT_OR_VALIDATION"] += 1

            quicktests = 0
            if "quicktest_reports" in tables:
                quicktests = connection.execute(
                    "SELECT COUNT(*) FROM quicktest_reports"
                ).fetchone()[0]
                if quicktests and "quicktest_dtcs" not in tables:
                    errors["QUICKTEST_SCHEMA_INCOMPLETE"] += 1
                elif quicktests:
                    orphan_dtcs = connection.execute(
                        "SELECT COUNT(*) FROM quicktest_dtcs d "
                        "LEFT JOIN quicktest_reports r ON d.report_id = r.report_id "
                        "WHERE r.report_id IS NULL"
                    ).fetchone()[0]
                    if orphan_dtcs:
                        errors["QUICKTEST_DTC_WITHOUT_REPORT"] += orphan_dtcs

            if checked_cases == 0 and quicktests == 0:
                print("NICHT BEREIT: Keine FIN-bezogenen Fall- oder QuickTest-Daten importiert.")
                return 2

            if errors:
                print("NICHT BESTANDEN: Aggregierte Integritaetspruefung hat Probleme gefunden.")
                for code, count in sorted(errors.items()):
                    print(f"  {code}: {count}")
                return 1

            print(
                "BESTANDEN: Lokale Falldaten/QuickTests sind lesbar; "
                "die geprueften Struktur- und Integritaetsregeln sind erfuellt."
            )
            print("Keine FINs, Originalberichte oder Datensaetze wurden ausgegeben.")
            return 0
        finally:
            connection.close()
    except Exception as exc:
        print(
            "PRUEFUNG ABGEBROCHEN: "
            f"{type(exc).__name__}. Details bitte nur lokal untersuchen."
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
