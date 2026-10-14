"""Synthetische Offline-Tests fuer TIPS Writer. Keine Fahrzeug-Originaldaten."""

from __future__ import annotations

import json
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from zipfile import ZipFile

import pytest

from ntf_insight.acquisition.tips_archive import local_tips_cases
from ntf_insight.acquisition.tips_writer import (
    TIPS_SECTIONS, TipsHit, TipsWriterDownloader, _section,
    _tips_url_valid, _unpack_attachment, parse_tips_attachment_rows,
    parse_tips_search_hits,
)

FIN = "WDD12345678901234"
OTHER_FIN = "WDD12345678901235"


def _case_table(fin=FIN, *, active=True, include_other=True):
    other = (
        f"<tr><td></td><td>88888888</td><td></td><td>{OTHER_FIN}</td>"
        "<td>de</td><td>Anderer Fall</td></tr>"
    ) if include_other else ""
    active_class = "p-tabpanel-active" if active else "p-tabpanel"
    return (
        '<p-tabpanel class="' + active_class + '">'
        "<table><thead><tr><th></th><th>Fall Nummer</th><th>TPR Id</th>"
        "<th>FIN</th><th>Sprache</th><th>Titel</th></tr></thead><tbody>"
        "<tr class='p-datatable-selectable-row' tabindex='0'><td></td>"
        f"<td> 01234567 </td><td></td><td>{fin}</td><td>de</td>"
        "<td> Synthetische Pumpe </td></tr>" + other
        + "</tbody></table></p-tabpanel>"
    )


def _attachment_table():
    return (
        '<p-tabpanel class="p-tabpanel-active"><table>'
        "<thead><tr><th></th><th>Vorschau</th><th>Datei</th><th>Upload-Zeit</th>"
        "<th>Beschreibung</th></tr></thead><tbody>"
        "<tr><td></td><td></td><td>erstbericht.pdf</td>"
        "<td>01.08.25</td><td>Kurztest</td></tr>"
        "<tr><td></td><td></td><td>fehlerfoto.jpg</td>"
        "<td>02.08.25</td><td>Fotodokumentation</td></tr>"
        "</tbody></table></p-tabpanel>"
    )


def test_case_rows_require_full_fin_and_numeric_id_and_active_panel():
    document = "<html><body>" + _case_table() + "</body></html>"
    hits = parse_tips_search_hits(document, FIN)
    assert len(hits) == 1
    assert hits[0] == TipsHit(
        fin=FIN, case_id="01234567", title="Synthetische Pumpe",
        cells={
            "Fall Nummer": "01234567", "TPR Id": "", "FIN": FIN,
            "Sprache": "de", "Titel": "Synthetische Pumpe",
        },
    )
    assert parse_tips_search_hits(document, OTHER_FIN)[0].case_id == "88888888"
    assert parse_tips_search_hits(
        _case_table(fin=FIN, active=False, include_other=False), FIN,
    ) == []


def test_tab_mapping_covers_all_ten_documented_sections():
    assert len(TIPS_SECTIONS) == 10
    assert len(set(TIPS_SECTIONS)) == 10
    assert _section("Fahrzeugdaten (0)") == "Fahrzeugdaten"
    assert _section("Inspektor (0) / Notizen (0)") == "Inspektor / Notizen"
    for expected in TIPS_SECTIONS:
        assert _section(expected) == expected
    assert _section("Neuer Fall") is None


def test_attachment_metadata_from_prime_ng_table():
    assert parse_tips_attachment_rows(_attachment_table()) == [
        {"Vorschau": "", "Datei": "erstbericht.pdf", "Upload-Zeit": "01.08.25",
         "Beschreibung": "Kurztest"},
        {"Vorschau": "", "Datei": "fehlerfoto.jpg", "Upload-Zeit": "02.08.25",
         "Beschreibung": "Fotodokumentation"},
    ]


def test_tips_host_requires_https_and_exact_path():
    assert _tips_url_valid("https://xentry.mercedes-benz.com/tips-writer/home/topics/search")
    assert _tips_url_valid("https://xentry.mercedes-benz.com/tips-writer/home/cases/123")
    assert not _tips_url_valid("https://xentry.mercedes-benz.com.attacker.invalid/tips-writer/")
    assert not _tips_url_valid("http://xentry.mercedes-benz.com/tips-writer/")
    assert not _tips_url_valid("https://xentry.mercedes-benz.com/other/")


