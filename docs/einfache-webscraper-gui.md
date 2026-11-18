# Einfache Webscraper-GUI – Optionen pro Datenquelle

Das separate Fenster startet die sechs bestehenden CLI-Downloader von NTF Insight.
Die Bedienung ist deutsch und benutzt eine zurückhaltende schwarz-weiß-graue Gestaltung.
Die CLI-Module, Anmeldung, FIN-Prüfung und Download-/Wiederaufnahmelogik bleiben erhalten.

## Start (Python 3.11 / Windows PowerShell)

```powershell
git switch main
git pull origin main
python -m pip install -e .
ntf-insight-scraper
```

Alternativ: `python -m ntf_insight.app.scraper_gui`.
Die Lightweight-GUI setzt eine Python-/Wheel-Installation voraus und ist derzeit
kein eigener Startknopf im bestehenden PyInstaller-Setup.

## Bedienung

1. **TXT-Datei auswählen**: lokalen Dateidialog für FINs (bei TIPS alternativ Fallnummern) öffnen.
2. Einen der sechs **Webscraper-Buttons** anklicken. **Jede Quelle** öffnet jetzt
   einen Einstellungsdialog mit ihren eigenen optionalen CLI-Parametern.
3. Gewünschte Felder ändern und **Abruf starten** drücken. **Abbrechen** schließt
   den Dialog, ohne einen neuen Prozess zu starten.
4. Gegebenenfalls SSO-/PING-ID-Anmeldung in Microsoft Edge bestätigen.
5. Die Statuszeile beobachten oder den Abruf abbrechen. Es läuft höchstens
   **ein** Quellenprozess gleichzeitig.

Die zuletzt bestätigten Optionen werden **pro Datenquelle nur während der
aktuellen Fensterlaufzeit** vorbelegt. Nicht geänderte Felder benutzen die
bestehenden CLI-Standardwerte. Es werden keine Shell-Befehle aus Nutzereingaben
erzeugt: Nur vorher definierte Flags werden als separate Prozessargumente übergeben.

## Parameter in den Dialogen

| Quelle | Verfügbare Einstellungen |
| --- | --- |
| **QEC** | Benennungsfilter (`--benennung`), Sachnummer, `--alle-bauteile`, **Anhangmodus `referenz`/`alle`**, SSO-Timeout, eigener Profilordner, manueller Login, Ausgabeort |
| **Diagnosis Viewer – QuickTests** | Erneut herunterladen, nur PDF (`--ohne-json`), SSO-Timeout, Profil, manueller Login, Ausgabeort |
| **XENTRY TIPS Writer** | SSO-Timeout, Profil, manueller Login, Ausgabeort (Eingabe über den globalen TXT-Dialog) |
| **Diagnosis Viewer – WEM** | Neue Sitzungen (`--aktualisieren`), erneut lesen, zusammenfassen, aufteilen, ohne Gesamt-JSON, nur Login, SSO-Tresor, Browser, fünf Zeit-/Abstandsparameter, Profil, manueller Login, Ausgabeort |
| **VeDoc – Fahrzeugcodes** | Erneut lesen, nur Login, Anmelde-/Ladezeit, Pause, Profil, manueller Login, Ausgabeort |
| **VeDoc – Hardwarehistorie** | Objekt (z. B. `CPC3`), Attribut, nur Login, Browser, Schritt-/Login-/Historien-Timeout, alternative freigegebene URL, manueller Login, Ausgabeort |

**QEC-Anhänge:** `referenz` ist die sichere Voreinstellung: Nur Dateien,
deren sichtbarer Dateiname die aktuelle QEC-Referenznummer bestätigt, werden
heruntergeladen. **`alle` lädt alle vom Downloader erkannten und im Popup
des jeweiligen passenden Schadteilfalls sichtbaren Anhänge**.
Ein sichtbarer Anhang ist dadurch nicht automatisch fachlich genau diesem
Fall zugeordnet; solche Dateien bleiben im `qec.json` als ungeprüft markiert.
Beispiel für DCDC: **QEC → Benennung `DCDC` → Anhänge `Alle im Fall-Popup sichtbaren Anhänge` → Abruf starten**.

