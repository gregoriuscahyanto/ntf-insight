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

## 04 – Unterlagen für die zweite ChatGPT-Clusteranalyse

Die sechs Workflowstationen bleiben **in einer Zeile**. Schritt 04 zeigt
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

### Zweiter ChatGPT-Durchlauf

1. Nach dem Import der QEC-/Diagnosis-/TIPS-Daten **Schritt 03 erneut**
   durchlaufen und ein **aktuelles erstes KI-Analysepaket** als ZIP erzeugen.
   Dieses enthält die pseudonymisierte FIN-/DTC-/QEC-Ausgangsmatrix und das
   validierte \`chatgpt_ergebnis_vorlage.json\`-/Schema-Paar.
2. In Schritt 04 \`1. KI-Analysepaket wählen …\` anklicken. Das Paket muss
   Schema-Version 3 und eine konsistente \`paket_id\` besitzen.
3. Unterlagen kategorisiert importieren. \`Originale beifügen\` ist
   standardmäßig **aus**. Ohne diese Option enthält das Ergebnis nur
   **Kategorieninventar**, keine lokal importierten fachlichen Belege.
4. \`Cluster-Kontextpaket exportieren\` erstellt eine lokale ZIP mit
   \`basis/\` (ursprüngliche Analyse-ZIP entpackt), \`cluster_kontext_manifest.json\`,
   \`CHATGPT_2_DURCHLAUF.txt\`, der bisherigen ChatGPT-Ergebnisvorlage und
   **nur nach ausdrücklichem Opt-in** \`unterlagen/<kategorie>/Dxxxx.<endung>\`.
   Es erfolgt **kein Upload**. Quellpfade und reale Namen werden nicht in
   neuen ZIP-Belegpfaden wiederholt.
5. Beim zweiten ChatGPT-Durchlauf werden **Setzbedingungen, Nachrichten,
   Topologie, HW-/SW-Änderungen und Kühlungsschema zunächst zur
   Clusterinterpretation/Validierung** genutzt. Für die DTC-Ähnlichkeitsbildung
   gelten weiterhin ausschließlich geeignete Merkmale **vor dem Tausch**.
   SSL-/Lieferantenbewertungen oder Diagnosen nach dem Tausch dürfen nicht
   unbemerkt als Gruppierungsmerkmale benutzt werden.
6. Der Rückimport erfolgt über den bestehenden JSON-Vertrag mit derselben
   \`paket_id\`, aber **neuer \`analyse_id\`** (in Schritt 03).
   ChatGPT-Hypothesen bleiben separat und zunächst ungeprüft.

Es gibt weiterhin **keine** automatisierte Lieferantenverantwortungszuweisung.
Der zweite Analyse-Durchlauf ist eine mit Belegen begründbare Hypothese,
die fachlich freigegeben werden muss.

## 05–06 – bestehende Analysetools

Clusteranalyse und Auswertung öffnen weiterhin die vorhandenen
Detailsichten. Der Selbstimport und der PC-Gesamtstandtransfer liegen bei 06.

## Speicher und Datenschutz

Der aktuelle Schritt, der Pause-Status und manuelle Bestätigungen liegen pro
Bauteilprofil/Sachnummer in der lokalen DuckDB und werden mit dem bestehenden
\`.ntfbackup\` mitgenommen. Pausieren beendet **keinen** bereits laufenden
Download; dafür sind die gesonderten Abbruchschaltflächen zuständig.

\`.ntfbackup\` ersetzt beim PC-Import den lokalen Datenbestand und ist **nicht
verschlüsselt**. QEC-, FIN-, Lieferanten- und Werkstattdaten dürfen nur
auf freigegebenen Systemen weitergegeben werden; keine Originalbelege oder
echte FINs in GitHub, GitHub-Actions-Artifacts oder ungeprüfte externe Uploads.
