"""Synthetische Tests fuer den parallelen Prozess-Sammelabruf ohne Browser."""

from __future__ import annotations

import io
import subprocess
import threading
import time
from pathlib import Path

import pytest

from ntf_insight.acquisition import beschaffung_cli as cli

FIN = "WDD12345678901234"


def _eingabe(tmp_path: Path, name: str = "FIN-Liste DCDC223 SensorIssue.txt") -> Path:
    quelle = tmp_path / name
    quelle.write_text(FIN, encoding="utf-8")
    return quelle


def _popen_simulieren(monkeypatch, *, returncode=0):
    commands: list[tuple[list[str], dict]] = []
    laufend = 0
    gleichzeitig = 0
    sperre = threading.Lock()

    class Prozess:
        def __init__(self, befehl, **options):
            nonlocal laufend, gleichzeitig
            with sperre:
                commands.append((befehl, options))
                laufend += 1
                gleichzeitig = max(gleichzeitig, laufend)
            self.stdout = io.StringIO("Synthetischer Abruf abgeschlossen\n")
            self.returncode = returncode
            self.terminated = False

        def wait(self):
            nonlocal laufend
            time.sleep(0.035)
            with sperre:
                laufend -= 1
            return self.returncode

        def poll(self):
            return None if not self.terminated else 130

        def terminate(self):
            self.terminated = True

    monkeypatch.setattr(cli.subprocess, "Popen", Prozess)
    return commands, lambda: gleichzeitig


