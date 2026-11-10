# NTF Insight

## Schnellstart: Daten per CLI herunterladen (Windows / PowerShell)

Die sechs Datenquellen lassen sich mit einer **FIN-TXT-Datei** gemeinsam oder einzeln abrufen. Der Sammelbefehl startet die ausgewählten Quellen parallel; jede Quelle speichert ihre Ergebnisse getrennt. Voraussetzung: **aktuelle NTF-Insight-Entwicklungsversion** mit installierten CLI-Befehlen, Microsoft Edge und Berechtigung für die jeweiligen Unternehmenssysteme.

**Einmalig installieren bzw. nach einem Update erneut ausführen** (im Repository, mit aktivierter Python-Umgebung):

```powershell
python -m pip install -e .
```

**Eingabe:** `--eingabe` ist der Pfad zu einer `.txt`-Datei mit Fahrzeugkennungen (**eine FIN pro Zeile**). Alle sechs Quellen unterstützen vollständige, 17-stellige FINs. **Für VeDoc-Historie und QuickTests sind zusätzlich 14-stellige Mercedes-Kurz-FINs möglich.** Beispiel `FIN-Liste DCDC223 SensorIssue.txt`:

```text
WDD12345678901234
WDD12345678901235
```

*Die FINs hier sind fiktive Testwerte. Leere Zeilen und mit `#` beginnende Kommentare sind erlaubt. Echte FIN-Dateien nur lokal speichern, nicht ins Repository hochladen.*

**Alle sechs Quellen abrufen** (standardmäßig maximal zwei gleichzeitig):

```powershell
ntf-insight-beschaffung --eingabe ".\FIN-Liste DCDC223 SensorIssue.txt"
```

**14-stellige Kurz-FINs für VeDoc-Historie und QuickTests parallel** (mit fiktiven Testwerten, nicht mit echten Fahrzeugdaten):

```text
1671061B000001
1671061B000002
```

```powershell
ntf-insight-beschaffung --eingabe ".\\FIN-Liste DCDC223 SensorIssue.txt" --quellen vedoc-historie,quicktests --objekt DCDC223 --attribut Seriennummer --parallel 2
```

Dabei bleiben die 14 Zeichen unverändert; es wird **kein unbekannter 3-stelliger Herstellerpräfix ergänzt**. Ein vom Portal angezeigter 17-stelliger Wert wird nur akzeptiert, wenn seine letzten 14 Zeichen genau übereinstimmen. Bei mehrdeutigen Treffern wird der Abruf abgelehnt. `--quellen alle` und die vier anderen Quellen setzen für diese Version weiterhin 17-stellige FINs voraus.

**VeDoc-Hardwarehistorie für ein selbst gewähltes Objekt** (statt fest DCDC223):

```powershell
ntf-insight-vedoc-historie --eingabe ".\FIN-Liste DCDC223 SensorIssue.txt" --objekt CPC3
ntf-insight-vedoc-historie --eingabe ".\FIN-Liste DCDC223 SensorIssue.txt" --objekt CPC3 --attribut Hardwarestand
```

**VeDoc-Historie und QuickTests parallel** (frei gewähltes Objekt gilt nur für VeDoc):

```powershell
ntf-insight-beschaffung --eingabe ".\FIN-Liste DCDC223 SensorIssue.txt" --quellen vedoc-historie,quicktests --objekt CPC3 --parallel 2
```

**QEC nur für eine Sachnummer inklusive aller angezeigten Anhänge** (auch ohne QEC-Referenz im Dateinamen):

```powershell
ntf-insight-qec --eingabe ".\FIN-Liste DCDC223 SensorIssue.txt" --sachnummer "A 123 456 78 90" --anhaenge alle
```

**QEC ohne Sachnummer: per Benennung filtern** (z. B. DCDC-Varianten):

```powershell
ntf-insight-qec --eingabe ".\FIN-Liste DCDC223 SensorIssue.txt" --benennung DCDC --anhaenge alle
```

