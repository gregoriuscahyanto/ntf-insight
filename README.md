# NTF Insight

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

- **Automatischer Berichtsdownload** aus den tatsächlichen internen Quellsystemen. Die technische Grundlage ist vorhanden, die Anbindungen fehlen noch.
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

## Download und Installation ohne Internet

**[NTF Insight auf GitHub herunterladen (Releases)](https://github.com/gregoriuscahyanto/ntf-insight/releases)**

Auf dem Ziel-PC wird **Windows (64 Bit) mit Python 3.11 (64 Bit)** benötigt.

1. Auf einem PC mit Internet die Datei `NTF-Insight-Offline.zip` aus dem neuesten GitHub Release herunterladen.
2. Das ZIP über einen freigegebenen Weg auf den Ziel-PC übertragen.
3. Das ZIP entpacken. Darin muss sich der Ordner `wheels` befinden.
4. Im entpackten Ordner **PowerShell** öffnen und diese Befehle nacheinander ausführen:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --no-index --find-links .\wheels ntf-insight
.\.venv\Scripts\ntf-insight.exe
```

Beim nächsten Start genügt:

```powershell
.\.venv\Scripts\ntf-insight.exe
```

Für die Installation der App ist keine Internetverbindung nötig. Der Zugriff auf interne Systeme zum Herunterladen von Berichten kann weiterhin eine Netzwerkverbindung erfordern.

**Falls unter „Releases“ noch keine Datei angezeigt wird, wurde noch kein Installationspaket veröffentlicht.** Python muss auf dem Ziel-PC bereits installiert oder separat über einen freigegebenen Weg bereitgestellt werden.

## Neues Installationspaket auf GitHub veröffentlichen

Dieser Abschnitt ist für die Entwicklung gedacht. Das Paket muss auf einem **Windows-64-Bit-PC mit Python 3.11 und Internetzugang** erstellt werden.

Im Hauptordner des Projekts PowerShell öffnen:

```powershell
Remove-Item -Recurse -Force .\dist\wheels -ErrorAction SilentlyContinue
py -3.11 -m pip wheel . --wheel-dir .\dist\wheels
Compress-Archive -Path .\dist\wheels -DestinationPath .\dist\NTF-Insight-Offline.zip -Force
```

Danach auf GitHub:

1. **Releases → Draft a new release** öffnen.
2. Ein neues Versions-Tag anlegen, zum Beispiel `v0.1.0`.
3. Die Datei `dist\NTF-Insight-Offline.zip` als Release-Datei hochladen.
4. Den Release veröffentlichen.

Das ZIP enthält die App als Wheel **und alle benötigten Python-Pakete**. Es gehört in einen GitHub Release, **nicht als große Datei in das Git-Repository**.

## Daten und Datenschutz

Importierte Daten und Berichte bleiben auf dem jeweiligen Rechner. Standardmäßig speichert die App sie unter `%USERPROFILE%\.ntf-insight\`.

**Keine echten FINs, Werkstattberichte, vertraulichen Lieferantendaten oder Zugangsdaten in GitHub hochladen** – auch nicht in Releases.

## Weitere Informationen

- [Daten importieren](docs/real-data-import.md)
- [FIN- und Fallanalyse bedienen](docs/fin-workspace.md)
- [Technischer Aufbau](docs/architecture.md)
- [Entwicklungsplan](ROADMAP.md)
