"""Isolierter Edge/Playwright-Downloadtest ohne FIN, SSO oder externe Webseiten.

Mit zwei separaten Python-Prozessen und einem einmaligen Wegwerfprofil
reproduziert dieser Test eine bekannte Edge-/CDP-Download-Fehlerklasse.
Das eigene produktive Edge-Profil wird nicht geoeffnet oder veraendert.
"""

from __future__ import annotations

import argparse
import base64
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

PROBE_BYTES = b"%PDF-1.7\nNTF-Insight-Synthetikprobe\n"
_KIND = "--_interner-test"


@dataclass(frozen=True)
class ProbeResult:
    returncode: int
    messages: tuple[str, ...]


def _child(profile: Path, output: Path) -> int:
    """Nur generierte, harmlose PDF-Daten in einem disposable Profil testen."""
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            print("PHASE Browserstart", flush=True)
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=str(profile),
                channel="msedge",
                headless=False,
                accept_downloads=True,
                no_viewport=True,
            )
            deliberate_close = False

            def context_closed(*_args) -> None:
                if not deliberate_close:
                    print("PHASE Unerwartetes-Kontextende", flush=True)

            context.on("close", context_closed)
            try:
                page = context.pages[0] if context.pages else context.new_page()
                daten = base64.b64encode(PROBE_BYTES).decode("ascii")
                page.set_content(
                    '<a id="probe" download="ntf_probe.pdf" '
                    f'href="data:application/pdf;base64,{daten}">Testdatei</a>'
                )
                print("PHASE Synthetischer-PDF-Klick", flush=True)
                with page.expect_download(timeout=20_000) as download_event:
                    page.locator("#probe").click(timeout=20_000)
                print("PHASE Download-Ereignis", flush=True)
                download = download_event.value
                print("PHASE PDF-Speichern", flush=True)
                download.save_as(str(output))
                if output.read_bytes() != PROBE_BYTES:
                    print("ERGEBNIS Ungueltige-Testdatei", flush=True)
                    return 3
                print("ERGEBNIS PDF-erfolgreich", flush=True)
                return 0
            finally:
                deliberate_close = True
                try:
                    context.close()
                except Exception:
                    pass
    except Exception as exc:
        print("ERGEBNIS Fehlerart-" + type(exc).__name__, flush=True)
        return 2


def _subprocess_lauf(profile: Path, output: Path) -> ProbeResult:
    command = [
        sys.executable, "-m", "ntf_insight.acquisition.edge_download_probe",
        _KIND, str(profile), str(output),
    ]
    try:
        result = subprocess.run(
            command, capture_output=True, text=True,
            timeout=75, check=False, encoding="utf-8", errors="replace",
        )
    except subprocess.TimeoutExpired:
        return ProbeResult(124, ("ERGEBNIS Testzeit-ueberschritten",))
    except OSError:
        return ProbeResult(125, ("ERGEBNIS Testprozess-konnte-nicht-starten",))
    # Nur unsere festen Diagnosemarker uebernehmen; keine ungefilterten
    # Browser-Stderr-, URL-, Profil- oder Cookie-Daten anzeigen.
    allowed = ("PHASE ", "ERGEBNIS ")
    messages = tuple(
        line.strip() for line in result.stdout.splitlines()
        if line.startswith(allowed) and len(line) < 150
    )
    return ProbeResult(result.returncode, messages)


def _bewertung(erster: ProbeResult, zweiter: ProbeResult, kontrolle: ProbeResult | None) -> str:
    if erster.returncode == 0 and zweiter.returncode == 0:
        return (
            "Keine Absturzreproduktion mit synthetischen PDF-Downloads. "
            "Ein portalabhaengiger Fehler bleibt moeglich."
        )
    if erster.returncode == 0 and zweiter.returncode != 0:
        if kontrolle is not None and kontrolle.returncode == 0:
            return (
                "Starker Hinweis auf einen Edge-Absturz bei Wiederverwendung "
                "des persistenten Browserprofils. Unternehmens-Diagnosis-Viewer "
                "und PING-ID waren daran nicht beteiligt."
            )
        return (
            "Zweiter Profilstart fehlgeschlagen. "
            "Die Ursache ist ohne weitere lokale Pruefung nicht gesichert."
        )
    return (
        "Schon der erste synthetische PDF-Test ist fehlgeschlagen. "
        "Edge-/Playwright-Installation, Richtlinien oder lokale Umgebung pruefen."
    )


def _probe() -> int:
    print("NTF-Insight | Lokale Edge-Downloaddiagnose", flush=True)
    print("Nur synthetische PDF-Datei, kein Portal, keine FINs, keine SSO-Daten.", flush=True)
    print("Jeder Test startet einen eigenen Edge-Prozess mit einem Wegwerfprofil.", flush=True)
    with tempfile.TemporaryDirectory(prefix="ntf-edge-pdf-probe-") as temp:
        root = Path(temp)
        profil = root / "gleiches-profil"
        erster = _subprocess_lauf(profil, root / "probe1.pdf")
        print(f"Versuch 1 (neues Profil): Exit {erster.returncode}", flush=True)
        for msg in erster.messages:
            print("  " + msg, flush=True)
        zweiter = _subprocess_lauf(profil, root / "probe2.pdf")
        print(f"Versuch 2 (wiederverwendetes Profil): Exit {zweiter.returncode}", flush=True)
        for msg in zweiter.messages:
            print("  " + msg, flush=True)
        kontrolle = None
        if erster.returncode == 0 and zweiter.returncode != 0:
            kontrolle = _subprocess_lauf(
                root / "neues-kontrollprofil", root / "kontrolle.pdf",
            )
            print(f"Kontrollversuch (frisches Profil): Exit {kontrolle.returncode}", flush=True)
            for msg in kontrolle.messages:
                print("  " + msg, flush=True)
        print("Befund: " + _bewertung(erster, zweiter, kontrolle), flush=True)
    print("Alle Wegwerfprofile und Testdateien wurden lokal aufgeraeumt.", flush=True)
    return 0 if erster.returncode == 0 and zweiter.returncode == 0 else 1


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == _KIND:
        if len(argv) != 3:
            return 2
        return _child(Path(argv[1]), Path(argv[2]))
    parser = argparse.ArgumentParser(
        description="Edge-PDF-Downloadtest ohne FINs, Mercedes-Portal oder PING-ID.",
    )
    parser.parse_args(argv)
    return _probe()


if __name__ == "__main__":
    raise SystemExit(main())
