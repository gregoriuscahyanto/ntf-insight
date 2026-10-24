"""Persistenter, bauteilunabhängiger Bearbeitungsstand des Analyseworkflows.

Der Zustand liegt in derselben lokalen DuckDB wie die Fall- und Quellendaten.
Damit wird er durch den bereits vorhandenen .ntfbackup-Transfer übernommen.
Ein manuell bestätigter Schritt ist keine automatische Ursachenfeststellung.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from ntf_insight.storage.duckdb_store import DuckDBStore

STEP_COUNT = 6
MANUAL_STEPS = frozenset({3, 4, 5})
DEFAULT_PROFILE = "coolant_pump"


def normalize_part_number(value: str) -> str:
    """Keine feste Pumpensachnummer und kein stummes Ersetzen von Zeichen."""
    number = str(value).strip().upper()
    if len(number) > 120 or any(ord(char) < 32 for char in number):
        raise ValueError("Sachnummer muss maximal 120 druckbare Zeichen enthalten.")
    return number


def _profile(value: str) -> str:
    profile = str(value).strip()
    if not profile or len(profile) > 80 or not all(
        char.isalnum() or char in {"_", "-"} for char in profile
    ):
        raise ValueError("Ungültiges Bauteilprofil.")
    return profile


@dataclass(frozen=True, slots=True)
class WorkflowProgress:
    step: int = 0
    paused: bool = False
    reviewed_steps: tuple[int, ...] = ()


class WorkflowProgressStore:
    """Schritt, Pausenstatus und manueller Review je Bauteil/Sachnummer."""

    def __init__(self, store: DuckDBStore) -> None:
        self.store = store
        with store.connect() as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS workflow_progress (
                    profile_id VARCHAR NOT NULL,
                    part_number VARCHAR NOT NULL,
                    step INTEGER NOT NULL,
                    paused BOOLEAN NOT NULL,
                    reviewed_json VARCHAR NOT NULL,
                    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (profile_id, part_number)
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS workflow_current_context (
                    slot INTEGER PRIMARY KEY,
                    profile_id VARCHAR NOT NULL,
                    part_number VARCHAR NOT NULL
                )
                """
            )

    def current_context(self) -> tuple[str, str]:
        with self.store.connect() as con:
            row = con.execute(
                "SELECT profile_id, part_number FROM workflow_current_context WHERE slot=1"
            ).fetchone()
        return (row[0], row[1]) if row else (DEFAULT_PROFILE, "")

    def select_context(self, profile_id: str, part_number: str) -> None:
        profile, part = _profile(profile_id), normalize_part_number(part_number)
        with self.store.connect() as con:
            con.execute(
                "INSERT INTO workflow_current_context VALUES (1, ?, ?) "
                "ON CONFLICT (slot) DO UPDATE SET "
                "profile_id=excluded.profile_id, part_number=excluded.part_number",
                [profile, part],
            )

    def load(self, profile_id: str, part_number: str) -> WorkflowProgress:
        profile, part = _profile(profile_id), normalize_part_number(part_number)
        with self.store.connect() as con:
            row = con.execute(
                "SELECT step, paused, reviewed_json FROM workflow_progress "
                "WHERE profile_id=? AND part_number=?",
                [profile, part],
            ).fetchone()
        if row is None:
            return WorkflowProgress()
        try:
            reviewed = tuple(
                sorted({int(step) for step in json.loads(row[2]) if int(step) in MANUAL_STEPS})
            )
        except (ValueError, TypeError, json.JSONDecodeError):
            reviewed = ()
        return WorkflowProgress(
            step=max(0, min(STEP_COUNT - 1, int(row[0]))),
            paused=bool(row[1]),
            reviewed_steps=reviewed,
        )

    def save(self, profile_id: str, part_number: str, state: WorkflowProgress) -> None:
        profile, part = _profile(profile_id), normalize_part_number(part_number)
        if not 0 <= state.step < STEP_COUNT:
            raise ValueError("Ungültiger Workflowschritt.")
        reviewed = tuple(sorted(set(state.reviewed_steps)))
        if any(step not in MANUAL_STEPS for step in reviewed):
            raise ValueError("Nur Unterlagen-, Analyse- und Review-Schritte dürfen manuell bestätigt werden.")
        with self.store.connect() as con:
            con.execute(
                """
                INSERT INTO workflow_progress
                    (profile_id, part_number, step, paused, reviewed_json)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT (profile_id, part_number) DO UPDATE SET
                    step=excluded.step,
                    paused=excluded.paused,
                    reviewed_json=excluded.reviewed_json,
                    updated_at=now()
                """,
                [profile, part, state.step, state.paused, json.dumps(reviewed)],
            )
