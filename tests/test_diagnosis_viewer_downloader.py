"""Offline-Tests fuer den Edge-Diagnosis-Viewer-Abruf (ohne SSO-Zugriff)."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ntf_insight.acquisition.diagnosis_viewer import (
    DIAGNOSIS_VIEWER, DownloadRow, FinDownloadResult,
    _save_pdf, _visible_rows, _write_manifest, parse_fins, search_url,
)

FIN = "WDD12345678901234"


def test_fin_validation_and_deduplication():
    assert parse_fins(f"{FIN.lower()}; {FIN}") == [FIN]
    with pytest.raises(ValueError):
        parse_fins("123")
    with pytest.raises(ValueError):
        parse_fins("WDD1234567890O234")


def test_source_url_matches_reference():
    assert search_url(FIN) == (
        f"{DIAGNOSIS_VIEWER}?fin={FIN}&sources=XD%2CXD%28AQT%29%2CTD%2CDAS"
    )


class FakeDownload:
    suggested_filename = "quicktest.pdf"

    def __init__(self, content):
        self.content = content

    def save_as(self, filename):
        Path(filename).write_bytes(self.content)


def test_pdf_verified_and_deduplicated(tmp_path):
    row = DownloadRow(0, "XD", "2026-10-12 12:00:00")
    first = _save_pdf(FakeDownload(b"%PDF-1.7\nTest A"), tmp_path / FIN, row)
    assert first.is_file()
    assert _save_pdf(FakeDownload(b"%PDF-1.7\nTest A"), tmp_path / FIN, row) == first
    assert _save_pdf(FakeDownload(b"%PDF-1.7\nTest B"), tmp_path / FIN, row) != first
    with pytest.raises(ValueError):
        _save_pdf(FakeDownload(b"<html>Login</html>"), tmp_path / FIN, row)


class Locator:
    def __init__(self, items):
        self.items = items

    def count(self):
        return len(self.items)

    def nth(self, i):
        return self.items[i]


class Row:
    def __init__(self, columns, clickable):
        self.columns = columns
        self.clickable = clickable

    def inner_text(self):
        return " ".join(self.columns)

    def locator(self, selector):
        if selector == "td":
            return Locator([SimpleNamespace(inner_text=lambda x=value: x) for value in self.columns])
        if selector == "span.cursor-pointer:has(svg.lucide-file-down)":
            return Locator([object()] if self.clickable else [])
        raise AssertionError(selector)


class Page:
    def __init__(self, rows):
        self.rows = rows

    def locator(self, selector):
        assert selector == "tbody tr"
        return Locator(self.rows)


def test_only_active_download_icons_are_selected():
    columns = ["XD", "2026-10-12 12:00:00", "", FIN, FIN, "123", "3", "", "200", "", ""]
    rows, empty = _visible_rows(Page([Row(columns, True), Row(columns, False)]))
    assert rows == [DownloadRow(0, "XD", "2026-10-12 12:00:00")]
    assert empty is False
    assert _visible_rows(Page([Row(["No Results Found"], False)])) == ([], True)


def test_manifest_is_fin_scoped(tmp_path):
    result = FinDownloadResult(fin=FIN, status="Keine Quicktests")
    _write_manifest(tmp_path / FIN, result)
    metadata = json.loads((tmp_path / FIN / "abrufstatus.json").read_text(encoding="utf-8"))
    assert metadata["fin"] == FIN
    assert metadata["status"] == "Keine Quicktests"
    assert metadata["pdf_dateien"] == []
