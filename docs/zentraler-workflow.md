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

- **QEC-Neuauswertung exportieren (ZIP)** erzeugt eine neue, nur aus den
  **projektbezogenen QEC-Fällen (Schritt 01)** und den nach FIN, QEC-Referenz
  und Sachnummer passenden **QEC-Befundungsdaten (Schritt 02)** gebildete
  Analysebasis mit ChatGPT-Ergebnisvorlage und -Schema. QuickTests, AutoExport,
  TIPS, SMR-D und technische Unterlagen aus Schritt 04/05 sind **nicht**
  Bestandteil dieses Erstexports. Keine automatische Übertragung.
- Alle fünf QEC-Reiter werden strukturiert ausgegeben. Fach-/Lieferantenfreitexte
  und Nachanalyse-Texte sind standardmäßig ausgeschlossen; sie dürfen nur mit
  ausdrücklichem Freitext-Opt-in ins ZIP. Unveränderte QEC-Berichte und Anhänge
  benötigen zusätzlich eine eigenständige Original-Opt-in-Freigabe.
- Die Datei qec_datenluecken.csv dokumentiert nicht vorhandene QEC-Berichte,
  fehlende oder ältere Reiter, unsichere Zuordnungen und nicht ausgewertete
  Anhänge. **Auch wenn kein einziger QEC-Bericht vorhanden ist, ist der
  Export zulässig.** Alle ausgewählten QEC-Fälle bleiben erhalten. Fehlende
  Dokumente dürfen weder als NTF-Nachweis noch als Fehlerfreiheit gelten.
- Eine neue ZIP erhält eine **neue Paket-ID**. Ältere Ergebnisse bleiben
  lokal archiviert und werden nicht überschrieben; die neue Auswertung
  wird erst nach dem zugehörigen, validierten JSON-Rückimport sichtbar.
- **ChatGPT-Ergebnis importieren (JSON)** prüft Paket-ID, Belegreferenzen,
  Pseudonym-Zuordnung und speichert Vorschläge **getrennt und ungeprüft**.
- Tabelle: FIN, QEC-Fall, SSL-Endbefund, manuelle QEC-Entscheidung,
  ChatGPT-Vorschlag, Verursachungsbereich und **ChatGPT-Prüfstatus**.
  Ein importierter ChatGPT-Vorschlag überschreibt **keine**
  QEC-Entscheidung und weist **keine** Schuld zu.
- **Zähler trennen:** `QEC-entschieden` zählt ausschließlich die manuell
  in `qec_workflow_decisions` gespeicherten NTF-/Kein-NTF-Fachentscheidungen.
  Ein bereits vorhandener SSL-Endbefund oder eine importierte ChatGPT-JSON
  erhöht diesen Zähler nicht. Der zweite Zähler zeigt separat importierte
  ChatGPT-Vorschläge; diese beginnen mit Prüfstatus `Offen`.
- **Fachlich entscheiden:** Unter **Datenquellen → QEC-Prüfworkflow** den Fall
  auswählen, `NTF` oder `Kein NTF` festlegen und
  **Bewertung speichern** drücken. Die KI-Vorschläge werden getrennt unter
  **Datenquellen → ChatGPT-Auswertung** einzeln geprüft und
  **Bestätigt** oder **Abgelehnt** markiert.
- **Tabelle filtern und sortieren:** Freitextsuche über alle sieben Spalten,
  kombinierbare Auswahlfilter für SSL-Endbefund, QEC-Entscheidung,
  ChatGPT-Vorschlag, Verursachungsbereich und ChatGPT-Prüfstatus;
  Klick auf einen Spaltenkopf sortiert auf- bzw. absteigend.
  **Filter zurücksetzen** zeigt wieder alle Fälle. Die Anzahl sichtbarer
  Tabellenzeilen wird separat angezeigt; Filter verändern **weder**
  die QEC-Kohorte **noch** Auswertungen, Entscheidungsstatus oder Exporte.
  Beim Wechsel des Sachnummernprojekts werden die Filter zurückgesetzt.