**Alle sechs Datenquellen parallel, QEC mit Benennungsfilter** (nur mit 17-stelligen Voll-FINs):

```powershell
ntf-insight-beschaffung --eingabe ".\FIN-Liste DCDC223 SensorIssue.txt" --quellen alle --parallel 6 --benennung DCDC --anhaenge alle
```

**QEC mit QuickTests und WEM parallel** (Sachnummer, Benennung und Anhangmodus gelten ausschließlich für QEC):

```powershell
ntf-insight-beschaffung --eingabe ".\FIN-Liste DCDC223 SensorIssue.txt" --quellen qec,quicktests,wem --sachnummer "A 123 456 78 90" --anhaenge alle --parallel 3
```

*Die Sachnummer oben ist fiktiv. Bei `--anhaenge alle` werden nicht eindeutig referenzbestätigte Anhänge in `qec.json` gekennzeichnet und müssen vor der fachlichen/ChatGPT-Auswertung geprüft werden. Ohne den Schalter bleibt die Referenzprüfung strikt.*

**Nur bestimmte Quellen, drei parallel:**

```powershell
ntf-insight-beschaffung --eingabe ".\FIN-Liste DCDC223 SensorIssue.txt" --quellen qec,quicktests,wem --parallel 3
```

**Alle sechs gleichzeitig mit eigenem Basisordner:**

```powershell
ntf-insight-beschaffung --eingabe ".\FIN-Liste DCDC223 SensorIssue.txt" --quellen alle --parallel 6 --ausgabe "D:\NTF\SensorIssue"
```

### Parameter und auswählbare Quellen

| Parameter | Eingabe / Standard | Bedeutung |
| --- | --- | --- |
| `--eingabe` | **Erforderlich:** `pfad\FIN-Liste.txt` | Textdatei mit den abzufragenden FINs; bei Leerzeichen Pfad in Anführungszeichen setzen. |
| `--quellen` | `alle` (Standard) oder kommagetrennte IDs | Nur die genannten Datenquellen abrufen, z. B. `qec,quicktests,wem`. Jede Quelle höchstens einmal angeben. |
| `--parallel` | Ganze Zahl von **1 bis 6**, Standard **2** | Maximale Zahl gleichzeitig laufender **Datenquellen** (nicht FINs). Innerhalb einer Quelle werden FINs nacheinander abgearbeitet. |
| `--ausgabe` | Optional: Ziel-**Basisordner** | Ohne Angabe: `data/processed/<bereinigter TXT-Dateiname>/`. |
| `--objekt` | Optional, z. B. `CPC3`; Standard `DCDC223` | Exakter Name des VeDoc-Hardwareobjekts im Historienreiter. Gilt nur für die Quelle `dcdc223` bzw. `vedoc-historie`. |
| `--attribut` | Optional, z. B. `Hardwarestand`; Standard `Seriennummer` | Exakter Name des VeDoc-Historienattributs. Gilt nur für VeDoc-Historie. |
| `--sachnummer` | Optional, z. B. `"A 123 456 78 90"` | **Nur QEC:** Exakte Sachnummer für alle FINs der TXT; damit werden auch Bauteile ohne Pumpenbezeichnung gesucht. |
| `--benennung` | Optional, z. B. `DCDC` | **Nur QEC:** Textsuche in „Benennung“, ohne Sachnummer möglich; Groß-/Kleinschreibung egal, Kommas trennen alternative Suchbegriffe (ODER). Mit `--sachnummer` kombiniert gilt UND. Alias: `--keyword`. |
| `--anhaenge` | `referenz` (Standard) oder `alle` | **Nur QEC:** Strikter Referenzabgleich am Dateinamen oder Download sämtlicher im QEC-Fall-Popup sichtbarer Dateien mit ungeprüfter Zuordnung. |
| `--login-manuell` | Optionaler Schalter | Automatisches Ausfüllen der SSO-Anmeldedaten deaktivieren; die PING-ID-Freigabe bleibt immer manuell. |

