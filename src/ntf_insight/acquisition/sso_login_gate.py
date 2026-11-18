"""Prozessuebergreifende SSO-/PING-ID-Sperre mit Abstand nach Login.

Sperrdatei: erstes Byte fuer OS-Lock, dahinter nur Zeitstempel/PID.
Keine Passwoerter, Cookies, Fahrzeug- oder FIN-Daten.
"""

from __future__ import annotations

import errno
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Callable, Iterator


@dataclass(slots=True)
class SsoPhase:
    """Der Aufrufer kann bei unveraenderter Sitzung eine neue Abstandsfrist vermeiden."""

    neue_anmeldung: bool = True


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


def _abstand_lesen(handle) -> tuple[float, int]:
    """Zeit und letzte PID aus dem exklusiv gesperrten Dateideskriptor lesen."""
    handle.seek(1)
    try:
        raw = handle.read(80).decode("ascii", errors="strict").strip()
        if not raw:
            return 0.0, 0
        zeit, pid = raw.split(":")
        timestamp = float(zeit)
        owner = int(pid)
        # Rechnerzeit kann angepasst worden sein: keine dauerhaften Blockaden.
        if not 0 < timestamp < time.time() + 3600:
            return 0.0, 0
        return timestamp, owner
    except (UnicodeError, ValueError, OverflowError):
        return 0.0, 0


def _abstand_schreiben(handle, frei_ab: float) -> None:
    """Kleinste Metadaten ohne sensible Nutzdaten unter OS-Lock ersetzen."""
    handle.seek(1)
    handle.write(f"{frei_ab:.3f}:{os.getpid()}".encode("ascii"))
    handle.truncate()
    handle.flush()
    os.fsync(handle.fileno())


def _standard_abstand() -> float:
    value = os.getenv("NTF_SSO_PAUSE_S", "45")
    try:
        result = float(value)
    except ValueError as exc:
        raise ValueError("NTF_SSO_PAUSE_S muss zwischen 0 und 60 liegen.") from exc
    if not 0 <= result <= 60:
        raise ValueError("NTF_SSO_PAUSE_S muss zwischen 0 und 60 liegen.")
    return result


@contextmanager
def serielle_sso_anmeldung(
    *,
    status: Callable[[str], None] | None = None,
    abbruch: Event | None = None,
    sperrdatei: Path | None = None,
    wartezeit_s: float = 3600,
    abstand_s: float | None = None,
) -> Iterator[SsoPhase]:
    """Eine Anmeldung zur Zeit, danach 0-60s Abstand vor der naechsten.

    Die Sperre greift VOR dem potentiellen SSO-Redirect. Ein erfolgreicher
    erster Login markiert unter der Sperre die naechste moegliche Anmeldung.
    Bereits aktive Portalsitzungen duerfen phase.neue_anmeldung = False
    setzen, damit sie bei jeder folgenden FIN nicht erneut 45s addieren.
    """
    melden = status or (lambda _meldung: None)
    pause = _standard_abstand() if abstand_s is None else float(abstand_s)
    if not 0 <= pause <= 60:
        raise ValueError("SSO-Abstand muss zwischen 0 und 60 Sekunden liegen.")
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
        phase = SsoPhase()
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
            frei_ab, zuletzt = _abstand_lesen(handle)
            if zuletzt != os.getpid():
                warten = max(0.0, frei_ab - time.time())
                if warten > 0:
                    melden(
                        "PING ID: Letzte Anmeldung abgeschlossen. "
                        f"Abstand vor der naechsten Anmeldung: {int(warten + 0.999)}s."
                    )
                while warten > 0:
                    if abbruch is not None and abbruch.is_set():
                        raise InterruptedError("SSO-Abstand vor der Anmeldung abgebrochen.")
                    if time.monotonic() >= deadline:
                        raise TimeoutError("SSO-Abstand: Sperrwartezeit ueberschritten.")
                    schritt = min(warten, max(0.01, deadline - time.monotonic()), 0.35)
                    if abbruch is not None:
                        abbruch.wait(schritt)
                    else:
                        time.sleep(schritt)
                    warten = max(0.0, frei_ab - time.time())
            melden("PING ID: Anmeldung exklusiv freigegeben; andere Quellen warten.")
            yield phase
            if phase.neue_anmeldung and pause:
                _abstand_schreiben(handle, time.time() + pause)
                melden(f"PING ID: Anmeldung erfolgreich; {pause:g}s Abstand bis zur naechsten.")
        finally:
            if gesperrt:
                _freigeben(handle)
                melden("PING ID: Anmelde-Sperre freigegeben; Datenabruf kann parallel laufen.")
