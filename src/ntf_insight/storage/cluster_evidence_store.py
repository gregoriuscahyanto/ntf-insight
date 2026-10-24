"""Fachlich klassifizierte Originalunterlagen für den zweiten Cluster-Durchlauf.

Die Dateien liegen unverändert im vorhandenen SHA-256-Rohdatenarchiv und
sind damit inklusive Metadaten über .ntfbackup übertragbar. Kein Parsen,
kein automatisches Hochladen, keine Rückwirkung auf QEC-Fachentscheidungen.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ntf_insight.ingestion.artifacts import RawArchive, SourceArtifact, SourceType
from ntf_insight.storage.duckdb_store import DuckDBStore
from ntf_insight.storage.workflow_progress import normalize_part_number

EVIDENCE_CATEGORIES = (
    ("tp_dashboard", "TP Dashboard"),
    ("diagnosis_viewer", "Diagnosis Viewer"),
    ("tips_writer", "TIPS Writer"),
    ("celonis", "Celonis"),
    ("cdd_smrd", "CDD / SMR-D"),
    ("ecu_messages", "ECU-Nachrichtenliste"),
    ("trigger_conditions", "Setzbedingungen (Excel)"),
    ("network_topology", "Vehicle Network Topology"),
    ("hardware_changes", "HW-Änderungsstände"),
    ("software_changes", "SW-Änderungsstände"),
    ("additional", "Weitere Unterlagen (Kühlung/Pumpe)"),
)
CATEGORY_LABELS = dict(EVIDENCE_CATEGORIES)
ALLOWED_SUFFIXES = frozenset({
    ".cdd", ".smr-d", ".pdf", ".csv", ".tsv", ".xlsx", ".xls", ".json",
    ".xml", ".txt", ".docx", ".doc", ".pptx", ".ppt", ".png", ".jpg",
    ".jpeg", ".svg", ".rtf", ".msg", ".eml", ".zip",
    ".smrd", ".dbc", ".arxml", ".odx", ".pdx", ".a2l", ".ldf", ".asc", ".fibex",
})
MAX_EVIDENCE_BYTES = 200 * 1024**2
MAX_CATEGORY_FILES = 500


def part_key(value: str) -> str:
    """Teilnummern nur innerhalb desselben Profils tolerant abgleichen."""
    return "".join(char for char in normalize_part_number(value) if char.isalnum())


def _profile(value: str) -> str:
    name = str(value).strip()
    if not name or len(name) > 80 or not all(c.isalnum() or c in "_-" for c in name):
        raise ValueError("Bauteilprofil ungültig.")
    return name


@dataclass(frozen=True)
class EvidenceFile:
    category: str
    sha256: str
    original_name: str
    size_bytes: int
    imported_at: datetime
    source_path: Path


class ClusterEvidenceStore:
    """Referenzgebundene Inventarliste pro Profil und Sachnummer, niemals FIN-Raten."""

    def __init__(self, store: DuckDBStore, *, raw_dir: Path | None = None) -> None:
        self.store = store
        self.archive = RawArchive(raw_dir or store.path.parent / "raw")
        with store.connect() as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS cluster_evidence_files (
                    profile_id VARCHAR NOT NULL,
                    part_key VARCHAR NOT NULL,
                    category VARCHAR NOT NULL,
                    sha256 VARCHAR NOT NULL,
                    imported_at TIMESTAMP NOT NULL DEFAULT now(),
                    PRIMARY KEY (profile_id, part_key, category, sha256)
                )
                """
            )

    def add_files(
        self, profile_id: str, part_number: str, category: str,
        files: list[Path],
    ) -> int:
        profile, part = _profile(profile_id), part_key(part_number)
        if category not in CATEGORY_LABELS:
            raise ValueError("Unbekannte Unterlagenkategorie.")
        if not files:
            return 0
        if len(files) > MAX_CATEGORY_FILES:
            raise ValueError("Zu viele Dateien in einer Auswahl.")
        existing = self.list_files(profile, part_number, category=category)
        if len(existing) + len(files) > MAX_CATEGORY_FILES:
            raise ValueError("Dateilimit für diese Kategorie erreicht.")
        # Vor dem ersten Schreibvorgang alle Pfade und Dateitypen prüfen.
        checked: list[Path] = []
        for candidate in files:
            source = Path(candidate).expanduser()
            if source.is_symlink() or not source.is_file():
                raise ValueError("Nur reguläre lokale Dateien, keine Verknüpfungen auswählen.")
            if source.suffix.casefold() not in ALLOWED_SUFFIXES:
                raise ValueError("Dateityp nicht zugelassen: " + source.suffix)
            if source.stat().st_size > MAX_EVIDENCE_BYTES:
                raise ValueError("Unterlage überschreitet 200 MiB.")
            checked.append(source)

        total_added = 0
        source_type = {
            "tp_dashboard": SourceType.TP_DASHBOARD,
            "tips_writer": SourceType.TIPS_CASE,
            "cdd_smrd": SourceType.DIAGNOSTIC_DESCRIPTION,
            "hardware_changes": SourceType.HW_SW_CHANGE_HISTORY,
            "software_changes": SourceType.HW_SW_CHANGE_HISTORY,
        }.get(category, SourceType.OTHER)
        for source in checked:
            kind = SourceType.SMR_D if source.suffix.lower() == ".smr-d" else source_type
            artifact = self.archive.archive(
                source, kind, source_system="Cluster-Kontext: " + CATEGORY_LABELS[category],
            )
            # Dieselbe Datei kann bereits aus einer anderen Datenquelle stammen.
            # Die bestehende Provenienz darf dabei nicht überschrieben werden.
            with self.store.connect() as con:
                exists = con.execute(
                    "SELECT 1 FROM source_artifacts WHERE sha256=?",
                    [artifact.sha256],
                ).fetchone()
            if not exists:
                self.store.save_artifact(artifact)
            with self.store.connect() as con:
                affected = con.execute(
                    "INSERT INTO cluster_evidence_files "
                    "(profile_id,part_key,category,sha256) VALUES (?,?,?,?) "
                    "ON CONFLICT DO NOTHING RETURNING sha256",
                    [profile, part, category, artifact.sha256],
                ).fetchone()
            total_added += int(affected is not None)
        return total_added

    def list_files(
        self, profile_id: str, part_number: str, *,
        category: str | None = None,
    ) -> list[EvidenceFile]:
        profile, part = _profile(profile_id), part_key(part_number)
        if category is not None and category not in CATEGORY_LABELS:
            raise ValueError("Unbekannte Unterlagenkategorie.")
        query = (
            "SELECT c.category,c.sha256,c.imported_at,a.payload_json "
            "FROM cluster_evidence_files c JOIN source_artifacts a "
            "ON a.sha256=c.sha256 "
            "WHERE c.profile_id=? AND c.part_key=?"
        )
        args: list[object] = [profile, part]
        if category is not None:
            query += " AND c.category=?"
            args.append(category)
        query += " ORDER BY c.category,c.imported_at,c.sha256"
        with self.store.connect() as con:
            rows = con.execute(query, args).fetchall()
        results: list[EvidenceFile] = []
        for kind, sha, imported, raw_json in rows:
            artifact = SourceArtifact.model_validate_json(raw_json)
            if artifact.sha256 != sha:
                raise ValueError("Dateizuordnung beschädigt.")
            results.append(EvidenceFile(
                category=kind, sha256=sha, original_name=artifact.original_name,
                size_bytes=artifact.size_bytes, imported_at=imported,
                source_path=Path(artifact.archived_path),
            ))
        return results

    def remove_file(
        self, profile_id: str, part_number: str, category: str, sha256: str,
    ) -> bool:
        """Nur Zuordnung entfernen, keine geteilten Originale oder Parserdaten löschen."""
        _profile(profile_id)
        if category not in CATEGORY_LABELS:
            raise ValueError("Unbekannte Unterlagenkategorie.")
        with self.store.connect() as con:
            row = con.execute(
                "DELETE FROM cluster_evidence_files "
                "WHERE profile_id=? AND part_key=? AND category=? AND sha256=? "
                "RETURNING sha256",
                [profile_id, part_key(part_number), category, sha256],
            ).fetchone()
        return row is not None

    def counts(self, profile_id: str, part_number: str) -> dict[str, int]:
        result = {category: 0 for category in CATEGORY_LABELS}
        for entry in self.list_files(profile_id, part_number):
            result[entry.category] += 1
        return result