| Quellen-ID für `--quellen` | Datenquelle | Inhalt |
| --- | --- | --- |
| `dcdc223` (Alias: `vedoc-historie`) | VeDoc – beliebiges Hardwareobjekt, Standard DCDC223 | Seriennummern- und Attributänderungshistorie (JSON/Excel) |
| `wem` | Diagnosis Viewer – WEM | Warn- und Fehlermeldungen (JSON) |
| `sa-codes` | VeDoc – Fahrzeugcodes | Fahrzeug-/SA-Codes (JSON) |
| `quicktests` | Diagnosis Viewer – QuickTests | Kurztest-PDFs |
| `qec` | QEC | Befundungsfälle und Anhänge |
| `tips` | XENTRY TIPS Writer | Fälle und Anhänge |

**Unterschiedliche Hardwareobjekte:** Die neue Direkt-CLI heißt `ntf-insight-vedoc-historie`. Der alte Befehl `ntf-insight-vedoc-dcdc223` bleibt erhalten und kann ebenfalls `--objekt` und `--attribut` verwenden. Ein benutzerdefiniertes Ziel wird nach `vedoc_historie/` exportiert, nicht mit DCDC223-Ergebnissen vermischt. Die Auswahl muss dem **tatsächlich in VeDoc angezeigten Objekt-/Attributnamen** entsprechen; der Scraper prüft beide exakt und bestätigt die vollständige FIN.

**Standardablage:** Bei `FIN-Liste DCDC223 SensorIssue.txt` entsteht `data/processed/FIN-Liste DCDC223 SensorIssue/` mit sechs getrennten Quell-Unterordnern, z. B. `qec/`, `diagnosis_viewer_quicktests/` und `vedoc_codes/`. Ungültige Windows-Zeichen im TXT-Dateinamen werden ersetzt; vorhandene ältere Downloads werden nicht automatisch verschoben. `--ausgabe` überschreibt die automatische Basisordnerwahl.

**Parallele Anmeldung:** **Alle sechs CLI-Datenquellen** nutzen die gemeinsame betriebssystemseitige SSO-/PING-ID-Sperre: Die erste Quelle meldet sich an und erhält bei Bedarf ihre **manuell** bestätigte PING ID, dann startet die Anmeldung der nächsten Quelle. Nach erfolgreichem Login laufen die Datenabrufe **parallel** weiter. Die sechs Edge-Profile bleiben getrennt. Auch ein später erforderlicher erneuter Login wird über die Sperre koordiniert. `--parallel 6` setzt für alle Quellen 17-stellige FINs voraus.

**QuickTest-Wiederaufnahme:** Die QuickTest-CLI **ignoriert die frühere 24-Stunden-Sperre**. Sie überspringt eine FIN nur bei bereits vorhandener, lesbarer PDF in genau `diagnosis_viewer_quicktests/<FIN>/`. Fehlt eine PDF, wird selbst nach einem fehlgeschlagenen oder als „Keine Quicktests“ protokollierten Abruf neu angefragt. `ntf-insight-quicktests --erneut` lädt auch FINs mit bereits vorhandenen PDFs nochmals. Die GUI behält ihre separate bisherige Wiederholungsregel.

**Einzelabrufe:** Alternativ `ntf-insight-qec --eingabe .\fins.txt`, `ntf-insight-quicktests --eingabe .\fins.txt` usw. starten. Die vollständige Anleitung mit allen sechs Einzelbefehlen, Unterordnern und Optionen steht in [Datenbeschaffung per CLI](docs/datenbeschaffung-cli.md). Die Details zu frei gewählten Hardwarehistorien findest du unter [VeDoc-Hardwarehistorie](docs/vedoc-hardware-historie.md).

---

