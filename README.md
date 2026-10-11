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

- [Daten importieren](docs/real-data-import.md)
- [FIN- und Fallanalyse bedienen](docs/fin-workspace.md)
- [Technischer Aufbau](docs/architecture.md)
- [Entwicklungsplan](ROADMAP.md)
