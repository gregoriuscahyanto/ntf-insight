# NTF Insight – horizontaler Arbeitsworkflow (Ausbaustufe 1)

## Prinzip

Die Startseite zeigt **fünf kompakte Stationen in einer Zeile** mit Ampelstatus.
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

## 04 – Unterlagen für die zweite ChatGPT-Clusteranalyse

Die fünf Workflowstationen bleiben **in einer Zeile**. Schritt 04 zeigt
darunter **ein Sammel-Dashboard**, keinen zusätzlichen Seiten-Scrollbereich.
Alle Unterlagen werden je Bauteilprofil und Sachnummer verwaltet; die
Tabellen darin dürfen für viele Dateien intern scrollen.

| Quelle / Datei | Workflow-Aktion | Technische Grenze |
| --- | --- | --- |
| **TP Dashboard** | CSV/Excel/PDF auswählen, im Rohdatenarchiv speichern | Noch kein TP-Dashboard-Scraper implementiert: Abrufbutton ist sichtbar deaktiviert |
| **Diagnosis Viewer** | QuickTests für alle bzw. in Schritt 02 markierte QEC-FINs abrufen, Stop | Vorhandener Edge-/SSO-Downloader; 24-h-Regel und sicherer Quellenimport bleiben erhalten |
| **TIPS Writer** | TIPS-Fälle für alle bzw. markierte QEC-FINs abrufen, Stop | Bestehender TIPS-Worker; Live-Abruf bedarf Prüfung im Unternehmensnetz |
| **Celonis** | Exportdateien auswählen und archivieren | Noch kein Celonis-Scraper/Portal-Link implementiert, daher kein erfundener Abruf |
| **CDD / SMR-D** | Ein oder mehrere technische Quelldokumente wählen | Als Original archiviert, keine automatische Validierung der DTC-Setzbedingungen |
| **ECU-Nachrichtenliste** | Datei auswählen | Fachliche Interpretation erfolgt erst im ChatGPT-Kontext |
| **Setzbedingungen** | Excel auswählen | Keine automatische Extraktion aus beliebigen Excel-Varianten |
| **Vehicle Network Topology** | Dateien auswählen | Keine erfundene Topologie aus Dateinamen |
| **HW-Änderungsstände** | Dateien auswählen | Fachliche HW-Zuordnung nicht aus Dateinamen ableiten |
| **SW-Änderungsstände** | Dateien auswählen | Fachliche SW-Zuordnung nicht aus Dateinamen ableiten |
| **Weitere Unterlagen** | Kühlungsschema, Pumpendatenblatt, Schaltplan usw. wählen | Kategorie bleibt frei für weitere Bauteile |

