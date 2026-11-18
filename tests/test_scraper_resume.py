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


def test_qec_kurzfin_resume_nutzt_ausschliesslich_bestaetigten_vollvin_ordner(tmp_path):
    """Dieselbe 14-stellige Suche startet keinen Browser und keinen Kurz-FIN-Ordner."""
    kurz = FIN[3:]
    target = QecTarget(kurz)
    dl = QecDownloader(
        tmp_path, tmp_path / "profil", benennung="DCDC",
        attachment_policy="alle", resume=True,
    )
    folder = case_folder(tmp_path, FIN, REF)
    folder.mkdir(parents=True)
    anhang = folder / "anhaenge" / "313_beleg.pdf"
    anhang.parent.mkdir()
    anhang.write_bytes(b"%PDF-1.7\nTest")
    report = folder / "qec.json"
    report.write_text(json.dumps({
        "fin": FIN, "referenznummer": REF, "anhang_downloadmodus": "alle",
        "benennung_suchfilter": "DCDC", "vollstaendige_reiter": True,
        "abschnitte": [{"bereich": name} for name in QEC_SECTIONS],
        "anhaenge": [{"anhang_id": "313", "datei": anhang.name, "status": "Gespeichert"}],
        "hinweise": [], "fehler": [],
    }), encoding="utf-8")
    _write_result(tmp_path / FIN, QecResult(
        fin=FIN, such_fin=kurz, status="Erfolgreich", references=[REF],
        files=[anhang], snapshots=[report],
        attempted_at="2026-11-18T10:00:00+00:00",
        abruf_parameter=dl._abruf_parameter(target),
    ))
    assert not (tmp_path / kurz).exists()
    meldungen = []
    results = dl.run([target], progress=meldungen.append)
    assert [x.fin for x in results] == [FIN]
    assert "FIN 1/1 bereits erledigt (Resume)." in meldungen
    assert not (tmp_path / kurz).exists()
    assert (tmp_path / FIN / "abrufstatus.json").is_file()


def test_qec_kurzfin_resume_verweigert_mehrdeutige_vin_ordner(tmp_path):
    kurz = FIN[3:]
    ziel = QecTarget(kurz)
    dl = QecDownloader(
        tmp_path, tmp_path / "profil", benennung="DCDC",
        attachment_policy="alle", resume=True,
    )
    for wmi in ("WDD", "WDC"):
        (tmp_path / (wmi + kurz)).mkdir()
        (tmp_path / (wmi + kurz) / "abrufstatus.json").write_text(
            json.dumps({
                "fin": wmi + kurz, "such_fin": kurz, "status": "Erfolgreich",
                "abruf_parameter": dl._abruf_parameter(ziel), "referenzen": [REF],
            }), encoding="utf-8",
        )
    assert dl._fertiges_ziel(ziel) is None


def _alter_qec_kurzfin_checkpoint(tmp_path, *, status="Erfolgreich", benennung="DCDC"):
    """Reales altes Layout synthetisch: Status unter 14er, Belege unter 17er."""
    kurz = FIN[3:]
    root = tmp_path / FIN / f"ref_{REF}"
    root.mkdir(parents=True)
    pdf = root / "anhaenge" / "313_lieferantenbeleg.pdf"
    pdf.parent.mkdir()
    pdf.write_bytes(b"%PDF-1.7\nTest")
    report = root / "qec.json"
    report.write_text(json.dumps({
        "fin": FIN, "such_fin": kurz, "referenznummer": REF,
        "benennung_suchfilter": benennung, "anhang_downloadmodus": "alle",
        "vollstaendige_reiter": True,
        "abschnitte": [{"bereich": name} for name in QEC_SECTIONS],
        "anhaenge": [{"datei": pdf.name, "status": "Gespeichert"}],
        "hinweise": [], "fehler": [],
    }), encoding="utf-8")
    downloader = QecDownloader(
        tmp_path, tmp_path / "profil", benennung="DCDC",
        attachment_policy="alle", resume=True,
    )
    alt = tmp_path / kurz
    alt.mkdir()
    alt_manifest = alt / "abrufstatus.json"
    alt_manifest.write_text(json.dumps({
        "fin": kurz, "pfade_relativ_zu": "qec_basisordner",
        "bestaetigte_voll_fins": [FIN], "status": status,
        "referenzen": [REF],
        "anhaenge": [pdf.relative_to(tmp_path).as_posix()],
        "seiten": [report.relative_to(tmp_path).as_posix()],
        "stand_utc": "2026-11-18T10:00:00+00:00",
        "hinweise": [], "fehler": [],
        "abruf_parameter": downloader._abruf_parameter(QecTarget(kurz)),
    }), encoding="utf-8")
    return downloader, kurz, alt_manifest, report, pdf


