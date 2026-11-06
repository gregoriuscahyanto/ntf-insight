# VeDoc: DCDC223-Seriennummernhistorie nach FIN exportieren

Das **eigenständige Python-Skript** `scripts/vedoc_dcdc223_seriennummern.py` arbeitet ohne GUI-Integration. Es liest eine TXT-Liste mit FINs, fragt VeDoc im berechtigten Browserzugang ab und exportiert die **Seriennummern-Änderungshistorie des Steuergeräts DCDC223** als JSON und Excel.

## Datenquelle und Ablauf (VeDoc-Anleitung v2)

**Fahrzeugdaten → vollständige FIN eingeben → Suchen → Historie → Filter öffnen → DCDC223 eingeben.** Danach werden ausschließlich Zeilen mit **Objekt = DCDC223**, **Attributname = Seriennummer** und **exakter FIN im Pfad** ausgewertet. Pro Treffer speichert das Skript:

- **Änderungszeitpunkt** in der von VeDoc angezeigten Schreibweise (ohne angenommene Zeitzone)
- **Alter Wert** der Seriennummer
- **Neuer Wert** der Seriennummer

Eine FIN kann mehrere passende Historieneinträge haben. **Alle** werden exportiert, nicht nur die letzte Änderung. Der zeitlich jüngste „Neue Wert“ erscheint zusätzlich in der Übersicht unter **„Letzter neuer Wert (Historie)“**. Dies ist der letzte **dokumentierte** Wert, kein unabhängig bestätigter Ist-Einbauzustand. Bei uneindeutigen oder nicht lesbaren Zeitstempeln wird kein letzter Wert geraten.

## Voraussetzungen

- Berechtigter VeDoc-Zugang, Unternehmensnetz/VPN, ggf. PING-ID/SSO.
- Python 3.11+ und die Projektabhängigkeiten: `python -m pip install -e .`.
- Microsoft Edge (Standard) oder Playwright-Chromium (`python -m playwright install chromium`).
- Die fest hinterlegte Startseite ist `https://prod.core.public.vedoc.i.mercedes-benz.com/ui/homepage.html`.

## Start in PowerShell

TXT-Datei **außerhalb des Repositorys** erstellen; pro Zeile eine 17-stellige FIN (leere Zeilen / `#`-Kommentare erlaubt). Doppelte FINs werden nur einmal verarbeitet. Ungültige FINs werden vor dem Browserstart zurückgewiesen.

```powershell
python scripts/vedoc_dcdc223_seriennummern.py --eingabe 'C:\lokal\fins.txt' --ausgabe 'C:\lokal\vedoc-ergebnisse'
```

Die Anmeldung nutzt vorhandene NTF-Insight-Zugangsdaten aus dem Windows-Anmeldetresor (`NTF Insight - Diagnosis Viewer`). Fehlen sie, fragt das Skript die Benutzerkennung und das **verdeckt eingegebene** Passwort in PowerShell ab. Es übermittelt die Zugangsdaten ausschließlich an `https://login.mercedes-benz.com`. Eine erforderliche PING-ID-Freigabe bleibt manuell. Danach beginnt die FIN-Verarbeitung. Optional: `--browser chromium`, `--timeout 60`, `--login-timeout 360`.

## Ausgabedateien

- **`dcdc223_seriennummern.json`**: `fahrzeuge` mit `fin`, `steuergeraet`, `seriennummer` (= letzter neuer Wert, soweit eindeutig), `status`, `hinweis`, `abgefragt_am_utc` und **`aenderungen`** (Liste mit `aenderungszeitpunkt`, `alter_wert`, `neuer_wert`). Quelle: `VeDoc/Historie`.
- **`dcdc223_seriennummern.xlsx`**, Blatt **DCDC223**: eine Zeile pro FIN, letzter dokumentierter neuer Wert, Anzahl Änderungen und Status.
- **`dcdc223_seriennummern.xlsx`**, Blatt **Historie**: **eine Zeile je Seriennummernänderung** mit FIN, Steuergerät, Attributname, Änderungszeitpunkt, altem und neuem Wert und FIN-Status.

Seriennummern und FINs bleiben in Excel Text; führende Nullen bleiben erhalten und Formeleinschleusungen werden nicht ausgeführt. Die JSON-Datei wird nach jeder FIN als Zwischenstand aktualisiert, am Ende werden beide Formate geschrieben. Erneute Läufe mit demselben Ausgabeordner überschreiben die Dateien.

Statuswerte: `gefunden`, `keine_seriennummer_aenderung`, `seriennummer_fehlt`, `mehrdeutig`, `zeitstempel_ungueltig`, `fin_nicht_bestaetigt`, `historie_nicht_bestaetigt`, `zeitueberschreitung`, `fehler`. **Keine Historienänderung bedeutet nicht, dass kein DCDC223 verbaut ist.** Eine nicht zur FIN passende Historie wird ausdrücklich zurückgewiesen.

## Datenschutz, technische Grenzen und Prüfung

Keine echten FINs, Seriennummern, HTML-Beispiele aus dem Unternehmenssystem oder VeDoc-PDFs nach GitHub übertragen. Die lokalen Eingaben und Exporte gehören nur in freigegebene Verzeichnisse. Das Skript speichert keine Passwörter, Browserprofile, Cookies oder HTML-Snapshots; es liest ggf. vorhandene Zugangsdaten aus dem Betriebssystem-Tresor und umgeht keine Zugriffsrechte.

Die Selektoren und Felder wurden anhand der mitgelieferten **VeDoc-Anleitung v2** und der sechs HTML-Snapshots geprüft. Die Ausleselogik wurde mit dem gefilterten HTML-Beispiel und synthetischen Testfällen offline getestet. **Ein echter VeDoc-Lauf im Unternehmensnetz steht weiterhin aus.** Bei geänderter Oberfläche können Anpassungen an Selektoren, Filter- und Ladeverhalten nötig werden.
