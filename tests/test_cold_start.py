import os
import subprocess
import sys


def test_application_imports_in_fresh_python_process() -> None:
    env = os.environ.copy()
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    completed = subprocess.run(
        [sys.executable, "-c", "import ntf_insight.app.application"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
