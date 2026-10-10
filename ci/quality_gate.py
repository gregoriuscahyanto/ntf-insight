"""Portable CI quality gate for GitHub and Mercedes-Benz internal CI/CD adapters."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"


def run(*args: str) -> None:
    print("+", " ".join(args), flush=True)
    subprocess.run(args, cwd=ROOT, check=True)


def main() -> int:
    REPORTS.mkdir(parents=True, exist_ok=True)
    run(sys.executable, "-m", "compileall", "-q", "src")
    run(sys.executable, "-m", "ruff", "check", "src", "tests", "ci")
    run(
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "-x",
        "--junitxml=reports/junit.xml",
        "--cov=ntf_insight",
        "--cov-report=term-missing",
        "--cov-report=xml:reports/coverage.xml",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
