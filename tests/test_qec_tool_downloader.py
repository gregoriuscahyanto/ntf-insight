"""Offline-Regressionstests fuer QEC-DOM und Downloads; keine Unternehmensanmeldung."""

import json
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest

from ntf_insight.acquisition.qec_tool import (
    QEC_SECTIONS, QEC_START, QecDownloader, QecHit, QecResult, QecTarget,
    _qec_url, _snapshot_data, _store_attachment, _write_result,
    parse_attachment_urls, parse_qec_targets, parse_search_hits,
    inspect_search_results, parse_attachment_listing, _validate_attachment_response_url,
    attachment_matches_reference, _matching_previous_attachments,
)

FIN = "WDD12345678901234"
SACHNUMMER = "A 999 999 99 99"


def _row(reference="123456789", fin=FIN, description="KUEHLMITTELPUMPE 100-140W",
         part=SACHNUMMER, identifier="1234"):
    values = [reference, "5", part, description, "MBC", fin[:3], fin[3:6], fin[6:9],
              fin[9:11], fin[-6:]] + [""] * 29
    cells = "".join(f"<td>{text}</td>" for text in values)
    cells = cells.replace(f"<td>{reference}</td>", (
        f'<td><a href="schadteilSelektieren.qec?schadteilID={identifier}">'
        f"{reference}</a></td>"
    ), 1)
    return f"<tr>{cells}</tr>"


def test_fin_and_sachnummer_validation():
    assert parse_qec_targets(f"{FIN.lower()};{SACHNUMMER}\n{FIN.lower()};{SACHNUMMER}") == [
        QecTarget(FIN, SACHNUMMER)
    ]
    assert parse_qec_targets(FIN) == [QecTarget(FIN)]
    with pytest.raises(ValueError):
        parse_qec_targets("ungültig")
    with pytest.raises(ValueError):
        parse_qec_targets("WDD12345678901O34")
    with pytest.raises(ValueError):
        parse_qec_targets(f"{FIN};{SACHNUMMER};zuviel")
    with pytest.raises(ValueError):
        parse_qec_targets(f"{FIN};../gefährlich")
    with pytest.raises(ValueError):
        parse_qec_targets(f"{FIN};{SACHNUMMER}\n{FIN};A 111 111 11 11")
    with pytest.raises(ValueError):
        parse_qec_targets("")


def test_search_filters_full_fin_pump_and_part():
    same_end_other_fin = "WDD99945678901234"
    doc = "<html><body><table>" + "".join([
        _row(), _row("777777777", same_end_other_fin, identifier="8888"),
        _row("777777778", description="TURBOLADER", identifier="2222"),
        _row("777777779", part="A 000 000 00 00", identifier="3333"),
    ]) + "</table></body></html>"
    result = parse_search_hits(doc, FIN, part_number=SACHNUMMER)
    assert len(result) == 1
    assert result[0].reference == "123456789"
    assert result[0].fin == FIN
    assert result[0].schadteil_id == "1234"
    assert len(parse_search_hits(doc, FIN)) == 2
    assert len(parse_search_hits(doc, FIN, pump_only=False)) == 3
    assert parse_search_hits("<html><body>Keine Ergebnisse</body></html>", FIN) == []


def _search_html(fin=FIN, rows=None, *, echo=True, total=1):
    """Synthetic structure matching QEC's sample: server-echo + Treffer indicator."""
    rows = [_row()] if rows is None else rows
    br = fin[3:6] if echo else ""
    end = fin[-6:] if echo else ""
    return (
        "<html><body><form>"
        f'<input name="_finBR" value="{br}">'
        f'<input name="_finEndnummerFrom" value="{end}">'
        "</form>"
        f'<div class="messageGreen">{total} Treffer</div>'
        "<table>" + "".join(rows) + "</table></body></html>"
    )


def test_server_echo_and_result_rows_required_for_confirmed_search():
    target = QecTarget(FIN, SACHNUMMER)
    pending = inspect_search_results(_search_html(rows=[], echo=False, total=0), target)
    assert pending["bestaetigt"] is False
    complete = inspect_search_results(_search_html(), target)
    assert complete == {
        "bestaetigt": True, "qec_trefferzahl": 1, "sichtbare_zeilen": 1,
        "fin_identisch": 1, "pumpen": 1, "sachnummer": 1,
    }
    no_results = inspect_search_results(_search_html(rows=[], total=0), target)
    assert no_results["bestaetigt"] is True
    assert no_results["sichtbare_zeilen"] == 0
    no_links_yet = inspect_search_results(_search_html(rows=[], total=1), target)
    assert no_links_yet["bestaetigt"] is False


