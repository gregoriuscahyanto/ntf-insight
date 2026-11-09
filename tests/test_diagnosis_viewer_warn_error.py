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
        {"href": view_url(FIN1, "first.xml.json.gz"), "quelle": "XD", "diagnosezeitpunkt": "2026-01-01", "fin": FIN1, "laufleistung": "120 km"},
        {"href": view_url(FIN1, "second.xml.json.gz"), "quelle": "XD", "diagnosezeitpunkt": "2026-01-02", "fin": FIN1, "laufleistung": "120 km"},
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
    assert another.empty_verified is False
    assert another.section_missing_verified is True
    assert another.messages is None
    missing = scraper.WarningCapture()
    missing.observe(FakeResponse(root + "/view", {"type": "sectioned", "sections": ["warningEventMessages"]}))
    assert missing.empty_verified is False
    assert missing.section_missing_verified is False
    unknown_section_format = scraper.WarningCapture()
    unknown_section_format.observe(FakeResponse(root + '/view', {
        'type': 'sectioned', 'sections': [{'name': 'warningEventMessages'}]
    }))
    assert unknown_section_format.section_missing_verified is False


def test_output_never_contains_session_link_or_s3_path(monkeypatch, tmp_path):
    ctx = FakeContext()
    monkeypatch.setitem(sys.modules, "playwright.sync_api", SimpleNamespace(
        sync_playwright=lambda: FakePlaywright(ctx)
    ))
    output = tmp_path / "warnings.json"
    url = view_url(FIN1)
    session = {"href": url, "quelle": "XD", "diagnosezeitpunkt": "2026-01-01", "fin": FIN1, "laufleistung": "120 km"}
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


def test_standardstart_ohne_kuenstlichen_aktionsabstand(tmp_path):
    args = scraper.build_parser().parse_args(["--eingabe", "liste.txt"])
    assert args.abstand == 0.0
    assert args.sitzungs_timeout == 5
    assert scraper.DiagnosisViewerScraper(tmp_path / "ergebnis.json", tmp_path / "profil").taktung.interval == 0
    assert scraper.build_parser().parse_args(["--abstand", "0"]).abstand == 0


def test_restzeit_anzeige_verwendet_beobachtete_sitzungszeiten(monkeypatch):
    jetzt = [100.0]
    monkeypatch.setattr(scraper.time, "monotonic", lambda: jetzt[0])
    eta = scraper.Restzeit(3)
    assert "wird ermittelt" in eta.text()
    jetzt[0] = 104.0
    eta.suche_fertig(4.0, 2)
    assert "wird ermittelt" in eta.text()
    jetzt[0] = 110.0
    eta.sitzung_fertig(6.0)
    # 1 Sitzung bei aktueller FIN, 2 FINs noch nicht durchsucht:
    # 1*6 + 2*(4 + 2*6) = 38 Sekunden.
    assert "Restzeit grob ca. 00:38" in eta.text()
    eta.sitzung_fertig(None)  # Uebersprungene bereits gespeicherte Sitzung: keine 0-Sekunden-Probe
    assert "Restzeit grob ca. 00:32" in eta.text()
    eta.fin_fertig()
    assert "Restzeit grob ca. 00:32" in eta.text()


class FakeMissingPage:
    """Offline-Browserdouble: Diagnoseinformationen sind da, Warnungssektion fehlt."""

    def __init__(self, *, ready=True, emit_missing_metadata=False, clock=None):
        self.ready = ready
        self.emit_missing_metadata = emit_missing_metadata
        self.clock = clock
        self.listeners = {}
        self.waits = 0
        self.closed = False
        self.goto_urls = []

    def on(self, name, callback):
        self.listeners[name] = callback

    def remove_listener(self, name, callback):
        assert self.listeners[name] == callback
        del self.listeners[name]

    def goto(self, url, **kwargs):
        self.goto_urls.append(url)
        if self.emit_missing_metadata:
            self.listeners['response'](FakeResponse(
                scraper.SEARCH_URL.replace('app.', 'api.').replace('/search', '/view'),
                {'type': 'sectioned', 'sections': ['quicktests', 'ecuProtocols']}
            ))

    def get_by_role(self, *args, **kwargs):
        return SimpleNamespace(count=lambda: 0)

    def evaluate(self, script, *args):
        assert "accordion" in script
        return {"ready": self.ready, "warning": False, "busy": False,
                "signature": "Diagnosis Session Info: Test|Quick Test(s): 2" if self.ready else ""}

    def wait_for_timeout(self, ms):
        self.waits += 1
        if self.clock is not None:
            self.clock[0] += ms / 1000

    def close(self):
        self.closed = True