**QEC-Filter:** Ohne Benennung und Sachnummer greift wie bisher der
Kühlmittelpumpen-Standardfilter. `DCDC` umfasst z. B. `DCDC223`.
Ein Komma verbindet alternative Benennungen durch ODER (`DCDC,DC/DC`).
Eine zusätzlich angegebene exakte Sachnummer wirkt als UND.

**Pfadoptionen:** Standardmäßig werden Downloads lokal unter
`%USERPROFILE%\.ntf-insight\abrufe\<TXT-Name>\<Quelle>` abgelegt
(oder unter `NTF_INSIGHT_DATA_DIR`, falls konfiguriert).
Ein optionaler anderer Ausgabeort kann im Popup ausgewählt werden.
WEM und VeDoc-Fahrzeugcodes benötigen als Ziel eine **`.json`-Datei**;
die anderen Quellen verwenden **Verzeichnisse**.
Browserprofile und Berichtsordner müssen voneinander getrennt bleiben.

**Sicherheit / Grenze:** Die Terminal-Parameter `--passwort-abfragen` und
`--benutzer-id` werden bewusst **nicht** im Popup angeboten: Der bestehende
CLI-Prozess wird ohne interaktives Terminal gestartet, und ein geheimer
Passwortwert darf nicht als Kommandozeilenargument oder Log erscheinen.
Stattdessen im Unternehmens-Browser manuell anmelden oder das unterstützte
Betriebssystem-Schlüsselspeicherverfahren verwenden. Für direkte
Passwortabfrage muss die betreffende CLI in PowerShell gestartet werden.

Ungültige Optionen (z. B. WEM `--sso-tresor` zusammen mit
`--login-manuell` oder gleichzeitig `--nur-aufteilen` und
`--nur-zusammenfassen`) werden vor dem Download abgelehnt.
Der Zugriff auf interne Portale erfordert weiterhin Microsoft Edge bzw.
den ausgewählten Browser, Unternehmenszugang und die nötigen Berechtigungen.
Keine realen FINs, Berichte, Browserprofile oder Zugangsdaten in GitHub speichern.

## QEC-Anhangfenster und Statusanzeige

Waehlt man `QEC` und `Anhaenge: alle`, werden alle **erkannten**
Links aus dem jeweiligen QEC-Fall-Popup geladen; ein fremder Dateiname
bleibt als nicht referenzbestaetigt markiert. Die CLI-Meldungen erscheinen
waehrend des Abrufs direkt unten im Fenster, unter anderem:

- `Anhangfenster geoeffnet; Dateiliste wird gelesen`
- `N QEC-Dateilink(s) erkannt (Anhangmodus: alle)`
- `QEC-Datei wird angefragt (max. 25s)`
- `versuche Edge-Download`, `gespeichert` oder `fehlgeschlagen`

Auch QEC-Unterframes und kurz nachgeladene Tabellen werden geprueft.
Bei **0 erkannten Links trotz sichtbarer Dateien** ist die konkrete
QEC-Linkstruktur zu pruefen; es werden keine fremden/ungeprueften
Webadressen abgerufen. Fehler und Hinweise werden weiterhin lokal
in `qec.json` je Schadteilfall dokumentiert.

## Regressionstests (ohne Unternehmenszugang)

```powershell
python -m pip install -e ".[dev]"
python -m pytest -q tests/test_scraper_gui.py tests/test_scraper_optionen.py
```

Die Tests überprüfen Dialoge und lokale CLI-Befehlsübergabe, nicht das echte
QEC-/TIPS-/VeDoc-Portal. Live-Abnahmen müssen auf einem berechtigten Arbeitsplatz erfolgen.

## Resume nach Abbruch

Die bereits gespeicherten Dateien und Checkpoints bleiben im lokalen Ausgabeordner.
Nach einem Abbruch die **gleiche FIN-/Fallliste** und den **gleichen Ausgabeordner**
erneut wählen und die Datenquelle wieder starten. Es werden grundsätzlich nur
nachweislich abgeschlossene Einheiten übersprungen:

