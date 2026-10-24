"""Persistente, nachvollziehbare QEC-Kohorte und fachliche Fallentscheidungen."""
from __future__ import annotations

import csv
import json
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
        from ntf_insight.storage.source_knowledge_store import SourceKnowledgeStore
        tp_fins = SourceKnowledgeStore(self.store).tp_dashboard_fins()
        # Avoid hundreds of DuckDB connections in a 173+ case QEC cohort.
        with self.store.connect() as con:
            saved = {
                case_id: json.loads(payload)
                for case_id, payload in con.execute(
                    "SELECT case_id, payload_json FROM case_snapshots"
                ).fetchall()
            }
            decisions = {
                case_id: (decision, reason)
                for case_id, decision, reason in con.execute(
                    "SELECT case_id, decision, reason FROM qec_workflow_decisions "
                    "WHERE source_sha256=?", [source.sha256],
                ).fetchall()
            }
        results = []
        for case in cases:
            reference = str(getattr(case, "qec_reference", "") or "")
            report = local_qec_archive(qec_root, case.vin, reference)
            finding = str(getattr(case, "qec_ssl_end_finding", "") or "")
            saved_case = saved.get(case.case_id)
            if saved_case is not None and saved_case.get("vehicle", {}).get("vin") == case.vin:
                finding = str(saved_case.get("qec_ssl_end_finding") or finding)
            decision, reason = decisions.get(case.case_id, ("Offen", ""))
            results.append({
                "case_id": case.case_id, "fin": case.vin,
                "reference": reference,
                "part_number": str(getattr(case, "qec_part_number", "") or ""),
                "finding": finding, "report": bool(report),
                "decision": decision, "reason": reason,
                "tp_dashboard": case.vin in tp_fins,
            })
        return results

    @staticmethod
    def summarize_rows(rows: list[dict]) -> dict[str, int]:
        counts = Counter(row["decision"] for row in rows)
        return {
            "cases": len(rows),
            "fins": len({r["fin"] for r in rows}),
            "downloaded": len({r["fin"] for r in rows if r["report"]}),
            "with_tp": len({r["fin"] for r in rows if r["tp_dashboard"]}),
            "without_tp": len({r["fin"] for r in rows if not r["tp_dashboard"]}),
            "ntf": counts["NTF"],
            "not_ntf": counts["Kein NTF"],
            "open": counts["Offen"],
        }

    def overview(self, qec_root: Path) -> dict[str, int]:
        return self.summarize_rows(self.rows(qec_root))

    def export_csv(
        self, destination: Path, qec_root: Path, *, part_number: str = "",
    ) -> int:
        """Lokale QEC-FIN-Liste – optional exakt zur gewählten Sachnummer.

        Das ist ein lokaler CSV-Export vorhandener QEC-Daten, kein automatischer
        Download aus dem QEC-Portal. Formeln aus Quelldaten bleiben Excel-sicher.
        """
        def normalize(value: str) -> str:
            return "".join(char for char in str(value).upper() if char.isalnum())

        def safe(value: object) -> object:
            text = str(value or "")
            return "'" + text if text.lstrip().startswith(("=", "+", "-", "@")) else text

        rows = self.rows(qec_root)
        if part_number.strip():
            part = normalize(part_number)
            rows = [row for row in rows if normalize(row["part_number"]) == part]
        with Path(destination).open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle, delimiter=";")
            writer.writerow(("FIN", "QEC-Fall", "Referenz", "Sachnummer",
                             "TP-Dashboard", "SSL-Endbefund", "QEC-Bericht vorhanden",
                             "NTF-Bewertung", "Begründung"))
            for row in rows:
                writer.writerow(tuple(map(safe, (
                    row["fin"], row["case_id"], row["reference"], row["part_number"],
                    "Vorhanden" if row["tp_dashboard"] else "Kein TP-Dashboard-Eintrag",
                    row["finding"], "Ja" if row["report"] else "Nein",
                    row["decision"], row["reason"],
                ))))
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
