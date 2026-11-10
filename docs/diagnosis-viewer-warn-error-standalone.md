# Diagnosis Viewer: Warning- und Error-Meldungen als JSON (eigenstaendiges Skript)

Das eigenstaendige Skript [`scripts/diagnosis_viewer_warn_error.py`](../scripts/diagnosis_viewer_warn_error.py) liest **Warning and Error Messages** aller im Diagnosis Viewer gefundenen Diagnose-Sitzungen je FIN. Es laedt **keine QuickTest-PDFs** herunter und hat **keine GUI-Anbindung**. Basis: die uebergebene Diagnosis-Viewer-Anleitung mit Augen-Link und dem Reiter `Warning and Error Messages`, der vorhandene QuickTest-Downloader der App sowie der Bedienablauf aus dem Branch `feature/vedoc-dcdc223-export-20261106`.

## Voraussetzungen und Installation

**Standardablage bei `--eingabe` ohne `--ausgabe`:** `data/processed/<bereinigter TXT-Name>/diagnosis_viewer_warn_error/warnings_errors.json`. Der Dateiname wird Windows-sicher bereinigt. Der separate `start_diagnosis_viewer_warn_error.cmd`-Starter nutzt weiterhin ausdrücklich seinen bisherigen festen Ausgabeort. Mit `--ausgabe` ist der bisherige Pfad unverändert nutzbar.

- Windows mit installiertem Microsoft Edge, berechtigter Diagnosis-Viewer-Zugang im Unternehmensnetz/VPN.
- Python 3.11+ und die beiden Skriptabhaengigkeiten (keine App-Installation erforderlich):

```powershell
py -3.11 -m pip install -r scripts/requirements_diagnosis_viewer_warn_error.txt
```

- Die SSO- und PING-ID-Freigabe erfolgen ueber die regulaere Mercedes-Anmeldung. Die Browserautomatisierung muss nach Unternehmensrichtlinien erlaubt sein. Es wird **kein** SSO umgangen und kein zweiter Browser installiert: Playwright verwendet den lokal installierten Edge.

## Start wie beim VeDoc-DCDC223-Exporter

**Eingabe:** eine UTF-8-TXT-Datei mit **einer 17-stelligen FIN pro Zeile**; leere Zeilen und `#`-Kommentare werden ignoriert, doppelte FINs nur einmal verarbeitet. Beispiel (ausschliesslich synthetische Daten):

```text
# FINs nur in lokalem, nicht versioniertem Verzeichnis speichern
WDD12345678901234
WDD12345678901235
```

**PowerShell:** im Repository-Stammverzeichnis:

```powershell
py -3.11 scripts/diagnosis_viewer_warn_error.py --eingabe 'C:\lokal\fins.txt' --ausgabe 'C:\lokal\warnings_errors.json'
```

**Doppelklick:** [`scripts/start_diagnosis_viewer_warn_error.cmd`](../scripts/start_diagnosis_viewer_warn_error.cmd). Diese legt beim ersten Start eine lokale FIN-Vorlage an unter:

- Eingabe: `data/raw/diagnosis_viewer_warn_error/fins.txt`
- JSON: `data/processed/diagnosis_viewer_warn_error/warnings_errors.json`

Nach Eintragen der FINs die CMD-Datei erneut doppelklicken. Beide Verzeichnisse sind durch `.gitignore` vom Git-Commit ausgeschlossen. Das Fenster bleibt zur Kontrolle offen. Unter Windows ohne `py` wird `python` verwendet.

**Abbruch und Resume:** Mit `Strg+C` unterbrechen; zum Fortsetzen **denselben** Befehl/dieselbe CMD-Datei mit **demselben `--ausgabe`-Pfad** erneut starten. **Jede Sitzung** wird in einer eigenen kleinen JSON atomar gespeichert. Die bisherige Gesamtdatei wird nicht bei jedem Checkpoint neu geschrieben. Erfolgreich gelesene Sitzungen werden anhand einer stabilen Sitzungs-ID ueberprueft und nicht erneut abgerufen. Fehlgeschlagene oder unterbrochene Sitzungen bleiben offen und werden erneut versucht. Ein bereits abgeschlossenes Fahrzeug wird standardmaessig uebersprungen. Nach `Strg+C` bleibt die bisherige Gesamtdatei unveraendert; der naechste Start liest trotzdem alle neuen Teildateien.

## Aufgeteilte JSON-Dateien: keine langsamen Voll-Rewrites