**NTF Insight hilft dabei, „No Trouble Found“-Fälle (NTF) zu untersuchen.** Das bedeutet: Ein Bauteil wurde im Fahrzeug ausgetauscht, aber bei der späteren Prüfung wurde kein Fehler gefunden.

Im Mittelpunkt steht zurzeit die **Kühlmittelpumpe**. Die App sammelt und vergleicht Informationen aus Fahrzeugdiagnosen, Werkstattdaten und Befundungsberichten.

## Ziele der App

NTF Insight soll helfen, **NTF-Fälle schneller und nachvollziehbarer aufzuklären**. Im Mittelpunkt steht der gesamte Fahrzeug- und Werkstattverlauf – nicht nur das zurückgesendete Bauteil.

Die App soll folgende Fragen beantworten:

- **Warum ist der Fall NTF?** Warum wurde das Bauteil ausgetauscht, obwohl die Befundung keinen passenden Fehler gefunden hat?
- **War der Austausch notwendig?** Hat der Tausch das Problem behoben oder lag die Ursache möglicherweise woanders?
- **Tritt der Fehler erneut auf?** Welche Fehlercodes (DTCs) gab es vor und nach dem Tausch? Wann und nach wie vielen Kilometern traten sie erneut auf? Sind neue Fehler hinzugekommen?
- **Was meldet das Fahrzeug?** Welche Hinweise liefern CPC3, andere Steuergeräte, Kurztests und die Fahrzeughistorie?
- **Wo liegt die mögliche Ursache?** Zum Beispiel im Bauteil, in der Verkabelung, der Spannungsversorgung, der Software, im übrigen Kühlsystem oder im Werkstattablauf.
- **Ist ein Lieferant verantwortlich?** Welche Daten sprechen für oder gegen einen Lieferantenfehler? Was ist noch ungeklärt?
- **Welche Rolle spielen Hard- und Software?** Hängen Fehler mit Steuergeräteversionen, Softwareänderungen oder geänderten Diagnosebedingungen zusammen?
- **Welche Fälle ähneln sich?** Lassen sich ähnliche Beschwerden, DTCs und Abläufe in Clustern zusammenfassen? Haben vergleichbare Maßnahmen geholfen?
- **Gibt es Auffälligkeiten im Feld?** Zum Beispiel bei Baureihen, Teilenummern, Lieferanten, Chargen, Produktionszeiträumen oder Softwareständen.
- **Welche Fälle sind besonders wichtig?** Welche Fälle sollten Fachleute zuerst prüfen, und welche Informationen fehlen für eine sichere Bewertung?
- **Wie lässt sich die Arbeit automatisieren?** Berichte herunterladen, einlesen, nach FIN zusammenführen, auswerten und verständliche Fallberichte erstellen.

Die Anwendung soll später auch für **andere Bauteile** genutzt werden können, zum Beispiel HV-Batterien, weitere Pumpen, Sensoren oder Steuergeräte.

## Stand der Umsetzung

### Bereits vorhanden (Testversion)

- **Fahrzeuge und Fälle:** FINs, Fälle und importierte Daten anzeigen; Fälle und Ereignisse auch manuell erfassen.
- **Datenimport:** QuickTest-PDFs, QEC-Excel, AutoExport-CSV, ausgewählte weitere Formate und ZIP-Dateien lokal einlesen.
- **Zeitachse:** DTCs, Werkstattmaßnahmen, Steuergerätestände und mögliche Bauteiltausche zeitlich darstellen.
- **Vorher-/Nachher-Vergleich:** Wiederkehrende, verschwundene und neue DTCs auswerten, soweit ein ausreichend belegter Tauschzeitpunkt und passende Diagnosedaten vorliegen.
- **Ähnliche Fälle:** Fallähnlichkeiten berechnen, Cluster bilden und in einem 2D-Streudiagramm anzeigen.
- **Erste Hinweise:** Vorhandene Daten auf mögliche Ursachen und Datenlücken prüfen; grundlegende Lieferantenübersichten anzeigen.
- **Nachvollziehbarkeit:** Originaldateien lokal aufbewahren, Änderungen dokumentieren und Fallberichte als Markdown exportieren.

