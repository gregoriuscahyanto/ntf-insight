"""Freigegebene Zusatzoptionen fuer die sechs Einzel-CLIs der Lightweight-GUI.

Jede Option ist explizit abgebildet; kein Shell-String und keine frei
waehlbaren CLI-Schalter. Passwort-Prompts im Terminal werden in der
fensterbasierten GUI bewusst nicht gestartet (QProcess hat kein TTY).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True)
class CliOption:
    name: str
    titel: str
    typ: str  # bool, text, choice, int, float, directory, output
    standard: str | int | float | bool = ""
    hilfe: str = ""
    auswahl: tuple[tuple[str, str], ...] = ()
    minimum: float | None = None
    maximum: float | None = None


AUSGABE = CliOption(
    "ausgabe", "Anderer Ausgabeort", "output",
    hilfe="Optional. Leer lassen für die private Standardablage.",
)
MANUELL = CliOption(
    "login-manuell", "SSO/PING-ID vollständig in Edge anmelden", "bool",
    hilfe="Betriebssystem-Tresor nicht für Zugangsdaten verwenden.",
)
PROFIL = CliOption(
    "profil", "Eigener Edge-Profilordner", "directory",
    hilfe="Optional. Ein separates Browserprofil; niemals im Downloadordner speichern.",
)
LOGIN_TIMEOUT = CliOption(
    "anmelde-timeout", "Wartezeit für SSO/PING-ID (Sek.)", "int", 300,
    minimum=30, maximum=900,
)
BROWSER = CliOption(
    "browser", "Browser", "choice", "edge",
    auswahl=(("edge", "Microsoft Edge"), ("chromium", "Chromium")),
)

_COMMON = (MANUELL, AUSGABE)

QUELLEN_OPTIONEN: dict[str, tuple[CliOption, ...]] = {
    "qec": (
        CliOption("erneut", "QEC-FINs vollständig erneut durchsuchen", "bool",
                  hilfe="Standard: abgeschlossene FINs mit identischem Filter fortsetzen."),
        CliOption("benennung", "Benennung enthält", "text",
                  hilfe="z. B. DCDC, DCDC223 oder DCDC,DC/DC (ODER). Leer = Pumpenfilter."),
        CliOption("sachnummer", "Exakte Sachnummer", "text",
                  hilfe="Optional; wird mit einer Benennung durch UND kombiniert."),
        CliOption(
            "anhaenge", "Anhänge herunterladen", "choice", "referenz",
            hilfe="Alle = alle sichtbaren Dateien aus den jeweiligen Fall-Popups; "
                  "die Zuordnung kann ungeprüft sein.",
            auswahl=(
                ("referenz", "Nur referenzbestätigte Dateien (Standard)"),
                ("alle", "Alle im Fall-Popup sichtbaren Anhänge"),
            ),
        ),
        CliOption("alle-bauteile", "Alle Bauteile (ohne Pumpenfilter)", "bool",
                  hilfe="Auch ohne Suchbegriff andere Schadteile berücksichtigen."),
        LOGIN_TIMEOUT, PROFIL, *_COMMON,
    ),
    "tips": (
        CliOption("erneut", "TIPS-FINs und Fälle erneut abrufen", "bool"),
        LOGIN_TIMEOUT, PROFIL, *_COMMON,
    ),
    "quicktests": (
        CliOption("erneut", "Vorhandene QuickTests erneut herunterladen", "bool"),
        CliOption("ohne-json", "Keine JSON-Konvertierung (nur PDF)", "bool"),
        LOGIN_TIMEOUT, PROFIL, *_COMMON,
    ),
    "wem": (
        CliOption("aktualisieren", "Nach neuen Sitzungen suchen", "bool"),
        CliOption("erneut", "Erfolgreiche Sitzungen erneut auslesen", "bool"),
        CliOption("ohne-gesamtdatei", "Gesamt-JSON nicht neu schreiben", "bool"),
        CliOption("nur-zusammenfassen", "Nur vorhandene Teildateien zusammenfassen", "bool",
                  hilfe="Offline-Modus ohne Browser."),
        CliOption("nur-aufteilen", "Nur vorhandene Gesamt-JSON aufteilen", "bool",
                  hilfe="Offline-Modus ohne Browser."),
        CliOption("nur-login", "Nur SSO/PING-ID testen (kein Download)", "bool"),
        CliOption("sso-tresor", "Gespeicherte SSO-Daten voraussetzen", "bool",
                  hilfe="Nicht mit manueller Anmeldung kombinieren."),
        BROWSER,
        CliOption("anmelde-timeout", "Wartezeit für SSO/PING-ID (Sek.)", "float", 300.0,
                  minimum=30, maximum=900),
        CliOption("seiten-timeout", "Seiten-Timeout (Sek.)", "float", 70.0,
                  minimum=5, maximum=180),
        CliOption("sitzungs-timeout", "Sitzungs-Timeout (Sek.)", "float", 5.0,
                  minimum=5, maximum=180),
        CliOption("abschnitt-wartezeit", "Wartezeit fehlender Abschnitte (Sek.)", "float", 1.25,
                  minimum=0.5, maximum=10),
        CliOption("abstand", "Abstand zwischen Browseraktionen (Sek.)", "float", 0.0,
                  minimum=0, maximum=10),
        PROFIL, *_COMMON,
    ),
    "sa-codes": (
        CliOption("erneut", "Vorhandene FINs erneut auslesen", "bool"),
        CliOption("nur-login", "Nur SSO/PING-ID testen (kein Download)", "bool"),
        CliOption("anmeldezeit", "Wartezeit für SSO/PING-ID (Sek.)", "int", 300,
                  minimum=30, maximum=900),
        CliOption("ladezeit", "Maximale Ladezeit pro Schritt (Sek.)", "int", 45,
                  minimum=5, maximum=300),
        CliOption("pause", "Pause zwischen Browseraktionen (Sek.)", "float", 1.5,
                  minimum=0.5, maximum=30),
        PROFIL, *_COMMON,
    ),
    "dcdc223": (
        CliOption("erneut", "Gespeicherte Hardwarehistorien erneut abfragen", "bool"),
        CliOption("objekt", "VeDoc-Objekt", "text", "DCDC223",
                  hilfe="Exakter Objektname, z. B. CPC3."),
        CliOption("attribut", "VeDoc-Attribut", "text", "Seriennummer",
                  hilfe="Exakter Attributname in der Hardwarehistorie."),
        CliOption("nur-login", "Nur SSO/PING-ID testen (kein Download)", "bool"),
        BROWSER,
        CliOption("timeout", "Schritt-Timeout (Sek.)", "int", 30,
                  minimum=5, maximum=120),
        CliOption("login-timeout", "Wartezeit für SSO/PING-ID (Sek.)", "int", 240,
                  minimum=30, maximum=900),
        CliOption("historie-wartezeit", "Wartezeit auf die Historie (Sek.)", "int", 20,
                  minimum=5, maximum=120),
        CliOption("url", "Alternative VeDoc-Start-URL", "text",
                  hilfe="Optional: nur freigegebene HTTPS-Adressen unter *.mercedes-benz.com."),
        *_COMMON,
    ),
}

DATEI_AUSGABEN = frozenset(("wem", "sa-codes"))


def extra_argumente(quelle: str, optionen: Mapping[str, Any] | None = None) -> tuple[list[str], Path | None]:
    """Typsichere, quellenspezifische CLI-Schalter ohne Shell oder Secrets.

    Die genauen CLI-Standardwerte werden weggelassen; damit folgen sie
    weiterhin den vorhandenen Entry-Points. Bei Ausgabe-Override wird
    der Pfad separat an --ausgabe uebergeben.
    """
    if quelle not in QUELLEN_OPTIONEN:
        raise ValueError("Unbekannte Datenquelle.")
    werte = dict(optionen or {})
    specs = {spec.name: spec for spec in QUELLEN_OPTIONEN[quelle]}
    unbekannt = set(werte) - set(specs)
    if unbekannt:
        raise ValueError(
            "Nicht unterstützte Zusatzoption für diese Quelle: " + ", ".join(sorted(unbekannt))
        )

    args: list[str] = []
    pfade: dict[str, Path] = {}
    aktiv: set[str] = set()
    for spec in QUELLEN_OPTIONEN[quelle]:
        standard = False if spec.typ == "bool" else spec.standard
        value = werte.get(spec.name, standard)
        if spec.typ == "bool":
            if type(value) is not bool:
                raise ValueError(f"{spec.titel}: erwartet Ja oder Nein.")
            if value:
                args.append("--" + spec.name)
                aktiv.add(spec.name)
            continue
        if spec.typ in {"int", "float"}:
            if type(value) not in (int, float) or (spec.typ == "int" and type(value) is not int):
                raise ValueError(f"{spec.titel}: erwartet eine Zahl.")
            if not (spec.minimum is None or value >= spec.minimum) or not (
                spec.maximum is None or value <= spec.maximum
            ):
                raise ValueError(f"{spec.titel}: Wert außerhalb des erlaubten Bereichs.")
            if value != spec.standard:
                args.extend(("--" + spec.name, str(value)))
                aktiv.add(spec.name)
            continue
        if not isinstance(value, str):
            raise ValueError(f"{spec.titel}: erwartet Text.")
        value = value.strip()
        if not value or value == spec.standard:
            continue
        if spec.typ == "choice":
            if value not in {entry[0] for entry in spec.auswahl}:
                raise ValueError(f"{spec.titel}: ungültige Auswahl.")
        elif spec.typ == "directory" or spec.typ == "output":
            pfad = Path(value).expanduser().resolve()
            if spec.typ == "directory" and pfad.exists() and not pfad.is_dir():
                raise ValueError(f"{spec.titel}: es muss ein Verzeichnis sein.")
            if spec.typ == "output":
                if quelle in DATEI_AUSGABEN:
                    if pfad.suffix.lower() != ".json" or (pfad.exists() and not pfad.is_file()):
                        raise ValueError("Ausgabe für WEM/VeDoc-Fahrzeugcodes muss eine JSON-Datei sein.")
                elif pfad.exists() and not pfad.is_dir():
                    raise ValueError("Der Ausgabeort muss ein Verzeichnis sein.")
            pfade[spec.name] = pfad
            value = str(pfad)
        elif spec.typ == "text":
            if spec.name == "benennung":
                from ntf_insight.acquisition.qec_tool import pruefe_benennung
                value = pruefe_benennung(value)
            elif spec.name == "sachnummer":
                from ntf_insight.acquisition.qec_tool import pruefe_sachnummer
                value = pruefe_sachnummer(value)
            elif spec.name in {"objekt", "attribut"}:
                from scripts.vedoc_dcdc223_seriennummern import pruefe_historienziel
                value = pruefe_historienziel(value, feld="--" + spec.name)
            elif spec.name == "url":
                from scripts.vedoc_dcdc223_seriennummern import pruefe_vedoc_url
                value = pruefe_vedoc_url(value)
        else:
            raise ValueError(f"Unbekannter Feldtyp: {spec.typ}.")
        if spec.name != "ausgabe":
            args.extend(("--" + spec.name, value))
        aktiv.add(spec.name)

    if quelle == "wem":
        einzelaktionen = {"nur-login", "nur-aufteilen", "nur-zusammenfassen"}
        if len(einzelaktionen & aktiv) > 1:
            raise ValueError("WEM: Nur-Login, Nur-Aufteilen und Nur-Zusammenfassen sind alternativ.")
        if "login-manuell" in aktiv and "sso-tresor" in aktiv:
            raise ValueError("WEM: Manuelle Anmeldung und SSO-Tresor schließen sich aus.")
    # Keine Browser-Profile innerhalb der lokal geschriebenen Berichtsdaten.
    if "profil" in pfade and "ausgabe" in pfade:
        profil, ausgabe = pfade["profil"], pfade["ausgabe"]
        basis = ausgabe.parent if quelle in DATEI_AUSGABEN else ausgabe
        if profil == basis or profil in basis.parents or basis in profil.parents:
            raise ValueError("Edge-Profil und Ausgabeverzeichnis müssen getrennt sein.")

    return args, pfade.get("ausgabe")