def test_search_diagnostics_separate_wrong_vin_and_wrong_part():
    target = QecTarget(FIN, SACHNUMMER)
    different_fin = "WDD98745678901234"
    doc = _search_html(rows=[_row("000123456", different_fin)])
    summary = inspect_search_results(doc, target)
    assert summary["bestaetigt"] is True
    assert summary["fin_identisch"] == 0
    assert parse_search_hits(doc, FIN) == []
    doc = _search_html(rows=[_row("000123456", FIN, part="A 111 222 33 44")])
    summary = inspect_search_results(doc, target)
    assert summary["fin_identisch"] == summary["pumpen"] == 1
    assert summary["sachnummer"] == 0
    doc = _search_html(rows=[_row("000123456")])
    assert parse_search_hits(doc, FIN)[0].reference == "000123456"


def test_only_qec_urls_and_attachment_ids():
    assert _qec_url("/qec-access/displayPruefberichtFile.qec?attachmentId=1001").startswith(QEC_START.split("/qec-access")[0])
    with pytest.raises(ValueError):
        _qec_url("https://qec.attacker.example/qec-access/displayPruefberichtFile.qec?attachmentId=1001")
    with pytest.raises(ValueError):
        _qec_url("http://qect.mo360cp.i.mercedes-benz.com/qec-access/displayPruefberichtFile.qec")
    doc = """<html><body>
      <a href="/qec-access/displayPruefberichtFile.qec?attachmentId=1001">Bericht</a>
      <a href="/qec-access/displayPruefberichtFile.qec?attachmentId=1001">Bericht</a>
      <a href="displayPruefberichtFile.qec?attachmentId=1002">Details</a>
    </body></html>"""
    files = parse_attachment_urls(doc)
    assert [key for key, _ in files] == ["1001", "1002"]
    inventory = parse_attachment_listing(doc)
    assert [i["anhang_id"] for i in inventory] == ["1001", "1002"]
    assert inventory[0]["linktext"] == "Bericht"
    assert all("displayPruefberichtFile.qec" in url for _, url in files)


def test_attachment_is_atomic_deduplicated_and_safe(tmp_path):
    headers = {"content-disposition": 'attachment; filename="../../geheim.pdf"',
               "content-type": "application/pdf"}
    folder = tmp_path / "anhaenge"
    first = _store_attachment(folder, "1001", headers, b"%PDF-1.7\nBefund A")
    assert first.parent == folder
    assert first.name == "1001_geheim.pdf"
    assert _store_attachment(folder, "1001", headers, b"%PDF-1.7\nBefund A") == first
    changed = _store_attachment(folder, "1001", headers, b"%PDF-1.7\nBefund B")
    assert changed != first and changed.exists()
    with pytest.raises(ValueError):
        _store_attachment(folder, "1001", {"content-type": "text/html"}, b"<html>SSO</html>")
    with pytest.raises(ValueError):
        _store_attachment(folder, "1001", {}, b"")
    with pytest.raises(ValueError, match="PDF-Header"):
        _store_attachment(folder, "1001", headers, b"THIS IS NOT A PDF")
    assert not list(folder.glob("*.partial"))


def test_write_manifest_contains_only_local_relative_paths(tmp_path):
    result = QecResult(FIN, status="Erfolgreich", attempted_at="2026-10-13T12:00:00+00:00")
    file = tmp_path / "ref_123" / "anhaenge" / "1001_bericht.pdf"
    file.parent.mkdir(parents=True)
    file.write_bytes(b"%PDF-1.7")
    result.files.append(file)
    _write_result(tmp_path, result)
    payload = json.loads((tmp_path / "abrufstatus.json").read_text(encoding="utf-8"))
    assert payload["fin"] == FIN
    assert payload["anhaenge"] == ["ref_123/anhaenge/1001_bericht.pdf"]
    assert payload["suchdiagnose"] == {}