### Noch nicht umgesetzt oder fachlich zu prüfen

- **Produktive Freigabe des automatischen Berichtsdownloads:** CLI-Anbindungen für sechs Quellen sind technisch vorhanden; echte SSO-/PING-ID-Abläufe, Systemberechtigungen und vollständige Datenerfassung müssen im Unternehmensnetz noch validiert werden.
- **Weitere Datenformate**, insbesondere Lieferanten-Befundungsberichte, SMR-D-Diagnosebedingungen und vollständige Software-/Änderungshistorien.
- **Kühlmittelpumpen-spezifische Diagnose:** Tatsächliche CPC3-DTCs, Auslösebedingungen, Fehlerbilder und Prüfregeln mit Fachleuten validieren.
- **Verlässliche Ursachenbewertung:** Hinweise aus Fahrzeug, Werkstatt und Befundung zusammenführen, die Regeln an echten Fällen prüfen und fachlich bestätigte Ursachen dokumentieren.
- **Lieferantenbewertung mit belastbaren Kennzahlen:** Teilenummern, Chargen und Produktionsdaten verknüpfen und NTF-Raten nur mit passender Anzahl verbauter Teile berechnen.
- **Bessere Mustererkennung:** Cluster-Gewichte und Grenzwerte mit realen Fällen prüfen; weitere ML-Verfahren nur bei ausreichender Datenqualität ergänzen.
- **Mehr Automatisierung und Berichte:** Größere Feldtrends auswerten, fehlende Daten gezielt anzeigen und Berichte später auch als PDF/HTML ausgeben.
- **Einfachere Verteilung:** Eigenständige Windows-App ohne separate Python-Installation und weitere Bauteilprofile.

Der detaillierte Entwicklungsstand steht in der [Roadmap](ROADMAP.md).

**Wichtig:** Ein Cluster oder ein Fehlercode beweist nicht, wer einen Fehler verursacht hat. Insbesondere eine Verantwortung des Lieferanten muss anhand der Originaldaten geprüft werden.

**Stand:** Die App ist noch eine Testversion. Einige Funktionen und Datenformate werden weiterentwickelt.

## Download und Installation (Windows 64 Bit)

