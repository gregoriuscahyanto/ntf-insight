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

    def active_sources(self) -> list:
        return active_qec_lists(self.store.load_artifacts())

    def active_source(self):
        primary = self.active_sources()
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
        source = next((a for a in self.active_sources() if a.sha256 == sha), None)
        if source is None:
            raise ValueError("QEC-FIN-Liste nicht aktiv.")
        from ntf_insight.ingestion.real_source_parsers import QECWorkbookParser
        cases = QECWorkbookParser(sha).parse(Path(source.archived_path)).cases
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
        """Alle eindeutigen QEC-Quellen; in der GUI nach Projekt-Sachnummer filtern."""
        sources = self.active_sources()
        if not sources:
            return []
        from ntf_insight.ingestion.real_source_parsers import QECWorkbookParser
        from ntf_insight.storage.source_knowledge_store import SourceKnowledgeStore

        tp_fins = SourceKnowledgeStore(self.store).tp_dashboard_fins()
        with self.store.connect() as con:
            saved = {
                case_id: json.loads(payload)
                for case_id, payload in con.execute(
                    "SELECT case_id, payload_json FROM case_snapshots"
                ).fetchall()
            }
            decisions = {
                (sha, case_id): (decision, reason)
                for sha, case_id, decision, reason in con.execute(
                    "SELECT source_sha256,case_id,decision,reason "
                    "FROM qec_workflow_decisions"
                ).fetchall()
            }
        results = []
        by_case: dict[str, tuple[str, str, str]] = {}
        for source in sources:
            cases = QECWorkbookParser(source.sha256).parse(
                Path(source.archived_path)
            ).cases
            for case in cases:
                reference = str(getattr(case, "qec_reference", "") or "")
                part_number = str(getattr(case, "qec_part_number", "") or "")
                identity = (str(case.vin), reference, part_number)
                previous = by_case.setdefault(case.case_id, identity)
                if previous != identity:
                    raise ValueError(
                        "Widersprüchliche QEC-Fall-ID in mehreren Listen. "
                        "Quelllisten müssen fachlich bereinigt werden."
                    )
                # Idempotent stored QEC lists don't create duplicate rows.
                if any(r["case_id"] == case.case_id for r in results):
                    continue
                report = local_qec_archive(qec_root, case.vin, reference)
                finding = str(getattr(case, "qec_ssl_end_finding", "") or "")
                saved_case = saved.get(case.case_id)
                if (
                    saved_case is not None
                    and saved_case.get("vehicle", {}).get("vin") == case.vin
                ):
                    finding = str(saved_case.get("qec_ssl_end_finding") or finding)
                decision, reason = decisions.get(
                    (source.sha256, case.case_id), ("Offen", "")
                )
                results.append({
                    "source_sha256": source.sha256,
                    "case_id": case.case_id,
                    "fin": case.vin,
                    "reference": reference,
                    "part_number": part_number,
                    "finding": finding,
                    "report": bool(report),
                    "decision": decision,
                    "reason": reason,
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

    def handoff_ntf(
        self, qec_root: Path, *, part_number: str = "",
    ) -> int:
        from ntf_insight.storage.cluster_evidence_store import part_key

        rows = self.rows(qec_root)
        if part_number.strip():
            key = part_key(part_number)
            rows = [row for row in rows if part_key(row["part_number"]) == key]
        by_source: dict[str, dict[str, list[str]]] = {}
        for row in rows:
            by_source.setdefault(
                row["source_sha256"], {}
            ).setdefault(row["fin"], []).append(row["decision"])
        selected: set[str] = set()
        with self.store.connect() as con:
            con.execute("BEGIN TRANSACTION")
            try:
                for source in self.active_sources():
                    candidates = by_source.get(source.sha256, {})
                    if part_number.strip():
                        # Do not erase previously released FINs of other parts.
                        for fin in candidates:
                            con.execute(
                                "DELETE FROM qec_cluster_handoff WHERE "
                                "source_sha256=? AND fin=?",
                                [source.sha256, fin],
                            )
                    else:
                        con.execute(
                            "DELETE FROM qec_cluster_handoff WHERE source_sha256=?",
                            [source.sha256],
                        )
                    for fin, decisions in candidates.items():
                        if decisions and all(x == "NTF" for x in decisions):
                            con.execute(
                                "INSERT INTO qec_cluster_handoff VALUES (?,?)",
                                [source.sha256, fin],
                            )
                            selected.add(fin)
                con.execute("COMMIT")
            except Exception:
                con.execute("ROLLBACK")
                raise
        return len(selected)

    def handed_off_fins(self) -> tuple[str, ...]:
        sources = self.active_sources()
        if not sources:
            return ()
        with self.store.connect() as con:
            rows = con.execute(
                "SELECT source_sha256,fin FROM qec_cluster_handoff ORDER BY fin"
            ).fetchall()
        shas = {source.sha256 for source in sources}
        return tuple(sorted({fin for sha, fin in rows if sha in shas}))