Bei derselben Ausgabe `C:\lokal\warnings_errors.json` speichert der Scraper ab jetzt **zusaetzlich** in den Ordner `C:\lokal\warnings_errors_teile\`:

```text
warnings_errors.json                 # Bisherige kompatible Gesamt-JSON
warnings_errors_teile/
  <FIN>/
    _status.json                     # FIN-Status, Suchfortschritt; ohne grosse Meldungslisten
    sitzungen/
      <stabile-sitzungs-id>.json     # Eine Diagnose-Sitzung einschliesslich ihrer Meldungen
      <weitere-sitzungs-id>.json
```

- **Beim ersten Start mit bestehender Datei:** Die bisherige `warnings_errors.json` wird verlustfrei und idempotent in Teildateien uebernommen. Ihre Original-Bytes bleiben waehrend der Migration unangetastet. Bereits neuere Teildateien werden niemals durch alte Daten ueberschrieben.
**Nur vorhandenen Altbestand aufteilen (kein Browser, keine FIN-TXT, kein Login):**

```powershell
py -3.11 scripts/diagnosis_viewer_warn_error.py --ausgabe 'C:\lokal\warnings_errors.json' --nur-aufteilen
```

Danach kann der regulaere Abruf mit demselben `--ausgabe`-Pfad sicher fortgesetzt werden. Ein wiederholtes `--nur-aufteilen` ueberschreibt keine neueren Sitzungsdateien.

- **Im laufenden Abruf:** Pro Sitzung werden nur ihre kleine JSON und der kurze FIN-Status atomar aktualisiert. Die grosse Gesamtdatei bleibt in dieser Phase auf ihrem letzten Stand.
- **Bei normalem Laufende (Standard):** Der Scraper erzeugt **einmal** eine aktualisierte `warnings_errors.json` mit derselben Struktur wie bisher. Das kostet bei sehr grossen Datenmengen einmalig Zeit, nicht nach jeder Sitzung.
- **Bei `Strg+C` oder Absturz:** Schon geschriebene Sitzungsdateien und der FIN-Status bleiben gueltig. Der teure Gesamtexport wird bei Unterbrechung nicht erzwungen; Resume kombiniert beim Laden die bisherige Gesamtdatei mit den neueren Teildateien. `fehler` wird erneut versucht, `erfolgreich`, `keine_meldungen`, `abschnitt_fehlt` und `ausgeschlossen` werden uebersprungen.
- **Fuer maximale Geschwindigkeit:** `--ohne-gesamtdatei` an den normalen Startbefehl anhaengen. Damit wird die Gesamtdatei **auch am normalen Laufende nicht neu geschrieben** (sie bleibt als alter Snapshot erhalten); die Teildateien sind der aktuelle Datenstand. Spaeter ohne Browser/SSO mit `--nur-zusammenfassen` manuell aktualisieren:

```powershell
py -3.11 scripts/diagnosis_viewer_warn_error.py --ausgabe 'C:\lokal\warnings_errors.json' --nur-zusammenfassen
```

**Wichtig:** Den Ordner `warnings_errors_teile` nicht loeschen oder umbenennen. **Gesamt-JSON und Teildateien muessen bei einem Wechsel des Rechners oder Ausgabeordners gemeinsam kopiert werden**, damit die Wiederaufnahme alle bereits geladenen Sitzungen kennt. `--nur-zusammenfassen` stellt eine aktuelle Gesamt-JSON wieder her, liest jedoch keine Diagnose-Sitzungen im Viewer. Nicht zwei Skriptprozesse mit demselben Ausgabe-Pfad gleichzeitig ausfuehren.

## Geschwindigkeit, Vorabfilter, fehlende Abschnitte und Restzeit

- **Source AKT oder fehlende Mileage:** In der Suchergebnisliste werden Sitzungen mit **Source = AKT** **ODER** leerem bzw. als nicht verfuegbar gekennzeichnetem **Mileage**-Feld schon **vor dem Oeffnen des Augen-Links** ausgeschlossen. Es wird fuer sie weder die WEM-Seite noch die WEM-API abgefragt. Der Ergebnisstatus lautet `ausgeschlossen`, mit `ausschlussgruende` (`source_akt` und/oder `mileage_fehlt`), `anzahl_meldungen: null` und `meldungen: []`. **Dieser Filter ist eine Heuristik, keine Aussage darueber, ob Warnungen tatsaechlich existieren.** Bereits in frueheren Laeufen gelesene Meldungen werden nicht geloescht. `--aktualisieren` kann eine bisher ausgeschlossene Sitzung abrufen, sobald eine gueltige Mileage und ein anderer Source-Wert angezeigt werden.
- **WEM-Timeout 5 Sekunden:** Ein WEM-Sitzungsabruf (Oeffnen der Sitzungsansicht, auf Warnungsabschnitt warten, Daten lesen) hat standardmaessig **maximal 5 Sekunden Zeitbudget**; vorher waren es 25 Sekunden. Auch Klicks und API-/DOM-Fallback teilen sich dieses Budget. Laeuft es ab, wird `fehler` gespeichert (kein falscher Negativbefund). `--sitzungs-timeout 10` kann bei langsamen Verbindungen gezielt laenger warten. **SSO-/PING-ID und FIN-Suche behalten ihre eigenen Timeouts** (`--anmelde-timeout`, `--seiten-timeout`).
- **Schneller Standard:** `--abstand 0` ist jetzt der Standard. Es gibt **keine kuenstliche Pause zwischen Browseraktionen**; Playwright wartet stattdessen nur auf benoetigte Navigation, gerenderte Daten und UI-Antworten. Die FINs und Sitzungen werden weiterhin **nacheinander** und nicht parallel verarbeitet. Falls das System langsamer reagieren soll, `--abstand 1.5` setzen.
- **Abschnitt fehlt:** Manche Diagnose-Sitzungen enthalten **keinen** Abschnitt `Warning and Error Messages`. Sobald die Sitzungsinformationen vollstaendig geladen sind und das Fehlen des Abschnitts fuer mindestens 1,25 Sekunden stabil ist, wird diese Sitzung mit dem Status **`abschnitt_fehlt`** gespeichert und die naechste Sitzung geoeffnet. Eine Backend-Abschnittsliste kann das Fehlen auch unmittelbar bestaetigen. Der Export wartet dafuer **nicht mehr standardmaessig 70 Sekunden**. `anzahl_meldungen` ist in diesem Fall **`null`**, nicht 0. Der Status wird beim Resume uebersprungen; mit `--erneut` kann erneut geprueft werden.
- **Unfertige Sitzungsansicht:** Wenn selbst die Sitzungsinformationen nicht laden, wird nach standardmaessig 5 Sekunden **`fehler`** statt `abschnitt_fehlt` gespeichert. Der Fall wird bei einem Folgeabruf erneut versucht. Eine eventuell haengende direkte API-Anfrage bricht nach vier Sekunden ab und faellt auf die sichtbare Tabelle zurueck.
- **ETA in der Konsole:** Nach jeder FIN-Suche und jeder Sitzung erscheinen **FIN x/y**, **Sitzung x/y**, **Laufzeit** und eine **grob geschaetzte Restzeit**. Sobald eine Sitzung gemessen ist, rechnet der Exporter mit bisherigen Such-/Sitzungsdauern und den bisher beobachteten Sitzungszahlen pro FIN. Zuvor wird `Restzeit wird ermittelt` ausgegeben. Die tatsaechliche Dauer kann insbesondere bei FINs mit unterschiedlich vielen Sitzungen abweichen.

Anpassbare Optionen: `--abstand 0.5`, `--sitzungs-timeout 10`, `--abschnitt-wartezeit 2` und `--seiten-timeout 90`. Das ist **keine** Umgehung von Unternehmens-Sicherheitsvorgaben oder Bot-Schutz.

Optional:

```powershell
# Nach bisher unbekannten, neu hinzugekommenen Sitzungen suchen:
py -3.11 scripts/diagnosis_viewer_warn_error.py --eingabe 'C:\lokal\fins.txt' --ausgabe 'C:\lokal\warnings_errors.json' --aktualisieren