class FakeSessionContext:
    def __init__(self, page):
        self.page = page

    def new_page(self):
        return self.page


def test_fehlender_abschnitt_wird_schnell_uebersprungen(monkeypatch, tmp_path):
    clock = [100.0]
    monkeypatch.setattr(scraper.time, 'monotonic', lambda: clock[0])
    page = FakeMissingPage(clock=clock)
    runner = scraper.DiagnosisViewerScraper(tmp_path / 'ausgabe.json', tmp_path / 'profil',
                                            pacing=0, session_timeout=25, missing_section_grace=1.25)
    monkeypatch.setattr(runner, '_read_api_section',
                        lambda *args: pytest.fail('Bei bestaetigt fehlendem Abschnitt keine API-Anfrage'))
    rows, method = runner._read_session(FakeSessionContext(page), view_url(FIN1))
    assert rows == [] and method == 'abschnitt_fehlt'
    assert clock[0] - 100 < 2.0  # Kein 25-/70-Sekunden-Timeout
    assert page.closed and not page.listeners
    assert page.waits > 0


def test_api_belegt_nicht_vorhandenen_abschnitt_ohne_warten(monkeypatch, tmp_path):
    clock = [0.0]
    monkeypatch.setattr(scraper.time, 'monotonic', lambda: clock[0])
    page = FakeMissingPage(ready=False, emit_missing_metadata=True, clock=clock)
    runner = scraper.DiagnosisViewerScraper(tmp_path / 'ausgabe.json', tmp_path / 'profil', pacing=0)
    assert runner._read_session(FakeSessionContext(page), view_url(FIN1)) == ([], 'abschnitt_fehlt')
    assert page.waits == 0


def test_unfertige_ansicht_nicht_faelschlich_als_fehlen_klassifizieren(monkeypatch, tmp_path):
    clock = [0.0]
    monkeypatch.setattr(scraper.time, 'monotonic', lambda: clock[0])
    page = FakeMissingPage(ready=False, clock=clock)
    runner = scraper.DiagnosisViewerScraper(tmp_path / 'ausgabe.json', tmp_path / 'profil',
                                            pacing=0, session_timeout=3)
    with pytest.raises(TimeoutError, match='nicht vollstaendig geladen'):
        runner._read_session(FakeSessionContext(page), view_url(FIN1))
    assert clock[0] >= 3
    assert page.closed


def test_abschnitt_fehlt_hat_eigenen_resume_status_und_keine_falsche_nullzahl(monkeypatch, tmp_path):
    context = FakeContext()
    monkeypatch.setitem(sys.modules, 'playwright.sync_api', SimpleNamespace(
        sync_playwright=lambda: FakePlaywright(context)))
    output = tmp_path / 'ergebnis.json'
    runner = scraper.DiagnosisViewerScraper(output, tmp_path / 'profil', pacing=0)
    sessions = [{"href": view_url(FIN1), "quelle": "XD", "diagnosezeitpunkt": "2026-01-01", "fin": FIN1, "laufleistung": "120 km"}]
    monkeypatch.setattr(runner, '_search', lambda ctx, page, fin: (page, sessions))
    monkeypatch.setattr(runner, '_read_session', lambda ctx, href: ([], 'abschnitt_fehlt'))
    messages = []
    monkeypatch.setattr(runner, 'log', messages.append)
    assert runner.run([FIN1], scraper.fresh_state(), refresh=False, redo=False) == 0
    state = scraper.load_state(output)
    assert state['fahrzeuge'][FIN1]['status'] == 'abgeschlossen'
    session = next(iter(state['fahrzeuge'][FIN1]['sitzungen'].values()))
    assert session['status'] == 'abschnitt_fehlt'
    assert session['anzahl_meldungen'] is None
    assert session['hinweis'] and session['meldungen'] == []
    assert any('Restzeit' in msg for msg in messages)
    assert any('Sitzung 1/1' in msg for msg in messages)
    assert runner.run([FIN1], state, refresh=False, redo=False) == 0


