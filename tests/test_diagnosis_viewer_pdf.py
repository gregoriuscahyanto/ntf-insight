"""QuickTest Inline-PDF-Fallback: nur verifizierte Dateibytes, keine Cookies/URLs im Log."""

from __future__ import annotations

import base64
from types import SimpleNamespace

import pytest

from ntf_insight.acquisition.diagnosis_viewer import (
    VIEWER_HOST, DownloadRow, _save_pdf,
)
from ntf_insight.acquisition.diagnosis_viewer_pdf import (
    MAX_PDF_BYTES, InlinePdfDownload, _beobachtete_pdf_antwort,
    _vertrauenswuerdige_pdf_url, pdf_aus_browser_antworten,
    pdf_aus_popup_blob, pdf_aus_popup_url,
)


PDF = b"%PDF-1.7\nsynthetischer QuickTest ohne echte FIN\n"
URL = f"https://{VIEWER_HOST}/file/quicktest.pdf?sig=TEST-KEIN-TOKEN"


class PdfNetworkResponse:
    def __init__(self, data=PDF, *, page=None, url=URL, content_type="application/pdf"):
        self.data = data
        self.url = url
        self.headers = {"content-type": content_type}
        self.request = SimpleNamespace(frame=SimpleNamespace(page=page))
        self.calls = 0

    def body(self):
        self.calls += 1
        return self.data


def test_geladene_inline_bytes_verwenden_dieselbe_pdf_validierung_und_resume_namen(tmp_path):
    download = InlinePdfDownload(PDF)
    assert download.failure() is None
    assert download.suggested_filename == "QuickTest.pdf"
    pfad = _save_pdf(
        download, tmp_path / "WDD12345678901234",
        DownloadRow(0, "XD", "2026-11-18 10:00:00"),
    )
    assert pfad.is_file()
    assert pfad.read_bytes() == PDF
    assert pfad.suffix == ".pdf"
    assert _save_pdf(download, pfad.parent, DownloadRow(0, "XD", "2026-11-18 10:00:00")) == pfad


@pytest.mark.parametrize("invalid", [b"", b"<!DOCTYPE html>Login", b"%PD", b"%PDF-" + b"x" * (MAX_PDF_BYTES + 1)])
def test_ungueltige_antworten_niemals_als_quicktest_speichern(invalid):
    with pytest.raises(ValueError, match="PDF-Antwort"):
        InlinePdfDownload(invalid)


def test_pdf_aus_angezeigter_http_antwort_auch_bei_popup(tmp_path):
    viewer, popup = object(), object()
    antwort = PdfNetworkResponse(page=popup)
    assert _beobachtete_pdf_antwort(antwort)
    result = pdf_aus_browser_antworten([antwort], viewer, [popup])
    assert result is not None and result.daten == PDF
    assert antwort.calls == 1
    assert _save_pdf(result, tmp_path, DownloadRow(0, "XD", "2026-11-18")).is_file()


def test_pdf_antwort_fremder_tabs_niemals_uebernehmen():
    viewer, popup, fremd = object(), object(), object()
    antwort = PdfNetworkResponse(page=fremd)
    assert pdf_aus_browser_antworten([antwort], viewer, [popup]) is None
    assert antwort.calls == 0
    assert not _beobachtete_pdf_antwort(PdfNetworkResponse(content_type="text/html"))
    teilantwort = PdfNetworkResponse(page=popup)
    teilantwort.status = 206
    assert not _beobachtete_pdf_antwort(teilantwort)
    assert pdf_aus_browser_antworten(
        [PdfNetworkResponse(b"<html>Login</html>", page=popup)], viewer, [popup],
    ) is None


@pytest.mark.parametrize("popup_url", [
    "http://" + VIEWER_HOST + "/pdf",
    "https://user:password@" + VIEWER_HOST + "/pdf",
    "https://" + VIEWER_HOST + ".evil.invalid/file.pdf",
    "https://evil.invalid/file.pdf",
    "file:///C:/secrets.pdf",
    "javascript:alert('hi')",
    "blob:https://" + VIEWER_HOST + "/file",
    "https://" + VIEWER_HOST + ":1234/file.pdf",
])
def test_unsichere_popup_urls_fuehren_zu_keinem_neuen_http_request(popup_url):
    assert not _vertrauenswuerdige_pdf_url(popup_url, VIEWER_HOST)
    calls = []

    class Request:
        def get(self, *_a, **_kw):
            calls.append("get")
            raise AssertionError("Fremde Adresse duerfte niemals geladen werden")

    assert pdf_aus_popup_url(SimpleNamespace(request=Request()), popup_url, VIEWER_HOST) is None
    assert calls == []


def test_same_origin_popup_url_wird_ohne_redirect_und_nur_als_pdf_geladen():
    calls = []

    class API:
        def __init__(self, data=PDF, status=200, mime="application/pdf"):
            self.data, self.status, self.mime = data, status, mime
            self.disposed = False

        @property
        def headers(self):
            return {"content-type": self.mime, "content-length": str(len(self.data))}

        def body(self):
            return self.data

        def dispose(self):
            self.disposed = True

    response = API()

    class Request:
        def get(self, url, *, timeout, max_redirects):
            calls.append((url, timeout, max_redirects))
            return response

    loaded = pdf_aus_popup_url(SimpleNamespace(request=Request()), URL, VIEWER_HOST)
    assert loaded is not None and loaded.daten == PDF
    assert calls == [(URL, 12000, 0)]
    assert response.disposed


def test_login_html_und_redirect_niemals_als_pdf_speichern():
    for status, mime, data in (
        (302, "text/plain", b"Redirect"),
        (200, "text/html", b"<html>SSO</html>"),
        (200, "application/pdf", b"<html>SSO</html>"),
    ):
        response = SimpleNamespace(
            status=status, headers={"content-type": mime},
            body=lambda: data,
        )
        requests = SimpleNamespace(get=lambda *args, **kw: response)
        assert pdf_aus_popup_url(
            SimpleNamespace(request=requests), URL, VIEWER_HOST,
        ) is None


def test_browser_blob_nur_aus_bestaetigtem_eigenen_viewer_lesbar():
    blob_url = f"blob:https://{VIEWER_HOST}/synthetic-id"
    called = []
    class Viewer:
        def evaluate(self, script, params):
            called.append(params["url"])
            assert params["maxBytes"] == MAX_PDF_BYTES
            return base64.b64encode(PDF).decode("ascii")

    result = pdf_aus_popup_blob(Viewer(), blob_url, VIEWER_HOST)
    assert result is not None and result.daten == PDF
    assert called == [blob_url]
    assert pdf_aus_popup_blob(Viewer(), "blob:https://evil.invalid/id", VIEWER_HOST) is None
    assert called == [blob_url]
