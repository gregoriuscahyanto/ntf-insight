"""Local, non-networking source import CLI for large ZIP files."""
from __future__ import annotations

import argparse
from pathlib import Path

from ntf_insight.app.settings import AppPaths
from ntf_insight.ingestion.batch_import import LocalBatchImporter
from ntf_insight.ingestion.service import SourceImportService


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="ntf-insight-import",
        description=(
            "Archive and normalize local QEC, AutoExport and QuickTest reports. "
            "No files are transmitted to GitHub."
        ),
    )
    parser.add_argument(
        "paths", nargs="+", type=Path,
        help="One or more local files or ZIP bundles",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="Local app data root; defaults to NTF_INSIGHT_DATA_DIR or the app default",
    )
    args = parser.parse_args()
    paths = AppPaths.from_data_dir(args.data_dir) if args.data_dir else AppPaths.default()
    paths.ensure()
    service = SourceImportService(paths.raw_dir, paths.database_path)
    summary = LocalBatchImporter(service).import_paths(
        args.paths, on_progress=lambda status: print(status, flush=True)
    )
    print(
        f"Archiviert: {summary.files_archived}; geparst: {summary.files_parsed}; "
        f"ausstehend: {summary.files_pending}; neue Fälle: {summary.cases_created}; "
        f"verknüpfte Ereignisse: {summary.events_linked}; "
        f"unzugeordnete Ereignisse: {summary.events_unassigned}"
    )
    if summary.issues:
        print(f"Hinweise ({len(summary.issues)}):")
        for message in summary.issues[:12]:
            print(f"- {message}")
    return 0
