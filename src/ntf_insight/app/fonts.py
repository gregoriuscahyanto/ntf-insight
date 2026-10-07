"""Mercedes-compatible corporate font discovery for managed workstations.

The repository never bundles proprietary font binaries. Instead, NTF Insight uses the
approved corporate fonts when they are already installed on the workstation or when an
approved internal font directory is supplied through NTF_INSIGHT_FONT_DIR.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtGui import QFontDatabase


CORPORATE_S_CANDIDATES = (
    "Corporate S Pro",
    "Corporate S Std",
    "Corporate S",
)

CORPORATE_A_CANDIDATES = (
    "Corporate A Pro",
    "Corporate A Std",
    "Corporate A",
)

SYSTEM_BODY_FALLBACKS = (
    "Segoe UI",
    "Arial",
)

SYSTEM_HEADING_FALLBACKS = (
    "Segoe UI",
    "Arial",
)


@dataclass(frozen=True, slots=True)
class FontSelection:
    body_family: str
    heading_family: str
    corporate_body: bool
    corporate_heading: bool
    loaded_font_files: tuple[str, ...] = ()


def _find_family(
    available: list[str],
    candidates: tuple[str, ...],
) -> str | None:
    exact = {family.casefold(): family for family in available}
    for candidate in candidates:
        found = exact.get(candidate.casefold())
        if found:
            return found

    normalized = {
        "".join(ch for ch in family.casefold() if ch.isalnum()): family
        for family in available
    }
    for candidate in candidates:
        key = "".join(ch for ch in candidate.casefold() if ch.isalnum())
        found = normalized.get(key)
        if found:
            return found
    return None


def _load_approved_font_directory(path: Path | None) -> tuple[str, ...]:
    if path is None or not path.is_dir():
        return ()

    loaded: list[str] = []
    for candidate in sorted(path.iterdir()):
        if candidate.suffix.casefold() not in {".ttf", ".otf", ".ttc"}:
            continue
        font_id = QFontDatabase.addApplicationFont(str(candidate))
        if font_id >= 0:
            loaded.append(candidate.name)
    return tuple(loaded)


def resolve_fonts(font_dir: Path | None = None) -> FontSelection:
    """Resolve the best available UI/body and headline fonts.

    Environment overrides take precedence:
    - NTF_INSIGHT_BODY_FONT_FAMILY
    - NTF_INSIGHT_HEADING_FONT_FAMILY
    - NTF_INSIGHT_FONT_DIR (approved internal font files)
    """
    configured_dir = os.environ.get("NTF_INSIGHT_FONT_DIR")
    effective_dir = font_dir or (Path(configured_dir).expanduser() if configured_dir else None)
    loaded_files = _load_approved_font_directory(effective_dir)

    available = list(QFontDatabase.families())

    body_override = os.environ.get("NTF_INSIGHT_BODY_FONT_FAMILY")
    heading_override = os.environ.get("NTF_INSIGHT_HEADING_FONT_FAMILY")

    body = (
        _find_family(available, (body_override,)) if body_override else None
    ) or _find_family(available, CORPORATE_S_CANDIDATES)
    corporate_body = body is not None

    heading = (
        _find_family(available, (heading_override,)) if heading_override else None
    ) or _find_family(available, CORPORATE_A_CANDIDATES)
    corporate_heading = heading is not None

    if body is None:
        body = _find_family(available, SYSTEM_BODY_FALLBACKS) or available[0]

    if heading is None:
        heading = _find_family(available, SYSTEM_HEADING_FALLBACKS) or body

    return FontSelection(
        body_family=body,
        heading_family=heading,
        corporate_body=corporate_body,
        corporate_heading=corporate_heading,
        loaded_font_files=loaded_files,
    )
