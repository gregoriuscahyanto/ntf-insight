"""Projektzuordnung fuer generische QEC-Faelle ohne erzwungene Bauteilannahmen.

Der QEC-Excel-Parser kennt nicht jedes moegliche Bauteilprofil. Bei
unbekannter Benennung darf ein Fall nur dann auf ein explizit gespeichertes
Sachnummernprojekt aufgeloest werden, wenn der Part-Key eindeutig diesem
Profil gehoert. Ein vorliegendes Quellprofil hat immer Vorrang.
"""
from __future__ import annotations

from collections.abc import Iterable

from ntf_insight.storage.cluster_evidence_store import part_key
from ntf_insight.storage.workflow_projects import NTFProject


def qec_case_matches_project(
    *,
    case_part_number: str,
    source_profile_id: str | None,
    project_profile_id: str,
    project_part_number: str,
    projects: Iterable[NTFProject],
) -> bool:
    """Fail closed when an unknown QEC component is ambiguous."""
    expected = part_key(project_part_number)
    if not expected or part_key(case_part_number) != expected:
        return False
    if source_profile_id:
        return source_profile_id == project_profile_id
    # Benennung unbekannt: niemals nur wegen gleicher FIN zuordnen.
    matching_profiles = {
        project.profile_id for project in projects
        if part_key(project.part_number) == expected
    }
    return matching_profiles == {project_profile_id}
