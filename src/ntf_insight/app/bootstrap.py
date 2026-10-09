"""Load application repositories from persistent storage or demo data."""

from __future__ import annotations

from dataclasses import dataclass

from ntf_insight.app.settings import AppPaths
from ntf_insight.demo.synthetic_cases import build_demo_repository
from ntf_insight.demo.synthetic_reference import build_demo_reference_repository
from ntf_insight.storage.duckdb_store import DuckDBStore
from ntf_insight.storage.quicktest_store import QuickTestStore
from ntf_insight.storage.source_knowledge_store import SourceKnowledgeStore
from ntf_insight.storage.reference_repositories import InMemoryReferenceRepository
from ntf_insight.storage.repositories import InMemoryCaseRepository


@dataclass(frozen=True, slots=True)
class ApplicationData:
    cases: InMemoryCaseRepository
    references: InMemoryReferenceRepository
    mode: str
    paths: AppPaths


def load_application_data(paths: AppPaths | None = None) -> ApplicationData:
    paths = paths or AppPaths.default()
    paths.ensure()

    store = DuckDBStore(paths.database_path)
    persisted_cases = store.load_cases()
    persisted_triggers = store.load_triggers()
    persisted_changes = store.load_changes()

    # PDF-only import is real FIN-scoped data even before any NTF repair case
    # exists. Do not mix fictional demo cases into that vehicle's analysis.
    has_real_quicktests = bool(QuickTestStore(store).list_fins())
    has_reference_sources = bool(SourceKnowledgeStore(store).summary())
    if persisted_cases or has_real_quicktests or has_reference_sources:
        return ApplicationData(
            cases=InMemoryCaseRepository(persisted_cases),
            references=InMemoryReferenceRepository(persisted_triggers, persisted_changes),
            mode="local",
            paths=paths,
        )

    return ApplicationData(
        cases=build_demo_repository(),
        references=build_demo_reference_repository(),
        mode="demo",
        paths=paths,
    )
