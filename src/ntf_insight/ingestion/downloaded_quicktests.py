"""Discover already downloaded local QuickTest PDFs without following links.

Historical downloads may exist on disk before a corresponding source import.
No report is assigned from its filename; the PDF parser verifies the FIN.
"""
from __future__ import annotations

import re
from pathlib import Path


_FIN = re.compile(r"[A-HJ-NPR-Z0-9]{17}\Z")


def list_downloaded_quicktests(data_dir: Path) -> list[Path]:
    root = Path(data_dir) / "quicktests"
    if not root.is_dir() or root.is_symlink():
        return []
    result: list[Path] = []
    for folder in root.iterdir():
        if (
            not folder.is_dir()
            or folder.is_symlink()
            or not _FIN.fullmatch(folder.name)
        ):
            continue
        for file in folder.iterdir():
            if file.is_file() and not file.is_symlink() and file.suffix.lower() == ".pdf":
                result.append(file)
    return sorted(result)
