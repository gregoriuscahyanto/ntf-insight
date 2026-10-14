"""Read-only inventory of local TIPS Writer cases for FIN analysis."""

from __future__ import annotations

import json
import re
from pathlib import Path

_FIN = re.compile(r"[A-HJ-NPR-Z0-9]{17}\Z")
_CASE = re.compile(r"fall_(\d{4,16})\Z")


def local_tips_cases(data_dir: Path, fin: str) -> tuple[Path, ...]:
    """A local TIPS case counts only with a matching full FIN + case number.

    A previously exported TIPS fall to a different vehicle must never colour
    the current FIN as a confirmed case link.
    """
    if not _FIN.fullmatch(str(fin)):
        return ()
    base = Path(data_dir) / "tips"
    folder = base / fin
    if (not folder.is_dir() or folder.is_symlink()
            or base.is_symlink()):
        return ()
    found = []
    for candidate in folder.glob("fall_*/tips.json"):
        case_dir = candidate.parent
        match = _CASE.fullmatch(case_dir.name)
        if (not match or candidate.is_symlink() or case_dir.is_symlink()
                or not candidate.is_file()):
            continue
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
            if (isinstance(payload, dict) and payload.get("fin") == fin
                    and payload.get("fallnummer") == match[1]):
                found.append(candidate)
        except (OSError, UnicodeError, ValueError, TypeError):
            continue
    return tuple(sorted(found))
