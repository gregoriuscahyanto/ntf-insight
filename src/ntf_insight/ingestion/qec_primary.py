"""Erkennung und Ein-Datei-Regel der QEC-generierten FIN-Liste.

Das Excel-Blatt "Schadteile QEC" mit FIN ist die *primäre* Kohorte.
Eine ergänzende SSL-Endbefundliste ("Schadteile" ohne FIN) ist erlaubt;
sie erzeugt keine zweite FIN-Kohorte.
"""
from __future__ import annotations

from pathlib import Path

from ntf_insight.ingestion.artifacts import SourceArtifact, sha256_file


def is_primary_qec_workbook(path: Path) -> bool:
    """True only for a primary QEC export, never for an SSL-only workbook."""
    path = Path(path)
    if path.suffix.casefold() != ".xlsx" or not path.is_file():
        return False
    from openpyxl import load_workbook

    workbook = load_workbook(
        path, read_only=True, data_only=True, keep_links=False,
    )
    try:
        if "Schadteile QEC" not in workbook.sheetnames:
            return False
        header = next(
            workbook["Schadteile QEC"].iter_rows(
                min_row=1, max_row=1, values_only=True,
            ), (),
        )
        return {"Referenznr.", "FIN", "Rep.-Datum"} <= set(header)
    finally:
        workbook.close()


def active_qec_lists(artifacts: list[SourceArtifact]) -> list[SourceArtifact]:
    """Identify all primary workbooks, including databases imported before this rule."""
    return [
        artifact for artifact in artifacts
        if is_primary_qec_workbook(Path(artifact.archived_path))
    ]


def validate_single_qec_list(
    incoming_paths: list[Path],
    archived: list[SourceArtifact],
) -> None:
    """Reject an additional primary cohort before importing any individual file.

    Reimport of an identical file (same SHA-256) remains idempotent.
    """
    existing = {artifact.sha256 for artifact in active_qec_lists(archived)}
    incoming = {
        sha256_file(path)
        for path in incoming_paths
        if is_primary_qec_workbook(path)
    }
    if len(existing | incoming) > 1:
        raise ValueError(
            "Es darf nur eine QEC-generierte FIN-Liste gleichzeitig verwendet "
            "werden. Bitte die bisherige aktive QEC-FIN-Liste zuerst unter "
            "Datenquellen gezielt löschen. Ergänzende SSL-Endbefundlisten "
            "ohne FIN bleiben erlaubt."
        )
