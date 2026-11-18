"""Geschuetzte Inline-PDF-Antworten aus dem vorhandenen Diagnosis-Viewer-Kontext.

Es werden keine Cookies, Tokens oder PDF-URLs persistiert oder protokolliert.
Nur nach echtem PDF-Dateikopf und beschraenkter Groesse wird gespeichert.
"""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

MAX_PDF_BYTES = 40 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class InlinePdfDownload:
    """Mit playwright.Download kompatible Bytes fuer _save_pdf()."""

    daten: bytes
    suggested_filename: str = "QuickTest.pdf"

    def __post_init__(self) -> None:
        if not _gueltige_pdf_bytes(self.daten):
            raise ValueError("Keine gueltige PDF-Antwort erhalten.")

    def failure(self) -> None:
        return None

    def save_as(self, pfad: str) -> None:
        Path(pfad).write_bytes(self.daten)


def _gueltige_pdf_bytes(data: bytes) -> bool:
    return (
        isinstance(data, bytes)
        and 5 <= len(data) <= MAX_PDF_BYTES
        and data.startswith(b"%PDF-")
    )


def _pdf_download_aus_bytes(daten: bytes) -> InlinePdfDownload | None:
    return InlinePdfDownload(daten) if _gueltige_pdf_bytes(daten) else None


def _beobachtete_pdf_antwort(response) -> bool:
    """Nur potentielle PDF-Datei-Antworten in den Kandidatenpuffer aufnehmen."""
    try:
        headers = response.headers
        mime = headers.get("content-type", "").lower()
        disposition = headers.get("content-disposition", "").lower()
        url_path = urlsplit(response.url).path.lower()
        return (
            "application/pdf" in mime
            or "application/octet-stream" in mime and url_path.endswith(".pdf")
            or ".pdf" in disposition and "attachment" in disposition
        )
    except (AttributeError, TypeError, ValueError):
        return False


def _antwort_gehoert_zu_klick(response, viewer_page, popups: list) -> bool:
    """Keine zufaelligen PDF-Antworten aus anderen SSO-/Browser-Tabs zuordnen."""
    try:
        antwort_page = response.request.frame.page
        if antwort_page is viewer_page or antwort_page in popups:
            return True
    except Exception:
        pass
    try:
        return any(response.url == popup.url for popup in popups)
    except Exception:
        return False


def pdf_aus_browser_antworten(antworten: list, viewer_page, popups: list) -> InlinePdfDownload | None:
    """Bereits empfangene PDF-Nutzdaten ohne erneute Netzwerkanfrage uebernehmen."""
    for antwort in antworten:
        if not _antwort_gehoert_zu_klick(antwort, viewer_page, popups):
            continue
        try:
            data = antwort.body()
            result = _pdf_download_aus_bytes(data)
            if result is not None:
                return result
        except Exception:
            # Edge kann die PDF-Vorschau oder ihren Netzwerkpuffer verwerfen.
            continue
    return None


def _vertrauenswuerdige_pdf_url(url: str, viewer_host: str) -> bool:
    """Nur vollstaendige HTTPS-URLs exakt vom erlaubten Viewer-Host abfragen."""
    try:
        parsed = urlsplit(url)
        return bool(
            parsed.scheme == "https"
            and parsed.hostname == viewer_host
            and parsed.port in (None, 443)
            and parsed.username is None
            and parsed.password is None
            and parsed.fragment == ""
        )
    except (ValueError, AttributeError):
        return False


def pdf_aus_popup_url(context, popup_url: str, viewer_host: str) -> InlinePdfDownload | None:
    """Nur die bereits im Viewer geoeffnete URL mit denselben SSO-Cookies abrufen.

    Redirects werden nicht verfolgt; fremde Hosts und Login-HTML werden nie
    als PDF-Datei akzeptiert. Die Browser-API uebernimmt Cookies intern.
    """
    if not _vertrauenswuerdige_pdf_url(popup_url, viewer_host):
        return None
    request = getattr(context, "request", None)
    if request is None:
        return None
    try:
        response = request.get(popup_url, timeout=12_000, max_redirects=0)
        try:
            if response.status != 200:
                return None
            headers = response.headers
            if not (
                "application/pdf" in headers.get("content-type", "").lower()
                or "application/octet-stream" in headers.get("content-type", "").lower()
            ):
                return None
            length = headers.get("content-length")
            if length is not None and int(length) > MAX_PDF_BYTES:
                return None
            return _pdf_download_aus_bytes(response.body())
        finally:
            dispose = getattr(response, "dispose", None)
            if callable(dispose):
                dispose()
    except (OSError, ValueError, TypeError, RuntimeError, AttributeError):
        return None


def pdf_aus_popup_blob(viewer_page, popup_url: str, viewer_host: str) -> InlinePdfDownload | None:
    """Browser-eigenes Same-Origin-blob auslesen, keine Fremdseiten kontaktieren.

    Das Script liest ausschliesslich eine bereits existierende PDF-Blob-URL,
    beachtet eine Groessenobergrenze und uebergibt nur die Datei-Bytes zurueck.
    """
    if not isinstance(popup_url, str) or not popup_url.startswith(
        f"blob:https://{viewer_host}/"
    ):
        return None
    try:
        encoded = viewer_page.evaluate(
            """async ({url, maxBytes}) => {
                const resp = await fetch(url, {credentials: 'same-origin'});
                if (!resp.ok) return null;
                const blob = await resp.blob();
                if (blob.size > maxBytes || blob.size < 5) return null;
                const bytes = new Uint8Array(await blob.arrayBuffer());
                const chunks = [];
                const chunkSize = 8192;
                for (let i = 0; i < bytes.length; i += chunkSize) {
                    chunks.push(String.fromCharCode(...bytes.subarray(i, i + chunkSize)));
                }
                return btoa(chunks.join(''));
            }""",
            {"url": popup_url, "maxBytes": MAX_PDF_BYTES},
        )
        if not isinstance(encoded, str) or len(encoded) > ((MAX_PDF_BYTES + 2) // 3) * 4:
            return None
        return _pdf_download_aus_bytes(base64.b64decode(encoded, validate=True))
    except (binascii.Error, OSError, ValueError, TypeError, RuntimeError, AttributeError):
        return None
