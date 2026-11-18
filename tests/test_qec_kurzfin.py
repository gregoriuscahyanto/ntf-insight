"""Synthetische Tests fuer QEC-Kurz-FIN und sichere Voll-FIN-Zuordnung."""

import json
from threading import Event

import pytest

from ntf_insight.acquisition.qec_tool import (
    QecDownloader, QecResult, QecTarget, _qec_suchfelder, _write_result,
    inspect_search_results, parse_qec_targets, parse_search_hits,
    pruefe_kurzfin_treffer,
)


FULL = "WDD1671061B000001"
SHORT = FULL[3:]
OTHER_WMI = "WDC1671061B000001"


def _row(fin: str, ref: str, identifier: str) -> str:
    cells = [
        ref, "5", "A 999 999 99 99", "DCDC223", "MBC",
        fin[:3], fin[3:6], fin[6:9], fin[9:11], fin[-6:],
    ] + [""] * 29
    cells[0] = (
        '<a href="schadteilSelektieren.qec?schadteilID='
        + identifier + '">' + ref + "</a>"
    )
    return "<tr>" + "".join(f"<td>{value}</td>" for value in cells) + "</tr>"


def _document(*rows: str, total: int | None = None) -> str:
    total = len(rows) if total is None else total
    return (
        '<html><form><input name="_finBR" value="167">'
        '<input name="_finEndnummerFrom" value="000001"></form>'
        f'<div class="messageGreen">{total} Treffer</div><table>'
        + "".join(rows) + "</table></html>"
    )


def test_qec_14_fin_suchfelder_und_validierung():
    assert len(SHORT) == 14
    assert parse_qec_targets(SHORT) == [QecTarget(SHORT)]
    assert _qec_suchfelder(SHORT) == ("167", "000001")
    assert _qec_suchfelder(FULL) == ("167", "000001")
    with pytest.raises(ValueError):
        parse_qec_targets("WDD1061B000001")  # BR nicht numerisch
    with pytest.raises(ValueError):
        parse_qec_targets("1671061B00000A")  # Endnummer nicht numerisch


def test_qec_kurzfin_bestaetigt_nur_passende_vollfin():
    doc = _document(
        _row(FULL, "10001", "1001"),
        _row("WDD1671061B999999", "10002", "1002"),
    )
    target = QecTarget(SHORT)
    evidence = inspect_search_results(doc, target, pump_only=False)
    assert evidence["bestaetigt"] is True
    assert evidence["fin_identisch"] == 1
    assert parse_search_hits(doc, SHORT, pump_only=False)[0].fin == FULL
    pruefe_kurzfin_treffer(doc, target, evidence)


def test_qec_kurzfin_mehrdeutig_ohne_download():
    doc = _document(
        _row(FULL, "10001", "1001"),
        _row(OTHER_WMI, "10002", "1002"),
    )
    target = QecTarget(SHORT)
    evidence = inspect_search_results(doc, target, pump_only=False)
    with pytest.raises(ValueError, match="mehrdeutig"):
        pruefe_kurzfin_treffer(doc, target, evidence)


def test_qec_kurzfin_verlangt_vollstaendige_trefferliste():
    doc = _document(_row(FULL, "10001", "1001"), total=2)
    target = QecTarget(SHORT)
    evidence = inspect_search_results(doc, target, pump_only=False)
    with pytest.raises(ValueError, match="nicht vollstaendig"):
        pruefe_kurzfin_treffer(doc, target, evidence)


def test_qec_kurzfin_keine_treffer_sind_erlaubt():
    doc = _document(total=0)
    target = QecTarget(SHORT)
    evidence = inspect_search_results(doc, target, pump_only=False)
    assert evidence["bestaetigt"] is True
    pruefe_kurzfin_treffer(doc, target, evidence)


def test_qec_kurzfin_ambiguitaet_stoppt_vor_fallabruf(tmp_path):
    doc = _document(
        _row(FULL, "10001", "1001"),
        _row(OTHER_WMI, "10002", "1002"),
    )
    target = QecTarget(SHORT)
    evidence = inspect_search_results(doc, target, pump_only=False)
    downloader = QecDownloader(tmp_path, tmp_path / "profil")
    page = object()
    downloader._search = lambda *_args: (page, page, doc, evidence)
    result, _ = downloader._one_target(
        None, page, target, lambda _message: None, Event(),
    )
    assert result.status == "Ergebnispruefung erforderlich"
    assert not result.snapshots and not result.files