# Erfolgreiche Sitzungen ebenfalls neu lesen:
py -3.11 scripts/diagnosis_viewer_warn_error.py --eingabe 'C:\lokal\fins.txt' --ausgabe 'C:\lokal\warnings_errors.json' --erneut

# Nur Mercedes SSO/PING ID pruefen - ohne FIN und ohne JSON-Veraenderung:
py -3.11 scripts/diagnosis_viewer_warn_error.py --nur-login --login-manuell
```

## Benutzerkennung, Passwort und PING ID

**Im Normalfall ist keine erneute Eingabe erforderlich**, wenn die App NTF Insight die Zugangsdaten bereits sicher im Windows-Anmeldeinformationsmanager unter `NTF Insight - Diagnosis Viewer` gespeichert hat. Der Scraper probiert beim Start **automatisch** diesen OS-Tresoreintrag; der Schalter `--sso-tresor` ist dafuer **nicht erforderlich**. Sind keine Daten gespeichert oder ist der Tresor nicht verfuegbar, kann der Benutzer die Anmeldung **im geoeffneten Edge-Fenster manuell** fortsetzen. Eine noch gueltige Edge-SSO-Sitzung braucht keinen erneuten Login. Die **PING-ID-Freigabe** erfolgt immer selbst am Smartphone.

- `--login-manuell`: gespeicherte Zugangsdaten bewusst nicht lesen, alles im Edge eingeben (auch mit `--nur-login` kombinierbar).
- `--sso-tresor`: einen vorhandenen, vollstaendigen Tresoreintrag **erzwingen**; andernfalls vor Browserstart abbrechen.
- `--benutzer-id NAME --passwort-abfragen`: alternative maskierte Passworteingabe in PowerShell; **niemals** das Passwort in die Kommandozeile schreiben.
- `--browser chromium`: nur fuer einen nach Unternehmensrichtlinien erlaubten Test; Playwright-Chromium muss ggf. separat installiert werden.

Das Edge-Profil dieses Skripts liegt unter `%USERPROFILE%\.ntf-insight\edge-diagnosis-warnungen` (getrennt vom NTF-Insight-QuickTest-Abruf), damit sich die Prozesse nicht gegenseitig blockieren. **Nicht parallel zwei Scraper mit demselben Profil oder der gleichen JSON starten.** Passwort, PIN und Login-Cookies werden nicht in die JSON geschrieben; der Betriebssystem-Tresor wird nur gelesen.

## Ablauf und Ausgabe

Je FIN fuehrt der Scraper die Suche mit `sources=XD,XD(AQT),TD,DAS` aus, klickt den **Augen-Link** jeder **nicht ausgeschlossenen** Sitzung (unabhaengig von der QuickTest-Anzahl), oeffnet **Warning and Error Messages** und liest die strukturierten Originalfelder aus den Diagnose-Antworten. Falls das nicht moeglich ist, liest er die sichtbare Tabelle einschliesslich virtualisierter Zeilen. Vorhandene Zaehler werden gegen die ausgelesene Anzahl geprueft; unvollstaendige Abfragen erhalten den Status `fehler`, nicht `keine_meldungen`.

Die **zusammengefuehrte** JSON-Datei enthaelt ein `fahrzeuge`-Objekt (FIN als Schluessel). Je Fahrzeug: `status`, `anzahl_sitzungen_gefunden`, `sitzungen`. Je Sitzung: Quelle, Diagnosezeitpunkt, Laufleistung, Abrufstatus, Auslesemethode (`datenstruktur`, `tabelle` oder `abschnitt_fehlt`) und `meldungen`. Bei ausgeschlossenen Sitzungen sind `auslesemethode` und `anzahl_meldungen` `null`; `ausschlussgruende` dokumentiert den Filter. Je Meldung: Kennung, ACTIVE-Status, erstes und letztes Auftreten mit Kilometerstand, Haeufigkeit, Zuendzyklen, Ereignistyp, Meldungstext und Lampen-/Tontext (wenn vorhanden in DE/EN). `rohdaten` bewahrt bei strukturierter Auslese die weiteren vom Viewer gelieferten Originalfelder.

Sitzungs-URLs und S3-Pfade werden **nicht** als Klartext in die JSON geschrieben; stattdessen wird eine stabile Sitzungskennung aus dem Original-Link abgeleitet. `keine_meldungen` bedeutet durch einen Datenbeleg oder eine eindeutige leere Tabelle bestaetigt, **nicht** Request-Fehler. Die FIN-Suche laesst fehlende/eine nicht verifizierte Anzahl nicht stillschweigend als erfolgreiche leere Historie durchgehen.

### Datenschutz und Live-Verifikation

**Keine** echten FINs, Diagnosedaten, HTML-Beispiele oder Browserprofile in GitHub, GitHub Actions, PR-Kommentare oder verteilte Pakete hochladen. Der Export enthaelt vertrauliche Fahrzeugdaten und gehoert auf berechtigte lokale Unternehmenslaufwerke. Die hier vorliegenden Tests laufen mit **synthetischen Werten**. Ein Live-Test im Mercedes-Unternehmensnetz mit einer freigegebenen FIN und einem manuellen Vergleich der Warnungstabelle ist noch notwendig; Aenderungen an der Diagnosis-Viewer-Oberflaeche koennen Selektoren beeinflussen.

## Tests

```powershell
py -3.11 -m pip install pytest
py -3.11 -m pytest -q tests/test_diagnosis_viewer_warn_error.py
```