def test_api_aufruf_hat_festes_abort_timeout(tmp_path):
    class BrowserPage:
        def evaluate(self, code, args):
            assert 'AbortController' in code
            assert 'timeout_ms' in code
            assert args == {'filename': 'beispiel.json.gz', 'timeout_ms': 4000}
            return None
    runner = scraper.DiagnosisViewerScraper(tmp_path / 'ausgabe.json', tmp_path / 'profil')
    assert runner._read_api_section(BrowserPage(), view_url(FIN1)) is None


def test_api_timeout_begrenzt_durch_restliches_sitzungsbudget(monkeypatch, tmp_path):
    monkeypatch.setattr(scraper.time, "monotonic", lambda: 100.0)
    timeouts = []

    class BrowserPage:
        def evaluate(self, code, args):
            timeouts.append(args["timeout_ms"])
            return None

    runner = scraper.DiagnosisViewerScraper(tmp_path / "out.json", tmp_path / "profil")
    assert runner._read_api_section(BrowserPage(), view_url(FIN1), deadline=100.7) is None
    assert 0 < timeouts[0] <= 700
    with pytest.raises(TimeoutError, match="Sitzungs-Timeout"):
        runner._read_api_section(BrowserPage(), view_url(FIN1), deadline=100.0)

# Einzeldateien und Resume: synthetische Beispieldaten, niemals echte FINs.
def _entry(title: str, status: str = 'erfolgreich') -> dict:
    return {'quelle': 'XD', 'status': status, 'meldungen': [{'kennung': title}],
            'anzahl_meldungen': 1, 'abgerufen_utc': '2026-01-01T00:00:00+00:00'}


def test_alte_gesamt_json_wird_verlustfrei_in_einzel_json_uebernommen(tmp_path):
    output = tmp_path / 'warnings_errors.json'
    keys = [scraper.session_key(view_url(FIN1, f'{i}.json.gz')) for i in range(3)]
    initial = scraper.fresh_state()
    initial['fahrzeuge'][FIN1] = {
        'status': 'teilweise', 'suchfehler': None,
        'sitzungen': {key: _entry(f'meldung-{index}') for index, key in enumerate(keys)},
    }
    scraper.save_state(output, initial)
    old_bytes = output.read_bytes()
    store = scraper.SitzungsSpeicher(output)
    store.bestand_uebernehmen(scraper.load_state(output))
    assert output.read_bytes() == old_bytes  # Original niemals bei der Migration antasten
    shard_dir = scraper.teile_verzeichnis(output) / FIN1
    assert (shard_dir / '_status.json').exists()
    assert len(list((shard_dir / 'sitzungen').glob('*.json'))) == 3
    assert scraper.load_state(output)['fahrzeuge'][FIN1]['sitzungen'] == initial['fahrzeuge'][FIN1]['sitzungen']
    assert not list(shard_dir.rglob('*.tmp'))


def test_teil_json_hat_vorrang_und_migration_ueberschreibt_nichts(tmp_path):
    output = tmp_path / 'messages.json'
    key = scraper.session_key(view_url(FIN1))
    initial = scraper.fresh_state()
    initial['fahrzeuge'][FIN1] = {'status': 'abgeschlossen', 'sitzungen': {key: _entry('alt')}}
    scraper.save_state(output, initial)
    store = scraper.SitzungsSpeicher(output)
    store.bestand_uebernehmen(scraper.load_state(output))
    newer = _entry('neuer Stand')
    store.sitzung_speichern(FIN1, key, newer)
    store.fahrzeug_speichern(FIN1, {'status': 'in_bearbeitung', 'sitzungen': {key: newer}})
    store.bestand_uebernehmen(scraper.load_state(output))  # Zweiter Start
    result = scraper.load_state(output)
    assert result['fahrzeuge'][FIN1]['status'] == 'in_bearbeitung'
    assert result['fahrzeuge'][FIN1]['sitzungen'][key] == newer
    assert json.loads(output.read_text())['fahrzeuge'][FIN1]['sitzungen'][key]['meldungen'][0]['kennung'] == 'alt'


