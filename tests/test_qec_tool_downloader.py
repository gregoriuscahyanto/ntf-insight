"""Offline-Regressionstests fuer QEC-DOM und Downloads; keine Unternehmensanmeldung."""

import json
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest

from ntf_insight.acquisition.qec_tool import (
    QEC_SECTIONS, QEC_START, QecDownloader, QecHit, QecResult, QecTarget,
    _qec_url, _snapshot, _store_attachment, _write_result,
    parse_attachment_urls, parse_qec_targets, parse_search_hits,
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


class SnapshotPage:
    def locator(self, selector):
        assert selector == "body"
        return SimpleNamespace(inner_text=lambda timeout: "Kühlmittelpumpe: geprüft")

    def evaluate(self, _):
        return [{"name": "befund", "typ": "text", "wert": "NTF", "deaktiviert": False}]


def test_snapshot_saves_json_and_read_only_html(tmp_path):
    hit = QecHit("123456789", SACHNUMMER, "Pumpe", FIN,
                 "schadteilSelektieren.qec?schadteilID=1234", "1234")
    result = _snapshot(SnapshotPage(), tmp_path, QEC_SECTIONS[0], hit)
    data = json.loads(result.read_text(encoding="utf-8"))
    assert data["felder"][0]["wert"] == "NTF"
    html = (tmp_path / "ansicht.html").read_text(encoding="utf-8")
    assert "<script" not in html
    assert "Kühlmittelpumpe" in html


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

    def fill(self, value):
        self.page.calls.append(("fill", self.selector, value))


class FakeQecPage:
    def __init__(self, *, has_nav=True):
        self.has_nav = has_nav
        self.state = "entry"
        self.calls = []
        self.url = "https://qect.mo360cp.i.mercedes-benz.com/qec-access/qecentry.qec"

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
    downloader = QecDownloader(Path("/tmp/a"), Path("/tmp/b"), navigation_timeout_ms=1000)
    returned = downloader._search(context, page, QecTarget(FIN), messages.append, Event())
    assert returned is page
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
