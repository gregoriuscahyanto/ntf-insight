# NTF Insight

**NTF Insight hilft dabei, „No Trouble Found“-Fälle (NTF) zu untersuchen.** Das bedeutet: Ein Bauteil wurde im Fahrzeug ausgetauscht, aber bei der späteren Prüfung wurde kein Fehler gefunden.

Im Mittelpunkt steht zurzeit die **Kühlmittelpumpe**. Die App sammelt und vergleicht Informationen aus Fahrzeugdiagnosen, Werkstattdaten und Befundungsberichten.

## Was kann die App?

- Fahrzeuge und Fälle anhand ihrer FIN anzeigen.
- Berichte importieren, zum Beispiel QuickTest-PDF, QEC-Excel, AutoExport-CSV oder ZIP-Dateien.
- Fehlercodes (DTC), Werkstattmaßnahmen und Bauteiltausche auf einer Zeitachse darstellen.
- Prüfen, ob Fehler vor und nach einem dokumentierten Bauteiltausch auftreten.
- Ähnliche Fälle finden und als Cluster darstellen.
- Hinweise auf mögliche Ursachen und fehlende Informationen sichtbar machen.

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
