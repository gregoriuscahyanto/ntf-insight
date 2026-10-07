"""Persistence abstractions for NTF Insight."""

from ntf_insight.storage.reference_repositories import InMemoryReferenceRepository, ReferenceRepository
from ntf_insight.storage.repositories import CaseRepository, InMemoryCaseRepository

__all__ = [
    "CaseRepository",
    "InMemoryCaseRepository",
    "InMemoryReferenceRepository",
    "ReferenceRepository",
]