class SnapshotPage:
    def locator(self, selector):
        assert selector == "body"
        return SimpleNamespace(inner_text=lambda timeout: "Kühlmittelpumpe: geprüft")

    def evaluate(self, script):
        if "querySelectorAll('table')" in script:
            return [{"nummer": 1, "zeilen": [[{"typ": "td", "text": "Gefunden", "colspan": 1}]]}]
        return [{"name": "befund", "typ": "text", "wert": "NTF",
                 "auswahltext": "Kein Fehler", "deaktiviert": False}]


def test_section_snapshot_is_structured_and_does_not_write_html(tmp_path):
    hit = QecHit("123456789", SACHNUMMER, "Pumpe", FIN,
                 "schadteilSelektieren.qec?schadteilID=1234", "1234")
    data = _snapshot_data(SnapshotPage(), QEC_SECTIONS[0], hit)
    assert data["felder"][0]["wert"] == "NTF"
    assert data["felder"][0]["auswahltext"] == "Kein Fehler"
    assert data["tabellen"][0]["zeilen"][0][0]["text"] == "Gefunden"
    assert data["sichtbarer_text"] == "Kühlmittelpumpe: geprüft"
    assert not list(tmp_path.rglob("*.html"))
    assert not list(tmp_path.rglob("*.json"))


class FakeControl:
    def __init__(self, page, selector: str):
        self.page = page
        self.selector = selector

    def count(self):
        if "nav_schadteile" in self.selector:
            return int(self.page.has_nav and self.page.state == "entry")
        if "_finBR" in self.selector or "_finEndnummerFrom" in self.selector:
            return int(self.page.state == "search")
        if "Filtern" in self.selector:
            return int(self.page.state == "search")
        return 0

    @property
    def first(self):
        return self

    def nth(self, _index):
        return self

    def is_visible(self):
        return bool(self.count())

    def get_attribute(self, name):
        assert name == "href"
        return "navigationDispatch.qec?nav_schadteile=1"

    def click(self, **_kwargs):
        self.page.calls.append(("click", self.selector))
        if "nav_schadteile" in self.selector:
            self.page.state = "search"
            self.page.url = "https://qect.mo360cp.i.mercedes-benz.com/qec-access/schadteileSearchlist.qec"
        if "Filtern" in self.selector:
            self.page.state = "pending"
            self.page.pending_polls = 2

    def fill(self, value):
        self.page.calls.append(("fill", self.selector, value))


class FakeQecPage:
    def __init__(self, *, has_nav=True):
        self.has_nav = has_nav
        self.state = "entry"
        self.calls = []
        self.url = "https://qect.mo360cp.i.mercedes-benz.com/qec-access/qecentry.qec"
        self.pending_polls = 0
        self.content_reads = 0

    def content(self):
        self.content_reads += 1
        if self.state == "pending":
            if self.pending_polls > 0:
                self.pending_polls -= 1
                return _search_html(rows=[], echo=False, total=0)
            self.state = "filtered"
        if self.state == "filtered":
            return _search_html()
        return _search_html(rows=[], echo=False, total=0)

    def is_closed(self):
        return False

    def locator(self, selector):
        return FakeControl(self, selector)

    def goto(self, url, **_kwargs):
        self.calls.append(("goto", url))
        if url == QEC_START:
            self.state = "entry"
            self.url = "https://qect.mo360cp.i.mercedes-benz.com/qec-access/qecentry.qec"
        elif "navigationDispatch.qec" in url:
            self.state = "search"
            self.url = "https://qect.mo360cp.i.mercedes-benz.com/qec-access/schadteileSearchlist.qec"


def test_qec_entry_is_ready_after_sso_even_without_exact_nav_link():
    page = FakeQecPage(has_nav=False)
    downloader = QecDownloader(Path("/tmp/a"), Path("/tmp/b"))
    assert downloader._is_qec_ready(page) is True
    page.url = QEC_START  # QEC login endpoint is not an authenticated landing.
    assert downloader._is_qec_ready(page) is False
    page.url = "https://example.org/qec-access/qecentry.qec"
    assert downloader._is_qec_ready(page) is False