def test_abbruch_nach_sitzungs_json_vor_status_checkpoint_ist_resumierbar(tmp_path):
    output = tmp_path / 'ausgabe.json'
    key = scraper.session_key(view_url(FIN1))
    old = scraper.fresh_state()
    old['fahrzeuge'][FIN1] = {'status': 'abgeschlossen', 'sitzungen': {}}
    scraper.save_state(output, old)
    store = scraper.SitzungsSpeicher(output)
    store.bestand_uebernehmen(scraper.load_state(output))
    # Der Prozess wird hart beendet, nachdem die Sitzungsdatei gespeichert ist,
    # aber bevor der FIN-Metadatenstatus aktualisiert werden konnte.
    store.sitzung_speichern(FIN1, key, _entry('gerettet', status='fehler'))
    result = scraper.load_state(output)
    assert result['fahrzeuge'][FIN1]['status'] == 'teilweise'
    assert result['fahrzeuge'][FIN1]['sitzungen'][key]['status'] == 'fehler'
    # Ein vollendeter Checkpoint hingegen wird beim Resume uebersprungen.
    store.sitzung_speichern(FIN1, key, _entry('gerettet'))
    result = scraper.load_state(output)
    assert result['fahrzeuge'][FIN1]['sitzungen'][key]['status'] in scraper.ENDED


def test_unvollstaendige_migration_kann_idempotent_fortgesetzt_werden(tmp_path):
    output = tmp_path / 'ausgabe.json'
    keys = [scraper.session_key(view_url(FIN1, f'{i}.json.gz')) for i in range(2)]
    initial = scraper.fresh_state()
    initial['fahrzeuge'][FIN1] = {'status': 'teilweise', 'sitzungen': {
        keys[0]: _entry('original-0'), keys[1]: _entry('original-1')}}
    scraper.save_state(output, initial)
    store = scraper.SitzungsSpeicher(output)
    store.sitzung_speichern(FIN1, keys[0], _entry('neuer-wert'))
    # Zweite Datei und Status fehlen - genau wie nach SIGKILL bei der Migration.
    store.bestand_uebernehmen(scraper.load_state(output))
    loaded = scraper.load_state(output)['fahrzeuge'][FIN1]
    assert loaded['status'] == 'teilweise'
    assert loaded['sitzungen'][keys[0]]['meldungen'][0]['kennung'] == 'neuer-wert'
    assert loaded['sitzungen'][keys[1]]['meldungen'][0]['kennung'] == 'original-1'


def test_sitzungen_schreiben_nicht_jedes_mal_gesamtdatei(monkeypatch, tmp_path):
    context = FakeContext()
    monkeypatch.setitem(sys.modules, 'playwright.sync_api', SimpleNamespace(
        sync_playwright=lambda: FakePlaywright(context)))
    output = tmp_path / 'warnungen.json'
    initial = scraper.fresh_state()
    initial['fahrzeuge'][FIN1] = {'status': 'teilweise', 'sitzungen': {}}
    scraper.save_state(output, initial)
    original_bytes = output.read_bytes()
    writes = []
    original_writer = scraper.save_state

    def counting_writer(path, state):
        writes.append(path)
        # Vor dem einzigen abschliessenden Gesamtexport bleibt das Original unveraendert.
        assert output.read_bytes() == original_bytes
        return original_writer(path, state)

    monkeypatch.setattr(scraper, 'save_state', counting_writer)
    runner = scraper.DiagnosisViewerScraper(output, tmp_path / 'browser', pacing=0)
    sessions = [{'href': view_url(FIN1, f'session-{i}.json.gz'), 'quelle': 'XD',
                 'diagnosezeitpunkt': f'2026-01-0{i+1}', 'fin': FIN1, 'laufleistung': '120 km'} for i in range(4)]
    monkeypatch.setattr(runner, '_search', lambda ctx, page, fin: (page, sessions))
    monkeypatch.setattr(runner, '_read_session', lambda ctx, href: ([{'kennung':'fake'}], 'datenstruktur'))
    assert runner.run([FIN1], scraper.load_state(output), refresh=False, redo=False) == 0
    assert writes == [output]  # Statt viele Voll-Rewrites nur EINER bei Abschluss
    assert len(list(scraper.teile_verzeichnis(output).glob(f'{FIN1}/sitzungen/*.json'))) == 4
    assert len(scraper.load_state(output)['fahrzeuge'][FIN1]['sitzungen']) == 4