def test_qec_resume_altes_14er_layout_sicher_uebernehmen_ohne_browser(tmp_path):
    """Alte Statusdatei bleibt 1:1 erhalten; neues Voll-VIN-Manifest wird angelegt."""
    downloader, kurz, alt_manifest, report, pdf = _alter_qec_kurzfin_checkpoint(tmp_path)
    vorher = alt_manifest.read_bytes()
    status = []
    result = downloader.run([QecTarget(kurz)], progress=status.append)
    assert len(result) == 1
    assert result[0].fin == FIN
    assert result[0].such_fin == kurz
    assert result[0].snapshots == [report]
    assert result[0].files == [pdf]
    assert "FIN 1/1 bereits erledigt (Resume)." in status
    assert alt_manifest.read_bytes() == vorher
    voll_status = tmp_path / FIN / "abrufstatus.json"
    checkpoint = json.loads(voll_status.read_text(encoding="utf-8"))
    assert checkpoint["fin"] == FIN
    assert checkpoint["such_fin"] == kurz
    assert checkpoint["seiten"] == [f"ref_{REF}/qec.json"]
    # Der alte Ordner ist ein unveraenderter Altbestand, keine Neuanlage.
    assert (tmp_path / kurz).is_dir() and (tmp_path / FIN).is_dir()
    assert (tmp_path / kurz / "abrufstatus.json").read_bytes() == vorher


def test_qec_legacy_resume_wird_bei_teilfertiger_datei_nicht_uebersprungen(tmp_path):
    dl, kurz, old, report, pdf = _alter_qec_kurzfin_checkpoint(tmp_path)
    alt = old.read_bytes()
    pdf.unlink()
    assert dl._fertiges_ziel(QecTarget(kurz)) is None
    assert old.read_bytes() == alt
    assert not (tmp_path / FIN / "abrufstatus.json").exists()


def test_qec_legacy_resume_passt_nicht_zu_neuem_anhangmodus(tmp_path):
    dl, kurz, old, _report, _pdf = _alter_qec_kurzfin_checkpoint(tmp_path)
    dl.attachment_policy = "referenz"
    assert dl._fertiges_ziel(QecTarget(kurz)) is None
    assert old.is_file()
    assert not (tmp_path / FIN / "abrufstatus.json").exists()


def test_qec_legacy_resume_darf_vorhandenen_vollvin_checkpoint_nicht_ueberschreiben(
    tmp_path,
):
    dl, kurz, old, _report, _pdf = _alter_qec_kurzfin_checkpoint(tmp_path)
    aktuell = tmp_path / FIN / "abrufstatus.json"
    aktuell.write_text('{"fin":"ANDERE DATEN","status":"Fehler"}', encoding="utf-8")
    before = aktuell.read_bytes()
    assert dl._fertiges_ziel(QecTarget(kurz)) is not None
    assert aktuell.read_bytes() == before
    assert old.is_file()


def test_qec_legacy_resume_verweigert_mehrdeutige_vin_funde(tmp_path):
    dl, kurz, old, _report, _pdf = _alter_qec_kurzfin_checkpoint(tmp_path)
    (tmp_path / ("WDC" + kurz)).mkdir()
    assert dl._fertiges_ziel(QecTarget(kurz)) is None
    assert old.is_file()
