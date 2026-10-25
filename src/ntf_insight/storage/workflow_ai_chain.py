"""Automatische, PC-übertragbare Verknüpfung der beiden LLM-Durchläufe.

Das in Schritt 03 erstellte ZIP wird als unveränderliches SHA-Artefakt im
bestehenden raw/-Archiv gehalten. Für Schritt 05 wird nur eine bereits
importierte erste LLM-Antwort mit derselben paket_id verwendet.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from ntf_insight.ingestion.artifacts import RawArchive, SourceArtifact, SourceType
from ntf_insight.reporting.chatgpt_exchange import ChatGPTRueckgabe
from ntf_insight.reporting.cluster_context_package import validate_first_package
from ntf_insight.storage.cluster_evidence_store import part_key
from ntf_insight.storage.duckdb_store import DuckDBStore

_CHUNK = 1024 * 1024


def _profile_id(profile_id: str) -> str:
    profile = str(profile_id).strip()
    if not profile or len(profile) > 80 or not all(
        c.isalnum() or c in "_-" for c in profile
    ):
        raise ValueError("Ungültiges Bauteilprofil.")
    return profile


@dataclass(frozen=True)
class FirstPackage:
    paket_id: str
    path: Path
    sha256: str
    analysis_id: str | None
    part_specific: bool


class WorkflowAIChainStore:
    """Paket-/Analyse-Zuordnung; Fallbewertungen bleiben separat gespeichert."""

    def __init__(self, store: DuckDBStore) -> None:
        self.store = store
        self.archive = RawArchive(store.path.parent / "raw")
        with store.connect() as con:
            con.execute("""
                CREATE TABLE IF NOT EXISTS workflow_first_ai_packages (
                    profile_id VARCHAR NOT NULL,
                    part_key VARCHAR NOT NULL,
                    paket_id VARCHAR NOT NULL,
                    sha256 VARCHAR NOT NULL,
                    registered_at TIMESTAMP NOT NULL DEFAULT now(),
                    PRIMARY KEY(profile_id,part_key,paket_id)
                )
            """)
            con.execute("""
                CREATE TABLE IF NOT EXISTS workflow_second_ai_exports (
                    paket_id VARCHAR NOT NULL,
                    analyse_id VARCHAR NOT NULL,
                    profile_id VARCHAR NOT NULL,
                    part_key VARCHAR NOT NULL,
                    exported_at TIMESTAMP NOT NULL DEFAULT now(),
                    PRIMARY KEY (paket_id,analyse_id)
                )
            """)
            con.execute("""
                CREATE TABLE IF NOT EXISTS workflow_ai_rounds (
                    paket_id VARCHAR NOT NULL,
                    analyse_id VARCHAR NOT NULL,
                    round_number INTEGER NOT NULL,
                    registered_at TIMESTAMP NOT NULL DEFAULT now(),
                    PRIMARY KEY(paket_id,analyse_id)
                )
            """)

    def register_first_export(
        self, profile_id: str, part_number: str, exported_zip: Path,
    ) -> FirstPackage:
        profile, key = _profile_id(profile_id), part_key(part_number)
        path = Path(exported_zip)
        if path.is_symlink():
            raise ValueError("Symbolische Links sind für KI-Analysepakete nicht zulässig.")
        package_id = validate_first_package(path)
        with self.store.connect() as con:
            mapping = con.execute(
                "SELECT 1 FROM chatgpt_export_mapping WHERE paket_id=? LIMIT 1",
                [package_id],
            ).fetchone()
        if mapping is None:
            raise ValueError(
                "Analysepaket hat keine lokale Pseudonymzuordnung. "
                "Nur erfolgreich in NTF Insight erzeugte Pakete sind zulässig."
            )
        artifact = self.archive.archive(
            path, SourceType.OTHER,
            source_system="Workflow: erste KI-Analysebasis",
        )
        with self.store.connect() as con:
            exists = con.execute(
                "SELECT 1 FROM source_artifacts WHERE sha256=?",
                [artifact.sha256],
            ).fetchone()
        if not exists:
            self.store.save_artifact(artifact)
        with self.store.connect() as con:
            con.execute(
                "INSERT INTO workflow_first_ai_packages "
                "(profile_id,part_key,paket_id,sha256) VALUES (?,?,?,?) "
                "ON CONFLICT (profile_id,part_key,paket_id) DO UPDATE SET "
                "sha256=excluded.sha256,registered_at=now()",
                [profile, key, package_id, artifact.sha256],
            )
        return self.latest_first_export(profile_id, part_number)

    def latest_first_export(
        self, profile_id: str, part_number: str,
    ) -> FirstPackage | None:
        profile, key = _profile_id(profile_id), part_key(part_number)
        with self.store.connect() as con:
            rows = con.execute(
                "SELECT f.paket_id,f.sha256,f.part_key,a.payload_json "
                "FROM workflow_first_ai_packages f "
                "JOIN source_artifacts a ON a.sha256=f.sha256 "
                "WHERE f.profile_id=? AND f.part_key=? "
                "ORDER BY f.registered_at DESC, f.paket_id DESC",
                [profile, key],
            ).fetchall()
        for package_id, sha, stored_key, payload in rows:
            artifact = SourceArtifact.model_validate_json(payload)
            path = Path(artifact.archived_path)
            if artifact.sha256 != sha or not path.is_file() or path.is_symlink():
                continue
            result = self.first_result(package_id)
            return FirstPackage(
                paket_id=package_id, path=path, sha256=sha,
                analysis_id=result["analyse_id"] if result else None,
                part_specific=bool(key and key == stored_key),
            )
        return None

    def record_import(self, analyse_id: str, *, round_number: int) -> bool:
        if round_number not in (1, 2):
            raise ValueError("Unbekannter LLM-Durchlauf.")
        with self.store.connect() as con:
            row = con.execute(
                "SELECT paket_id FROM chatgpt_imports WHERE analyse_id=?",
                [analyse_id],
            ).fetchone()
            if row is None:
                raise ValueError("LLM-Ergebnis wurde noch nicht importiert.")
            package_id = row[0]
            linked = con.execute(
                "SELECT 1 FROM workflow_first_ai_packages "
                "WHERE paket_id=? LIMIT 1", [package_id],
            ).fetchone()
            if not linked:
                return False
            if round_number == 2:
                prepared = con.execute(
                    "SELECT 1 FROM workflow_second_ai_exports "
                    "WHERE paket_id=? AND analyse_id=?",
                    [package_id, analyse_id],
                ).fetchone()
                if prepared is None:
                    raise ValueError(
                        "Zweites LLM-Ergebnis passt zu keinem zuvor "
                        "erzeugten Cluster-Kontextpaket."
                    )
            con.execute(
                "INSERT INTO workflow_ai_rounds "
                "(paket_id,analyse_id,round_number) VALUES (?,?,?) "
                "ON CONFLICT (paket_id,analyse_id) DO UPDATE SET "
                "round_number=excluded.round_number",
                [package_id, analyse_id, round_number],
            )
        return True

    def first_result(self, package_id: str) -> dict | None:
        """Nur explizit als 1. Durchlauf importierte Antwort verwenden."""
        with self.store.connect() as con:
            row = con.execute(
                "SELECT i.original_json FROM chatgpt_imports i "
                "JOIN workflow_ai_rounds r ON r.analyse_id=i.analyse_id "
                "AND r.paket_id=i.paket_id "
                "WHERE r.paket_id=? AND r.round_number=1 "
                "ORDER BY r.registered_at DESC,r.analyse_id DESC LIMIT 1",
                [package_id],
            ).fetchone()
        if row is None:
            return None
        payload = json.loads(row[0])
        data = ChatGPTRueckgabe.model_validate(payload)
        if data.paket_id != package_id:
            raise ValueError("Erste LLM-Auswertung gehört zu einem anderen Paket.")
        return data.model_dump(exclude_none=True)

    def validate_cached_zip(self, package: FirstPackage) -> None:
        """Beim Export Prüfsumme und Paket-ID erneut verifizieren."""
        digest = hashlib.sha256()
        with package.path.open("rb") as handle:
            for block in iter(lambda: handle.read(_CHUNK), b""):
                digest.update(block)
        if digest.hexdigest() != package.sha256:
            raise ValueError("Gespeichertes KI-Analysepaket wurde verändert.")
        if validate_first_package(package.path) != package.paket_id:
            raise ValueError("Paket-ID und interne KI-Basis stimmen nicht überein.")


    def register_second_export(
        self, profile_id: str, part_number: str,
        paket_id: str, analyse_id: str,
    ) -> None:
        profile, key = _profile_id(profile_id), part_key(part_number)
        with self.store.connect() as con:
            row = con.execute(
                "SELECT 1 FROM workflow_first_ai_packages "
                "WHERE profile_id=? AND part_key=? AND paket_id=?",
                [profile, key, paket_id],
            ).fetchone()
            if row is None:
                raise ValueError("Die zweite Exportbasis gehört zu einem anderen Projekt.")
            con.execute(
                "INSERT INTO workflow_second_ai_exports "
                "(paket_id,analyse_id,profile_id,part_key) VALUES (?,?,?,?) "
                "ON CONFLICT (paket_id,analyse_id) DO NOTHING",
                [paket_id, analyse_id, profile, key],
            )

    def is_prepared_second(
        self, profile_id: str, part_number: str,
        paket_id: str, analyse_id: str,
    ) -> bool:
        profile, key = _profile_id(profile_id), part_key(part_number)
        with self.store.connect() as con:
            return con.execute(
                "SELECT 1 FROM workflow_second_ai_exports WHERE "
                "profile_id=? AND part_key=? AND paket_id=? AND analyse_id=?",
                [profile, key, paket_id, analyse_id],
            ).fetchone() is not None

    def second_status(self, paket_id: str) -> tuple[int, int]:
        """Erzeugte Clusterpakete und zugehörige importierte Ergebnisse."""
        with self.store.connect() as con:
            prepared = con.execute(
                "SELECT COUNT(*) FROM workflow_second_ai_exports WHERE paket_id=?",
                [paket_id],
            ).fetchone()[0]
            imported = con.execute(
                "SELECT COUNT(*) FROM workflow_ai_rounds "
                "WHERE paket_id=? AND round_number=2",
                [paket_id],
            ).fetchone()[0]
        return int(prepared), int(imported)