**[NTF Insight auf GitHub herunterladen](https://github.com/gregoriuscahyanto/ntf-insight/releases)**

Du kannst zwischen zwei Installationswegen wählen.

### Weg 1: Windows-Setup (empfohlen)

1. `NTF-Insight-Setup-0.1.0.exe` oder eine neuere Version aus **Releases** herunterladen.
2. Auf den Ziel-PC übertragen und das Setup **doppelklicken**.
3. NTF Insight über die **Desktop-Verknüpfung** oder das **Startmenü** öffnen.

**Python ist nicht nötig.** Alles wird mit dem Setup installiert. Auch auf einem PC ohne Internet nutzbar.

### Weg 2: Wheel mit automatischer Offline-Installation

Dieser Weg eignet sich, wenn du Python bereits installiert hast oder das Wheel weitergeben möchtest.

1. Falls noch nicht vorhanden: [**Python 3.11.9 für Windows 64 Bit herunterladen**](https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe) und auf dem Ziel-PC installieren.
2. Aus **Releases** das Paket `NTF-Insight-Wheel-Offline-0.1.0-Windows-x64-Python311.zip` (oder eine neuere Version) herunterladen und vollständig entpacken.
3. Die Datei **`installiere_offline.cmd` doppelklicken**.
4. NTF Insight danach über die angelegte Verknüpfung starten.

Das Skript richtet automatisch eine `venv` ein und installiert alle mitgelieferten Wheels **ohne Internetverbindung**. **Eine einzelne `.whl`-Datei allein reicht für einen Offline-PC nicht**, weil weitere Python-Pakete benötigt werden.

**Noch kein Download sichtbar?** Die Pakete müssen erst über den GitHub-Workflow veröffentlicht werden.

## Entwicklungs-Branch auf neuem Windows-PC starten (PowerShell)

Dieser Weg installiert die aktuelle Entwicklungsfassung einschließlich der
projektbezogenen Workflows. Für die veröffentlichte Setup-Version sind
keine Python-Abhängigkeiten notwendig.

Vorher **Git**, **Python 3.11 (64 Bit)** und für die Erstinstallation
Internetzugang bereitstellen.

```powershell
git clone --branch feature/workflow-zentrale-sachnummer-20261024 https://github.com/gregoriuscahyanto/ntf-insight.git
cd ntf-insight
py -3.11 -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
python -m playwright install chromium
ntf-insight
```

Bei einem vorhandenen Checkout stattdessen im Repository
`git switch feature/workflow-zentrale-sachnummer-20261024`
und `git pull --ff-only` ausführen, die `.venv` aktivieren
und Abhängigkeiten mit `python -m pip install -e ".[dev]"` aktualisieren.

**Wichtig:** Code-Installation und Projektdaten sind getrennt. Ein neuer
PC erhält QEC-FINs, QuickTests, ChatGPT-Ergebnisse und Unterlagen erst
über **Projekt-Export / Projekt-Import** mit einer `.ntfproject`-Datei
oder über einen gesonderten Gesamtstandtransfer. Das Projektpaket kann
vertrauliche Originaldaten enthalten und muss über freigegebene Wege
übertragen werden.

## Neue Version auf GitHub veröffentlichen (Entwicklung)

1. [**Actions → Windows Release – Setup und Wheel**](https://github.com/gregoriuscahyanto/ntf-insight/actions/workflows/release-windows.yml) öffnen.
2. **Run workflow → main** auswählen.
3. Unter **paket** `beide` (empfohlen), `setup` oder `wheel` auswählen.
4. Workflow starten. Nach erfolgreichem Test erscheinen die Dateien unter **[Releases](https://github.com/gregoriuscahyanto/ntf-insight/releases)**.

**Wenn du bereits ein eigenes Wheel erstellt hast:** Du kannst es direkt als Datei in einen GitHub Release hochladen. Für die Installation ohne Internet müssen die passenden Abhängigkeiten mitgeliefert werden. Dafür gibt es das Skript `scripts/baue_offline_wheel_paket.ps1`. Die [technische Anleitung](docs/windows-setup.md) erklärt beide Wege.

**Sicherheit:** Beide Pakete werden standardmäßig auf einem isolierten GitHub-Windows-Runner gebaut, nicht auf den Self-Hosted-Runnern mit vertraulichen Fahrzeugdaten. Das Setup ist derzeit **nicht unternehmenssigniert**; auf Firmen-PCs kann eine IT-Freigabe nötig sein.

## Daten und Datenschutz

Importierte Daten und Berichte bleiben auf dem jeweiligen Rechner. Standardmäßig speichert die App sie unter `%USERPROFILE%\.ntf-insight\`.

**Keine echten FINs, Werkstattberichte, vertraulichen Lieferantendaten oder Zugangsdaten in GitHub hochladen** – auch nicht in Releases.

## Weitere Informationen

- [Sechs Datenquellen per CLI abrufen (VeDoc, Diagnosis Viewer, QEC, TIPS)](docs/datenbeschaffung-cli.md)
- [Daten importieren](docs/real-data-import.md)
- [FIN- und Fallanalyse bedienen](docs/fin-workspace.md)
- [CPC3-Softwarestand und Pumpentausch bewerten](docs/cpc3-softwareanalyse.md)
- [VeDoc-Fahrzeugcodes aus einer FIN-Liste abrufen](docs/vedoc-codes-abruf.md)
- [Technischer Aufbau](docs/architecture.md)
- [Entwicklungsplan](ROADMAP.md)
