"""Offline-Faelle: Resume ohne Browser/SSO und Live-FIN-Zaehlung."""

from __future__ import annotations

import json
from pathlib import Path

from ntf_insight.acquisition.qec_archive import case_folder
from ntf_insight.acquisition.qec_tool import (
    QEC_SECTIONS, QecDownloader, QecResult, QecTarget, _write_result,
)
from ntf_insight.acquisition.tips_writer import TIPS_SECTIONS, TipsWriterDownloader
from scripts.vedoc_dcdc223_seriennummern import (
    Ergebnis, _lade_erfolgreiche_historie, _schreibe_json,
    _sichere_unlesbare_historie, main as historie_main,
)


FIN = "WDD12345678901234"
REF = "900000625"


def _qec_checkpoint(tmp_path: Path, *, mode: str = "alle"):
    target = QecTarget(FIN)
    dl = QecDownloader(
        tmp_path, tmp_path / "profil", benennung="DCDC",
        attachment_policy=mode, resume=True,
    )
    folder = case_folder(tmp_path, FIN, REF)
    folder.mkdir(parents=True)
    anhang = folder / "anhaenge" / "313_beleg.pdf"
    anhang.parent.mkdir()
    anhang.write_bytes(b"%PDF-1.7\nTest")
    report = folder / "qec.json"
    report.write_text(json.dumps({
        "fin": FIN, "referenznummer": REF, "anhang_downloadmodus": mode,
        "benennung_suchfilter": "DCDC", "vollstaendige_reiter": True,
        "abschnitte": [{"bereich": name} for name in QEC_SECTIONS],
        "anhaenge": [{"anhang_id": "313", "datei": anhang.name, "status": "Gespeichert"}],
        "hinweise": [], "fehler": [],
    }), encoding="utf-8")
    status = QecResult(
        fin=FIN, status="Erfolgreich", references=[REF],
        files=[anhang], snapshots=[report], attempted_at="2026-11-18T10:00:00+00:00",
        abruf_parameter=dl._abruf_parameter(target),
    )
    _write_result(tmp_path / FIN, status)
    return dl, target, report, anhang


def test_qec_resume_laedt_keinen_browser_wenn_fin_abgeschlossen(tmp_path):
    dl, target, report, anhang = _qec_checkpoint(tmp_path)
    meldungen = []
    result = dl.run([target], progress=meldungen.append)
    assert len(result) == 1
    assert result[0].snapshots == [report]
    assert result[0].files == [anhang]
    assert any("FIN 1/1 bereits erledigt" in m for m in meldungen)


def test_qec_resume_nicht_bei_anderem_anhangmodus_oder_fehlendem_dokument(tmp_path):
    dl, target, _report, anhang = _qec_checkpoint(tmp_path)
    assert dl._fertiges_ziel(target) is not None
    dl.attachment_policy = "referenz"
    assert dl._fertiges_ziel(target) is None
    dl.attachment_policy = "alle"
    anhang.unlink()
    assert dl._fertiges_ziel(target) is None


def test_qec_erneut_ueberspringt_keine_vollstaendigen_zielobjekte(tmp_path):
    dl, target, _report, _anhang = _qec_checkpoint(tmp_path)
    dl.resume = False
    assert dl._fertiges_ziel(target) is None


def test_tips_resume_kompletter_fall_ohne_browser(tmp_path):
    folder = tmp_path / FIN / "fall_12345678"
    folder.mkdir(parents=True)
    report = folder / "tips.json"
    report.write_text(json.dumps({
        "fin": FIN, "fallnummer": "12345678",
        "vollstaendige_reiter": True,
        "abschnitte": [{"bereich": name} for name in TIPS_SECTIONS],
        "dateien": [], "hinweise": [], "fehler": [],
    }), encoding="utf-8")
    status = tmp_path / FIN / "abrufstatus.json"
    status.write_text(json.dumps({
        "fin": FIN, "status": "Erfolgreich", "fallnummern": ["12345678"],
    }), encoding="utf-8")
    dl = TipsWriterDownloader(tmp_path, tmp_path / "profil", resume=True)
    assert dl._fertiges_ziel(FIN) is not None
    messages = []
    result = dl.run([FIN], progress=messages.append)
    assert result[0].reports == [report]
    assert "FIN 1/1 bereits erledigt (Resume)." in messages


def test_vedoc_historie_resume_nur_erfolgreiche_objektgleiche_fins(tmp_path):
    quelle = tmp_path / "dcdc223_seriennummern.json"
    data = [
        Ergebnis(FIN, "DCDC223", "SERIE-01", "gefunden", "", "2026-11-18T10:00:00Z"),
        Ergebnis("WDD12345678901235", "DCDC223", None, "zeitueberschreitung", "",
                "2026-11-18T10:01:00Z"),
    ]
    _schreibe_json(quelle, data)
    loaded = _lade_erfolgreiche_historie(
        quelle, [item.fin for item in data], objekt="DCDC223", attribut="Seriennummer",
    )
    assert list(loaded) == [FIN]
    assert loaded[FIN].seriennummer == "SERIE-01"


def test_vedoc_historie_komplettes_resume_ohne_browser(tmp_path):
    eingabe = tmp_path / "fin.txt"
    eingabe.write_text(FIN + "\n", encoding="utf-8")
    _schreibe_json(
        tmp_path / "dcdc223_seriennummern.json",
        [Ergebnis(FIN, "DCDC223", "S1", "gefunden", "", "2026-11-18T10:00:00Z")],
    )
    assert historie_main(["--eingabe", str(eingabe), "--ausgabe", str(tmp_path)]) == 0
    assert (tmp_path / "dcdc223_seriennummern.xlsx").is_file()


def test_vedoc_resume_bewahrt_unlesbare_vorherige_json(tmp_path):
    datei = tmp_path / "dcdc223_seriennummern.json"
    datei.write_bytes(b"altes-json")
    loaded = _lade_erfolgreiche_historie(
        datei, [FIN], objekt="DCDC223", attribut="Seriennummer",
    )
    assert loaded == {}
    assert datei.read_bytes() == b"altes-json"
    _sichere_unlesbare_historie(datei)
    backups = list(tmp_path.glob("dcdc223_seriennummern.unlesbar_*.bak"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == b"altes-json"
    assert datei.read_bytes() == b"altes-json"