def test_sammelabruf_startet_alle_sechs_unabhaengig_parallel(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    commands, max_gleichzeitig = _popen_simulieren(monkeypatch)
    fin = _eingabe(tmp_path)
    assert cli.main(["--eingabe", str(fin), "--parallel", "3"]) == 0
    assert len(commands) == 6
    assert max_gleichzeitig() >= 2
    assert max_gleichzeitig() <= 3
    erwartete = {
        q: cli.ausgabe_in_gruppe(
            tmp_path / "data/processed/FIN-Liste DCDC223 SensorIssue", q,
        )
        for q in cli.quellennamen()
    }
    gefunden = {}
    for argv, options in commands:
        assert argv[0] == cli.sys.executable
        assert argv[1:3] == ["-u", "-c"]
        assert "--eingabe" in argv and "--ausgabe" in argv
        assert options["stdout"] == subprocess.PIPE
        assert options["stderr"] == subprocess.STDOUT
        assert options["env"]["PYTHONIOENCODING"] == "utf-8"
        assert options.get("shell") is not True
        quelle = next(
            q for q, (modul, funktion) in cli._EINSTIEGE.items()
            if f"from {modul} import {funktion}" in argv[3]
        )
        assert quelle not in gefunden
        gefunden[quelle] = Path(argv[argv.index("--ausgabe") + 1])
    assert gefunden == erwartete
    assert "[qec]" in capsys.readouterr().out


def test_subset_eigenes_verzeichnis_manuelles_login(tmp_path, monkeypatch):
    commands, max_gleichzeitig = _popen_simulieren(monkeypatch)
    root = tmp_path / "Benutzerwahl"
    assert cli.main([
        "--eingabe", str(_eingabe(tmp_path)), "--quellen", "qec,wem,tips",
        "--parallel", "2", "--ausgabe", str(root), "--login-manuell",
    ]) == 0
    assert len(commands) == 3
    assert 1 <= max_gleichzeitig() <= 2
    assert set(Path(argv[argv.index("--ausgabe") + 1]) for argv, _ in commands) == {
        root / "qec",
        root / "diagnosis_viewer_warn_error" / "warnings_errors.json",
        root / "tips_writer",
    }
    assert all(argv[-1] == "--login-manuell" for argv, _ in commands)


@pytest.mark.parametrize("extra", [
    ["--parallel", "0"],
    ["--parallel", "7"],
    ["--quellen", ""],
    ["--quellen", "quicktests,quicktests"],
    ["--quellen", "unbekannt"],
])
def test_ungueltige_argumente_starten_keinen_prozess(tmp_path, monkeypatch, extra):
    commands, _ = _popen_simulieren(monkeypatch)
    assert cli.main(["--eingabe", str(_eingabe(tmp_path)), *extra]) == 2
    assert commands == []


@pytest.mark.parametrize("dateiname,inhalt", [
    ("liste.csv", FIN),
    ("liste.txt", "WDD12345I78901234"),
    ("liste.txt", "# leer\n"),
])
def test_ungueltige_eingabe_verhindert_prozess(tmp_path, monkeypatch, dateiname, inhalt):
    commands, _ = _popen_simulieren(monkeypatch)
    fin = tmp_path / dateiname
    fin.write_text(inhalt, encoding="utf-8")
    assert cli.main(["--eingabe", str(fin)]) == 2
    assert not commands


def test_fehlendes_eingabefile_verhindert_prozess(tmp_path, monkeypatch):
    commands, _ = _popen_simulieren(monkeypatch)
    assert cli.main(["--eingabe", str(tmp_path / "fehlend.txt")]) == 2
    assert not commands


def test_eine_fehlgeschlagene_quelle_ergibt_exitcode_eins(tmp_path, monkeypatch):
    commands, _ = _popen_simulieren(monkeypatch, returncode=1)
    assert cli.main([
        "--eingabe", str(_eingabe(tmp_path)), "--quellen", "qec,tips",
    ]) == 1
    assert len(commands) == 2


def test_prozessstartfehler_wird_als_fehler_gemeldet(tmp_path, monkeypatch):
    def fehler(*args, **kwargs):
        raise OSError("synthetische Prozessstart-Sperre")
    monkeypatch.setattr(cli.subprocess, "Popen", fehler)
    assert cli.main([
        "--eingabe", str(_eingabe(tmp_path)), "--quellen", "qec",
    ]) == 1


def test_exitcode_null_bei_leeren_ergebnislisten_fehlt_nicht(tmp_path, monkeypatch):
    commands, _ = _popen_simulieren(monkeypatch)
    assert cli.main([
        "--eingabe", str(_eingabe(tmp_path)), "--quellen", "sa-codes",
        "--parallel", "6",
    ]) == 0
    assert len(commands) == 1


def test_uebergabepfade_mit_leerzeichen_ohne_shell(tmp_path, monkeypatch):
    commands, _ = _popen_simulieren(monkeypatch)
    ziel = tmp_path / "Ziel Ordner mit Leerzeichen"
    assert cli.main([
        "--eingabe", str(_eingabe(tmp_path)), "--ausgabe", str(ziel),
        "--quellen", "quicktests",
    ]) == 0
    assert commands[0][0][-1] == str(ziel / "diagnosis_viewer_quicktests")
    assert commands[0][0][-3] == str(_eingabe(tmp_path))


def test_genau_sechs_quellen_in_vordefinierter_reihenfolge():
    assert tuple(cli._EINSTIEGE) == cli.quellennamen()
    assert cli._quellen("alle") == list(cli.quellennamen())
    assert cli._quellen(" QEC , TIPS ") == ["qec", "tips"]



def test_freies_hardwareobjekt_nur_an_vedoc_weiterreichen(monkeypatch, tmp_path):
    commands, _ = _popen_simulieren(monkeypatch)
    root = tmp_path / "Ergebnisse"
    assert cli.main([
        "--eingabe", str(_eingabe(tmp_path)), "--ausgabe", str(root),
        "--quellen", "vedoc-historie,wem", "--parallel", "2",
        "--objekt", "CPC3", "--attribut", "Hardwarestand",
    ]) == 0
    assert len(commands) == 2
    ven = next(args for args, _ in commands if "vedoc_dcdc223_seriennummern" in args[3])
    wem = next(args for args, _ in commands if "diagnosis_viewer_warn_error" in args[3])
    assert ven[ven.index("--objekt") + 1] == "CPC3"
    assert ven[ven.index("--attribut") + 1] == "Hardwarestand"
    assert ven[ven.index("--ausgabe") + 1] == str(root / "vedoc_historie")
    assert "--objekt" not in wem and "--attribut" not in wem
    assert cli._quellen("vedoc-historie,wem") == ["dcdc223", "wem"]


def test_freie_vedoc_historie_bei_alle_ohne_andere_quellen_zu_aendern(monkeypatch, tmp_path):
    commands, _ = _popen_simulieren(monkeypatch)
    assert cli.main([
        "--eingabe", str(_eingabe(tmp_path)), "--quellen", "alle",
        "--objekt", "Pumpensteuergeraet",
    ]) == 0
    assert len(commands) == 6
    v = next(argv for argv, _ in commands if "vedoc_dcdc223_seriennummern" in argv[3])
    assert Path(v[v.index("--ausgabe") + 1]).name == "vedoc_historie"


def test_unzulaessige_doppelte_vedoc_aliasse_oder_andere_quellen(monkeypatch, tmp_path):
    commands, _ = _popen_simulieren(monkeypatch)
    fin = _eingabe(tmp_path)
    assert cli.main([
        "--eingabe", str(fin), "--quellen", "dcdc223,vedoc-historie",
    ]) == 2
    assert cli.main([
        "--eingabe", str(fin), "--quellen", "qec,tips", "--objekt", "CPC3",
    ]) == 2
    assert commands == []


def test_qec_sachnummer_und_anhangmodus_nur_an_qec_prozess(tmp_path, monkeypatch):
    cmds, _ = _popen_simulieren(monkeypatch)
    fin = _eingabe(tmp_path)
    assert cli.main([
        "--eingabe", str(fin),
        "--quellen", "qec,quicktests,wem", "--parallel", "3",
        "--sachnummer", "A 111 222 33 44", "--anhaenge", "alle",
    ]) == 0
    assert len(cmds) == 3
    qec = next(argv for argv, _ in cmds if "portal_cli" in argv[3])
    assert qec[qec.index("--sachnummer") + 1] == "A 111 222 33 44"
    assert qec[qec.index("--anhaenge") + 1] == "alle"
    for argv, _ in cmds:
        if argv is not qec:
            assert "--sachnummer" not in argv and "--anhaenge" not in argv


@pytest.mark.parametrize("extra", [
    ["--quellen", "wem,quicktests", "--sachnummer", "A 111 222 33 44"],
    ["--quellen", "wem", "--anhaenge", "alle"],
    ["--quellen", "qec", "--sachnummer", "INVALID/../"],
    ["--quellen", "qec", "--sachnummer", ""],
])
def test_batch_ungueltige_qec_parameter_starten_keinen_prozess(
    tmp_path, monkeypatch, extra,
):
    cmds, _ = _popen_simulieren(monkeypatch)
    assert cli.main(["--eingabe", str(_eingabe(tmp_path)), *extra]) == 2
    assert cmds == []

def test_kombinierter_hardware_und_qec_sammelabruf(tmp_path, monkeypatch):
    """VeDoc-Objekt und QEC-Sachnummer bleiben auch im selben Batch getrennt."""
    commands, _ = _popen_simulieren(monkeypatch)
    fin = _eingabe(tmp_path)
    assert cli.main([
        "--eingabe", str(fin),
        "--quellen", "vedoc-historie,qec,quicktests",
        "--objekt", "CPC3", "--attribut", "Hardwarestand",
        "--sachnummer", "A 111 222 33 44", "--anhaenge", "alle",
        "--parallel", "3",
    ]) == 0
    assert len(commands) == 3
    vedoc = next(args for args, _ in commands if "vedoc_dcdc223_seriennummern" in args[3])
    qec = next(args for args, _ in commands if "portal_cli" in args[3])
    quicktests = next(args for args, _ in commands if "diagnosis_viewer_cli" in args[3])
    assert vedoc[vedoc.index("--objekt") + 1] == "CPC3"
    assert vedoc[vedoc.index("--attribut") + 1] == "Hardwarestand"
    assert "--sachnummer" not in vedoc and "--anhaenge" not in vedoc
    assert qec[qec.index("--sachnummer") + 1] == "A 111 222 33 44"
    assert qec[qec.index("--anhaenge") + 1] == "alle"
    assert "--objekt" not in qec and "--attribut" not in qec
    assert "--objekt" not in quicktests and "--sachnummer" not in quicktests
    assert vedoc[vedoc.index("--ausgabe") + 1].endswith("vedoc_historie")
    assert qec[qec.index("--ausgabe") + 1].endswith("qec")



def test_batch_kurz_fin_ve_doc_und_quicktests_gleichzeitig(tmp_path, monkeypatch):
    """Regression: 14-stellige Kurz-FINs duerfen die zwei Quellen starten."""
    commands, zugleich = _popen_simulieren(monkeypatch)
    fin = tmp_path / "FIN-Liste DCDC223 SensorIssue.txt"
    fin.write_text(
        "1671061B000001\n1671061B000002\n1671061B000003\n",
        encoding="utf-8",
    )
    assert cli.main([
        "--eingabe", str(fin), "--quellen", "vedoc-historie,quicktests",
        "--objekt", "DCDC223", "--attribut", "Seriennummer",
        "--parallel", "2",
    ]) == 0
    assert len(commands) == 2
    assert 1 <= zugleich() <= 2
    assert all(str(fin) == argv[argv.index("--eingabe") + 1] for argv, _ in commands)
    zielordner = {
        Path(argv[argv.index("--ausgabe") + 1]).name for argv, _ in commands
    }
    assert zielordner == {"vedoc_historie", "diagnosis_viewer_quicktests"}


@pytest.mark.parametrize("quellen", [
    "alle", "qec,quicktests", "quicktests,wem", "sa-codes,vedoc-historie", "tips",
])
def test_batch_kurz_fin_unsupportierte_quellen_frueh_abweisen(
    tmp_path, monkeypatch, quellen, capsys,
):
    commands, _ = _popen_simulieren(monkeypatch)
    fin = tmp_path / "kurz.txt"
    fin.write_text("1671061B000001\n", encoding="utf-8")
    assert cli.main(["--eingabe", str(fin), "--quellen", quellen]) == 2
    assert not commands
    assert "14-stellige Kurz-FINs" in capsys.readouterr().err


def test_batch_gemischte_14_und_17stellige_fins_fuer_zwei_quellen(tmp_path, monkeypatch):
    commands, _ = _popen_simulieren(monkeypatch)
    fin = tmp_path / "gemischt.txt"
    fin.write_text("1671061B000001\nWDD12345678901234\n", encoding="utf-8")
    assert cli.main([
        "--eingabe", str(fin), "--quellen", "dcdc223,quicktests",
        "--parallel", "2",
    ]) == 0
    assert len(commands) == 2



def test_batch_sechs_parallel_mit_qec_keyword_nur_an_qec_prozess(tmp_path, monkeypatch):
    commands, gleichzeitig = _popen_simulieren(monkeypatch)
    fin = _eingabe(tmp_path)
    assert cli.main([
        "--eingabe", str(fin), "--quellen", "alle", "--parallel", "6",
        "--benennung", "DCDC", "--anhaenge", "alle",
    ]) == 0
    assert len(commands) == 6
    assert gleichzeitig() >= 2
    qec = next(cmd for cmd, _ in commands if "qec_main" in cmd[3])
    assert qec[qec.index("--benennung") + 1] == "DCDC"
    assert qec[qec.index("--anhaenge") + 1] == "alle"
    assert all("--benennung" not in cmd for cmd, _ in commands if cmd is not qec)


@pytest.mark.parametrize("more", [
    ["--quellen", "wem,quicktests", "--benennung", "DCDC"],
    ["--quellen", "qec", "--benennung", "X"],
    ["--quellen", "qec", "--benennung", "DCDC,"],
])
def test_batch_benennung_vor_prozessstart_validieren(tmp_path, monkeypatch, more):
    commands, _ = _popen_simulieren(monkeypatch)
    assert cli.main(["--eingabe", str(_eingabe(tmp_path)), *more]) == 2
    assert commands == []



def test_batch_nur_tips_erlaubt_fallnummern_als_haupteingabe(tmp_path, monkeypatch):
    calls, _ = _popen_simulieren(monkeypatch)
    case_txt = tmp_path / "TIPS-Fallnummern.txt"
    case_txt.write_text("01234567\n00001234\n", encoding="utf-8")
    assert cli.main([
        "--eingabe", str(case_txt), "--quellen", "tips",
    ]) == 0
    assert len(calls) == 1
    cmd = calls[0][0]
    assert "tips_main" in cmd[3]
    assert cmd[cmd.index("--eingabe") + 1] == str(case_txt)


def test_batch_sechs_quellen_getrennte_tips_fallnummern_liste(tmp_path, monkeypatch):
    calls, gleichzeitig = _popen_simulieren(monkeypatch)
    fin_list = _eingabe(tmp_path)
    case_txt = tmp_path / "TIPS-Fallnummern.txt"
    case_txt.write_text("01234567\n00001234\n", encoding="utf-8")
    assert cli.main([
        "--eingabe", str(fin_list),
        "--tips-eingabe", str(case_txt),
        "--quellen", "alle", "--parallel", "6",
    ]) == 0
    assert len(calls) == 6
    assert gleichzeitig() >= 2
    for cmd, _ in calls:
        origin = cmd[cmd.index("--eingabe") + 1]
        assert origin == str(case_txt if "tips_main" in cmd[3] else fin_list)


@pytest.mark.parametrize("falltext", [
    "", "00001A2Z\n", "123\n", "../01234567\n", "01234567\n00000ABC\n",
])
def test_batch_ungueltige_separate_tips_liste_vor_prozessstart_blockiert(
    tmp_path, monkeypatch, falltext,
):
    calls, _ = _popen_simulieren(monkeypatch)
    file = tmp_path / "faelle.txt"
    file.write_text(falltext, encoding="utf-8")
    assert cli.main([
        "--eingabe", str(_eingabe(tmp_path)), "--quellen", "alle",
        "--tips-eingabe", str(file),
    ]) == 2
    assert not calls


def test_batch_fallnummern_als_gemeinsame_liste_bei_mehreren_quellen_unzulaessig(
    tmp_path, monkeypatch,
):
    calls, _ = _popen_simulieren(monkeypatch)
    fall = tmp_path / "faelle.txt"
    fall.write_text("01234567\n", encoding="utf-8")
    assert cli.main(["--eingabe", str(fall), "--quellen", "tips,quicktests"]) == 2
    assert not calls


def test_batch_tips_separat_aber_nicht_ausgewaehlt_ergibt_fehler(tmp_path, monkeypatch):
    calls, _ = _popen_simulieren(monkeypatch)
    file = tmp_path / "faelle.txt"
    file.write_text("01234567\n", encoding="utf-8")
    assert cli.main([
        "--eingabe", str(_eingabe(tmp_path)), "--quellen", "wem,quicktests",
        "--tips-eingabe", str(file),
    ]) == 2
    assert not calls



def test_batch_14stellige_numerische_fallnummer_ist_keine_mercedes_kurz_fin(
    tmp_path, monkeypatch,
):
    commands, _ = _popen_simulieren(monkeypatch)
    datei = tmp_path / "TIPS-Fallnummern.txt"
    datei.write_text("12345678901234\n", encoding="utf-8")
    assert cli.main(["--eingabe", str(datei), "--quellen", "tips"]) == 0
    assert len(commands) == 1
    assert commands[0][0][commands[0][0].index("--eingabe") + 1] == str(datei)



def test_batch_quicktests_json_standard_auto_und_spezifisch_deaktivierbar(
    tmp_path, monkeypatch,
):
    commands, _ = _popen_simulieren(monkeypatch)
    fin = _eingabe(tmp_path)
    assert cli.main([
        "--eingabe", str(fin), "--quellen", "quicktests,qec",
        "--parallel", "2",
    ]) == 0
    assert len(commands) == 2
    assert all("--ohne-json" not in cmd for cmd, _ in commands)

    commands.clear()
    assert cli.main([
        "--eingabe", str(fin), "--quellen", "quicktests,qec",
        "--ohne-quicktest-json",
    ]) == 0
    quick = next(cmd for cmd, _ in commands if "diagnosis_viewer_cli" in cmd[3])
    qec = next(cmd for cmd, _ in commands if "portal_cli" in cmd[3])
    assert "--ohne-json" in quick
    assert "--ohne-json" not in qec


def test_batch_ohne_quicktest_json_ohne_quicktests_unzulaessig(
    tmp_path, monkeypatch,
):
    commands, _ = _popen_simulieren(monkeypatch)
    assert cli.main([
        "--eingabe", str(_eingabe(tmp_path)), "--quellen", "qec,tips",
        "--ohne-quicktest-json",
    ]) == 2
    assert not commands