def test_ohne_gesamtdatei_funktioniert_resume_ohne_legacy_datei(monkeypatch, tmp_path):
    context = FakeContext()
    monkeypatch.setitem(sys.modules, 'playwright.sync_api', SimpleNamespace(
        sync_playwright=lambda: FakePlaywright(context)))
    output = tmp_path / 'file.json'
    runner = scraper.DiagnosisViewerScraper(output, tmp_path / 'browser',
                                            gesamtdatei_am_ende=False)
    sessions = [{'href': view_url(FIN1, f'session-{i}.json.gz'), 'quelle': 'XD',
                 'diagnosezeitpunkt': f'2026-01-0{i+1}', 'fin': FIN1, 'laufleistung': '120 km'} for i in range(2)]
    monkeypatch.setattr(runner, '_search', lambda ctx, page, fin: (page, sessions))
    attempted = []

    def interrupt(ctx, href):
        attempted.append(href)
        if len(attempted) == 2:
            raise KeyboardInterrupt
        return ([{'kennung': 'synthetisch'}], 'datenstruktur')

    monkeypatch.setattr(runner, '_read_session', interrupt)
    with pytest.raises(KeyboardInterrupt):
        runner.run([FIN1], scraper.fresh_state(), refresh=False, redo=False)
    assert not output.exists()
    resumed_state = scraper.load_state(output)
    assert resumed_state['fahrzeuge'][FIN1]['status'] == 'unterbrochen'
    assert len(resumed_state['fahrzeuge'][FIN1]['sitzungen']) == 1
    runner2 = scraper.DiagnosisViewerScraper(output, tmp_path / 'browser', gesamtdatei_am_ende=False)
    monkeypatch.setattr(runner2, '_search', lambda ctx, page, fin: (page, sessions))
    remaining = []
    monkeypatch.setattr(runner2, '_read_session', lambda ctx, href: (remaining.append(href) or [], 'datenstruktur'))
    assert runner2.run([FIN1], resumed_state, refresh=False, redo=False) == 0
    assert remaining == [sessions[1]['href']]
    assert not output.exists()
    assert scraper.load_state(output)['fahrzeuge'][FIN1]['status'] == 'abgeschlossen'


def test_nur_zusammenfassen_offline_baut_alte_json_aus_teilen(monkeypatch, tmp_path):
    output = tmp_path / 'warnungen.json'
    key = scraper.session_key(view_url(FIN1))
    store = scraper.SitzungsSpeicher(output)
    store.sitzung_speichern(FIN1, key, _entry('synthetische Warnung'))
    store.fahrzeug_speichern(FIN1, {'status': 'abgeschlossen', 'sitzungen': {key: _entry('synthetische Warnung')}})
    monkeypatch.setattr(scraper, '_load_keyring_credentials',
                        lambda: pytest.fail('Offline-Zusammenfassen darf keinen SSO-Tresor verwenden'))
    assert scraper.main(['--nur-zusammenfassen', '--ausgabe', str(output)]) == 0
    assert output.exists()
    assert scraper.load_state(output)['fahrzeuge'][FIN1]['sitzungen'][key]['meldungen'][0]['kennung'] == 'synthetische Warnung'


def test_sitzungs_id_und_url_validieren_gegen_sensible_dateinamen(tmp_path):
    store = scraper.SitzungsSpeicher(tmp_path / 'ausgabe.json')
    with pytest.raises(ValueError, match='Sitzungs-ID'):
        store.sitzung_speichern(FIN1, '../unzulässig', _entry('test'))
    with pytest.raises(ValueError, match='Sitzungslinks'):
        store.sitzung_speichern(FIN1, scraper.session_key(view_url(FIN1)),
                                {'status': 'erfolgreich', 'href': view_url(FIN1)})


