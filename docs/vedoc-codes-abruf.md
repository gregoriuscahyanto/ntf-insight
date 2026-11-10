# VeDoc-Codes-Scraper für NTF Insight

Automatisierter Abruf der **Fahrzeug-/Ausstattungscodes (SA-Codes)** aus **VeDoc PROD**, Bereich **Fahrzeugdaten → Codes**, für eine Liste von FINs. Grundlage sind die mitgelieferte `Anleitung VeDoc.pdf`, gespeicherte HTML-Seiten und `VehicleCodes_040.js` aus `Vedoc Codes.zip`.

> **Abgrenzung:** Dies sind nicht die Diagnosefehlercodes (DTC) des CPC3. Für NTF-Kühlmittelpumpen können die VeDoc-Codes als Fahrzeugkonfiguration zur Gruppierung/Analyse herangezogen werden; DTCs müssen aus den Diagnosedaten kommen.

## Installation (Windows / PowerShell)

Voraussetzungen: Python 3.11+ mit Playwright und bereits installiertem **Microsoft Edge**, gültige VeDoc-Berechtigung und reguläre Unternehmensanmeldung.

```powershell
py -m pip install -e .
```

Ein zusätzlicher Chromium-Download ist nicht nötig: Das Skript verwendet `channel="msedge"`.

## FIN-TXT

Datei `fins.txt` im UTF-8-Format, beispielsweise:

```text
FIN
W1N12345678901234
WDD98765432109876
```

Auch durch Leerzeichen, `,` oder `;` getrennte FINs sind zulässig. Kommentare beginnen mit `#`. Es werden 17 Zeichen ohne die Buchstaben `I`, `O`, `Q` verlangt; Duplikate werden automatisch entfernt. Die FINs oben sind nur synthetische Beispieldaten.

## Abrufen

```powershell
ntf-insight-vedoc-codes --eingabe .\fins.txt --ausgabe .\daten\vedoc_codes.json
```

Ohne `--ausgabe` schreibt der Scraper automatisch nach **`data/processed/vedoc_codes.json`** (relativ zum aktuellen Arbeitsverzeichnis, normalerweise das Repository-Hauptverzeichnis). Der Ordner wird automatisch erstellt. Mit `--ausgabe` lässt sich ein anderer JSON-Zielpfad angeben.

```powershell
ntf-insight-vedoc-codes --eingabe .\fins.txt
```

Das bisherige Positionsargument bleibt gültig, z. B. `ntf-insight-vedoc-codes .\fins.txt`. Bitte entweder `--eingabe` **oder** das Positionsargument verwenden, nicht beide.

1. Das Skript öffnet Microsoft Edge mit einem **separaten lokalen Profil** (`%USERPROFILE%\.ntf-insight\vedoc-edge-profile`).
2. Wenn VeDoc eine Anmeldung verlangt, übernimmt der Scraper **Benutzerkennung und Passwort automatisch** aus dem bereits vorhandenen NTF-Insight-Tresoreintrag (Dienst `NTF Insight - Diagnosis Viewer`, Windows-Anmeldeinformationsmanager). Fehlt dieser Eintrag, fragt er beide Daten einmalig im Terminal ab (Passwort verdeckt); ohne interaktives Terminal erfolgt die Anmeldung manuell im Browser. Das Programm übermittelt Anmeldedaten nur an `https://login.mercedes-benz.com`, speichert sie nicht in JSON oder Git und übernimmt **keine PING-ID-Freigabe**. Bei bestehender Edge-Anmeldung wird keine erneute Passworteingabe benötigt.
3. Das Skript wählt **FIN oder VIN**, sucht jede FIN und öffnet **Codes**.
4. Es versucht zunächst die durch die Tabelle verwendete AngularJS-Datenstruktur auszulesen (`consolidatedProductData.equipmentCode`); bei eingeschränktem Zugriff nutzt es die sichtbare HTML-Tabelle mit automatischem Scrollen.
5. Nach **jeder FIN** wird das JSON atomar gesichert. Bei Neustart werden erfolgreich abgerufene FINs übersprungen. Fehlerhafte FINs werden erneut versucht.

Alle FINs gezielt neu abfragen:

```powershell
ntf-insight-vedoc-codes --eingabe .\fins.txt --erneut
```

**Anmeldung separat prüfen (ohne FIN und ohne JSON-Änderung):**

```powershell
ntf-insight-vedoc-codes --nur-login
```

**Komplett manuelle Anmeldung im Edge-Fenster** (Tresor wird nicht gelesen, weder Benutzername noch Passwort automatisch eingegeben):

```powershell
ntf-insight-vedoc-codes --eingabe .\fins.txt --login-manuell
```

Weitere Optionen: `-i` (alias für `--eingabe`), `-o` (alias für `--ausgabe`), `--profil`, `--anmeldezeit`, `--ladezeit`, `--pause`, `--nur-login` und `--login-manuell` (siehe `--help`).

**Windows nach dem Merge aktualisieren:** Im Repository `git pull --ff-only` ausführen, dann `.\.venv\Scripts\python.exe -m pip install -e .` (falls der Konsolenbefehl noch nicht registriert ist). Über `.\.venv\Scripts\ntf-insight-vedoc-codes.exe` lässt sich der Befehl auch ohne aktivierte virtuelle Umgebung starten.

## JSON-Schema

```json
{
  "schema_version": "1.0",
  "quelle": "VeDoc PROD / Fahrzeugdaten > Codes",
  "codeart": "Fahrzeug-/Ausstattungscodes (SA), keine Diagnosefehlercodes (DTC)",
  "stand_utc": "2026-11-09T12:00:00+00:00",
  "anzahl_fins": 1,
  "fahrzeuge": [
    {
      "fin": "W1N12345678901234",
      "status": "erfolgreich",
      "anzahl_codes": 1,
      "codes": [
        {
          "code": "01U",
          "benennung": "Beispieltext (kein echter VeDoc-Abruf)",
          "produktgruppe": "",
          "codetyp": "",
          "verwendung": "V",
          "quelle": "vehicle"
        }
      ],
      "extraktionsmethode": "angular-und-dom",
      "abgerufen_am_utc": "2026-11-09T12:00:00+00:00",
      "fehler": null
    }
  ]
}
```

Die JSON-Beispiele sind **fiktiv**; Daten entstehen erst nach echtem VeDoc-Abruf. Das Skript wurde **offline** geprüft, ein Live-Test gegen das interne VeDoc-System war hier nicht möglich. Da VeDoc seine Oberfläche verändern kann, sind die Angular- und Tabellen-Selektoren bei Bedarf anzupassen.

## Datenschutz / Betrieb

- Nur im Rahmen der eigenen Zugriffsberechtigung und internen Vorgaben verwenden; keine SSO-/PING-Umgehung. Automatisches Ausfüllen nur auf dem verifizierten HTTPS-SSO-Host; keine Passwortablage im Skript, in JSON, in Umgebungsvariablen oder im Repository.
- Das Edge-Profil kann SSO-Sitzungsdaten enthalten: ausschließlich lokal und geschützt ablegen.
- FIN-Listen und Ergebnis-JSON nicht in ein öffentliches Git-Repository committen. Die lokalen Standardnamen `fins.txt` und `vedoc_codes.json` sind in `.gitignore` geschützt.
- Das Skript begrenzt Browseraktionen mit einer Pause von standardmäßig 1,5 Sekunden und unterstützt Wiederaufnahme; umfangreiche Abfragen vorher mit dem zuständigen Systembetreiber abstimmen.

## Tests (offline)

```powershell
py -m pip install pytest
py -m pytest -q tests/test_vedoc_codes_scraper.py
```