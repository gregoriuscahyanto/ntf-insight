"""Prozessuebergreifende PING-ID-/SSO-Sperre fuer VeDoc und QuickTest-CLI.

Die Sperrdatei enthaelt keine Login-, FIN- oder Cookie-Daten. Der Betriebssystem-
Dateilock wird bei normalem Verlassen oder Prozessabsturz automatisch frei.
Die Browser-Sitzungen und die anschliessenden Downloads bleiben unabhaengig.
"""

from __future__ import annotations

import errno
import os
import time
from contextlib import contextmanager
from pathlib import Path
from threading import Event
from typing import Callable, Iterator


def _anfordern(handle) -> bool:
    """Genau ein Byte nicht blockierend sperren (Windows und POSIX)."""
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except OSError as exc:
            if exc.errno in (errno.EACCES, errno.EAGAIN) or getattr(
                exc, "winerror", None
            ) in (33, 36):
                return False
            raise

    import fcntl

    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError as exc:
        if exc.errno in (errno.EACCES, errno.EAGAIN):
            return False
        raise


def _freigeben(handle) -> None:
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def serielle_sso_anmeldung(
    *,
    status: Callable[[str], None] | None = None,
    abbruch: Event | None = None,
    sperrdatei: Path | None = None,
    wartezeit_s: float = 1200,
) -> Iterator[None]:
    """Eine PING-ID-Bestaetigung zur Zeit, danach parallel weiterarbeiten.

    Der Lock wird vor dem Aufruf der Portal-Startseite erworben, weil
    bereits eine Navigation den SSO-Redirect/PING-ID-Dialog starten kann.
    Warten wird nicht auf den eigentlichen SSO-Timeout angerechnet.
    """
    melden = status or (lambda _meldung: None)
    pfad = Path(sperrdatei) if sperrdatei is not None else (
        Path.home() / ".ntf-insight" / "sso-anmeldung.lock"
    )
    if wartezeit_s <= 0:
        raise ValueError("SSO-Sperrwartezeit muss positiv sein.")
    pfad.parent.mkdir(parents=True, exist_ok=True)
    if pfad.is_symlink():
        raise OSError("SSO-Sperrdatei darf kein symbolischer Link sein.")
    try:
        with pfad.open("xb") as neu:
            neu.write(b"0")
    except FileExistsError:
        pass
    if pfad.is_symlink():
        raise OSError("SSO-Sperrdatei darf kein symbolischer Link sein.")

    with pfad.open("r+b") as handle:
        deadline = time.monotonic() + wartezeit_s
        wartet = False
        gesperrt = False
        try:
            while True:
                if abbruch is not None and abbruch.is_set():
                    raise InterruptedError("SSO-Anmeldung vor dem Start abgebrochen.")
                if _anfordern(handle):
                    gesperrt = True
                    break
                if not wartet:
                    melden(
                        "PING ID: Eine andere Datenquelle meldet sich gerade an. "
                        "Warte auf Abschluss dieser Anmeldung ..."
                    )
                    wartet = True
                if time.monotonic() >= deadline:
                    raise TimeoutError(
                        "SSO-Anmeldung konnte nicht starten: Eine andere "
                        "PING-ID-Anmeldung ist zu lange aktiv."
                    )
                if abbruch is not None:
                    abbruch.wait(0.35)
                else:
                    time.sleep(0.35)
            melden("PING ID: Anmeldung exklusiv freigegeben; andere Quellen warten.")
            yield
        finally:
            if gesperrt:
                _freigeben(handle)
                melden("PING ID: Anmelde-Sperre freigegeben; Datenabruf kann parallel laufen.")
