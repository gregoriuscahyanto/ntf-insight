"""Gesicherter Ersatz eines vorhandenen Projekts derselben Sachnummer.

Austausch ausschliesslich in einer Arbeitskopie. Der Zielbestand bleibt bis
zur erfolgreichen Validierung des Ersatzstands unangetastet. Die vollstaendige
Sicherung des Ziel-PCs wird dauerhaft ausserhalb der App abgelegt.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Callable

from ntf_insight.ingestion.portable_backup import (
    DATABASE_NAME, export_portable_backup, restore_portable_backup,
)
from ntf_insight.ingestion.project_portable import (
    ProjectImportResult, import_project, inspect_project_identity,
)
from ntf_insight.storage.cluster_evidence_store import part_key
from ntf_insight.storage.duckdb_store import DuckDBStore
from ntf_insight.storage.workflow_project_deletion import fully_delete_project
from ntf_insight.storage.workflow_projects import WorkflowProjectStore

Progress = Callable[[int, str], None]


def replace_existing_project(
    source: Path,
    data_dir: Path,
    backup_path: Path,
    *,
    progress: Progress | None = None,
) -> ProjectImportResult:
    """Vorhandenes Sachnummernprojekt durch ein geprueftes Paket ersetzen.

    Ablauf: dauerhafte .ntfbackup-Sicherung, Zielbestand in isolierter
    Arbeitskopie wiederherstellen, NUR das eindeutige alte Projekt entfernen,
    das eingehende Projekt importieren, Gesamtergebnis erneut validieren,
    schliesslich atomar ueber den bestehenden Restore-Mechanismus anwenden.
    Vor der letzten Aktion wird das laufende Original NICHT veraendert.
    """
    root = Path(data_dir).absolute()
    source = Path(source).absolute()
    backup = Path(backup_path).absolute()
    if root.is_symlink() or not (root / DATABASE_NAME).is_file():
        raise ValueError("Ziel-Datenordner ist ungültig oder unvollständig.")
    if (
        source == backup or source.is_relative_to(root)
        or backup.is_relative_to(root) or backup.exists() or backup.is_symlink()
    ):
        raise ValueError(
            "Sicherung als neue .ntfbackup außerhalb des Datenordners "
            "und getrennt vom Projektpaket speichern."
        )
    if backup.suffix.lower() != ".ntfbackup":
        raise ValueError("Die Sicherheitssicherung benötigt die Endung .ntfbackup.")

    if progress:
        progress(2, "Projektidentität und Sachnummer prüfen")
    identity = inspect_project_identity(source)
    target = WorkflowProjectStore(DuckDBStore(root / DATABASE_NAME))
    existing = target.get(identity.profile_id, identity.part_number)
    if existing is None:
        raise ValueError(
            "Für diese Sachnummer existiert kein Projekt. "
            "Bitte den normalen Projekt-Import verwenden."
        )
    expected = {
        (project.profile_id, part_key(project.part_number))
        for project in target.list_projects()
    }
    project_key = (identity.profile_id, part_key(identity.part_number))
    if project_key not in expected:
        raise ValueError("Projektprofil und Sachnummer stimmen nicht überein.")

    # Ein bestaendiges Benutzer-Backup anlegen, BEVOR irgendwelche
    # projektbezogenen Falldaten geloescht werden.
    if progress:
        progress(8, "Vollständige Sicherung des bisherigen Laptop-Stands erstellen")
    export_portable_backup(root, backup)

    try:
        # Alle Schritte bis zum abschliessenden Restore finden in einem
        # temporaeren, getrennten Datenverzeichnis statt.
        with tempfile.TemporaryDirectory(
            prefix="ntf-projekt-ersatz-", dir=root.parent,
        ) as temp_name:
            temp = Path(temp_name)
            staged = temp / "arbeitskopie"
            prepared_backup = temp / "ersatzstand.ntfbackup"

            if progress:
                progress(25, "Bisherigen Datenstand in Arbeitskopie vorbereiten")
            restore_portable_backup(backup, staged)

            if progress:
                progress(43, "Altes Projekt in Arbeitskopie sicher entfernen")
            fully_delete_project(
                DuckDBStore(staged / DATABASE_NAME), staged,
                existing.profile_id, existing.part_number,
            )

            if progress:
                progress(58, "Importiertes Projekt in Arbeitskopie übernehmen")
            result = import_project(source, staged)
            if (result.profile_id, part_key(result.part_number)) != project_key:
                raise ValueError("Importiertes Projekt hat eine andere Sachnummer.")

            staged_store = WorkflowProjectStore(DuckDBStore(staged / DATABASE_NAME))
            observed = {
                (project.profile_id, part_key(project.part_number))
                for project in staged_store.list_projects()
            }
            if observed != expected:
                raise ValueError(
                    "Projektbestand der Arbeitskopie widerspricht dem Zielbestand."
                )

            if progress:
                progress(78, "Neuen Gesamtstand und Prüfsummen vorbereiten")
            export_portable_backup(staged, prepared_backup)

            if progress:
                progress(93, "Geprüften Projektstand auf dem Laptop übernehmen")
            restore_portable_backup(prepared_backup, root, replace_existing=True)
    except Exception as exc:
        raise RuntimeError(
            f"Projektersatz nicht erfolgreich abgeschlossen: {exc}. "
            f"Die vorherige Gesamtsicherung liegt unter {backup}. "
            "Falls die abschließende Wiederherstellung nicht vollständig "
            "zurückgerollt wurde, diesen Sicherungsstand über "
            "'Gesamtstand aus Datei wiederherstellen' zurückspielen."
        ) from exc

    if progress:
        progress(100, "Projekt ersetzt; alte Laptop-Sicherung bleibt erhalten")
    return ProjectImportResult(
        profile_id=result.profile_id,
        part_number=result.part_number,
        case_count=result.case_count,
        file_count=result.file_count,
        replaced=True,
        backup_path=backup,
    )
