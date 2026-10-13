"""Anmeldeinformationen ausschließlich im Betriebssystem-Tresor ablegen.

Es gibt bewusst keinen Fallback auf QSettings, Dateien oder Umgebungsvariablen:
ein Passwort darf niemals unverschlüsselt gespeichert oder protokolliert werden.
"""

from __future__ import annotations

from dataclasses import dataclass

SERVICE_NAME = "NTF Insight - Diagnosis Viewer"
USER_KEY = "benutzer-id"
PASSWORD_KEY = "passwort"


@dataclass(frozen=True)
class LoginCredentials:
    user_id: str
    password: str


def _keyring():
    try:
        import keyring
    except ImportError as exc:
        raise RuntimeError(
            "Sicheres Speichern benötigt die Bibliothek 'keyring'. "
            "Bitte 'python -m pip install keyring' ausführen oder "
            "Benutzer-ID und Passwort nur für diesen Abruf eingeben."
        ) from exc
    try:
        if keyring.get_keyring().priority <= 0:
            raise RuntimeError("Kein verfügbarer sicherer Betriebssystem-Tresor.")
    except AttributeError as exc:
        raise RuntimeError("Kein geeigneter Betriebssystem-Tresor vorhanden.") from exc
    return keyring


def load_saved_credentials() -> LoginCredentials | None:
    """Only read from an OS-managed key store; no filesystem secrets."""
    ring = _keyring()
    try:
        user_id = ring.get_password(SERVICE_NAME, USER_KEY)
        password = ring.get_password(SERVICE_NAME, PASSWORD_KEY)
    except Exception as exc:
        raise RuntimeError("Anmeldedaten konnten nicht aus dem Betriebssystem-Tresor gelesen werden.") from exc
    if user_id and password:
        return LoginCredentials(user_id=user_id, password=password)
    return None


def save_credentials(user_id: str, password: str) -> None:
    """Save credentials to the OS password vault. Passwords are never logged."""
    if not user_id.strip() or not password:
        raise ValueError("Benutzer-ID und Passwort werden zum Speichern benötigt.")
    ring = _keyring()
    try:
        ring.set_password(SERVICE_NAME, USER_KEY, user_id.strip())
        ring.set_password(SERVICE_NAME, PASSWORD_KEY, password)
    except Exception as exc:
        raise RuntimeError(
            "Anmeldedaten konnten nicht sicher gespeichert werden. "
            "Bitte nur für diese Sitzung eingeben oder IT-Freigabe prüfen."
        ) from exc


def clear_saved_credentials() -> None:
    """Remove saved credentials without inspecting or displaying them."""
    ring = _keyring()
    for key in (USER_KEY, PASSWORD_KEY):
        try:
            ring.delete_password(SERVICE_NAME, key)
        except Exception:
            pass