@pytest.mark.parametrize("has_nav", [True, False])
def test_every_search_reopens_qec_start_and_fills_after_login(has_nav):
    page = FakeQecPage(has_nav=has_nav)
    context = SimpleNamespace(pages=[page])
    messages = []
    downloader = QecDownloader(Path("/tmp/a"), Path("/tmp/b"),
                               navigation_timeout_ms=1000, click_delay_seconds=0)
    returned, scope, document, evidence = downloader._search(
        context, page, QecTarget(FIN), messages.append, Event(),
    )
    assert returned is page and scope is page
    assert evidence["bestaetigt"] and evidence["fin_identisch"] == 1
    assert parse_search_hits(document, FIN)[0].reference == "123456789"
    assert page.content_reads >= 3  # initial empty form must not pass
    assert page.calls[0] == ("goto", QEC_START)
    assert ("fill", 'input[name="_finBR"]', "123") in page.calls
    assert ("fill", 'input[name="_finEndnummerFrom"]', "901234") in page.calls
    assert ("click", 'input[type="submit"][value="Filtern"]') in page.calls
    assert any("Anmeldung abgeschlossen" in message for message in messages)
    if has_nav:
        assert ("click", 'a[href*="navigationDispatch.qec"][href*="nav_schadteile=1"]') in page.calls
        assert not any(
            "navigationDispatch.qec" in value
            for action, value, *rest in page.calls
            if action == "goto" and value != QEC_START
        )
    else:
        assert any(
            "navigationDispatch.qec?nav_schadteile=1" in value
            for action, value, *rest in page.calls if action == "goto"
        )


def test_no_match_manifest_distinguishes_real_server_response(tmp_path):
    target = QecTarget(FIN, SACHNUMMER)
    other = "WDD98745678901234"
    document = _search_html(rows=[_row("000123456", fin=other)])
    evidence = inspect_search_results(document, target)
    downloader = QecDownloader(tmp_path, tmp_path / "profile")
    page = object()
    downloader._search = lambda *_args: (page, page, document, evidence)
    result, _ = downloader._one_target(
        SimpleNamespace(pages=[]), page, target, lambda _: None, Event()
    )
    assert result.status == "Keine passenden Schadteile"
    manifest = json.loads((tmp_path / FIN / "abrufstatus.json").read_text(encoding="utf-8"))
    assert manifest["suchdiagnose"]["bestaetigt"] is True
    assert manifest["suchdiagnose"]["fin_identisch"] == 0
    assert manifest["status"] == "Keine passenden Schadteile"


def test_partial_result_count_is_not_reported_as_zero_parts(tmp_path):
    target = QecTarget(FIN)
    document = _search_html(rows=[_row("000123456", fin="WDD98745678901234")], total=2)
    evidence = inspect_search_results(document, target)
    downloader = QecDownloader(tmp_path, tmp_path / "profile")
    page = object()
    downloader._search = lambda *_args: (page, page, document, evidence)
    result, _ = downloader._one_target(
        SimpleNamespace(pages=[]), page, target, lambda _: None, Event()
    )
    assert result.status == "Ergebnispruefung erforderlich"
    assert result.errors and not result.references


def test_wait_search_rejects_stale_filter_response():
    page = FakeQecPage()
    page.state = "search"
    page.content = lambda: _search_html(
        fin="WDD77745678905432", rows=[_row()], total=1,
    )
    downloader = QecDownloader(Path("/tmp/a"), Path("/tmp/b"), navigation_timeout_ms=100)
    with pytest.raises(TimeoutError, match="nicht bestaetigt"):
        downloader._wait_search_results(
            SimpleNamespace(pages=[page]), QecTarget(FIN), lambda _: None, Event(),
        )


