"""Persistente SSL-Endbefund-Auswahl je Sachnummernprojekt.

Die Auswahl wirkt auf die nachfolgenden FIN-Kohorten (02-05), nicht auf
die ursprüngliche QEC-Tabelle oder den gespeicherten Rohdatenbestand.
"""
from __future__ import annotations

from collections import defaultdict

from ntf_insight.storage.cluster_evidence_store import part_key
from ntf_insight.storage.duckdb_store import DuckDBStore

MISSING = "Nicht angegeben"
MULTIPLE = "Mehrere Endbefunde"


def fin_ssl_groups(rows: list[dict]) -> dict[str, str]:
    """Ein FIN zählt bei mehreren widersprüchlichen Endbefunden separat."""
    findings: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        fin = str(row.get("fin") or "").strip().upper()
        if fin:
            findings[fin].add(str(row.get("finding") or "").strip() or MISSING)
    return {
        fin: next(iter(names)) if len(names) == 1 else MULTIPLE
        for fin, names in findings.items()
    }


class WorkflowSSLSelection:
    def __init__(self, store: DuckDBStore) -> None:
        self.store = store
        with store.connect() as con:
            con.execute("""
                CREATE TABLE IF NOT EXISTS workflow_ssl_selection (
                    profile_id VARCHAR NOT NULL,
                    part_key VARCHAR NOT NULL,
                    category VARCHAR NOT NULL,
                    included BOOLEAN NOT NULL,
                    PRIMARY KEY(profile_id,part_key,category)
                )
            """)

    def selected(self, profile: str, part: str) -> set[str] | None:
        with self.store.connect() as con:
            rows = con.execute(
                "SELECT category,included FROM workflow_ssl_selection "
                "WHERE profile_id=? AND part_key=?",
                [profile, part_key(part)],
            ).fetchall()
        if not rows:
            return None  # Noch nicht konfiguriert: alle vorhandenen FINs.
        return {category for category, included in rows if included}

    def save(
        self, profile: str, part: str,
        categories: set[str], selected: set[str],
    ) -> None:
        """Auch 'keine ausgewählt' bleibt als explizite Auswahl gespeichert."""
        if selected - categories:
            raise ValueError("Unbekannter SSL-Endbefund ausgewählt.")
        if not categories:
            return
        with self.store.connect() as con:
            con.execute("BEGIN TRANSACTION")
            try:
                con.execute(
                    "DELETE FROM workflow_ssl_selection "
                    "WHERE profile_id=? AND part_key=?",
                    [profile, part_key(part)],
                )
                con.executemany(
                    "INSERT INTO workflow_ssl_selection VALUES (?,?,?,?)",
                    [(profile, part_key(part), category, category in selected)
                     for category in sorted(categories)],
                )
                con.execute("COMMIT")
            except Exception:
                con.execute("ROLLBACK")
                raise

    def allowed_fins(
        self, profile: str, part: str, rows: list[dict],
    ) -> set[str]:
        grouped = fin_ssl_groups(rows)
        selected = self.selected(profile, part)
        if selected is None:
            return set(grouped)
        return {fin for fin, label in grouped.items() if label in selected}