def test_nur_aufteilen_altbestand_offline_und_original_unveraendert(monkeypatch, tmp_path):
    output = tmp_path / 'warnungen.json'
    key = scraper.session_key(view_url(FIN1))
    initial = scraper.fresh_state()
    initial['fahrzeuge'][FIN1] = {'status': 'abgeschlossen', 'sitzungen': {key: _entry('alt')}}
    scraper.save_state(output, initial)
    alte_bytes = output.read_bytes()
    monkeypatch.setattr(scraper, '_load_keyring_credentials',
                        lambda: pytest.fail('Offline-Aufteilen darf keinen SSO-Tresor verwenden'))
    assert scraper.main(['--nur-aufteilen', '--ausgabe', str(output)]) == 0
    assert output.read_bytes() == alte_bytes
    assert (scraper.teile_verzeichnis(output) / FIN1 / 'sitzungen' / (key + '.json')).exists()
    # Idempotent, auch bei wiederholtem Start.
    assert scraper.main(['--nur-aufteilen', '--ausgabe', str(output)]) == 0
    assert output.read_bytes() == alte_bytes
    assert scraper.load_state(output)['fahrzeuge'][FIN1]['sitzungen'][key] == _entry('alt')



@pytest.mark.parametrize(
    ("session", "expected"),
    [
        ({"quelle": "AKT", "laufleistung": "2000 km"}, ["source_akt"]),
        ({"quelle": " akt ", "laufleistung": "0 km"}, ["source_akt"]),
        ({"quelle": "XD", "laufleistung": ""}, ["mileage_fehlt"]),
        ({"quelle": "TD", "laufleistung": None}, ["mileage_fehlt"]),
        ({"quelle": "XD", "laufleistung": "N/A"}, ["mileage_fehlt"]),
        ({"quelle": "DAS", "laufleistung": "—"}, ["mileage_fehlt"]),
        ({"quelle": "AKT", "laufleistung": ""}, ["source_akt", "mileage_fehlt"]),
        ({"quelle": "XD", "laufleistung": "0 km"}, []),
        ({"quelle": "TD", "laufleistung": "176.543 km"}, []),
    ],
)
def test_wem_ausschlussregel_source_akt_oder_mileage_fehlt(session, expected):
    assert scraper.ausschlussgruende(session) == expected


def test_wem_filter_schliesst_sitzungen_vor_browser_oeffnung_aus(monkeypatch, tmp_path):
    ctx = FakeContext()
    monkeypatch.setitem(sys.modules, 'playwright.sync_api', SimpleNamespace(
        sync_playwright=lambda: FakePlaywright(ctx)
    ))
    output = tmp_path / 'wem.json'
    sessions = [
        {'href': view_url(FIN1, 'gueltig.json.gz'), 'quelle': 'XD',
         'diagnosezeitpunkt': '2026-01-01', 'fin': FIN1, 'laufleistung': '100 km'},
        {'href': view_url(FIN1, 'akt.json.gz'), 'quelle': 'AKT',
         'diagnosezeitpunkt': '2026-01-02', 'fin': FIN1, 'laufleistung': '100 km'},
        {'href': view_url(FIN1, 'ohne-km.json.gz'), 'quelle': 'TD',
         'diagnosezeitpunkt': '2026-01-03', 'fin': FIN1, 'laufleistung': ''},
        {'href': view_url(FIN1, 'beides.json.gz'), 'quelle': 'AKT',
         'diagnosezeitpunkt': '2026-01-04', 'fin': FIN1, 'laufleistung': 'N/A'},
    ]
    runner = scraper.DiagnosisViewerScraper(output, tmp_path / 'profil')
    monkeypatch.setattr(runner, '_search', lambda ctx, page, fin: (page, sessions))
    opened = []
    def read_session(context, href):
        opened.append(href)
        return [{'kennung': 'synthetische Meldung'}], 'datenstruktur'
    monkeypatch.setattr(runner, '_read_session', read_session)

    assert runner.run([FIN1], scraper.fresh_state(), refresh=False, redo=False) == 0
    assert opened == [sessions[0]['href']]
    state = scraper.load_state(output)['fahrzeuge'][FIN1]
    assert state['status'] == 'abgeschlossen'
    assert state['anzahl_sitzungen_gefunden'] == 4
    records = state['sitzungen']
    assert len(records) == 4
    assert records[scraper.session_key(sessions[0]['href'])]['status'] == 'erfolgreich'
    for session in sessions[1:]:
        record = records[scraper.session_key(session['href'])]
        assert record['status'] == 'ausgeschlossen'
        assert record['ausschlussgruende'] == scraper.ausschlussgruende(session)
        assert record['anzahl_meldungen'] is None
        assert record['meldungen'] == []
        assert 'href' not in record
        assert record['hinweis']
    assert '"href"' not in output.read_text(encoding='utf-8')
    assert '"status": "keine_meldungen"' not in output.read_text(encoding='utf-8')

    opened.clear()
    assert runner.run([FIN1], scraper.load_state(output), refresh=True, redo=True) == 0
    assert opened == [sessions[0]['href']]  # Ausgeschlossene trotz --erneut nicht lesen