def test_sso_credentials_are_submitted_only_on_verified_mercedes_login_host():
    class LoginField:
        def __init__(self, selector, page):
            self.selector = selector
            self.page = page

        def count(self):
            return int(self.selector in self.page.visible_fields)

        def is_visible(self):
            return bool(self.count())

        def fill(self, value):
            self.page.filled.append((self.selector, value))

        def click(self, **_kwargs):
            self.page.clicked.append(self.selector)

    class LoginPage:
        def __init__(self, url, fields):
            self.url = url
            self.visible_fields = fields
            self.filled = []
            self.clicked = []

        def locator(self, selector):
            return LoginField(selector, self)

    downloader = QecDownloader(Path("/tmp/a"), Path("/tmp/b"),
                               user_id="test-id", password="test-secret")
    submitted = {"user": False, "password": False}
    impostor = LoginPage("https://login.mercedes-benz.com.attacker.invalid/sso",
                         {"#userid", "#next-btn", "#password", "#loginSubmitButton"})
    downloader._enter_credentials(impostor, submitted, lambda _: None)
    assert impostor.filled == [] and impostor.clicked == []
    assert submitted == {"user": False, "password": False}

    actual = LoginPage("https://login.mercedes-benz.com/sso", {"#userid", "#next-btn"})
    downloader._enter_credentials(actual, submitted, lambda _: None)
    actual.visible_fields = {"#password", "#loginSubmitButton"}
    downloader._enter_credentials(actual, submitted, lambda _: None)
    assert submitted == {"user": True, "password": True}
    assert actual.filled == [("#userid", "test-id"), ("#password", "test-secret")]
    assert actual.clicked == ["#next-btn", "#loginSubmitButton"]


def test_no_live_browser_or_credentials_needed_for_parsers():
    assert QEC_SECTIONS == (
        "WE-Daten", "Voranalysen", "Stellungnahme Lieferant", "Ergebnis + Nachanalyse", "Historie"
    )


def test_attachment_destination_may_redirect_within_qec_but_never_to_sso():
    valid = "https://qect.mo360cp.i.mercedes-benz.com/qec-access/attachmentDownload.qec?id=1001"
    assert _validate_attachment_response_url(valid) == valid
    for unsafe in (
        "https://login.mercedes-benz.com/authorize",
        "https://qect.mo360cp.i.mercedes-benz.com/qec-access/supp/login.qec",
        "https://qect.mo360cp.i.mercedes-benz.com/qec-access/qecentry.qec",
        "https://other.example/qec-access/attachmentDownload.qec",
        "http://qect.mo360cp.i.mercedes-benz.com/qec-access/attachmentDownload.qec",
        "https://qect.mo360cp.i.mercedes-benz.com:8443/qec-access/attachmentDownload.qec",
    ):
        with pytest.raises(ValueError):
            _validate_attachment_response_url(unsafe)


def test_api_attachment_accepts_safe_internal_redirect(tmp_path):
    from types import SimpleNamespace

    class Request:
        headers = None
        def get(self, url, **kwargs):
            self.headers = kwargs.get("headers")
            return SimpleNamespace(
                url="https://qect.mo360cp.i.mercedes-benz.com/qec-access/redirectedDownload.qec",
                ok=True, status=200,
                headers={"content-type": "application/pdf",
                         "content-disposition": 'attachment; filename="lieferantenbericht.pdf"'},
                body=lambda: b"%PDF-1.7\nTest data",
            )
    request = Request()
    context = SimpleNamespace(request=request)
    popup = SimpleNamespace(url="https://qect.mo360cp.i.mercedes-benz.com/qec-access/listAttachments.qec")
    dl = QecDownloader(tmp_path, tmp_path / "profile")
    url = "https://qect.mo360cp.i.mercedes-benz.com/qec-access/displayPruefberichtFile.qec?attachmentId=1001"
    result = dl._download_attachment_api(context, popup, "1001", url, tmp_path)
    assert result.name == "1001_lieferantenbericht.pdf"
    assert result.read_bytes().startswith(b"%PDF-")
    assert request.headers == {"Referer": popup.url}


def test_api_attachment_rejects_login_html_instead_of_pdf(tmp_path):
    from types import SimpleNamespace

    class Request:
        def get(self, url, **kwargs):
            return SimpleNamespace(url="https://qect.mo360cp.i.mercedes-benz.com/qec-access/supp/login.qec",
                                   ok=True, status=200, headers={"content-type": "text/html"},
                                   body=lambda: b"<html>Login</html>")
    dl = QecDownloader(tmp_path, tmp_path / "profile")
    popup = SimpleNamespace(url="https://qect.mo360cp.i.mercedes-benz.com/qec-access/listAttachments.qec")
    url = "https://qect.mo360cp.i.mercedes-benz.com/qec-access/displayPruefberichtFile.qec?attachmentId=1001"
    with pytest.raises(ValueError, match="Anmeldung"):
        dl._download_attachment_api(SimpleNamespace(request=Request()), popup, "1001", url, tmp_path)
    assert not list(tmp_path.glob("*.pdf"))


