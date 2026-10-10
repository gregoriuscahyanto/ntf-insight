"""Lokal gespeicherte Fachmarkierungen fuer exakte ECU:DTC-Kombinationen.

Die Markierung ist eine menschliche Pruefhypothese und weder ein
Ursachenurteil noch ein automatisch erlerntes Clustering-Merkmal.
"""
from __future__ import annotations

from dataclasses import dataclass

from ntf_insight.storage.duckdb_store import DuckDBStore

FaultKey = tuple[str, str]


def normalize_key(ecu: str, dtc: str) -> FaultKey:
    key = (ecu.strip().upper(), dtc.strip().upper())
    if not all(key) or any(len(part) > 128 for part in key):
        raise ValueError("Bitte eine gueltige ECU:DTC-Kombination auswaehlen.")
    return key


@dataclass(frozen=True, slots=True)
class DtcReviewMark:
    ecu: str
    dtc: str
    note: str = ""

    @property
    def key(self) -> FaultKey:
        return self.ecu, self.dtc


class DtcReviewStore:
    """Independent local table; source imports must NEVER overwrite it."""

    def __init__(self, store: DuckDBStore, *, initialize: bool = True) -> None:
        self.store = store
        if initialize:
            with self.store.connect() as con:
                con.execute(
                    """
                    CREATE TABLE IF NOT EXISTS dtc_manual_review_marks (
                        ecu VARCHAR NOT NULL,
                        dtc VARCHAR NOT NULL,
                        note VARCHAR NOT NULL DEFAULT '',
                        updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY(ecu, dtc)
                    )
                    """
                )

    def list_marks(self) -> dict[FaultKey, DtcReviewMark]:
        with self.store.connect() as con:
            rows = con.execute(
                "SELECT ecu, dtc, note FROM dtc_manual_review_marks "
                "ORDER BY ecu, dtc"
            ).fetchall()
        return {
            (ecu, dtc): DtcReviewMark(ecu, dtc, note or "")
            for ecu, dtc, note in rows
        }

    def mark(
        self, ecu: str, dtc: str, *, relevant: bool, note: str = "",
    ) -> None:
        ecu, dtc = normalize_key(ecu, dtc)
        if len(note) > 500:
            raise ValueError("Fachliche Notiz darf hoechstens 500 Zeichen haben.")
        with self.store.connect() as con:
            if relevant:
                con.execute(
                    """
                    INSERT INTO dtc_manual_review_marks
                        (ecu, dtc, note, updated_at)
                    VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT (ecu, dtc) DO UPDATE SET
                        note = excluded.note,
                        updated_at = excluded.updated_at
                    """,
                    [ecu, dtc, note.strip()],
                )
            else:
                con.execute(
                    "DELETE FROM dtc_manual_review_marks "
                    "WHERE ecu = ? AND dtc = ?",
                    [ecu, dtc],
                )
