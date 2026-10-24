"""Projektverwaltung für den sachnummernbasierten NTF-Workflow.

Ein Projekt ist ein Bauteilprofil + Sachnummer. Steuergeräte und Hinweise
sind editierbar; der bestehende Fallbestand wird nicht automatisch umbenannt.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from ntf_insight.storage.cluster_evidence_store import part_key
from ntf_insight.storage.duckdb_store import DuckDBStore
from ntf_insight.storage.workflow_progress import normalize_part_number


@dataclass(frozen=True)
class NTFProject:
    profile_id: str
    part_number: str
    component_name: str
    ecu_names: tuple[str, ...]
    description: str = ""

    @property
    def title(self) -> str:
        return f"{self.component_name} [{self.part_number}]"


class WorkflowProjectStore:
    def __init__(self, store: DuckDBStore) -> None:
        self.store = store
        with store.connect() as con:
            con.execute("""
                CREATE TABLE IF NOT EXISTS workflow_projects (
                    profile_id VARCHAR NOT NULL,
                    part_key VARCHAR NOT NULL,
                    part_number VARCHAR NOT NULL,
                    component_name VARCHAR NOT NULL,
                    ecu_json VARCHAR NOT NULL,
                    description VARCHAR NOT NULL DEFAULT '',
                    created_at TIMESTAMP NOT NULL DEFAULT now(),
                    modified_at TIMESTAMP NOT NULL DEFAULT now(),
                    PRIMARY KEY(profile_id,part_key)
                )
            """)

    @staticmethod
    def _validate(
        profile: str, part: str, name: str, ecus: tuple[str, ...],
        description: str,
    ) -> tuple[str, str, str, str, tuple[str, ...]]:
        profile = str(profile).strip()
        if not profile or len(profile) > 80 or not all(
            ch.isalnum() or ch in "_-" for ch in profile
        ):
            raise ValueError("Ungültiges Bauteilprofil.")
        part = normalize_part_number(part)
        if not part:
            raise ValueError("Für ein Projekt ist eine Sachnummer erforderlich.")
        name = str(name).strip()
        if not name or len(name) > 100 or any(ord(x) < 32 for x in name):
            raise ValueError("Bauteilbezeichnung ungültig.")
        if len(description) > 2000 or any(ord(x) < 32 and x not in "\n\t" for x in description):
            raise ValueError("Projektbeschreibung ungültig.")
        normalized_ecus = tuple(dict.fromkeys(x.strip().upper() for x in ecus if x.strip()))
        if len(normalized_ecus) > 40 or any(
            len(ecu) > 48 or any(ord(c) < 32 for c in ecu) for ecu in normalized_ecus
        ):
            raise ValueError("Steuergeräteliste enthält ungültige Einträge.")
        return profile, part, name, description, normalized_ecus

    def save(self, project: NTFProject, *, create_only: bool = False) -> NTFProject:
        profile, part, name, description, ecus = self._validate(
            project.profile_id, project.part_number,
            project.component_name, project.ecu_names, project.description,
        )
        key = part_key(part)
        with self.store.connect() as con:
            old = con.execute(
                "SELECT 1 FROM workflow_projects WHERE profile_id=? AND part_key=?",
                [profile, key],
            ).fetchone()
            if old and create_only:
                raise ValueError(
                    "Dieses Bauteil/Sachnummer-Projekt existiert bereits. "
                    "Bitte in der Projektauswahl öffnen."
                )
            con.execute(
                "INSERT INTO workflow_projects "
                "(profile_id,part_key,part_number,component_name,ecu_json,description) "
                "VALUES (?,?,?,?,?,?) "
                "ON CONFLICT (profile_id,part_key) DO UPDATE SET "
                "part_number=excluded.part_number,"
                "component_name=excluded.component_name,"
                "ecu_json=excluded.ecu_json,description=excluded.description,"
                "modified_at=now()",
                [profile,key,part,name,json.dumps(ecus,ensure_ascii=False),description],
            )
        return NTFProject(profile,part,name,ecus,description)

    def get(self, profile: str, part: str) -> NTFProject | None:
        if not part.strip():
            return None
        with self.store.connect() as con:
            row = con.execute(
                "SELECT profile_id,part_number,component_name,ecu_json,description "
                "FROM workflow_projects WHERE profile_id=? AND part_key=?",
                [profile,part_key(part)],
            ).fetchone()
        if row is None:
            return None
        return NTFProject(
            row[0],row[1],row[2],tuple(json.loads(row[3])),row[4]
        )

    def list_projects(self) -> list[NTFProject]:
        with self.store.connect() as con:
            rows = con.execute(
                "SELECT profile_id,part_number,component_name,ecu_json,description "
                "FROM workflow_projects ORDER BY modified_at DESC,profile_id,part_number"
            ).fetchall()
        return [
            NTFProject(p,n,c,tuple(json.loads(e)),description)
            for p,n,c,e,description in rows
        ]