- **QEC** prüft den FIN-Checkpoint, die dokumentierten Schadteilreferenzen,
  alle fünf Berichtsreiter, vorhandene Anhänge sowie **Benennung, Sachnummer
  und Anhangmodus**. Fehlende oder unvollständige Referenzen werden erneut
  verarbeitet. Alter Fallinhalt wird nicht als neu heruntergeladen ausgegeben.
- **QuickTests** prüft PDF-Sitzungen und fehlende Dateien, statt eine bloße
  24-Stunden-Frist als erfolgreichen Abschluss anzusehen.
- **TIPS Writer** verwendet vollständig gespeicherte Fall-/FIN-Checkpoints;
  unvollständige Fälle werden neu abgefragt.
- **WEM** speichert einzelne Diagnosesitzungen und setzt mit der nächsten
  unvollständigen FIN fort.
- **VeDoc-Fahrzeugcodes** schreibt nach jeder FIN und überspringt erfolgreich
  abgeschlossene FINs.
- **VeDoc-Hardwarehistorie** übernimmt erfolgreich bestätigte Historien aus
  der bestehenden JSON und ergänzt nur offene FINs; XLSX wird wiederhergestellt.

**Nicht nachgewiesene Vollständigkeit wird nicht übersprungen.** Ein
Abbruch mitten im Dateidownload lässt den letzten Fall oder die letzte
Sitzung eventuell unvollständig; dieser Teil wird beim Neustart geprüft.
Die Optionen **Erneut abrufen** in QEC, QuickTests, TIPS und VeDoc deaktivieren
das Überspringen bereits abgeschlossener Ergebnisse. In WEM/VeDoc-Fahrzeugcodes
existieren eigene Wiederholungsoptionen.

## FIN-Fortschritt und paralleler Abruf

In der Lightweight-GUI lassen sich **1 bis 6 unterschiedliche Datenquellen**
parallel starten (**Standard: 2**). Ein erneuter Start derselben Quelle ist
während ihres laufenden Prozesses gesperrt. Die FINs **innerhalb** einer Quelle
werden weiterhin nacheinander abgefragt; dadurch bleiben Portal-Sitzung und
lokale Checkpoints eindeutig. Jeder aktive Quellen-Button zeigt einen eigenen
FIN-Fortschritt, z. B. **FIN 2/80** (bei gemischten TIPS-Listen **Ziel 2/80**).
Bereits erledigte FINs zählen mit.

Über **Stop** kann eine einzelne Quelle beendet werden; mit **Alle laufenden
Abrufe abbrechen** werden alle Quellen beendet. Laufende Teildateien und
bisherige Berichte bleiben lokal erhalten. Wechsel der FIN-Liste und der
Parallelitäts-/SSO-Einstellungen ist während des Abrufs gesperrt.

### SSO-/PING-ID-Sperre

Auch bei parallelen Downloadern startet **nur eine SSO-/PING-ID-Anmeldung
gleichzeitig**. Nach erfolgreicher Anmeldung eines Quellenprozesses sperrt
die gemeinsame Betriebssystem-Dateisperre die nächste Anmeldung zusätzlich
für **45 Sekunden (Standard)**, einstellbar auf **30–60 Sekunden**.
Andere Quellen dürfen währenddessen nach ihrer erfolgten Anmeldung
**parallel Daten abrufen**. Die Pause gilt für neue Anmeldungen und wird
**nicht nach jeder bereits authentifizierten FIN** neu gestartet.

Die Sperrdatei liegt unter
`%USERPROFILE%\.ntf-insight\sso-anmeldung.lock` und enthält nur
Zeitstempel und Prozess-ID, **keine PING-ID-Nummern, Anmeldeinformationen
oder FINs**. PING-ID-Bestätigungen erfolgen weiterhin ausschließlich durch
berechtigte Nutzer in Edge bzw. der offiziellen Anmeldung.

**Grenze:** Zwei separate Lightweight-App-Instanzen können dieselbe Quelle
starten und um das gleiche Edge-Profil konkurrieren. Nur eine Instanz der App
verwenden; die Oberfläche verhindert Mehrfachstarts je Quelle innerhalb
ihres Fensters.