def test_credentials_are_never_sent_to_unverified_host():
    class Field:
        def __init__(self, selector, page):
            self.selector, self.page = selector, page

        def count(self):
            return int(self.selector in self.page.visible)

        def is_visible(self):
            return self.count() > 0

        def fill(self, value):
            self.page.values.append((self.selector, value))

        def click(self, **kwargs):
            self.page.clicked.append(self.selector)

    class Page:
        def __init__(self, url, visible):
            self.url, self.visible = url, visible
            self.clicked, self.values = [], []

        def locator(self, selector):
            return Field(selector, self)

    downloader = TipsWriterDownloader(
        Path("/tmp/test"), Path("/tmp/profile"),
        user_id="test-user", password="test-secret",
    )
    attempted = {"user": False, "password": False}
    fake = Page("https://login.mercedes-benz.com.attacker.invalid/signin",
                {"#userid", "#password", "#next-btn", "#loginSubmitButton"})
    downloader._sso(fake, attempted, lambda _: None)
    assert fake.values == [] and fake.clicked == []
    assert attempted == {"user": False, "password": False}

    login = Page("https://login.mercedes-benz.com/signin", {"#userid", "#next-btn"})
    downloader._sso(login, attempted, lambda _: None)
    login.visible = {"#password", "#loginSubmitButton"}
    downloader._sso(login, attempted, lambda _: None)
    assert login.values == [("#userid", "test-user"), ("#password", "test-secret")]
    assert login.clicked == ["#next-btn", "#loginSubmitButton"]


def test_attachment_zip_filters_executables_and_preserves_documents(tmp_path):
    downloaded = tmp_path / "xentry.zip"
    with ZipFile(downloaded, "w") as archive:
        archive.writestr("original/bericht.pdf", b"%PDF-1.7\nsynthetic")
        archive.writestr("original/bild.jpg", b"synthetic-image")
        archive.writestr("original/tabelle.csv", b"synthetic,values")
        archive.writestr("original/malware.exe", b"should never be copied")
    folder = tmp_path / "output"
    files = _unpack_attachment(downloaded, folder)
    assert {p.name for p in files} == {"bericht.pdf", "bild.jpg", "tabelle.csv"}
    assert all(p.is_relative_to(folder) for p in files)
    assert downloaded.exists()
    assert not list(folder.glob("*.exe"))


def test_attachment_zip_rejects_traversal(tmp_path):
    downloaded = tmp_path / "xentry.zip"
    with ZipFile(downloaded, "w") as archive:
        archive.writestr("../unbefugt.pdf", b"not safe")
    folder = tmp_path / "output"
    with pytest.raises(ValueError, match="Unsicherer"):
        _unpack_attachment(downloaded, folder)
    assert not folder.exists()


def test_single_document_is_not_unpackaged_or_lost(tmp_path):
    downloaded = tmp_path / "beleg.pdf"
    downloaded.write_bytes(b"%PDF-1.7\nsynthetic")
    target = tmp_path / "output"
    files = _unpack_attachment(downloaded, target)
    assert len(files) == 1
    assert files[0].read_bytes().startswith(b"%PDF")
    assert not downloaded.exists()


def test_local_tips_presence_requires_matching_fin_and_case_number(tmp_path):
    root = tmp_path / "tips" / FIN
    valid = root / "fall_01234567" / "tips.json"
    valid.parent.mkdir(parents=True)
    valid.write_text(json.dumps({
        "fin": FIN, "fallnummer": "01234567", "abschnitte": [],
    }), encoding="utf-8")
    invalid = root / "fall_01234568" / "tips.json"
    invalid.parent.mkdir(parents=True)
    invalid.write_text(json.dumps({
        "fin": OTHER_FIN, "fallnummer": "01234568",
    }), encoding="utf-8")
    assert local_tips_cases(tmp_path, FIN) == (valid,)
    assert local_tips_cases(tmp_path, OTHER_FIN) == ()
    assert local_tips_cases(tmp_path, "INVALID") == ()


