"""Use NTF Insight's existing SourceKnowledgeStore for SMR-D references."""
from __future__ import annotations

from pathlib import Path
from ntf_insight.smrd.library import SmrdLocalLibrary, digest
from ntf_insight.smrd.xml_reference import parse_xml


class SmrdImportService:
    def __init__(self, *, data_dir: Path | None = None):
        self.library = SmrdLocalLibrary(data_dir=data_dir)

    def preview(self, xml: Path, *, skip_dtcs: bool = False):
        return parse_xml(xml, include_dtcs=not skip_dtcs)

    def import_xml(self, xml: Path, *, skip_dtcs: bool = False) -> int:
        metadata, rows = self.preview(xml, skip_dtcs=skip_dtcs)
        from ntf_insight.storage.duckdb_store import DuckDBStore
        from ntf_insight.storage.source_knowledge_store import SourceKnowledgeStore
        sha = digest(Path(xml))
        metadata["xml_sha256"] = sha
        metadata["is_vehicle_event"] = False
        metadata["trigger_conditions_validated"] = False
        store = SourceKnowledgeStore(DuckDBStore(self.library.root.parent / "ntf-insight.duckdb"))
        return store.save_records(sha, "smrd_xml_reference", rows, metadata=metadata)