- **Projektschutz:** Beide ChatGPT-Runden nutzen das ausgewählte Profil
  plus Sachnummer. Der Erstexport nimmt nur die QEC-Fall-IDs aus Schritt 01;
  gleiche FIN allein reicht nicht zur Übernahme fremder Schadteile.
  Der zweite Export verifiziert die zu diesem Projekt registrierte erste
  KI-Basis und liest nur die eigenen Kontextunterlagen aus Schritt 04.
- **Bauteilneutral:** Batterie, DC/DC-Wandler und weitere Bauteile können die
  QEC-Erstrunde sowie die vertiefte zweite ChatGPT-Runde verwenden. QEC-Fälle
  mit unbekannter Benennung brauchen eine eindeutige Projekt-Sachnummer.
  Bei mehrdeutiger Zuordnung wird nicht geraten. Die **lokale**
  Clustering-Implementierung kann unabhängig davon weiterhin eigene
  bauteilspezifische Grenzen haben.
- Der allgemeine Quellenexport unter **Datenquellen** ist eine separate
  Funktion mit anderem Datenumfang.


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
3. **QEC-Neuauswertung:** Erstes KI-Paket nur aus Schritt 01/02 exportieren,
   Rückgabe-JSON über den bestehenden validierten ChatGPT-Import einlesen.
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

## Projekte, Einstellungen und Projekttransfer

