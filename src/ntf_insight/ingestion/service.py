"""High-level local source ingestion service.

This service archives and registers original files. Parsing is deliberately separate so
unsupported formats can still be preserved with full provenance.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from ntf_insight.ingestion.artifacts import RawArchive, SourceArtifact, SourceType
from ntf_insight.storage.duckdb_store import DuckDBStore


class SourceImportService:
    def __init__(self, raw_dir: Path, database_path: Path) -> None:
        self.archive = RawArchive(raw_dir)
        self.store = DuckDBStore(database_path)

    def import_raw(
        self,
        path: Path,
        source_type: SourceType,
        *,
        source_system: str | None = None,
        vin_hint: str | None = None,
        case_id_hint: str | None = None,
        remote_ref: str | None = None,
        report_date: datetime | None = None,
    ) -> SourceArtifact:
        artifact = self.archive.archive(
            path,
            source_type=source_type,
            source_system=source_system,
            vin_hint=vin_hint,
            case_id_hint=case_id_hint,
            remote_ref=remote_ref,
            report_date=report_date,
        )
        self.store.save_artifact(artifact)
        return artifact

    def list_artifacts(self) -> list[SourceArtifact]:
        return self.store.load_artifacts()

    def delete_artifact(self, sha256: str) -> None:
        """Remove one archived source and source-owned derived data.

        Never touch files outside the content-addressed local raw archive.
        A QEC-primary list is allowed to be deleted only when it has no
        independently manually edited cases; this avoids silent evidence loss.
        """
        from ntf_insight.ingestion.qec_primary import active_qec_lists
        from ntf_insight.ingestion.real_source_parsers import QECWorkbookParser
        from ntf_insight.storage.quicktest_store import QuickTestStore
        from ntf_insight.storage.source_knowledge_store import SourceKnowledgeStore

        artifacts = self.list_artifacts()
        target = next((a for a in artifacts if a.sha256 == sha256), None)
        if target is None:
            raise ValueError("Archivierte Datei nicht gefunden.")
        archive_path = Path(target.archived_path).resolve()
        raw_root = self.archive.root.resolve()
        if not archive_path.is_relative_to(raw_root) or archive_path.is_symlink():
            raise ValueError("Quelldatei liegt außerhalb des sicheren Rohdatenarchivs.")

        primary = bool(active_qec_lists([target]))
        source_cases = []
        if primary:
            source_cases = QECWorkbookParser(target.sha256).parse(archive_path).cases
        original_ids = {c.case_id for c in source_cases}

        # Manual edits must never be silently dropped.
        with self.store.connect() as con:
            if original_ids:
                for case_id in original_ids:
                    if con.execute(
                        "SELECT COUNT(*) FROM manual_changes WHERE case_id=?",
                        [case_id],
                    ).fetchone()[0]:
                        raise ValueError(
                            "Die QEC-Liste enthält manuell bearbeitete Fälle. "
                            "Bitte Änderungen vor dem Löschen gesondert prüfen."
                        )
            con.execute("BEGIN TRANSACTION")
            try:
                if primary:
                    for case_id in original_ids:
                        con.execute("DELETE FROM case_snapshots WHERE case_id=?", [case_id])
                    con.execute("DELETE FROM qec_workflow_decisions WHERE source_sha256=?", [sha256])
                    con.execute("DELETE FROM qec_cluster_handoff WHERE source_sha256=?", [sha256])
                # Source-specific normalized knowledge.
                SourceKnowledgeStore(self.store) if False else None
                con.execute("DELETE FROM source_knowledge_rows WHERE source_sha256=?", [sha256])
                con.execute("DELETE FROM source_knowledge_documents WHERE source_sha256=?", [sha256])
                # QuickTest reports can be shared across PDFs: remove only
                # an unreferenced report with no other imported source.
                report = con.execute(
                    "SELECT report_id FROM quicktest_sources WHERE artifact_sha256=?",
                    [sha256],
                ).fetchone()
                con.execute("DELETE FROM quicktest_sources WHERE artifact_sha256=?", [sha256])
                if report:
                    report_id = report[0]
                    if not con.execute(
                        "SELECT 1 FROM quicktest_sources WHERE report_id=? LIMIT 1",
                        [report_id],
                    ).fetchone():
                        for name in (
                            "quicktest_parameters", "quicktest_dtcs", "quicktest_ecus",
                            "quicktest_pages", "quicktest_reports",
                        ):
                            con.execute(f"DELETE FROM {name} WHERE report_id=?", [report_id])
                con.execute("DELETE FROM parse_runs WHERE artifact_sha256=?", [sha256])
                con.execute("DELETE FROM source_artifacts WHERE sha256=?", [sha256])
                con.execute("COMMIT")
            except Exception:
                con.execute("ROLLBACK")
                raise
        archive_path.unlink(missing_ok=True)
