#!/usr/bin/env python3
"""Direktaufruf aus dem Repository: python scripts/diagnosis_viewer_quicktests.py ..."""

from __future__ import annotations

import sys
from pathlib import Path

projekt_src = Path(__file__).resolve().parents[1] / "src"
if projekt_src.is_dir():
    sys.path.insert(0, str(projekt_src))

from ntf_insight.acquisition.diagnosis_viewer_cli import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