def test_one_case_writes_one_json_with_ten_sections_and_download_metadata(
    tmp_path, monkeypatch,
):
    from ntf_insight.acquisition import tips_writer

    class Element:
        def inner_text(self):
            return "Synthetischer Fallkopf"

    class Page:
        def locator(self, selector):
            return SimpleNamespace(first=Element(), count=lambda: 1)

    downloader = TipsWriterDownloader(
        tmp_path / "tips", tmp_path / "edge-profile", click_delay_seconds=0,
    )
    hit = TipsHit(FIN, "01234567", "Pumpe", {"FIN": FIN})
    downloader._open_case = lambda _ctx, page, *_: page
    downloader._tab = lambda _page, label, _cancel: SimpleNamespace(name=label)

    def capture(panel):
        return {
            "sichtbarer_text": panel.name,
            "felder": [{"name": "synthetisch", "wert": panel.name}],
            "tabellen": [],
        }
    monkeypatch.setattr(tips_writer, "_capture_section", capture)

    def download(_page, _panel, folder, _progress, _cancel):
        folder.mkdir(parents=True)
        pdf = folder / "test.pdf"
        pdf.write_bytes(b"%PDF-1.7\nsynthetic")
        return [pdf], [{"Datei": "test.pdf"}], []
    downloader._download_attachments = download

    report, files, warnings, errors, _ = downloader._one_case(
        SimpleNamespace(), Page(), hit, lambda _: None, Event(),
    )
    saved = json.loads(report.read_text(encoding="utf-8"))
    assert report == tmp_path / "tips" / FIN / "fall_01234567" / "tips.json"
    assert saved["fin"] == FIN and saved["fallnummer"] == "01234567"
    assert saved["schema_version"] == 1
    assert saved["aktuell_erfasste_reiter"] == 10
    assert saved["vollstaendige_reiter"] is True
    assert [section["bereich"] for section in saved["abschnitte"]] == list(TIPS_SECTIONS)
    assert saved["abschnitte"][4]["sichtbarer_text"] == "Kommunikation"
    assert saved["anhangliste"] == [{"Datei": "test.pdf"}]
    assert saved["dateien"][0]["datei"] == "dateien/test.pdf"
    assert len(files) == 1 and files[0].is_file()
    assert not warnings and not errors
    assert not list(report.parent.rglob("*.html"))


def test_partial_followup_preserves_older_tab_without_claiming_recapture(tmp_path, monkeypatch):
    from ntf_insight.acquisition import tips_writer

    folder = tmp_path / "tips" / FIN / "fall_01234567"
    folder.mkdir(parents=True)
    report = folder / "tips.json"
    report.write_text(json.dumps({
        "fin": FIN, "fallnummer": "01234567",
        "abschnitte": [{"bereich": "Kommunikation", "sichtbarer_text": "Alt"}],
    }), encoding="utf-8")
    downloader = TipsWriterDownloader(
        tmp_path / "tips", tmp_path / "profile", click_delay_seconds=0,
    )
    downloader._open_case = lambda _ctx, page, *_: page
    downloader._tab = lambda _page, label, _cancel: (
        SimpleNamespace(name=label) if label == "Erstanfrage" else None
    )
    monkeypatch.setattr(tips_writer, "_capture_section",
                        lambda panel: {"sichtbarer_text": panel.name,
                                       "felder": [], "tabellen": []})

    class Page:
        def locator(self, selector):
            return SimpleNamespace(count=lambda: 0)

    downloader._one_case(
        SimpleNamespace(), Page(), TipsHit(FIN, "01234567"),
        lambda _: None, Event(),
    )
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["vollstaendige_reiter"] is False
    assert payload["aktuell_erfasste_reiter"] == 1
    old_section = next(x for x in payload["abschnitte"]
                       if x["bereich"] == "Kommunikation")
    assert old_section["aus_vorherigem_abruf"] is True


def test_opening_tips_case_verifies_details_fin_and_case_id(tmp_path):
    hit = TipsHit(FIN, "01234567")
    calls = []

    class FakeElement:
        def __init__(self, value=""):
            self.value = value
            self.first = self

        def count(self):
            return 1

        def inner_text(self):
            return self.value

        def click(self, **_kwargs):
            calls.append("clicked")

        def wait_for(self, **_kwargs):
            pass

    class Cells:
        def count(self):
            return 4

        def nth(self, index):
            return FakeElement({
                1: hit.case_id,
                3: hit.fin,
            }.get(index, ""))

    class Row(FakeElement):
        def locator(self, selector):
            assert selector == "td"
            return Cells()

    class Rows:
        def count(self):
            return 1

        def nth(self, index):
            assert index == 0
            return Row()

    class Page:
        url = "https://xentry.mercedes-benz.com/tips-writer/home/topics/search"

        def __init__(self, header):
            self.header = header

        def locator(self, selector):
            if selector == "p-tabpanel.p-tabpanel-active tbody tr.p-datatable-selectable-row":
                return Rows()
            if selector == "tn-case-edit header":
                return FakeElement(self.header)
            raise AssertionError(selector)

        def get_by_role(self, role, name):
            assert role == "tab"
            return FakeElement("Erstanfrage")

    downloader = TipsWriterDownloader(
        tmp_path / "tips", tmp_path / "profile", click_delay_seconds=0,
    )
    downloader._search = lambda _ctx, page, *_args: (page, [hit])
    good = Page(f"Fallkopfdaten: ID: {hit.case_id} FIN: {FIN}")
    assert downloader._open_case(
        SimpleNamespace(), good, hit, lambda _: None, Event()
    ) is good
    assert calls == ["clicked"]

    wrong = Page(f"Fallkopfdaten: ID: {hit.case_id} FIN: {OTHER_FIN}")
    with pytest.raises(RuntimeError, match="stimmt nicht"):
        downloader._open_case(
            SimpleNamespace(), wrong, hit, lambda _: None, Event()
        )
