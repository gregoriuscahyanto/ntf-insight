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

Die Anmeldung nutzt vorhandene NTF-Insight-Zugangsdaten aus dem Windows-Anmeldetresor (`NTF Insight - Diagnosis Viewer`). Fehlen sie, fragt das Skript die Benutzerkennung und das **verdeckt eingegebene** Passwort in PowerShell ab. Es übermittelt die Zugangsdaten ausschließlich an `https://login.mercedes-benz.com`. Eine erforderliche PING-ID-Freigabe bleibt manuell. Danach beginnt die FIN-Verarbeitung. Optional: `--browser chromium`, `--timeout 60`, `--login-timeout 360`, `--historie-wartezeit 40` (Standard: 20 Sekunden pro FIN bei fehlendem Filtertreffer). Mit `--login-manuell` erfolgt die gesamte Benutzerkennung-/Passworteingabe direkt im Browser; der Betriebssystem-Tresor wird dabei **nicht** ausgelesen.

## Verzoegerte Historie und scheinbar fehlende Seriennummernaenderungen

VeDoc aktualisiert seine Historientabelle nach FIN-Suche und Filtereingabe asynchron. Eine unmittelbar leere Tabelle ist deshalb **kein sicherer Negativbefund**. Der Exporter setzt den DCDC223-Filter bei jeder FIN neu, kontrolliert die Voll-FIN der angezeigten Eintraege und wartet auf einen mindestens 1,5 Sekunden stabilen Datenstand. Falls nach standardmaessig 20 Sekunden keine passende Seriennummernaenderung sichtbar ist, entfernt er den Filter und prueft die ungefilterte Historie erneut. Vorhandene Zeilen werden nach Moeglichkeit vollstaendig aufgeklappt.

- `gefunden`: Passende Aenderung nach stabiler gefilterter oder ungefilterter Kontrolle erfasst.
- `keine_seriennummer_aenderung`: Auch die nachgepruefte ungefilterte Historie hatte andere, eindeutig zur FIN gehoerende Eintraege, aber keine passende DCDC223-Seriennummernaenderung. Das ist kein Beweis fuer einen fehlenden Verbau.
- `historie_nicht_bestaetigt`: Historientabelle blieb leer, unvollstaendig oder die Zuordnung der angezeigten Zeilen zur FIN liess sich nicht sicher pruefen. **Nicht als fehlende Aenderung interpretieren**, sondern erneut abrufen.

Bei auffaelligen FINs fuer einen gezielten Wiederholungstest eine neue TXT-Liste verwenden und die Exporte in einem **neuen** Ordner speichern:

```powershell
python scripts/vedoc_dcdc223_seriennummern.py --eingabe 'C:\lokal\fins_nachpruefen.txt' --ausgabe 'C:\lokal\vedoc-nachpruefung' --historie-wartezeit 45
```

Die zusaetzliche Wartezeit ist eine Absicherung gegen langsames Laden, keine Garantie fuer fehlerfreie Quellsystemdaten. Einen echten Live-Test mit verschiedenen FINs bitte weiterhin im Unternehmensnetz durchfuehren.

## Ausgabedateien

- **`dcdc223_seriennummern.json`**: `fahrzeuge` mit `fin`, `steuergeraet`, `seriennummer` (= letzter neuer Wert, soweit eindeutig), `status`, `hinweis`, `abgefragt_am_utc` und **`aenderungen`** (Liste mit `aenderungszeitpunkt`, `alter_wert`, `neuer_wert`). Quelle: `VeDoc/Historie`.
- **`dcdc223_seriennummern.xlsx`**, Blatt **DCDC223**: eine Zeile pro FIN, letzter dokumentierter neuer Wert, Anzahl Änderungen und Status.
- **`dcdc223_seriennummern.xlsx`**, Blatt **Historie**: **eine Zeile je Seriennummernänderung** mit FIN, Steuergerät, Attributname, Änderungszeitpunkt, altem und neuem Wert und FIN-Status.

Seriennummern und FINs bleiben in Excel Text; führende Nullen bleiben erhalten und Formeleinschleusungen werden nicht ausgeführt. Die JSON-Datei wird nach jeder FIN als Zwischenstand aktualisiert, am Ende werden beide Formate geschrieben. Erneute Läufe mit demselben Ausgabeordner überschreiben die Dateien. **Wenn noch keine FIN verarbeitet wurde**, bleiben bereits vorhandene Exporte nach einem Loginfehler oder Browserabsturz unangetastet.

Statuswerte: `gefunden`, `keine_seriennummer_aenderung`, `seriennummer_fehlt`, `mehrdeutig`, `zeitstempel_ungueltig`, `fin_nicht_bestaetigt`, `historie_nicht_bestaetigt`, `zeitueberschreitung`, `fehler`. **Keine Historienänderung bedeutet nicht, dass kein DCDC223 verbaut ist.** Eine nicht zur FIN passende Historie wird ausdrücklich zurückgewiesen.

## Datenschutz, technische Grenzen und Prüfung

