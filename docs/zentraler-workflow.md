# NTF Insight – horizontaler Arbeitsworkflow (Ausbaustufe 1)

## Prinzip

Die Startseite zeigt **sechs kompakte Stationen in einer Zeile** mit Ampelstatus.
Ein Klick schaltet den **Arbeitsbereich darunter** um – die Anwendung verlässt
die Workflow-Seite nicht. Das Fenster besitzt keinen globalen Scrollbereich,
nur die eingebetteten FIN-/QEC-Tabellen scrollen bei Bedarf intern.

**Ampel:** Grün = vollständig bzw. fachlich bestätigt; Gelb = teilweise;
Grau = noch offen; Rot = beim jeweiligen Schritt ist ein Import-/Datenfehler
aufgetreten. Die aktive Station ist zusätzlich blau umrandet. Der Prozentbalken
summiert Statusfortschritt (teilweise = halber Schritt), keine Qualitätssicherheit
und keine Wahrscheinlichkeit einer Lieferantenverursachung.

## 01 – QEC-FIN-Liste

- **QEC-FIN-Liste importieren:** eine oder mehrere QEC-Excel-Dateien auswählen;
  verwendet den bewährten Quellenimport mit SHA-256 und Ein-Datei-Regel für die
  primäre QEC-Liste. **Import abbrechen** beendet sicher nach der laufenden
  Datei. **Import fortsetzen** verarbeitet die zuletzt ausgewählten Dateien
  idempotent erneut, soweit der aktuelle App-Lauf sie noch kennt.
- **QEC öffnen · FIN-Liste herunterladen:** öffnet das berechtigte QEC-Portal.
  Dort müssen **Sachnummer filtern und Excel herunterladen bisher manuell**
  erfolgen. Ein freigegebener automatischer Download einer vollständigen FIN-Liste
  nur anhand der Sachnummer ist im Repository **nicht vorhanden** und wird nicht
  vorgetäuscht. Die Excel-Datei anschließend importieren.
- **Gefilterte FIN-Liste als CSV:** exportiert ausschließlich die bereits
  importierten QEC-Zeilen der eingegebenen Sachnummer. Das ist ein lokaler Export,
  kein neuer QEC-Abruf. Die CSV enthält echte FINs und erfordert einen
  freigegebenen internen Speicherort.
- Tabelle: FIN, QEC-Fall, Referenz, Sachnummer, SSL-Endbefund, TP-Abdeckung,
  QEC-NTF-Entscheidung, QEC-Bericht vorhanden.

## 02 – QEC-Befundungsberichte

- **Alle QEC-Berichte herunterladen/aktualisieren** oder **Markierte
  herunterladen**. Quelle ist die in Schritt 1 importierte und nach Sachnummer
  gefilterte FIN-/Referenzliste.
- Nur validierte FINs mit **exakter QEC-Referenz** werden über den bestehenden
  QEC-Worker abgerufen; Downloadwünsche ohne valide Referenz werden nicht
  stillschweigend auf alle QEC-Fälle einer FIN ausgeweitet.
- Der bestehende Mercedes-SSO-/Edge-Login, Mengenbestätigung, Abbruch und
  automatische lokale Quellenimport bleiben erhalten.
- Eine kompakte Tabelle zeigt die FIN, Fall- und Referenznummer, Sachnummer
  sowie **letztes lokales Download-Datum** und Berichtstatus. Daten zu
  anderen Teilenummern werden beim Abruf nicht als Ziel aufgenommen.
- **Abruf abbrechen** wirkt auf den tatsächlich laufenden QEC-Worker;
  **Lokale Berichte einlesen** verwendet den vorhandenen Quellenimport.

## 03 – NTF-Entscheidung

- **Für ChatGPT exportieren (ZIP)** verwendet das schon vorhandene
  pseudonymisierte Analysepaket mit \`chatgpt_ergebnis_vorlage.json\` und
  \`chatgpt_ergebnis_schema.json\`. Keine automatische Übertragung.
- **ChatGPT-Ergebnis importieren (JSON)** prüft Paket-ID, Belegreferenzen,
  Pseudonym-Zuordnung und speichert Vorschläge **getrennt und ungeprüft**.
- Tabelle: FIN, QEC-Fall, SSL-Endbefund, manuelle QEC-Entscheidung,
  ChatGPT-Vorschlag und Prüfstatus. Ein importierter ChatGPT-Vorschlag
  überschreibt **keine** QEC-Entscheidung und weist **keine** Schuld zu.
- **Wichtig:** Der bestehende KI-Analysepaketexport umfasst zurzeit **alle
  lokal importierten Fälle**, nicht automatisch nur die gewählte Sachnummer.
  Bei gesetztem Sachnummernfilter gibt es davor eine explizite Warnung.

## 04–06 – weitere Bearbeitungsstationen

Diagnosen, Cluster und Auswertung öffnen vorerst die bereits vorhandenen,
etablierten Detailsichten. Ihre gesonderten kompakten Schrittoberflächen
werden anschließend fachlich ausgestaltet. Der bisherige globale
Import-/Export-Buttonblock entfällt; allgemeiner Selbstimport und
PC-Gesamtstandtransfer sind zunächst bei Schritt 06 erreichbar.

## Speicher und Datenschutz

Der aktuelle Schritt, der Pause-Status und manuelle Bestätigungen liegen pro
Bauteilprofil/Sachnummer in der lokalen DuckDB und werden mit dem bestehenden
\`.ntfbackup\` mitgenommen. Pausieren beendet **keinen** bereits laufenden
Download; dafür sind die gesonderten Abbruchschaltflächen zuständig.

\`.ntfbackup\` ersetzt beim PC-Import den lokalen Datenbestand und ist **nicht
verschlüsselt**. QEC-, FIN-, Lieferanten- und Werkstattdaten dürfen nur
auf freigegebenen Systemen weitergegeben werden; keine Originalbelege oder
echte FINs in GitHub, GitHub-Actions-Artifacts oder ungeprüfte externe Uploads.