**Workflow-Kopfzeile:** \`Kühlmittelpumpe [Sachnummer]\` mit optionaler
ECU-Anzeige; \`Projekt wählen\`, \`+ Neues Projekt\`, \`Einstellungen\`,
\`Projekt-Export\`, \`Projekt-Import\`. Es gibt **kein altes
Bauteil-Dropdown** mehr in der sichtbaren Workflow-Kopfzeile und keinen
sechsten Schritt für den Datenaustausch.

**Bestehender nicht zugeordneter QEC-Bestand**: Falls noch kein
Sachnummernprojekt existiert, erscheint die Aktion
\`Bestehenden QEC-Bestand übernehmen\`. Sie zeigt Sachnummern und die
vorhandene QEC-Fallzahl. Erst nach ausdrücklicher Bestätigung wird
ein Projekt mit dem passenden Bauteil/Sachnummern-Paar angelegt.
Die bereits importierten QEC-, FIN-, Diagnose- und Archivdateien werden
**nicht** neu importiert, gelöscht oder überschrieben. Im Projekt werden
die betreffenden vorhandenen Fälle anhand ihrer Sachnummer angezeigt.
Bei **genau einer** erkannten Sachnummer werden außerdem der alte,
sachnummernlose Workflowfortschritt und bisher ungebundene Unterlagen/
KI-Paketreferenzen übernommen, ohne die alten Einträge zu löschen.
Bei mehreren Sachnummern erfolgt eine Auswahl, ungebundene Unterlagen
müssen jedoch erst fachlich zugeordnet werden.

In \`Projekteinstellungen\` sind Bauteilprofil, Sachnummer,
Bauteilbezeichnung, relevante Steuergeräte und Beschreibung editierbar.
Neue Sachnummer = neues Projekt. Die Steuergeräteliste ist reine
Projektkonfiguration und keine Ursachenfeststellung.

### .ntfproject gegenüber .ntfbackup

- **Projekt-Export** erstellt eine eigene \`.ntfproject\`-Datei mit dem
  selektierten Projektdatensatz: Projektkonfiguration/Workflowfortschritt,
  zugeordneten QEC- und Fallentscheidungen, FIN-bezogenen QuickTests,
  Archivdateien, technischer Unterlagensammlung und projektgebundenen
  ChatGPT-Zuordnungen. Die Projekt-Datenbank ist gefiltert;
  *bekannte weitere Projekte* werden nicht als fremde Tabellenzeilen
  exportiert. Es gibt keinen neuen Parserlauf.
- **Mehrere QEC-FIN-Listen** für verschiedene Sachnummern sind erlaubt;
  für dieselbe Sachnummer sind widersprüchliche aktive QEC-Master gesperrt.
  Die Workflow-Tabelle zeigt die Vereinigung aller aktiven QEC-Listen und
  filtert erst danach die Fälle der ausgewählten Projektsachnummer.
  QEC-Entscheidungen bleiben weiterhin über die konkrete Quell-SHA gebunden.
- **Projekt-Import** überprüft Hüllenformat, SHA-256-Prüfsummen und den
  enthaltenen portablen Datenstand. Das neue Projekt wird zur bestehenden
  Datenbank hinzugefügt, ohne andere Projekte oder deren Dateien zu
  ersetzen. Bei gleicher bereits vorhandener Bauteilprofil/Sachnummer
  wird **nicht** automatisch überschrieben oder zusammengeführt,
  sondern der Vorgang mit erklärender Meldung abgelehnt.
- **Wichtige Freigabegrenze:** Eine physische Originalquelldatei kann
  mehrere Projekte enthalten (z. B. gemeinsame QEC-Master-Excel).
  Sie kann nicht bytegleich UND auf nur eine Sachnummer reduziert sein;
  der Export nimmt solche für das Projekt erforderlichen gemeinsamen
  Rohbelege unverändert mit. Vor Weitergabe Inhaltsprüfung und Freigabe
  notwendig. Das Paket ist nicht verschlüsselt und nicht signiert.
- Bei neuen oder unbekannten Datenbanktabellen bricht der Transfer
  kontrolliert ab statt unklassifizierte Daten anderer Projekte
  ungeprüft mitzunehmen. Der erste Import in eine App-Version, die
  die entsprechenden Tabellenschemata nicht kennt, wird ebenso verweigert.

Der bisherige **Gesamtstandtransfer** \`.ntfbackup\` bleibt für
explizite Komplettbackups über Datenquellen erreichbar, ist aber
**kein Projekttransfer**: Die Wiederherstellung ersetzt den
gesamten lokalen Bestand. Die zwei Schaltflächen in der Workflow-
Kopfzeile verwenden ausschließlich \`.ntfproject\`.

## Speicher und Datenschutz

Der aktuelle Schritt, der Pause-Status und manuelle Bestätigungen liegen pro
Bauteilprofil/Sachnummer in der lokalen DuckDB und werden mit dem bestehenden
\`.ntfbackup\` mitgenommen. Pausieren beendet **keinen** bereits laufenden
Download; dafür sind die gesonderten Abbruchschaltflächen zuständig.

\`.ntfbackup\` ersetzt beim PC-Import den lokalen Datenbestand und ist **nicht
verschlüsselt**. QEC-, FIN-, Lieferanten- und Werkstattdaten dürfen nur
auf freigegebenen Systemen weitergegeben werden; keine Originalbelege oder
echte FINs in GitHub, GitHub-Actions-Artifacts oder ungeprüfte externe Uploads.


## Kompakte Workflow-Dashboards und SSL-Kohorten (Ausbaustufe 2)

Die **fünf horizontalen Schrittkacheln sind die einzige Navigation**;
die redundanten Schaltflächen Zurück, Pausieren und Weiter wurden
entfernt. Ein zuvor lokal gespeicherter Pausenstatus wird beim
Neustart in den neuen Workflow migriert und nicht als Sperre weitergeführt.

### 01 QEC-FIN-Liste und Auswahl der Analysegrundgesamtheit

- Donut: eindeutige FINs nach **SSL-Endbefund**; dieselbe FIN zählt
  innerhalb dieser Verteilung genau einmal. Bei widersprüchlichen
  SSL-Endbefunden derselben FIN gibt es die eigene Kategorie
  \`Mehrere Endbefunde\`, bei Leerwerten \`Nicht angegeben\`.
- Über \`SSL-Endbefunde auswählen\` können Kategorien an- und
  abgewählt werden. \`Alle übernehmen\` aktiviert alle.
  Die Auswahl wird je Profil/Sachnummer in DuckDB gespeichert
  (\`workflow_ssl_selection\`) und mit \`.ntfproject\` übertragen.
- Die FIN-Liste zeigt weiterhin **sämtliche** QEC-Fälle des Projekts.
  Ausgeschlossene FINs sind dezent grau hinterlegt. Erst ab Schritt 02
  werden ausschließlich ausgewählte FINs berücksichtigt: QEC-Abruf,
  ChatGPT-1-Export, QuickTests/TIPS-Abruf, lokales Clustering und
  ChatGPT-2-Auswertung. Der QEC-CSV-Export respektiert dieselbe Auswahl.
- Die erste ChatGPT-ZIP enthält **nur** die ausgewählten QEC-Fälle der
  aktuellen Sachnummer und die passenden QEC-Befunde. Sie nimmt **keine**
  FIN-weiten QuickTests, AutoExport-Daten oder separaten TIPS-Berichte auf.
  Die private FIN-/Fallzuordnung bleibt lokal und gehört niemals in den Upload.

### 02 QEC-Befundung

- Donut mit drei sich ausschließenden FIN-Status:
  **alle** QEC-Fallberichte heruntergeladen, **teilweise** vorhanden
  oder **noch keiner** vorhanden. Gezählt werden eindeutige FINs.
- Die Tabelle markiert vorhandene, lokal validierte QEC-Berichte grün,
  ausstehende Zeilen neutral. Das vorhandene lokale Download-Datum
  bleibt je FIN/Referenz sichtbar.

### 03 QEC-basierte Neuauswertung und NTF-Hypothesen

- Erneuter Export bildet eine **neue** erste Analysebasis. Bereits
  gespeicherte KI-Ergebnisse und QEC-Fachentscheidungen bleiben bestehen.
- Die erste Auswertung ist vorläufig. SSL-Endbefunde und Lieferantenberichte
  sind kein Nachweis der Ursache; DTC-Wiederkehr und weitere Diagnosequellen
  werden erst in Schritt 04/05 gesondert geprüft.
- Die ZIP-Export- und JSON-Import-Schaltflächen sind vergrößert.
- Ein Donut für \`NTF plausibel\`, \`NTF fraglich\`, \`Kein reiner NTF\`,
  \`Nicht bewertbar\`, \`Nicht bewertet\` sowie ggf. \`Mehrere Bewertungen\`;
  ein zweiter für die vorgeschlagenen Verursachungsbereiche.
  Freitextkategorien werden für die kompakte Legende ab sechs
  Kategorien zusammengefasst. Die Tabelle kennzeichnet Status
  semantisch farbig und zeigt den vorgeschlagenen Verursachungsbereich.
- Es werden nur die **validiert importierten Bewertungen des ersten
  ChatGPT-Durchlaufs** angezeigt. Die QEC-Entscheidung bleibt unverändert.

### 04 Unterlagen / Einlesen und Aktualität

- TP Dashboard, Diagnosis Viewer, TIPS Writer und Celonis besitzen
  jeweils eine explizite **Einlesen**-Aktion. Diese nutzt die
  bereits vorhandene Parser-/Quellenimport-Pipeline. Für Celonis
  existiert noch kein freigegebener strukturierter Parser; die
  Aktion lautet \`Einlesen (Archiv)\` und archiviert Originale.
- Bei Diagnosis Viewer/TIPS Writer gibt es nur \`Abrufen\`,
  \`Stop\`, \`Einlesen\` und \`+ Beleg\`. Die missverständliche
  Funktion \`Markierte\` entfällt. \`Abrufen\` nutzt die über
  Schritt 01 gewählte FIN-Kohorte.
- Die App speichert **Abrufzeitpunkt mit Erfolgs-/Fehlerstatus** und
  **Einlesezeitpunkt** getrennt für jedes Projekt. Historische globale
  Quellimporte werden als solche gekennzeichnet und sind nicht
  automatisch einer Sachnummer zurechenbar. Datumsinformationen
  sind kein Beweis für erfolgreiche Fachprüfung.
- Originale in der Unterlageninventartabelle sind grün hinterlegt,
  wenn sie im lokalen Archiv nachweislich vorhanden sind. Die eigene
  überflüssige Schaltfläche \`Sonstige Dateien importieren\` entfällt;
  die Kategorie \`Weitere Dokumente\` bleibt erhalten.

### 05 Clusteranalyse – zwei Ansichten, keine doppelte KI

- \`Lokal · HDBSCAN / Cosinus\` zeigt die einmalig vorhandene
  lokale Clusterimplementierung, mit sinnvollem Scrollbereich.
  Doppelte Beschreibungs-/Quellenabdeckungs-Texte entfallen.
- \`ChatGPT · Ergebnis anzeigen\` zeigt **nur die validierte
  zweite ChatGPT-Rückgabe** mit Clustertiteln, Hypothesen,
  Sicherheit, FIN/Fall-Zuordnung und fachlichem Prüfstatus.
  Dieser Tab führt **keinen** neuen ChatGPT-Request aus.
- Die zwei zentralen Bedienelemente für den zweiten ZIP-Export und
  JSON-Rückimport sind groß hervorgehoben. Beide Durchläufe bleiben
  paket-/analyse-ID-gebunden.


### Projekt entfernen oder vollständig löschen (Projekteinstellungen)

Die Einstellungen haben zwei Aktionen mit **Warnung, ausdrücklicher Bestätigung
und exakter Wiedereingabe der Sachnummer**. Bei laufenden Imports/Downloads,
KI-Exporten oder Datentransfers sind beide Aktionen gesperrt.

- **Projekt entfernen** entfernt ausschließlich den Projekt-Registrierungseintrag
  (Profil, Sachnummer, Name und ECU-Einstellungen). QEC-Quellen, FIN-/Falldaten,
  Unterlagen, Workflowfortschritt und ChatGPT-Auswertungen bleiben im lokalen
  Datenbestand. Dieselbe Sachnummer kann später wieder als Projekt aufgenommen
  werden.
- **Projekt vollständig löschen** entfernt die eindeutig diesem Profil/
  dieser Sachnummer zugeordneten Fall-/QEC-Entscheidungen, FIN-QuickTests,
  manuelle Bewertungen, ChatGPT-Paket- und Auswertungsdaten, Workflow- und
  Unterlagenzuordnungen sowie exklusive lokale Archivdateien.
  **Gemeinsame QEC-/TP-Quelldateien oder überlappende FIN-/KI-Zuordnungen
  führen zum vollständigen Abbruch der Aktion.** Globale ECU-Diagnose-
  referenzen, die nicht eindeutig einer Sachnummer gehören, bleiben erhalten.
  Der Vorgang erfindet keine Quellzuordnung: Wenn sich vorhandene Daten
  nicht zuverlässig einem einzelnen Projekt zuordnen lassen, wird die
  Löschung abgelehnt statt Daten anderer Projekte zu gefährden.
- **Dateisicherheit:** Eindeutig betroffene lokale Dateien werden erst in
  einen reversiblen Quarantäneordner verschoben. Anschließend wird die
  Datenbanktransaktion abgeschlossen und erst dann werden die Dateien
  endgültig gelöscht. Bei einem transaktionalen Fehler erfolgt Rollback
  und Rückverschiebung; bei nicht automatisch wiederherstellbaren Dateifehlern
  erscheint der Quarantänepfad im Fehlertext.

**Vor vollständigem Löschen** immer ein freigegebenes Projekt-Backup oder
ein lokales vollständiges Backup anlegen und dessen Inhalt prüfen.
Ein exportiertes \`.ntfproject\` ist selbst vertraulich, nicht verschlüsselt
und nicht durch die Projektlöschung betroffen, wenn es außerhalb der lokalen
App-Datenablage gespeichert ist.


### Hintergrundverarbeitung ohne dauerhaftes Popup

Die Aktionen **„Parsing fortsetzen“**, **„Alle neu parsen“**,
**„FINs neu abrufen“** und **„Fehlende abrufen“** verwenden vorhandene
QThread-Worker. Der Fortschritt erscheint **ausschließlich in der
jeweiligen Quellenzeile im Workflow**; eine zusätzliche Statusleisten-
Fortschrittsanzeige mit eigenem Stoppen-Button gibt es nicht.
Während der Verarbeitung wird die entsprechende Schaltfläche in der Zeile
zu **„Parsing stoppen“** beziehungsweise **„Abruf stoppen“**.
Es gibt dafür weder eine modale Importkarte noch ein ausgegrautes
Hauptfenster. Andere App-Seiten bleiben bedienbar.

Ein Stoppsignal beendet den Parser am sicheren Dateirand bzw. fordert
den Portal-Downloader zum Abbruch auf; gespeicherte Daten bleiben erhalten.
Ein App-Schließen während aktiver Worker wird zur Vermeidung zerstörter
QThreads verhindert, ohne einen weiteren modalen Dialog zu zeigen.
Im laufenden Vorgang wird der nicht nutzbare Zeitstempel der Quellenzeile
auch textlich geleert, damit er nicht vom Progressbalken überdeckt wird;
nach Ende des Vorgangs steht der Zeitstempel wieder zur Verfügung.

Einmalige Sicherheitsbestätigungen vor einem Neuparsen/Neuabruf
und erforderliche Mercedes-SSO-Interaktionen bleiben erhalten.
Automatisch anschließende Quellenimporte aus Workflow-Downloads laufen
ebenfalls ohne Fortschrittspopup. Andere, ausdrücklich exklusive
Transfer-/Exportvorgänge behalten ihre Sicherheitsdialoge.

### Fortschritt je Datenquelle: Download und Parsing separat

Die Oberfläche zeigt zwei **belegte, unterschiedliche** Verarbeitungszustände:
**lokale Originaldokumente** und **Dokumente mit erfolgreich oder mit
Hinweisen gespeichertem Parsergebnis**. Die Parserkennung/-version sowie die
Datei-SHA müssen mit den aktuell vorhandenen Quellen übereinstimmen.
Bei teilweiser Befundung wird die Anzahl mit Parserhinweisen separat
ausgewiesen. Kein Checkmark nur wegen eines Dateinamens oder Dateidatums.

- **QEC-Befundung (02):** pro QEC-Fall (volle FIN und Schadteilreferenz)
  Zähler, lokales Download-Datum und Parserstatus in der Tabelle.
  „Download fortsetzen“ ruft nur Fälle ohne gültigen aktuellen
  JSON-Bericht ab; „Parsing fortsetzen“ indexiert nur noch nicht
  erfolgreich gespeicherte lokale QEC-JSONs. Legacy-Downloads bleiben
  Downloadnachweise, erfordern für strukturiertes Parsing aber einen
  neuen JSON-Abruf.
- **Diagnosis Viewer (04):** zählt vorhandene PDFs und geparste PDFs
  getrennt; die FIN-Abdeckung ergibt sich aus bestätigten
  QuickTest-Report-Verknüpfungen. Ein Abrufstatus ohne PDF ist kein
  Download. „Fehlende abrufen“ berücksichtigt FINs ohne QuickTest
  oder mit abgebrochenem/teilweisem Abruf. Ein vollständiger,
  bekannter Abruf mit „Keine Quicktests“ wird nicht als Download
  gezählt. Die Portal-Gesamtzahl von Sitzungen ist vor der Abfrage
  nicht sicher bekannt.
- **TIPS Writer (04):** zählt TIPS-Fallberichte \`tips.json\` unter
  validierter FIN/Fallnummer und deren strukturierten Parserstatus.
  Der neue \`TipsJsonParser\` (Schema 1) indexiert die sichtbaren
  TIPS-Reiter und referenziert Anhänge nur als Inventar.
  Anhänge selbst gelten **nicht** als geparste Dokumente.
  Nicht vollständige/abgebrochene FIN-Abfragen können erneut
  gestartet werden. Erfolgreiche Anfragen ohne TIPS-Fälle
  erzeugen keinen erfundenen Fall.
- **TP Dashboard (04):** aktuell nur importierte CSV-Originale und
  vorhandene AutoExport-Parserläufe. FIN-Abdeckung wird nur aus
  nachweisbaren TP-Quellenzeilen ermittelt. Da ein TP-Export mehrere
  FINs enthalten kann, wird **keine** fiktive Eins-zu-eins-Beziehung
  zwischen CSV-Dokument und Fahrzeug dargestellt. Ohne Portal-Scraper
  gibt es kein „Download fortsetzen“, aber „Parsing fortsetzen“
  für lokal vorhandene, noch nicht indexierte CSV.
- **Celonis (04):** die Zahl archivierter Originaldateien ist bekannt;
  Parser-, Portal- und FIN/Fall-Abdeckung sind **nicht verfügbar**.
  Das UI zeigt dies ausdrücklich an. „Parsing fortsetzen“ ist
  bis zu einem echten Celonis-Parser deaktiviert.

Die neuen Zähler berücksichtigen stets die aktive Projekt-Sachnummer
und den SSL-Endbefundfilter aus Schritt 01. *Geparst* ist keine
fachlich bestätigte NTF-Bewertung und kein Nachweis, dass der Portaldatenstand
aktuell oder vollständig ist. Die großen ZIP-/JSON-Aktionen aus
03 und 05 bleiben davon unabhängig.
