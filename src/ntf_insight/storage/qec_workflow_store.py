"""Persistente, nachvollziehbare QEC-Kohorte und fachliche Fallentscheidungen."""
from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path

from ntf_insight.acquisition.qec_archive import local_qec_archive
from ntf_insight.ingestion.qec_primary import active_qec_lists
from ntf_insight.storage.duckdb_store import DuckDBStore

VALID_DECISIONS = ("Offen", "NTF", "Kein NTF")


class QecWorkflowStore:
    def __init__(self, store: DuckDBStore) -> None:
        self.store = store
        with store.connect() as con:
            con.execute("""
                CREATE TABLE IF NOT EXISTS qec_workflow_decisions (
                    source_sha256 VARCHAR NOT NULL,
                    case_id VARCHAR NOT NULL,
                    decision VARCHAR NOT NULL,
                    reason VARCHAR NOT NULL,
                    PRIMARY KEY (source_sha256, case_id)
                )
            """)
            con.execute("""
                CREATE TABLE IF NOT EXISTS qec_cluster_handoff (
                    source_sha256 VARCHAR NOT NULL,
                    fin VARCHAR NOT NULL,
                    PRIMARY KEY (source_sha256, fin)
                )
            """)

    def active_source(self):
        primary = active_qec_lists(self.store.load_artifacts())
        return primary[0] if len(primary) == 1 else None

    def decision(self, sha: str, case_id: str) -> tuple[str, str]:
        with self.store.connect() as con:
            result = con.execute(
                "SELECT decision, reason FROM qec_workflow_decisions "
                "WHERE source_sha256=? AND case_id=?", [sha, case_id],
            ).fetchone()
        return tuple(result) if result else ("Offen", "")

    def set_decision(self, sha: str, case_id: str, decision: str, reason: str) -> None:
        if decision not in VALID_DECISIONS:
            raise ValueError("Ungültige NTF-Entscheidung.")
        if not any(a.sha256 == sha for a in active_qec_lists(self.store.load_artifacts())):
            raise ValueError("QEC-FIN-Liste nicht aktiv.")
        from ntf_insight.ingestion.real_source_parsers import QECWorkbookParser
        source = self.active_source()
        cases = QECWorkbookParser(sha).parse(Path(source.archived_path)).cases if source else []
        if case_id not in {case.case_id for case in cases}:
            raise ValueError("Fall gehört nicht zur aktiven QEC-Liste.")
        with self.store.connect() as con:
            con.execute(
                "INSERT INTO qec_workflow_decisions VALUES (?, ?, ?, ?) "
                "ON CONFLICT (source_sha256, case_id) DO UPDATE SET "
                "decision=excluded.decision, reason=excluded.reason",
                [sha, case_id, decision, reason.strip()],
            )
            # Previously released selections become invalid when a decision changes.
            con.execute("DELETE FROM qec_cluster_handoff WHERE source_sha256=?", [sha])

    def rows(self, qec_root: Path) -> list[dict]:
        source = self.active_source()
        if source is None:
            return []
        from ntf_insight.ingestion.real_source_parsers import QECWorkbookParser
        cases = QECWorkbookParser(source.sha256).parse(Path(source.archived_path)).cases
        results = []
        for case in cases:
            reference = str(getattr(case, "qec_reference", "") or "")
            report = local_qec_archive(qec_root, case.vin, reference)
            finding = str(getattr(case, "qec_ssl_end_finding", "") or "")
            dbcase = self.store.get_case(case.case_id)
            if dbcase is not None and dbcase.vin == case.vin:
                finding = str(getattr(dbcase, "qec_ssl_end_finding", "") or finding)
            decision, reason = self.decision(source.sha256, case.case_id)
            results.append({
                "case_id": case.case_id, "fin": case.vin,
                "reference": reference,
                "part_number": str(getattr(case, "qec_part_number", "") or ""),
                "finding": finding, "report": bool(report),
                "decision": decision, "reason": reason,
            })
        return results

    def overview(self, qec_root: Path) -> dict[str, int]:
        rows = self.rows(qec_root)
        counts = Counter(row["decision"] for row in rows)
        return {
            "cases": len(rows),
            "fins": len({r["fin"] for r in rows}),
            "downloaded": len({r["fin"] for r in rows if r["report"]}),
            "ntf": counts["NTF"],
            "not_ntf": counts["Kein NTF"],
            "open": counts["Offen"],
        }

    def export_csv(self, destination: Path, qec_root: Path) -> int:
        rows = self.rows(qec_root)
        with Path(destination).open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle, delimiter=";")
            writer.writerow(("FIN", "QEC-Fall", "Referenz", "Sachnummer",
                             "SSL-Endbefund", "QEC-Bericht vorhanden",
                             "NTF-Bewertung", "Begründung"))
            for row in rows:
                writer.writerow((
                    row["fin"], row["case_id"], row["reference"], row["part_number"],
                    row["finding"], "Ja" if row["report"] else "Nein",
                    row["decision"], row["reason"],
                ))
        return len(rows)

    def handoff_ntf(self, qec_root: Path) -> int:
        source = self.active_source()
        if source is None:
            return 0
        rows = self.rows(qec_root)
        # Ungeklärte Fälle derselben FIN dürfen nicht in die bestätigte NTF-Kohorte.
        by_fin = {}
        for row in rows:
            by_fin.setdefault(row["fin"], []).append(row["decision"])
        fins = sorted(
            fin for fin, statuses in by_fin.items()
            if statuses and all(status == "NTF" for status in statuses)
        )
        with self.store.connect() as con:
            con.execute("BEGIN TRANSACTION")
            try:
                con.execute("DELETE FROM qec_cluster_handoff WHERE source_sha256=?",
                            [source.sha256])
                for fin in fins:
                    con.execute("INSERT INTO qec_cluster_handoff VALUES (?, ?)",
                                [source.sha256, fin])
                con.execute("COMMIT")
            except Exception:
                con.execute("ROLLBACK")
                raise
        return len(fins)

    def handed_off_fins(self) -> tuple[str, ...]:
        source = self.active_source()
        if source is None:
            return ()
        with self.store.connect() as con:
            return tuple(row[0] for row in con.execute(
                "SELECT fin FROM qec_cluster_handoff WHERE source_sha256=? ORDER BY fin",
                [source.sha256],
            ).fetchall())