Keine echten FINs, Seriennummern, HTML-Beispiele aus dem Unternehmenssystem oder VeDoc-PDFs nach GitHub übertragen. Die lokalen Eingaben und Exporte gehören nur in freigegebene Verzeichnisse. Das Skript speichert keine Passwörter oder HTML-Snapshots und liest ggf. vorhandene Zugangsdaten aus dem Betriebssystem-Tresor. Für die Browseranmeldung legt Playwright ein **temporäres, separates Browserprofil** mit Sitzungsdaten an, das beim normalen Schließen aufgeräumt wird. Nach einem Absturz können temporäre Profilreste verbleiben. Es werden keine Zugriffsrechte umgangen.

Die Selektoren und Felder wurden anhand der mitgelieferten **VeDoc-Anleitung v2** und der sechs HTML-Snapshots geprüft. Die Ausleselogik wurde mit dem gefilterten HTML-Beispiel und synthetischen Testfällen offline getestet. **Ein echter VeDoc-Lauf im Unternehmensnetz steht weiterhin aus.** Bei geänderter Oberfläche können Anpassungen an Selektoren, Filter- und Ladeverhalten nötig werden.


## SSO/PING ID gezielt testen

Der VeDoc-Exporter nutzt ab jetzt - wie QEC und Diagnosis Viewer - einen eigenen Playwright-**Persistent Context** statt des bisherigen Inkognito-Kontexts. Playwright erstellt dazu ein separates, temporäres Browserprofil, das bei regulärem Beenden entfernt wird. Das normale Edge-Benutzerprofil bleibt unberührt. Der Wechsel ist ein **Lösungsversuch**, keine Garantie, dass die unternehmensspezifische SSO-/PING-ID-Weiterleitung funktioniert.

Zur Eingrenzung bitte zunächst **nur die Anmeldung** testen; dazu ist keine FIN-Liste nötig:

```powershell
python scripts/vedoc_dcdc223_seriennummern.py --nur-login --login-manuell
```

Nach der Passwort-Eingabe gegebenenfalls PING ID im vorgesehenen Verfahren bestätigen. Erfolgreich ist der Test erst bei der Meldung **„SSO/PING ID erfolgreich: VeDoc ist erreichbar“**. In diesem Modus werden keine FINs abgefragt und keine JSON-/Excel-Dateien erstellt oder überschrieben.

Falls Edge erneut beim Übergang zu PING ID abstürzt: VeDoc einmal **ohne Skript im normal gestarteten Edge** öffnen und den regulären Login prüfen. Funktioniert der Standard-Edge, liegt die Ursache eher an der isolierten Automatisierungssitzung, einer Sicherheitsrichtlinie oder an Browserintegration. Stürzt auch der reguläre Edge ab, zuerst die Windows-/Edge- bzw. SSO-Umgebung mit der Unternehmens-IT überprüfen. Bitte nicht versuchen, SSO, PING ID oder Unternehmensrichtlinien zu umgehen.

## Problembehebung: Browser schliesst nach der SSO-Passworteingabe

Wenn Edge unmittelbar nach „Mercedes-SSO: Passwort gesendet“ verschwindet, ist die **technische Ursache des Browserabsturzes noch nicht bekannt**. Der Exporter erkennt nun sowohl den Verlust der Browser-Verbindung als auch einen abgestuerzten Browser-Tab und beendet den Prozess mit einem klaren Fehler, statt still bis zum Login-Timeout zu warten. Waerend einer normalen SSO-/PING-ID-Wartephase erscheint etwa alle 12 Sekunden eine Statusmeldung.

1. Den bisherigen Prozess in PowerShell mit **Strg+C** abbrechen. Anschliessend den aktuellen Stand des Branches mit `git pull --ff-only` abrufen und zuerst `--nur-login --login-manuell` testen.
2. Den Login ohne automatische Formularausfuellung testen:

   ```powershell
   python scripts/vedoc_dcdc223_seriennummern.py --eingabe 'C:\lokal\fins.txt' --login-manuell
   ```

   Im geoeffneten Browser Benutzerkennung, Passwort und ggf. PING ID selbst eingeben. Der Exporter wartet weiterhin auf die erfolgreich geladene VeDoc-Oberflaeche.
3. Falls Edge weiterhin abstuerzt, **sofern nach Unternehmensrichtlinie erlaubt** in einem Playwright-Chromium-Fenster testen. Vorher einmalig `python -m playwright install chromium` ausfuehren; dann `--browser chromium --login-manuell` an den Befehl anhaengen.
4. Schlaegt auch die manuelle Anmeldung fehl, Browser-Version, Unternehmenssicherheitsrichtlinien und Windows-Ereignisanzeige (Anwendung) pruefen und ggf. die lokale IT hinzuziehen. **Keine** Passwoerter, PING-ID-Codes, Cookies oder vollstaendigen FINs in Fehlermeldungen oder Tickets weitergeben.

Die Browserinstanz und alle Anmeldedaten bleiben temporaer. Ein Neustart der Browser-Anmeldung erfolgt **nicht automatisch**, um ungewollte wiederholte Loginversuche zu vermeiden. Der Statuscode des Skripts ist `3` bei erkanntem Browserabbruch und `4` bei Login-Timeout.
