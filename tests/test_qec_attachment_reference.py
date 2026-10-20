"""QEC popup attachment selection: strictly one case reference per download.

All file names and reference numbers are synthetic. No live QEC access.
"""
from __future__ import annotations

from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest

from ntf_insight.acquisition.qec_tool import (
    QecDownloader, QecResult, _matching_previous_attachments,
    _store_attachment, attachment_matches_reference, parse_attachment_listing,
)

FIN = "WDD12345678901234"
REF = "900000625"


@pytest.mark.parametrize(("name", "expected"), [
    ("900000625_26TEST_2.pdf", True),
    ("INTERNAL_900000625_Z.pdf", True),
    ("900000517_26TEST_1.pdf", False),
    ("900000754_26TEST_3.pdf", False),
    ("9000006250_26TEST.pdf", False),
    ("1900000625_26TEST.pdf", False),
    ("90000062_26TEST.pdf", False),
    ("900000625_without_extension", False),
    ("", False),
])
def test_visible_filename_must_contain_exact_reference(name, expected):
    assert attachment_matches_reference(name, REF) is expected


def _listing(*names: str) -> str:
    rows = []
    for number, filename in enumerate(names, start=1):
        rows.append(
            '<tr>'
            f'<td><a href="displayPruefberichtFile.qec?attachmentId={number}">'
            f'{number}</a></td><td>10.04.2026</td><td>10.04.2026</td>'
            f'<td>{filename}</td></tr>'
        )
    return (
        '<html><body><table><tr>'
        '<th>Dateinummer</th><th>Aktuelle Version</th>'
        '<th>Ursprungsversion</th><th>Dateiname</th></tr>'
        + "".join(rows) + '</table></body></html>'
    )


class _Popup:
    url = "https://qect.mo360cp.i.mercedes-benz.com/qec-access/pruefberichtAttachmentsList.qec"

    def __init__(self, document: str):
        self.document = document

    def wait_for_load_state(self, *_args, **_kwargs):
        pass

    def content(self):
        return self.document

    def close(self):
        pass


class _Page:
    def __init__(self, doc: str):
        self.popup = _Popup(doc)

    def locator(self, _selector):
        class _Locator:
            def count(self):
                return 1

            def nth(self, _idx):
                return self

            def is_visible(self):
                return True

            def click(self, **_kwargs):
                pass

        return _Locator()

    def expect_popup(self, **_kwargs):
        popup = self.popup

        class _PopupEvent:
            def __enter__(self):
                return SimpleNamespace(value=popup)

            def __exit__(self, *_args):
                return False

        return _PopupEvent()


def test_only_second_pdf_is_retrieved_and_recorded(tmp_path: Path):
    names = (
        "900000517_26TEST_1.pdf",
        "900000625_26TEST_2.pdf",
        "900000754_26TEST_3.pdf",
    )
    popup = _Page(_listing(*names))
    items = parse_attachment_listing(popup.popup.content())
    assert [item["dateiname"] for item in items] == list(names)

    downloader = QecDownloader(tmp_path, tmp_path / "profile", click_delay_seconds=0)
    visited = []

    def fake_download(_context, _popup, identifier, _url, folder):
        visited.append(identifier)
        # Using the matching popup name verifies that no other ID is fetched.
        return _store_attachment(
            folder, identifier,
            {"content-disposition": 'attachment; filename="900000625_26TEST_2.pdf"'},
            b"%PDF-1.7\nSynthetischer Bericht",
        )

    downloader._download_attachment_api = fake_download
    downloader._download_attachment_browser = lambda *_args: pytest.fail(
        "No Edge fallback should be needed."
    )
    result = QecResult(FIN)
    inventory = {}
    progress = []
    folder = tmp_path / "anhaenge"
    downloader._save_popups(
        SimpleNamespace(), popup, folder, result,
        progress.append, Event(), inventory, reference=REF,
    )
    assert visited == ["2"]
    assert list(inventory) == ["2"]
    assert inventory["2"]["dateiname"] == names[1]
    assert inventory["2"]["status"] == "Gespeichert"
    assert len(result.files) == 1
    assert result.files[0].name == "2_900000625_26TEST_2.pdf"
    assert [p.name for p in folder.iterdir()] == ["2_900000625_26TEST_2.pdf"]
    assert any("2 fremde" in message for message in progress)

    # A second retrieval should not trigger a new download.
    downloader._save_popups(
        SimpleNamespace(), popup, folder, result,
        progress.append, Event(), inventory, reference=REF,
    )
    assert visited == ["2"]
    assert len(result.files) == 1


def test_missing_visible_filename_is_not_downloaded(tmp_path: Path):
    popup = _Page(_listing("ohne_dateiname", "900000625_26TEST_2.pdf"))
    downloader = QecDownloader(tmp_path, tmp_path / "profile", click_delay_seconds=0)
    downloader._download_attachment_api = lambda *_args: pytest.fail(
        "This test must not fetch an attachment."
    )
    result = QecResult(FIN)
    inventory = {}
    folder = tmp_path / "anhaenge"
    # Same reference token with an invalid extension is not a file name;
    # when the only valid filename belongs to a different reference, skip all.
    popup.popup.document = _listing("ohne_dateiname", "900000517_26TEST_2.pdf")
    downloader._save_popups(
        SimpleNamespace(), popup, folder, result,
        lambda *_args: None, Event(), inventory, reference=REF,
    )
    assert inventory == {}
    assert result.files == []
    assert not folder.exists()


def test_legacy_metadata_with_foreign_reference_is_not_preserved():
    previous = [
        {
            "anhang_id": "1", "dateiname": "900000517_26TEST_1.pdf",
            "datei": "1_900000517_26TEST_1.pdf", "status": "Gespeichert",
        },
        {
            "anhang_id": "2", "spalten": ["2", "900000625_26TEST_2.pdf"],
            "datei": "2_900000625_26TEST_2.pdf", "status": "Gespeichert",
        },
        {"anhang_id": "3", "datei": "3_bericht.pdf", "status": "Gespeichert"},
    ]
    assert list(_matching_previous_attachments(previous, REF)) == ["2"]
