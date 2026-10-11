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


def test_app_enters_event_loop_and_exits_cleanly(tmp_path) -> None:
    """Echte App starten: bisher wurde nur das Hauptfenster konstruiert."""
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["NTF_INSIGHT_SMOKE_TEST"] = "1"
    env["NTF_INSIGHT_DATA_DIR"] = str(tmp_path / "ntf-starttest")
    completed = subprocess.run(
        [sys.executable, "-m", "ntf_insight"],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, (
        f"NTF Insight GUI exit code: {completed.returncode}\n"
        f"stderr:\n{completed.stderr[-5000:]}\n"
        f"stdout:\n{completed.stdout[-1000:]}"
    )