def test_visible_browser_download_can_replace_failed_api_download(tmp_path):
    from types import SimpleNamespace

    url = "https://qect.mo360cp.i.mercedes-benz.com/qec-access/displayPruefberichtFile.qec?attachmentId=1001"

    class Link:
        def get_attribute(self, _):
            return url
        def click(self, **_):
            pass

    class Locator:
        def count(self):
            return 1
        def nth(self, _):
            return Link()

    class Download:
        suggested_filename = "beweis.pdf"
        def failure(self):
            return None
        def save_as(self, path):
            Path(path).write_bytes(b"%PDF-1.7\nBrowser download")

    class Event:
        def __enter__(self):
            return SimpleNamespace(value=Download())
        def __exit__(self, *args):
            return False

    class Popup:
        def locator(self, _):
            return Locator()
        def expect_download(self, **_):
            return Event()

    saved = QecDownloader(tmp_path, tmp_path / "profile")._download_attachment_browser(
        Popup(), "1001", url, tmp_path,
    )
    assert saved.name == "1001_beweis.pdf"
    assert not list(tmp_path.glob("*.partial"))


def test_popup_inventory_is_saved_and_existing_files_not_redownloaded(tmp_path):
    from types import SimpleNamespace

    document = '''<html><body><table>
      <tr><th>Dateinummer</th><th>Aktuelle Version</th><th>Dateiname</th></tr>
      <tr><td><a href="displayPruefberichtFile.qec?attachmentId=1001">1001</a></td>
          <td>10.04.2026</td><td>900000625_A.pdf</td></tr>
      <tr><td><a href="displayPruefberichtFile.qec?attachmentId=1002">1002</a></td>
          <td>11.04.2026</td><td>900000625_B.pdf</td></tr>
      <tr><td><a href="displayPruefberichtFile.qec?attachmentId=1003">1003</a></td>
          <td>11.04.2026</td><td>900000754_C.pdf</td></tr>
      <tr><td><a href="displayPruefberichtFile.qec?attachmentId=1001">1001</a></td></tr>
    </table></body></html>'''
    popup_url = "https://qect.mo360cp.i.mercedes-benz.com/qec-access/listAttachments.qec"

    class FakePopup:
        url = popup_url

        def wait_for_load_state(self, *_args, **_kwargs):
            pass

        def content(self):
            return document

        def close(self):
            pass

    class Clickable:
        def is_visible(self):
            return True

        def click(self, **_kwargs):
            pass

    class PopupButton:
        def count(self):
            return 1

        def nth(self, _):
            return Clickable()

    class Event:
        def __enter__(self):
            return SimpleNamespace(value=FakePopup())

        def __exit__(self, *args):
            return False

    class FakePage:
        def locator(self, _):
            return PopupButton()

        def expect_popup(self, **_kwargs):
            return Event()

    downloader = QecDownloader(tmp_path, tmp_path / "profile", click_delay_seconds=0)
    calls = []

    def api(_context, _popup, attachment_id, _url, folder):
        calls.append(attachment_id)
        return _store_attachment(folder, attachment_id,
                                 {"content-disposition": 'attachment; filename="befund.pdf"'},
                                 b"%PDF-1.7\nTest")

    downloader._download_attachment_api = api
    folder = tmp_path / "ref_test" / "anhaenge"
    result = QecResult(FIN)
    inventory = {}
    downloader._save_popups(SimpleNamespace(), FakePage(), folder, result,
                            lambda _msg: None, __import__("threading").Event(),
                            inventory, reference="900000625")
    assert calls == ["1001", "1002"]
    assert len(result.files) == 2 and not result.errors
    assert sorted(inventory) == ["1001", "1002"]
    assert all(x["status"] == "Gespeichert" for x in inventory.values())
    assert not (folder.parent / "anhangliste.json").exists()
    downloader._save_popups(SimpleNamespace(), FakePage(), folder, result,
                            lambda _msg: None, __import__("threading").Event(),
                            inventory, reference="900000625")
    assert calls == ["1001", "1002"]


