"""Offline-Pruefung: Eine PING-ID-Bestaetigung zur Zeit, Downloads parallel."""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from ntf_insight.acquisition.sso_login_gate import serielle_sso_anmeldung


def test_zweite_anmeldung_wartet_bis_erste_fertig(tmp_path):
    lockfile = tmp_path / "sso.lock"
    eins_bereit = threading.Event()
    zwei_bereit = threading.Event()
    eins_freigeben = threading.Event()
    meldungen = []

    def erste():
        with serielle_sso_anmeldung(
            sperrdatei=lockfile, status=meldungen.append,
            wartezeit_s=4,
        ):
            eins_bereit.set()
            assert eins_freigeben.wait(3)
        return "erledigt"

    def zweite():
        with serielle_sso_anmeldung(
            sperrdatei=lockfile, status=meldungen.append,
            wartezeit_s=4,
        ):
            zwei_bereit.set()
        return "erledigt"

    with ThreadPoolExecutor(max_workers=2) as pool:
        one = pool.submit(erste)
        try:
            assert eins_bereit.wait(2)
            two = pool.submit(zweite)
            assert not zwei_bereit.wait(0.15)
        finally:
            eins_freigeben.set()
        assert one.result(timeout=4) == "erledigt"
        assert two.result(timeout=4) == "erledigt"
    assert zwei_bereit.is_set()
    assert any("Eine andere Datenquelle" in m for m in meldungen)
    assert sum("Sperre freigegeben" in m for m in meldungen) == 2
    assert lockfile.read_bytes() == b"0"  # Keine Logins, keine FINs gespeichert


def test_sperre_wird_auch_nach_exception_wieder_frei(tmp_path):
    lockfile = tmp_path / "sso.lock"
    with pytest.raises(RuntimeError, match="synthetisch"):
        with serielle_sso_anmeldung(sperrdatei=lockfile):
            raise RuntimeError("synthetisch")
    with serielle_sso_anmeldung(sperrdatei=lockfile, wartezeit_s=1):
        pass


def test_abbruch_und_timeout_waehrend_anderer_login_gesperrt(tmp_path):
    lockfile = tmp_path / "sso.lock"
    cancel = threading.Event()
    with serielle_sso_anmeldung(sperrdatei=lockfile):
        cancel.set()
        with pytest.raises(InterruptedError, match="abgebrochen"):
            with serielle_sso_anmeldung(
                sperrdatei=lockfile, abbruch=cancel, wartezeit_s=0.1,
            ):
                pytest.fail("Darf nie eintreten.")
        with pytest.raises(TimeoutError, match="zu lange aktiv"):
            with serielle_sso_anmeldung(sperrdatei=lockfile, wartezeit_s=0.05):
                pytest.fail("Darf nie eintreten.")


def test_sso_os_lock_wirkt_ueber_zwei_python_prozesse(tmp_path):
    """Ein echtes zweites Python darf den Lock des ersten nicht umgehen."""
    lock = tmp_path / "sso.lock"
    marker = tmp_path / "hat-lock"
    script_halter = (
        "from ntf_insight.acquisition.sso_login_gate import serielle_sso_anmeldung\n"
        "from pathlib import Path\n"
        "import sys, time\n"
        "with serielle_sso_anmeldung(sperrdatei=Path(sys.argv[1])):\n"
        "    Path(sys.argv[2]).write_text('bereit', encoding='utf-8')\n"
        "    time.sleep(0.85)\n"
    )
    halter = subprocess.Popen(
        [sys.executable, "-c", script_halter, str(lock), str(marker)],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
    )
    try:
        deadline = time.monotonic() + 5
        while not marker.is_file() and time.monotonic() < deadline:
            if halter.poll() is not None:
                pytest.fail(f"Erster Sperrprozess abgebrochen: {halter.stderr.read()}")
            time.sleep(0.025)
        assert marker.is_file()
        script_zweiter = (
            "from ntf_insight.acquisition.sso_login_gate import serielle_sso_anmeldung\n"
            "from pathlib import Path\n"
            "import sys\n"
            "with serielle_sso_anmeldung(sperrdatei=Path(sys.argv[1])):\n"
            "    print('eingetreten', flush=True)\n"
        )
        started = time.monotonic()
        zweiter = subprocess.run(
            [sys.executable, "-c", script_zweiter, str(lock)],
            capture_output=True, text=True, timeout=8, check=True,
        )
        assert zweiter.stdout.strip() == "eingetreten"
        assert time.monotonic() - started >= 0.3
        assert halter.wait(timeout=5) == 0
    finally:
        if halter.poll() is None:
            halter.terminate()
        halter.communicate(timeout=5)


@pytest.fixture(autouse=True)
def ohne_cooldown_fuer_bisherige_lock_tests(monkeypatch):
    """Alte Exklusiv-Tests sollen nicht 45 Sekunden je Lauf warten."""
    monkeypatch.setenv("NTF_SSO_PAUSE_S", "0")


def test_verteilte_pause_nach_login_zwischen_prozessen(tmp_path):
    """Auch getrennte Programme warten nach dem erfolgreichen ersten Login."""
    lock = tmp_path / "sso.lock"
    with serielle_sso_anmeldung(sperrdatei=lock, abstand_s=0.5):
        pass
    assert lock.read_bytes().startswith(b"0")
    assert b":" in lock.read_bytes()
    script = (
        "from ntf_insight.acquisition.sso_login_gate import serielle_sso_anmeldung\n"
        "from pathlib import Path\nimport sys\n"
        "with serielle_sso_anmeldung(sperrdatei=Path(sys.argv[1]), abstand_s=0.0):\n"
        " print('erfolgreich', flush=True)\n"
    )
    start = time.monotonic()
    result = subprocess.run(
        [sys.executable, "-c", script, str(lock)],
        capture_output=True, text=True, timeout=6, check=True,
    )
    assert result.stdout.strip() == "erfolgreich"
    assert time.monotonic() - start >= 0.35


def test_sso_reuse_legt_keine_neue_pause_nach_jeder_fin_an(tmp_path):
    lock = tmp_path / "sso.lock"
    with serielle_sso_anmeldung(sperrdatei=lock, abstand_s=1.0):
        pass
    davor = lock.read_bytes()
    with serielle_sso_anmeldung(sperrdatei=lock, abstand_s=1.0) as phase:
        phase.neue_anmeldung = False
    assert lock.read_bytes() == davor


def test_abgebrochene_anmeldung_verlaengert_cooldown_nicht(tmp_path):
    lock = tmp_path / "sso.lock"
    with pytest.raises(RuntimeError, match="synthetisch"):
        with serielle_sso_anmeldung(sperrdatei=lock, abstand_s=1.0):
            raise RuntimeError("synthetisch")
    assert lock.read_bytes() == b"0"


def test_ungueltiges_sso_abstand_env_wird_abgewiesen(tmp_path, monkeypatch):
    monkeypatch.setenv("NTF_SSO_PAUSE_S", "99")
    with pytest.raises(ValueError, match="0 und 60"):
        with serielle_sso_anmeldung(sperrdatei=tmp_path / "sso.lock"):
            pass
