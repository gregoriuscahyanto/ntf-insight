"""Lokaler, streng referenzgebundener QEC-Abrufstand fuer FIN-/Fallanalyse.

Ein Fall darf niemals nur wegen identischer FIN einem anderen Schadteilordner
zugeordnet werden. Originaldateien verbleiben ausschliesslich lokal.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

_FIN = re.compile(r"[A-HJ-NPR-Z0-9]{17}\Z")
_REF = re.compile(r"[0-9]{1,14}\Z")


@dataclass(frozen=True, slots=True)
class QecArchiveInfo:
    """Anzeigeinformation, keine fachliche Befundauswertung."""

    folder: Path
    timestamp: datetime
    legacy: bool = False

    @property
    def date_label(self) -> str:
        return self.timestamp.astimezone().strftime("%d.%m.%Y %H:%M")


def case_folder(output_root: Path, fin: str, reference: str) -> Path:
    """Validated path: no absolute, traversal or foreign FIN/reference inputs."""
    if not _FIN.fullmatch(fin) or not _REF.fullmatch(reference):
        raise ValueError("QEC-FIN oder Referenznummer ungueltig.")
    return Path(output_root) / fin / f"ref_{reference}"


def _stamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def local_qec_archive(output_root: Path, fin: str, reference: str) -> QecArchiveInfo | None:
    """Return only exports explicitly matching the full FIN and QEC reference.

    Supports the old laeufe/NN_Reiter/daten.json layout read-only, without
    creating new legacy folders or deleting previous engineering evidence.
    """
    try:
        folder = case_folder(output_root, fin, reference)
    except ValueError:
        return None
    if not folder.is_dir():
        return None
    report = folder / "qec.json"
    if report.is_file() and not report.is_symlink():
        try:
            payload = json.loads(report.read_text(encoding="utf-8"))
            timestamp = _stamp(payload.get("abgerufen_am_utc"))
            if (payload.get("fin") == fin
                    and payload.get("referenznummer") == reference
                    and timestamp is not None):
                return QecArchiveInfo(folder, timestamp)
        except (OSError, ValueError, TypeError, AttributeError):
            pass

    # Old exports contain separate page files. They are not modified.
    candidates: list[datetime] = []
    for path in folder.glob("laeufe/*/*/daten.json"):
        if path.is_symlink() or not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("fin") != fin or data.get("referenznummer") != reference:
                continue
            timestamp = _stamp(data.get("zeitpunkt_utc"))
            if timestamp is not None:
                candidates.append(timestamp)
        except (OSError, ValueError, TypeError, AttributeError):
            continue
    return QecArchiveInfo(folder, max(candidates), legacy=True) if candidates else None