def test_one_case_contains_five_sections_and_no_reiter_or_html_files(tmp_path):
    """Offline Playwright substitute for case-specific tab and metadata export."""
    class Locator:
        def __init__(self, callback=lambda: None):
            self._callback = callback

        @property
        def first(self):
            return self

        def nth(self, _):
            return self

        def count(self):
            return 1

        def is_visible(self):
            return True

        def click(self, **_):
            self._callback()

        def wait_for(self, **_):
            pass

        def inner_text(self, **_):
            return page.active_section

    class TabPage:
        active_section = ""

        def locator(self, selector):
            return Locator()

        def get_by_text(self, *_args, **_kwargs):
            return Locator()

        def get_by_role(self, _role, *, name, exact):
            return Locator(lambda: setattr(self, "active_section", name))

        def evaluate(self, script):
            if "querySelectorAll('table')" in script:
                return [{"nummer": 1, "zeilen": [[{
                    "typ": "td", "text": self.active_section, "colspan": 1
                }]]}]
            return [{"name": "feld", "typ": "text", "wert": self.active_section}]

    page = TabPage()
    hit = QecHit("022301658", SACHNUMMER, "KUEHLMITTELPUMPE 100-140W", FIN,
                 "schadteilSelektieren.qec?schadteilID=1234", "1234")
    target = QecTarget(FIN, reference="022301658")
    result = QecResult(FIN)
    downloader = QecDownloader(tmp_path, tmp_path / "profile", click_delay_seconds=0)
    downloader._search = lambda *_args: (page, page, _search_html(
        rows=[_row(reference=hit.reference)]), {})
    downloader._save_popups = lambda _ctx, _page, _folder, _result, _log, _cancel, inv, *, reference: inv.update({
        "1001": {"anhang_id": "1001", "linktext": "Bericht", "status": "Gespeichert",
                 "datei": "1001_bericht.pdf"},
    })
    downloader._one_hit(SimpleNamespace(), page, target, hit, result,
                        lambda _: None, Event())
    folder = tmp_path / FIN / "ref_022301658"
    report = json.loads((folder / "qec.json").read_text(encoding="utf-8"))
    assert report["schema_version"] == 2
    assert report["referenznummer"] == "022301658"
    assert [a["bereich"] for a in report["abschnitte"]] == list(QEC_SECTIONS)
    assert report["vollstaendige_reiter"] is True
    assert report["anhaenge"][0]["anhang_id"] == "1001"
    assert report["abschnitte"][1]["felder"][0]["wert"] == "Voranalysen"
    assert result.snapshots == [folder / "qec.json"]
    assert not (folder / "laeufe").exists()
    assert not list(folder.rglob("ansicht.html"))
    assert not (folder / "anhangliste.json").exists()


def test_target_reference_restricts_hits_even_when_same_fin(tmp_path):
    target = QecTarget(FIN, reference="022301658")
    document = _search_html(rows=[
        _row(reference="022301658", identifier="1001"),
        _row(reference="022301659", identifier="1002"),
    ], total=2)
    evidence = inspect_search_results(document, target)
    downloader = QecDownloader(tmp_path, tmp_path / "profile", click_delay_seconds=0)
    page = object()
    downloader._search = lambda *_args: (page, page, document, evidence)
    selected = []

    def select_one(_context, current_page, _target, hit, result, *_args):
        selected.append(hit.reference)
        result.references.append(hit.reference)
        return current_page

    downloader._one_hit = select_one
    result, _ = downloader._one_target(
        SimpleNamespace(), page, target, lambda _: None, Event()
    )
    assert selected == ["022301658"]
    assert result.references == selected
    assert result.status == "Erfolgreich"


def test_unknown_reference_does_not_download_other_case(tmp_path):
    target = QecTarget(FIN, reference="022301660")
    document = _search_html(rows=[_row(reference="022301658")])
    evidence = inspect_search_results(document, target)
    downloader = QecDownloader(tmp_path, tmp_path / "profile", click_delay_seconds=0)
    page = object()
    downloader._search = lambda *_args: (page, page, document, evidence)
    result, _ = downloader._one_target(
        SimpleNamespace(), page, target, lambda _: None, Event()
    )
    assert result.status == "Keine passenden Schadteile"
    assert not result.references