def test_qec_kurzfin_status_nur_im_bestaetigten_vollvin_ordner(tmp_path):
    report = tmp_path / FULL / "ref_10001" / "qec.json"
    report.parent.mkdir(parents=True)
    report.write_text("{}", encoding="utf-8")
    result = QecResult(FULL, status="Erfolgreich", snapshots=[report], such_fin=SHORT)
    _write_result(tmp_path / FULL, result)
    status = json.loads(
        (tmp_path / FULL / "abrufstatus.json").read_text(encoding="utf-8")
    )
    assert status["fin"] == FULL
    assert status["such_fin"] == SHORT
    assert status["bestaetigte_voll_fins"] == [FULL]
    assert status["seiten"] == ["ref_10001/qec.json"]
    assert status["pfade_relativ_zu"] == "fin_ordner"
    assert not (tmp_path / SHORT).exists()


def test_kurzfin_ohne_eindeutige_vollvin_schreibt_nur_suchstatus(tmp_path):
    result = QecResult(SHORT, status="Keine passenden Schadteile", such_fin=SHORT)
    _write_result(tmp_path / SHORT, result)
    status = json.loads(
        (tmp_path / f"qec_suchstatus_{SHORT}.json").read_text(encoding="utf-8")
    )
    assert status["fin"] == SHORT
    assert status["such_fin"] == SHORT
    assert status["bestaetigte_voll_fins"] == []
    assert not (tmp_path / SHORT).exists()


def test_kurzfin_suche_legt_bei_eindeutigem_treffer_nur_vollfin_ordner_an(tmp_path):
    doc = _document(_row(FULL, "10001", "1001"))
    target = QecTarget(SHORT)
    evidence = inspect_search_results(doc, target, pump_only=False)
    downloader = QecDownloader(
        tmp_path, tmp_path / "profil", benennung="DCDC", click_delay_seconds=0,
    )
    page = object()
    downloader._search = lambda *_args: (page, page, doc, evidence)

    def speichere_fall(_ctx, current, _target, hit, result, _progress,
                       _cancel, search_result=None):
        assert hit.fin == FULL
        assert search_result is not None
        path = tmp_path / hit.fin / f"ref_{hit.reference}" / "qec.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"fin": hit.fin, "referenznummer": hit.reference}),
                        encoding="utf-8")
        result.references.append(hit.reference)
        result.snapshots.append(path)
        return current

    downloader._one_hit = speichere_fall
    result, _ = downloader._one_target(
        None, page, target, lambda _message: None, Event(),
    )
    assert result.status == "Erfolgreich"
    assert result.fin == FULL
    assert result.such_fin == SHORT
    assert not (tmp_path / SHORT).exists()
    assert (tmp_path / FULL / "abrufstatus.json").is_file()
    assert sorted(p.name for p in tmp_path.iterdir() if p.is_dir()) == [FULL]


def test_kurzfin_ohne_treffer_legt_keinen_fahrzeugordner_an(tmp_path):
    doc = _document(total=0)
    target = QecTarget(SHORT)
    evidence = inspect_search_results(doc, target, pump_only=False)
    downloader = QecDownloader(tmp_path, tmp_path / "profil")
    page = object()
    downloader._search = lambda *_args: (page, page, doc, evidence)
    result, _ = downloader._one_target(
        None, page, target, lambda _message: None, Event(),
    )
    assert result.status == "Keine passenden Schadteile"
    assert result.fin == SHORT
    assert (tmp_path / f"qec_suchstatus_{SHORT}.json").is_file()
    assert not (tmp_path / SHORT).exists()
    assert not (tmp_path / FULL).exists()


def test_kurzfin_mehrdeutig_wird_niemals_automatisch_vollvin(tmp_path):
    doc = _document(
        _row(FULL, "10001", "1001"),
        _row(OTHER_WMI, "10002", "1002"),
    )
    target = QecTarget(SHORT)
    evidence = inspect_search_results(doc, target, pump_only=False)
    downloader = QecDownloader(tmp_path, tmp_path / "profil")
    page = object()
    downloader._search = lambda *_args: (page, page, doc, evidence)
    result, _ = downloader._one_target(
        None, page, target, lambda _message: None, Event(),
    )
    assert result.status == "Ergebnispruefung erforderlich"
    assert result.fin == SHORT
    assert (tmp_path / f"qec_suchstatus_{SHORT}.json").is_file()
    assert not (tmp_path / SHORT).exists()
    assert not (tmp_path / FULL).exists()
    assert not (tmp_path / OTHER_WMI).exists()


def test_kurzfin_mit_bestaetigter_vollvin_aber_ohne_pumpentreffer(tmp_path):
    doc = _document(_row(FULL, "10001", "1001"))
    target = QecTarget(SHORT)
    evidence = inspect_search_results(doc, target, pump_only=True)
    downloader = QecDownloader(tmp_path, tmp_path / "profil")  # Pumpenfilter
    page = object()
    downloader._search = lambda *_args: (page, page, doc, evidence)
    result, _ = downloader._one_target(
        None, page, target, lambda _message: None, Event(),
    )
    assert result.status == "Keine passenden Schadteile"
    assert result.fin == FULL
    assert (tmp_path / FULL / "abrufstatus.json").is_file()
    assert not (tmp_path / SHORT).exists()