Der Datei-Import archiviert die Originaldatei ohne automatisches Parsen
mit SHA-256 und führt die Zuordnung in der lokalen DuckDB unter
\`cluster_evidence_files\`. Duplikate werden identifiziert; dieselbe Datei
darf in unterschiedlichen Sachnummernkontexten verwendet werden.
**Zuordnung entfernen** löscht niemals die gemeinsame Rohdatei.
Die bisherigen Datenquellenparser bleiben unverändert nutzbar.

### Neuer Ablauf: Keine doppelte Paketauswahl

Die Arbeit geschieht in **fünf horizontalen Schritten**, mit
einer einzigen integrierten lokalen Clusteranalyse:

1. **QEC-FIN-Liste:** Excel/Portal, Sachnummern-Kohorte.
2. **QEC-Befundung:** Berichte nach FIN und QEC-Referenz.
3. **NTF-Entscheidung:** Erstes pseudonymisiertes KI-Paket exportieren,
   Rückgabe-JSON über bestehenden validierten ChatGPT-Import einlesen.
   Bei erfolgreich exportierten Paketen wird zusätzlich eine
   **SHA-256-gesicherte Kopie im lokalen raw/-Archiv** registriert.
   Paket-ID, Profil und Sachnummer werden in DuckDB gespeichert und
   über das vorhandene \`.ntfbackup\` mitgenommen.
4. **Unterlagen:** Nur Sammeln, Klassifizieren und Anzeigen der technischen
   Dokumente. Kein \`erstes Paket wählen\` und kein ChatGPT-Export.
5. **Clusteranalyse:** Der **bestehende HDBSCAN-/AutoExport-/QEC-Workspace**
   wird genau einmal in der Workflow-Seite angezeigt. Die bisherige
   Clusterregisterkarte in Fälle/FIN entfällt; Fälle/FIN dient weiterhin
   dem Fall- und Diagnosenachweis. Außerdem:
   **\`2. ChatGPT-Paket exportieren\`**, **\`Cluster-Ergebnis importieren\`**
   und fachliche Bestätigung. Das erste exportierte Paket und die erste
   importierte JSON-Auswertung werden automatisch mittels \`paket_id\`
   miteinander verknüpft. Der Export funktioniert erst, wenn beides vorliegt.

Das zweite Clusterpaket enthält das **erste gespeicherte ChatGPT-Ergebnis**
als \`voranalyse/erstes_chatgpt_ergebnis.json\` zusätzlich zu \`basis/\`,
\`cluster_kontext_manifest.json\`, \`CHATGPT_2_DURCHLAUF.txt\` und einer
**neuen** \`analyse_id\` mit derselben \`paket_id\`. Die Rückimportprüfung
akzeptiert nur eine aus diesem Projekt tatsächlich erzeugte zweite
Analyse-ID; nicht zugeordnete Pakete werden abgewiesen.

Die technischen Unterlagen aus Schritt 04 erscheinen im Kontextmanifest
als Kategorien/Belegkennungen. Die unveränderten Fachdateien selbst werden
nur bei aktiver **\`Technische Originale beifügen (vertraulich)\`**-Option
beigefügt. Die erste ChatGPT-Auswertung kann ebenfalls vertrauliche
Freitexte enthalten; vor jeder Weitergabe prüfen und intern freigeben.
Es erfolgen keine automatischen Uploads.

Die lokale Clusterberechnung bleibt bei der aktuellen Ausbaustufe
pumpenspezifisch und wird nur für ein Kühlmittelpumpen-Projekt mit Sachnummer
aktiviert. Für andere Bauteile müssen geeignete Diagnosemerkmale
fachlich definiert werden. Für die Merkmalsbildung gelten weiterhin
vor-Tausch-DTCs, nicht NTF-/Lieferantenbewertungen oder Nach-Tausch-Ergebnisse.

## Projekte, Einstellungen und PC-Datenaustausch

**Oben in der Workflow-Kopfzeile:** \`Bauteil [Sachnummer]\`,
Projektauswahl, \`+ Neues Projekt\`, \`Einstellungen\`,
\`PC-Export\`, \`PC-Import\`. Es gibt keinen sechsten Schritt für
den Datenaustausch.

Die **Projekteinstellungen** sind eine eigene Seite: Bauteilprofil,
Sachnummer, editierbare Bauteilbezeichnung, freie Liste wichtiger
Steuergeräte (z. B. CPC3, MCM) und optionale Projektbeschreibung.
Ein neues Projekt benötigt eine neue Sachnummer; bereits vorhandene
Bauteil-/Sachnummern-Kombinationen bleiben eindeutig und werden per
Projektauswahl wieder aufgerufen. Das Projekt löst keinen Import und keine
Neuanlage vorhandener Fallstammdaten aus.

Alle projektbezogenen Tabellen liegen in der bestehenden lokalen DuckDB.
Die zwei ChatGPT-Runden sind über dieselbe Paket-ID verbunden und über den
PC-Gesamtstandwechsel mitnehmbar. Der PC-Import **ersetzt** den lokalen
Gesamtstand und führt ihn nicht mit der vorhandenen Datenbank zusammen.

## Speicher und Datenschutz

Der aktuelle Schritt, der Pause-Status und manuelle Bestätigungen liegen pro
Bauteilprofil/Sachnummer in der lokalen DuckDB und werden mit dem bestehenden
\`.ntfbackup\` mitgenommen. Pausieren beendet **keinen** bereits laufenden
Download; dafür sind die gesonderten Abbruchschaltflächen zuständig.

\`.ntfbackup\` ersetzt beim PC-Import den lokalen Datenbestand und ist **nicht
verschlüsselt**. QEC-, FIN-, Lieferanten- und Werkstattdaten dürfen nur
auf freigegebenen Systemen weitergegeben werden; keine Originalbelege oder
echte FINs in GitHub, GitHub-Actions-Artifacts oder ungeprüfte externe Uploads.