def test_gespeicherte_wem_bei_neuem_ausschluss_aufbewahren(monkeypatch, tmp_path):
    ctx = FakeContext()
    monkeypatch.setitem(sys.modules, 'playwright.sync_api', SimpleNamespace(
        sync_playwright=lambda: FakePlaywright(ctx)
    ))
    output = tmp_path / 'wem.json'
    href = view_url(FIN1)
    key = scraper.session_key(href)
    state = scraper.fresh_state()
    existing = {'status': 'erfolgreich', 'meldung': 'bestehender Datensatz',
                'anzahl_meldungen': 1, 'meldungen': [{'kennung': 'alt'}]}
    state['fahrzeuge'][FIN1] = {'status': 'abgeschlossen', 'sitzungen': {key: existing}}
    scraper.save_state(output, state)
    runner = scraper.DiagnosisViewerScraper(output, tmp_path / 'profil')
    monkeypatch.setattr(runner, '_search', lambda ctx, page, fin: (page, [
        {'href': href, 'quelle': 'AKT', 'fin': FIN1, 'laufleistung': ''}
    ]))
    monkeypatch.setattr(runner, '_read_session', lambda ctx, href:
                        pytest.fail('Archivierte WEM und ausgeschlossene Sitzungen nicht erneut lesen'))
    assert runner.run([FIN1], scraper.load_state(output), refresh=True, redo=True) == 0
    assert scraper.load_state(output)['fahrzeuge'][FIN1]['sitzungen'][key] == existing


def test_zuvor_ausgeschlossene_sitzung_bei_neuer_mileage_abrufen(monkeypatch, tmp_path):
    ctx = FakeContext()
    monkeypatch.setitem(sys.modules, 'playwright.sync_api', SimpleNamespace(
        sync_playwright=lambda: FakePlaywright(ctx)
    ))
    output = tmp_path / 'wem.json'
    href = view_url(FIN1)
    key = scraper.session_key(href)
    state = scraper.fresh_state()
    state['fahrzeuge'][FIN1] = {'status': 'abgeschlossen', 'sitzungen': {
        key: {'status': 'ausgeschlossen', 'ausschlussgruende': ['mileage_fehlt'],
              'anzahl_meldungen': None, 'meldungen': []}
    }}
    scraper.save_state(output, state)
    runner = scraper.DiagnosisViewerScraper(output, tmp_path / 'profil')
    monkeypatch.setattr(runner, '_search', lambda ctx, page, fin: (page, [
        {'href': href, 'quelle': 'XD', 'fin': FIN1,
         'diagnosezeitpunkt': '2026-01-01', 'laufleistung': '345 km'}
    ]))
    opened = []
    monkeypatch.setattr(runner, '_read_session', lambda ctx, href:
                        (opened.append(href) or [{'kennung': 'neu'}], 'datenstruktur'))
    assert runner.run([FIN1], scraper.load_state(output), refresh=True, redo=False) == 0
    assert opened == [href]
    record = scraper.load_state(output)['fahrzeuge'][FIN1]['sitzungen'][key]
    assert record['status'] == 'erfolgreich'
    assert record['meldungen'][0]['kennung'] == 'neu'
