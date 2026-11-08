"""Offline-Tests: keine Mercedes-Dienste, Logins oder echten FIN-Daten."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import diagnosis_viewer_warn_error as scraper

FIN1 = "WDD12345678901234"
FIN2 = "WDD12345678901235"


def view_url(fin: str, file: str = "beispiel.json.gz") -> str:
    return (
        "https://app.diagviewer.prod.gspp-eu.cloud.corpintra.net/view/XD/"
        f"{file}?fin={fin}&sources=XD%2CXD%28AQT%29%2CTD%2CDAS"
        "&s3PathName=freigegebene-synthetische-testdaten%2F2026%2F"
    )


def test_txt_bom_comments_dedup_and_validation(tmp_path):
    file = tmp_path / "fahrzeuge.txt"
    file.write_text(f"\ufeff# Kommentar\n{FIN1.lower()}\n{FIN1}; {FIN2}\n", encoding="utf-8")
    assert scraper.read_fins(file) == [FIN1, FIN2]
    file.write_text(f"{FIN1}\nWDD1234567890O234", encoding="utf-8")
    with pytest.raises(ValueError, match="Ungueltige"):
        scraper.read_fins(file)
    with pytest.raises(ValueError, match=".txt"):
        scraper.read_fins(tmp_path / "liste.csv")


def test_search_url_stays_on_expected_sources():
    assert scraper.search_url(FIN1) == (
        "https://app.diagviewer.prod.gspp-eu.cloud.corpintra.net/search?"
        f"fin={FIN1}&sources=XD%2CXD%28AQT%29%2CTD%2CDAS"
    )


def test_safe_browser_links_enforce_https_host_and_fin():
    assert scraper.safe_view_link(view_url(FIN1), FIN1)
    assert not scraper.safe_view_link(view_url(FIN1), FIN2)
    assert not scraper.safe_view_link(view_url(FIN1).replace("https://", "http://"), FIN1)
    assert not scraper.safe_view_link(view_url(FIN1).replace(".net/view/", ".net.evil/view/"), FIN1)
    assert scraper.view_filename(view_url(FIN1, "test%3B2026-03-04.xml.json.gz")) == (
        "test;2026-03-04.xml.json.gz"
    )


def test_session_key_does_not_depend_on_order_of_query_parameters():
    one = view_url(FIN1)
    other = one.replace(f"?fin={FIN1}&sources=XD%2CXD%28AQT%29%2CTD%2CDAS", 
                        f"?sources=XD%2CXD%28AQT%29%2CTD%2CDAS&fin={FIN1}")
    assert scraper.session_key(one) == scraper.session_key(other)
    assert scraper.session_key(one) != scraper.session_key(one.replace("beispiel", "anderes"))


def test_raw_sections_keep_every_original_field_and_both_translations():
    raw = {
        "warn_hil_id": "0x123456", "warn_message_status_txt": "ACTIVE",
        "warn_original_odometer_nu": 0, "warn_original_odometer_unit_txt": "km",
        "warn_most_recent_odometer_nu": 12034, "warn_most_recent_odometer_unit_txt": "km",
        "warn_frequency_nu": 21, "warn_ignition_cycle_nu": 116,
        "warn_event_type_id": 2,
        "warn_text_de_txt": "Kuehlmittelstand pruefen", "warn_text_en_txt": "Check coolant",
        "warn_icon_de_txt": "Lampe", "warn_icon_en_txt": "Lamp",
        "neuer_rohwert_aus_zukuenftigem_viewer": {"feld": "bewahren"},
    }
    assert scraper._raw_warnings({"type": "data", "data": {"warningEventMessages": [raw]}}) == [raw]
    assert scraper._raw_warnings({"warningEventMessages": []}) == []
    assert scraper._raw_warnings({"type": "sectioned", "sections": ["logInfo"]}) is None
    normalized = scraper.normalize_raw(raw)
    assert normalized["kennung"] == "0x123456"
    assert normalized["erstes_auftreten"] == {"wert": 0, "einheit": "km"}
    assert normalized["ereignistyp"]["bezeichnung"] == "Displaymeldung"
    assert normalized["anzeigetext"]["en"] == "Check coolant"
    assert normalized["rohdaten"] == raw


def test_dom_fallback_has_nine_columns_and_includes_all_types():
    row = ["0x123", "NOT_ACTIVE", "1 km", "9 km", "2", "4", "Lamp", "", "Battery red"]
    result = scraper.normalize_dom(row)
    assert result["status"] == "NOT_ACTIVE"
    assert result["haeufigkeit"] == 2
    assert result["lampen_ton_symbol_text"]["angezeigt"] == "Battery red"
    with pytest.raises(ValueError):
        scraper.normalize_dom(row[:8])


def test_state_write_atomic_and_resume(tmp_path):
    output = tmp_path / "messages.json"
    state = scraper.fresh_state()
    state["fahrzeuge"][FIN1] = {"status": "teilweise", "sitzungen": {"one": {"status": "erfolgreich"}}}
    scraper.save_state(output, state)
    assert scraper.load_state(output)["fahrzeuge"][FIN1]["sitzungen"]["one"]["status"] == "erfolgreich"
    assert json.loads(output.read_text("utf-8"))["schema_version"] == 1
    assert not list(tmp_path.glob(".*.tmp"))
    output.write_text("{not-valid", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        scraper.load_state(output)
    assert output.read_text("utf-8") == "{not-valid"


class FakeContext:
    def __init__(self):
        self.pages = [object()]
        self.closed = False

    def close(self):
        self.closed = True


class FakePlaywright:
    def __init__(self, context):
        self.context = context
        self.chromium = SimpleNamespace(launch_persistent_context=lambda **kwargs: context)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


def test_interrupted_job_resumes_at_next_session(monkeypatch, tmp_path):
    context = FakeContext()
    monkeypatch.setitem(sys.modules, "playwright.sync_api", SimpleNamespace(
        sync_playwright=lambda: FakePlaywright(context)
    ))
    file = tmp_path / "warnings.json"
    profile = tmp_path / "profile"
    state = scraper.fresh_state()
    sessions = [
        {"href": view_url(FIN1, "first.xml.json.gz"), "quelle": "XD", "diagnosezeitpunkt": "2026-01-01", "fin": FIN1},
        {"href": view_url(FIN1, "second.xml.json.gz"), "quelle": "XD", "diagnosezeitpunkt": "2026-01-02", "fin": FIN1},
    ]
    runner = scraper.DiagnosisViewerScraper(file, profile, pacing=0)
    monkeypatch.setattr(runner, "_search", lambda ctx, page, fin: (page, sessions))
    attempts = []

    def fail_at_second(ctx, href):
        attempts.append(href)
        if len(attempts) == 2:
            raise KeyboardInterrupt
        return ([{"kennung": "synthetische Meldung"}], "datenstruktur")

    monkeypatch.setattr(runner, "_read_session", fail_at_second)
    with pytest.raises(KeyboardInterrupt):
        runner.run([FIN1], state, refresh=False, redo=False)
    checkpoint = scraper.load_state(file)
    assert checkpoint["fahrzeuge"][FIN1]["status"] == "unterbrochen"
    assert len(checkpoint["fahrzeuge"][FIN1]["sitzungen"]) == 1

    runner2 = scraper.DiagnosisViewerScraper(file, profile, pacing=0)
    monkeypatch.setattr(runner2, "_search", lambda ctx, page, fin: (page, sessions))
    resumed = []
    monkeypatch.setattr(runner2, "_read_session", lambda ctx, href: (resumed.append(href) or [], "datenstruktur"))
    final_state = scraper.load_state(file)
    assert runner2.run([FIN1], final_state, refresh=False, redo=False) == 0
    assert resumed == [sessions[1]["href"]]
    assert scraper.load_state(file)["fahrzeuge"][FIN1]["status"] == "abgeschlossen"
    assert len(scraper.load_state(file)["fahrzeuge"][FIN1]["sitzungen"]) == 2


def test_existing_complete_fin_skips_edge_entirely(tmp_path):
    state = scraper.fresh_state()
    state["fahrzeuge"][FIN1] = {"status": "abgeschlossen", "sitzungen": {}}
    runner = scraper.DiagnosisViewerScraper(tmp_path / "out.json", tmp_path / "edge")
    assert runner.run([FIN1], state, refresh=False, redo=False) == 0
    assert not (tmp_path / "edge").exists()


def test_error_logging_sanitizes_link_arguments():
    err = RuntimeError("Hilfe: https://example.com/path?token=secret another")
    text = scraper.no_sensitive_error(err)
    assert "token=secret" not in text
    assert "<URL>" in text

class FakeResponse:
    def __init__(self, url: str, payload: dict, status=200, content_type="application/json"):
        self.url = url
        self._payload = payload
        self.status = status
        self.headers = {"content-type": content_type}

    def json(self):
        return self._payload


def test_response_observer_reads_only_warning_section():
    capture = scraper.WarningCapture()
    root = "https://api.diagviewer.prod.gspp-eu.cloud.corpintra.net"
    capture.observe(FakeResponse(root + "/view/section?section=quicktests", {"data": []}))
    assert capture.messages is None
    assert capture.empty_verified is False
    capture.observe(FakeResponse(root + "/view/section?section=warningEventMessages", {
        "type": "data", "data": {"warningEventMessages": [{"warn_hil_id": "synthetic"}]}
    }))
    assert capture.messages == [{"warn_hil_id": "synthetic"}]
    assert capture.empty_verified is False


def test_empty_warning_section_requires_explicit_api_proof():
    root = "https://api.diagviewer.prod.gspp-eu.cloud.corpintra.net"
    capture = scraper.WarningCapture()
    capture.observe(FakeResponse(root + "/view/section?section=warningEventMessages", {
        "type": "data", "data": {"warningEventMessages": []}
    }))
    assert capture.messages == []
    assert capture.empty_verified is True
    another = scraper.WarningCapture()
    another.observe(FakeResponse(root + "/view", {
        "type": "sectioned", "sections": ["quicktests", "ecuProtocols"]
    }))
    assert another.empty_verified is True
    assert another.messages is None
    missing = scraper.WarningCapture()
    missing.observe(FakeResponse(root + "/view", {"type": "sectioned", "sections": ["warningEventMessages"]}))
    assert missing.empty_verified is False


def test_output_never_contains_session_link_or_s3_path(monkeypatch, tmp_path):
    ctx = FakeContext()
    monkeypatch.setitem(sys.modules, "playwright.sync_api", SimpleNamespace(
        sync_playwright=lambda: FakePlaywright(ctx)
    ))
    output = tmp_path / "warnings.json"
    url = view_url(FIN1)
    session = {"href": url, "quelle": "XD", "diagnosezeitpunkt": "2026-01-01", "fin": FIN1}
    runner = scraper.DiagnosisViewerScraper(output, tmp_path / "edge", pacing=0)
    monkeypatch.setattr(runner, "_search", lambda context, page, fin: (page, [session]))
    monkeypatch.setattr(runner, "_read_session", lambda context, href: ([{"kennung": "synthetic"}], "datenstruktur"))
    assert runner.run([FIN1], scraper.fresh_state(), refresh=False, redo=False) == 0
    content = output.read_text(encoding="utf-8")
    assert '"href"' not in content
    assert "freigegebene-synthetische-testdaten" not in content
    assert "synthetic" in content


def test_tresor_wird_automatisch_gelesen_ohne_passwort_prompt(monkeypatch, tmp_path):
    state = tmp_path / 'out.json'
    fins = tmp_path / 'fins.txt'
    fins.write_text(FIN1, encoding='utf-8')
    monkeypatch.setattr(scraper, '_load_keyring_credentials', lambda: ('gespeicherte-id', 'passwort-test'))
    monkeypatch.setattr(scraper.getpass, 'getpass', lambda *args: pytest.fail('Unnoetiger Prompt'))
    monkeypatch.setattr('builtins.input', lambda *args: pytest.fail('Unnoetiger Prompt'))
    called = []

    def only_check(self, values, payload, **kwargs):
        called.append((self.user_id, self.password, values, kwargs))
        return 0

    monkeypatch.setattr(scraper.DiagnosisViewerScraper, 'run', only_check)
    assert scraper.main(['--eingabe', str(fins), '--ausgabe', str(state)]) == 0
    assert called[0][0:3] == ('gespeicherte-id', 'passwort-test', [FIN1])


def test_fehlender_tresor_und_manuell_schliessen_nicht_aus(monkeypatch):
    monkeypatch.setattr(scraper, '_load_keyring_credentials', lambda: None)
    recorded = []
    monkeypatch.setattr(scraper.DiagnosisViewerScraper, 'run',
                        lambda self, values, payload, **kwargs: recorded.append(
                            (self.user_id, self.password, values, kwargs)) or 0)
    assert scraper.main(['--nur-login']) == 0
    assert recorded[0][0:3] == ('', '', [])
    assert recorded[0][3]['login_only'] is True
    assert scraper.main(['--nur-login', '--sso-tresor']) == 2


def test_login_manuell_laesst_tresor_und_export_unberuehrt(monkeypatch, tmp_path):
    output = tmp_path / 'beschuetzter_stand.json'
    output.write_text('{kaputte-ausgabe}', encoding='utf-8')
    monkeypatch.setattr(scraper, '_load_keyring_credentials',
                        lambda: pytest.fail('Tresor darf nicht gelesen werden'))
    called = []
    monkeypatch.setattr(scraper.DiagnosisViewerScraper, 'run',
                        lambda self, values, payload, **kwargs: called.append(kwargs) or 0)
    assert scraper.main(['--nur-login', '--login-manuell', '--ausgabe', str(output)]) == 0
    assert output.read_text(encoding='utf-8') == '{kaputte-ausgabe}'
    assert called[0]['login_only'] is True


def test_login_only_oeffnet_edge_und_erzeugt_keine_json_datei(monkeypatch, tmp_path):
    class LoginProbePage:
        def __init__(self):
            self.gotos = []
        def goto(self, url, **kwargs):
            self.gotos.append(url)
    page = LoginProbePage()
    context = FakeContext()
    context.pages = [page]
    monkeypatch.setitem(sys.modules, 'playwright.sync_api', SimpleNamespace(
        sync_playwright=lambda: FakePlaywright(context)
    ))
    runner = scraper.DiagnosisViewerScraper(
        tmp_path / 'niemals-schreiben.json', tmp_path / 'profile', pacing=0
    )
    monkeypatch.setattr(runner, '_login', lambda ctx: page)
    assert runner.run([], scraper.fresh_state(), refresh=False, redo=False,
                      login_only=True) == 0
    assert page.gotos == [scraper.SEARCH_URL]
    assert not runner.output.exists()
    assert context.closed


def test_unknown_api_payload_keine_erfundenen_leeren_meldungen():
    root = 'https://api.diagviewer.prod.gspp-eu.cloud.corpintra.net/view'
    watcher = scraper.WarningCapture()
    watcher.observe(FakeResponse(root, {'type':'url', 'downloadUrl':'https://example.invalid'}))
    assert watcher.messages is None
    assert watcher.empty_verified is False