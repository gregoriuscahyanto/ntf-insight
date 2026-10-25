# KI-Analysepaket für fallübergreifende NTF-Clusterung

## Zwei verschiedene Exportzwecke

| Export | Im Paket | Zweck |
|---|---|---|
| **Gesamtstand** (`.ntfbackup`) | DuckDB und vollständige Rohdateien | Privater Datentransfer zwischen zugelassenen Rechnern |
| **KI-Analysepaket** (`.zip`) | Strukturierte Daten, Excel-Überblick und Methodik | Kompaktes Analyse-/Clusterinput-Paket |
| **Technische Grundlagen** (separate ZIP) | Netzwerktopologie, Setzbedingungen, ECU-Nachrichten, CDD, Kühlungsschema und HW-Update-Historie | Sachliche Ergänzung, nicht aus NTF-Insight erzeugt |

Die KI-Analyse-ZIP ist **kein** vollständiges Backup. Sie enthält **keine**
QuickTest-PDFs, QEC-/TIPS-Rohdateien, Anhänge, SMR-D-XML/JSON oder Originalpfade.
Bereits extrahierte Daten sind zur fallbezogenen Analyse als Tabellen verfügbar.

## Workflow 03: QEC-basierte Erst-/Neuauswertung

**Für jedes registrierte Bauteilprofil nutzbar:** Neben Kühlmittelpumpe auch
HV-Batterie, DC/DC-Wandler und das frei benennbare Profil „Weiteres Bauteil“.
Die Eingangs-QEC-Excel muss eine Sachnummer und eine eindeutige Fallreferenz
haben. Bei unbekannter Bauteilbenennung darf eine Sachnummer nur einem
Profilprojekt zugeordnet sein, ansonsten bleibt der Fall getrennt.

**Auch Runde 2 ist bauteilneutral:** Ihr Kontext-ZIP verwendet die
registrierte erste Analysebasis und Unterlagen aus demselben
Bauteilprofil-/Sachnummernprojekt. Die Hinweise setzen weder eine Pumpe
noch CPC3 voraus. Diagnosen und Ursachen werden nur bei vorhandenen
Nachweisen als Hypothesen ausgewertet. Fehlt eine Quelle, ist das eine
Datenlücke – kein Grund, ihre Inhalte zu erfinden.

### Workflow 05: vollständiger technischer Kontext (zweiter LLM-Export)

**Ziel des zweiten LLM-Durchlaufs:** Belegorientierte technische Neubewertung
aller ausgewählten QEC-Fälle. Gemeinsamkeiten in DTCs, ECU-Daten, Betriebs-
bedingungen, Zeitverläufen und tatsächlich vorhandenen Dokumenten
dürfen zu nachvollziehbaren Clustern zusammengeführt werden. Fälle ohne
belastbare Gemeinsamkeiten bleiben `cluster_id=null` und dürfen
nicht künstlich zugeordnet werden. Cluster sind Hypothesen, keine
Beweise einer technischen oder rechtlichen Verursachung.

**Verbesserte Clusterung auf zwei unabhängigen Ebenen:** Das zweite
LLM muss für **jeden einzelnen Fall** `fehlerbilder[]` und
`nachweisprofil[]` nach dem JSON-Schema ausgeben. Zur
**Fehlerbild-Ebene** gehören ausdrücklich auch Werkstatt- und QEC-
Beanstandungsangaben zu Stromaufnahme, Kurzschluss, Sicherung,
Buskommunikation, thermischem Verhalten, Mechanik, Korrosion,
Versorgung oder sonstigen Symptomen. Ein Fall kann mehrere Fehlerbilder
haben, und jedes besitzt seinen eigenen Nachweisstatus und Belege.
Eine nicht bestätigte Werkstattmeldung bleibt als Meldung sichtbar.

Die **Nachweis-Ebene** unterscheidet Laborbefund, nicht
reproduzierten Laborbefund, objektive Diagnose, Werkstattangabe und
unzureichende Datenlage – auch gleichzeitig. Die übergeordnete
technische `cluster_id` bleibt eine **separate, vorsichtige
Mechanismus-Hypothese**. `cluster_id=null` darf deshalb nicht mit
»Fall hat kein erkennbares Fehlerbild« verwechselt werden. Fehlt
jegliches beschreibbares Symptom, wird `Fehlerbild unbekannt`
vergeben, nicht eine fiktive Clusterursache.

Die mögliche Ursache wird **pro Fall** mit Verursachungsbereich,
Zuordnungssicherheit, Begründung, Gegenindizien, Quelle und
empfohlener Prüfung dokumentiert. Eine Aussage über Lieferanten-
verantwortung braucht unabhängige technische Nachweise; eine
Häufung gleicher Fehler oder ein SSL-/NTF-Endbefund reicht nicht.

Das rückwärtskompatibel erweiterte Rückgabeformat unterscheidet
`fehlerwiederkehr` und `begruendung_fehlerwiederkehr` mit den
Werten „Nach Tausch erneut nachgewiesen“, „Hinweise auf Wiederkehr“,
„Kein erneuter Fehler im dokumentierten Nachtest“ und
„Nicht beurteilbar“. Ohne gesicherte Zeitanker und Nachtests ist
keine Aussage über ausbleibende Fehler möglich.

**Visualisierung in Schritt 05:** Nach erfolgreichem Rückimport
zeigt `LLM · Cluster & Verursachung` interaktive Balkendiagramme,
Clustergrößen und Verursacher-Hypothesen sowie eine filterbare
Falltabelle. Die Belegfundstellen, technische Clusterhypothese und
Vor-/Nach-Tausch-Aussagen sind im Detailbereich lesbar. Die Anzeige
übernimmt nur validierte Daten des aktuellen Sachnummernprojekts.



Der zweite ZIP-Export übernimmt in `basis/` die **gesamte erste QEC-ZIP**
und in `voranalyse/erstes_chatgpt_ergebnis.json` die validierte erste
LLM-Auswertung. Alle Fälle und Pseudonyme bleiben erhalten.

Zusätzlich befinden sich im Ordner `diagnose/` automatisch,
aber **nur für FINs der gewählten Profil-/Sachnummern-Fallkohorte**:

- `quicktests.csv`: alle lokal geparsten Diagnosis-Viewer-Berichte mit
  Pseudonym, Diagnosezeitpunkt, Kilometerstand und DTC-/ECU-Anzahlen.
- `ecu_staende.csv`, `dtc_beobachtungen.csv`,
  `dtc_parameter.csv`: geparste ECU- und DTC-Einzelwerte samt
  Fehlerstatus, Häufigkeit, Kilometerständen und Parameterwerten.
- `quicktest_fallbezug.csv`: zeitlicher Vergleich je ausgewähltem
  QEC-Fall; bei fehlendem **QEC-belegtem** Tauschdatum ausdrücklich
  `tauschdatum_nicht_belegt`. Jeder vorhandene QuickTest am
  **Tauschtag** behält `zeitlich_unklar_gleicher_tag`, bekommt aber
  zusätzlich QT-Datum/-Uhrzeit, QT-km, QEC-Tauschdatum/-km,
  `km_relativ_zum_tausch` und `zeitindiz`.
  Beispiel: QT 15.808 km, Tausch 15.890 km, beide am 05.01.2024:
  **82 km niedriger = plausibles Vortausch-Indiz**, nicht
  automatisch ein bewiesener Vortauschtest. Ein am Tauschtag vorhandener
  QT wird nie als »kein QuickTest vorhanden« gewertet. Bei
  widersprüchlichen Datum-/Kilometerangaben werden die Quellen
  zur manuellen Prüfung markiert. Keine automatische Zuschreibung
  zum Bauteil oder Lieferanten.
- `tp_dashboard_dtc.csv`, `tp_dashboard_reparaturen.csv`,
  `tp_dashboard_tips.csv`: geparste TP-Dashboard-Zeilen der ausgewählten
  FINs. Multi-FIN-Sammeldateien werden nie ungefiltert kopiert.
- `tips_writer.csv`: gegebenenfalls strukturierte TIPS-Writer-Einträge.
  Mit expliziter Freigabe auch `quicktest_seitentexte.csv` mit dem
  geparsten Text der vorhandenen Diagnosis-Viewer-Seiten.
- `LESEHINWEISE.txt`: genaue Tabellenbezüge, Quellenstatus und
  Trennung von Fahrzeugbeobachtung und Schadteilbefund.

### Sehr große Diagnosebestände: vollständige CSV-Teildateien

Eine große Diagnose-/DTC-/Parameter-/TP-/TIPS-Tabelle wird im zweiten
LLM-ZIP automatisch aufgeteilt. Die bisherige **globale Grenze von
1.000.000 Diagnosezeilen** entfällt. Der Export schreibt pro CSV-Teil
maximal **250.000 Datenzeilen oder 200 MiB** (je nachdem, was zuerst
erreicht wird). Es werden keine Belegzeilen wegen einer vollen
Teildatei ausgelassen.

Die erste Datei behält ihren bisherigen Namen, z. B.
`diagnose/dtc_parameter.csv`. Weitere Dateien heißen
`diagnose/dtc_parameter_teil_0002.csv`,
`diagnose/dtc_parameter_teil_0003.csv` usw.
Jede Datei hat einen eigenen Tabellenkopf und kann separat gelesen
werden. Die komplette Liste steht unter `diagnose_tabellen` im
`cluster_kontext_manifest.json`, mit **Zeilenanzahl und Bytegröße je
Teil**. Eine LLM-Auswertung muss **alle Teildateien** derselben Tabelle
gemeinsam auswerten und darf nur die jeweils erste Kopfzeile als
Spaltenbeschreibung betrachten.

Die exportierten TP-Dashboard- und TIPS-Daten werden bereits in der
SQL-Abfrage auf die FINs des **aktuellen Sachnummernprojekts** begrenzt.
Die Original-Sammeldatei mit weiteren FINs wird nicht ungefiltert
übernommen. Geparste QuickTests bleiben tabellarisch; PDF-Originale
sind nur bei fehlender Parserfassung als Fallback vorgesehen.

Das ZIP bleibt auf **1 GiB unkomprimierte Gesamtdaten** begrenzt.
Wenn dieser Gesamtumfang oder eine einzelne 200-MiB-Datenzeile
überschritten wird, erscheint ein konkreter Fehler. Es wird weder
unbemerkt abgeschnitten noch ein unvollständiges ZIP freigegeben.

Mit **getrennter Freigabe** umfasst `unterlagen/` zusätzlich alle
diesem Projekt explizit zugeordneten Originalunterlagen aus Schritt 04,
nicht geparste QuickTest-PDFs als Fallback sowie abrufbare TIPS-Writer-
Originale/Anhänge. Ein bereits geparster QuickTest wird nicht noch
einmal als PDF mitgeschickt. Die vollständigen QEC-Freitexte/Originale
aus Runde 1 haben **ihre eigene Freigabe**, unabhängig von den
zusätzlichen technischen Unterlagen.

Das `cluster_kontext_manifest.json` nennt den Projektbezug, den
Diagnosedatenumfang, die Kategorie der Originalbelege und
**Auslassungsgründe**. Beispiele: ein Beleg hat einen unpassenden
FIN-/Fallhinweis, ist bereits geparst, ist nicht freigegeben oder
ist eine nicht filterbare globale TP-Sammeldatei.

**Wichtig:** Unstrukturierte, manuell einem Projekt zugeordnete Dateien
werden nach Profil/Sachnummer archiviert, ihr gesamter Inhalt kann aber
nicht automatisch auf weitere Sachnummern/FINs geprüft werden.
Alle Daten benötigen eine Unternehmensfreigabe. Das Programm erstellt
nur eine lokale ZIP; einen Upload löst es nicht aus.
Für mehr als 1 GiB unkomprimierte Unterlagen ist eine bewusste Aufteilung
erforderlich; die App ersetzt keine Dateibelege stillschweigend.

Die Schaltfläche **QEC-Neuauswertung exportieren (ZIP)** in Schritt 03 ist
absichtlich **enger** als der bisherige allgemeine Quellenexport:

- **Schritt 01:** Nur explizit ausgewählte QEC-Fälle des aktuellen
  Kühlmittelpumpen-Profils und der aktuellen Sachnummer, Fahrzeugpseudonym,
  Teilegruppe und Pumpentauschanker. Auch eine gemeinsame FIN mit einem
  anderen Schadteilfall führt **nicht** zu einer Übernahme des Fremdfalls.
- **Schritt 02:** Alle gespeicherten, eindeutig passenden QEC-Befundungsreiter
  (WE-Daten, Voranalysen, Stellungnahme Lieferant, Ergebnis/Nachanalyse,
  Historie), strukturierte Feld- und Tabellenbelege und QEC-Datenlücken.
- **Nicht enthalten:** QuickTests, DTCs aus Diagnosis Viewer, AutoExport,
  separate TIPS-Quellen, SMR-D oder technische Unterlagen aus Schritt 04.
  Die vertiefte Untersuchung dieser Zusatzquellen folgt erst in Schritt 05.
- **Standardmäßig ohne Freitext:** Originale Feldtexte, Lieferantenstellungnahme,
  Nachanalyse und ganze QEC-Reitertexte werden nur bei aktivierter
  **vertraulicher Freitext-Option** aufgenommen. Eine getrennte Option
  erlaubt unveränderte QEC-Originale und Anhänge. Beide Optionen erfordern
  Unternehmensfreigabe; auch Pseudonyme sind keine sichere Anonymisierung.

Das erste ZIP enthält in diesem Modus unter anderem
`faelle.csv`, `fahrzeuge.csv`, `fallmerkmale.csv`,
`qec_berichte.csv`, `qec_felder.csv`,
`qec_datenluecken.csv`, `bewertungen_NICHT_CLUSTER.csv`,
`methodik.csv`, `Auswertung.xlsx`, das Manifest und den bestehenden
LLM-Rückgabevertrag. Die Datensätze in `qec_felder.csv` verweisen auf
die pseudonymisierten QEC-Berichte und ihre konkrete Fundstelle.
Ein veralteter, widersprüchlicher oder fehlender QEC-Teilbericht wird nicht
als verlässlicher Originalbefund ausgegeben. **Fehlende Dokumente sind
ausdrücklich zulässig:** Auch ohne einen einzigen QEC-Bericht erzeugt Schritt
03 ein vollständiges Fallpaket mit leeren QEC-Belegtabellen und
`qec_datenluecken.csv`. Für unbelegte Fälle ist `Nicht bewertbar`
die richtige Ausgangskategorie, nicht eine behauptete Fehlerfreiheit.

**Getrennte LLM-Runden:** Der erste Workflow-Export dient **nur** der
vorläufigen NTF-Einzelfallentscheidung. Zulässige Einstufungen sind
`NTF plausibel`, `NTF fraglich`, `Kein reiner NTF` und
`Nicht bewertbar`/`Nicht zuordenbar` bei unzureichender Datenlage.
Ein möglicher Verursachungsbereich ist eine getrennte Hypothese, keine
Schuldzuschreibung. Runde 1 liefert `cluster=[]`, keine Cluster-IDs und
auch keine `cluster_input.csv`. Die tiefgehende technische Ursachenanalyse
und Clusterung erfolgen erst mit dem zweiten LLM-Export aus Schritt 05.
Der **allgemeine** Datenquellen-Export besitzt weiterhin seine eigene
`cluster_input.csv`, unabhängig vom QEC-Erstworkflow.
**Neuauswertung:** Ein erneuter Export erzeugt eine neue `paket_id`
mit eigener lokaler `_NICHT_HOCHLADEN_ZUORDNUNG.csv`. Frühere Pakete
und die zugehörigen LLM-Ergebnisse bleiben bestehen. Die erste
Auswertung des neuen Pakets erscheint erst nach Import ihrer neuen
Ergebnis-JSON; manuelle QEC-Entscheidungen bleiben unverändert.

### Separater allgemeiner Quellenexport

Der nachfolgend dokumentierte **allgemeine Quellenexport unter
Datenquellen** behält für bestehende Arbeitsweisen den größeren
Datenumfang mit QuickTests, AutoExport, TIPS und Lieferantenkontext.
Die Tabellenliste im nächsten Abschnitt beschreibt **diesen allgemeinen
Export**, nicht das QEC-ZIP von Workflow 03.

## Bedienung

Unter **Datenquellen**:

1. **Lightweight KI-Analysepaket als ZIP exportieren…** auswählen.
2. **QEC-/TIPS-Originalfreitext beifügen** ist standardmäßig deaktiviert.
3. ZIP in einem zulässigen lokalen Ordner speichern.
4. Die App erzeugt **zwei getrennte Dateien**:
   - `NTF-Insight-KI-Analyse-….zip` = KI-Analysepaket
   - `NTF-Insight-KI-Analyse-…_NICHT_HOCHLADEN_ZUORDNUNG.csv`
     = **private Zuordnung** der Pseudonyme zu echten FINs, Fällen,
       QEC-Referenzen und Teilenummern. **Niemals hochladen.**
5. Prüfen, ob eine Freigabe zur Weitergabe der strukturierten technischen
   Daten an den vorgesehenen Dienst besteht. Pseudonymisierung ist
   **keine** garantierte Anonymisierung.

## ZIP-Struktur

| Datei | Zweck |
|---|---|
| `Auswertung.xlsx` | Übersicht, Fallliste, Falldaten, Belege, Methodik – an die bisherige QEC-Excel-Struktur angelehnt |
| `cluster_input.csv` | **Explizite Vor-Tausch-Cluster-Eingaben**, ohne NTF-, Lieferanten- oder Nach-Tausch-Ergebnisse |
| `fahrzeuge.csv` | Eine Zeile je pseudonymisierter FIN, auch ohne QEC-Fall |
| `faelle.csv` | Fälle mit Fall-ID, Fahrzeug-ID, QEC-Verfügbarkeit und Quellenabdeckung |
| `fallmerkmale.csv` | Fallkontext **inklusive Nach-Tausch-Daten** – nur für spätere Validierung, nicht ungeprüft als Cluster-Matrix |
| `quicktests.csv` | Eine Zeile pro eingelesenem QuickTest (ohne PDF-Rohtext) |
| `quicktest_fallbezug.csv` | Vor-/Nach-/gleichdatiger oder unbekannter Bezug zwischen QuickTest und Pumpentausch |
| `dtc_beobachtungen.csv` | ECU, DTC-Code, Status, Häufigkeit und QuickTest-Pseudonym |
| `ecu_staende.csv` | Software-/Hardwarestände aus QuickTests, soweit technisch sicher als Code darstellbar |
| `qec_berichte.csv` | QEC-JSON-Berichte, Verknüpfung mit Fällen, Reiter-Vollständigkeit und Befundumfang |
| `qec_felder.csv` | QEC-Felder/Tabellen: Reiter, Feldtyp und technisch eindeutige Ja/Nein-/Zahlenwerte |
| `tips.csv` | Verknüpfte TIPS-Beobachtungen und Verfügbarkeit von Beschwerde/Werkstatt/Maßnahme |
| `smrd_bestand.csv` | SMR-D-Quelleninventar, **keine vorgetäuschte SMR-D-Feature-Extraktion** |
| `bewertungen_NICHT_CLUSTER.csv` | Fachlich bewertete Ursachen/Lieferantenbefunde: ausschließlich nach dem Clustering ansehen |
| `autoexport_diagnosen.csv` | ECU:DTC-Diagnosezeilen aller importierten AutoExport-FINs; Zeit, Kilometer, ECU-SW-/HW-Versionen und Quelle |
| `autoexport_fallbezug.csv` | Explizite Vor-/Nach-/unklare Zeitlage jeder AutoExport-Diagnose je Fall |
| `werkstatt_historie.csv` | AutoExport-Werkstatt- und Claimdaten; originale Beanstandungs-/Maßnahmentexte nur bei Freitext-Opt-in |
| `autoexport_tips.csv` | Auch bisher unverbundene TIPS-Rohvorgänge mit vorsichtigen Fallkandidaten; Freitext nur Opt-in |
| `pumpentausch_historie.csv` | Dokumentierte Tauschereignisse, pseudonymisierte Teile-/Lieferanten-/Serien- und Chargenkennungen |
| `fall_ereignisse.csv` | Lokal vorhandene Diagnose-, Reparatur-, ECU- und Software-Ereignisse, getrennt von AutoExport-Rohzeilen |
| `ecu_versionshistorie.csv` | Fahrzeug-/Fallbezogene Hardware-/Softwarebeobachtungen aus AutoExport und Fallereignissen |
| `diagnose_qualitaet.csv` | Abdeckung mit Vor-/Nachtests, fehlenden Tests und positiven AutoExport-Beobachtungen |
| `lieferantenbefunde_NICHT_CLUSTER.csv` | Bereits im Fallmodell vorhandene Lieferantenbefunde – nur nach dem Clustering für die Ursachenprüfung |
| `lieferantenquellen_bestand_NICHT_CLUSTER.csv` | Inventar separat gespeicherter Lieferantenquellen, keine Originalbytes |
| `methodik.csv`, `README.txt`, `manifest.json` | Interpretation, Datenlücken, Version und Integritätsangaben |

**Erweiterung ab Paketversion 3:** Der Export umfasst nun auch FINs, die nur in
AutoExport-Quellen vorkommen. Die zusätzlichen Diagnosezeilen werden nicht als
vollständige QuickTests interpretiert. Insbesondere fehlt bei AutoExport-DTC-only-Quellen
der Beleg eines tatsächlich DTC-freien Nachtests. Die zusätzlichen
`*_NICHT_CLUSTER.csv`-Dateien bleiben strikt außerhalb der Clusterfeatures.

**Fallzuordnung:** `fahrzeug_id` verknüpft unabhängige QuickTests und QEC
mit ihren Fahrzeugen. `fall_id` identifiziert den Schadteilfall.
`quicktest_fallbezug.csv` klassifiziert den zeitlichen Bezug eines Tests
zu jedem Fall getrennt. Dadurch können mehrere Schadteilfälle derselben
FIN unabhängig voneinander betrachtet werden.

**Zusätzliche technische Merkmale aus AutoExport:** Nur
`autoexport_diagnosen.csv` mit `autoexport_fallbezug.csv` und
`lage_zum_pumpentausch=vor_tausch` als technische DTC-Clustermerkmale
verwenden. Lieferantenbefunde, Austausch-, Werkstatt- und Softwaremaßnahmen
sind nachgelagerte Kontexte; dokumentierte ECU-Zustände können nach
zeitlicher und fachlicher Prüfung als technische Merkmale verwendet werden.
Gleichdatige AutoExport-Beobachtungen bleiben konservativ `zeitlich_unklar`.

**Clustergrundlage:** `cluster_input.csv` und DTCs aus tatsächlich vor dem Tausch liegenden
QuickTests. Spätere DTCs helfen, die Wiederkehr zu bewerten, aber dürfen
keine unbekannte technische Vor-Tausch-Ursache vorwegnehmen. QEC-Funde,
Lieferantenbewertungen, NTF-Labels und Nachanalysen sind zunächst
**Kontext / Hypothesenprüfung**, nicht Cluster-Labels oder Eingangsfeatures.
Fehlende Diagnosedaten sind ausdrücklich keine Fehlerfreiheit.

**Unvollständige Quellen:** Wenn keine geparsten QuickTests, QEC-JSONs oder
zugeordneten TIPS vorhanden sind, bleibt dies sichtbar. SMR-D wird
derzeit als Originaldatei erkannt und im Bestand gezählt; manuell
als SMR-D klassifizierte XML-/JSON-Quellen können ebenfalls inventarisiert
werden. Ohne
kompatiblen Parser stehen noch keine SMR-D-XML-/JSON-Merkmale zur Verfügung.
Für SMR-D v3 müssen zunächst **freigegebene anonymisierte** Beispieldateien
und eine Formatbeschreibung vorliegen.

## Originaltexte: zwei Schutzstufen

- **Standard:** Kein QEC-/TIPS-Freitext, keine FIN-/QEC-IDs,
  keine Quellnamen oder PDF-Inhalte. Technische DTC-/ECU-Codes, Softwarestände
  und Fahrzeugmerkmale sind weiterhin potenziell vertraulich.
- **Opt-in:** Originalbeschriftungen, QEC-Feldwerte und verknüpfte TIPS-Texte
  werden **unverändert** in die Tabellen geschrieben, um qualitative
  Schadensbilder zu analysieren. Dieser Modus ist **nicht anonymisiert**
  und kann FINs, Namen und vertrauliche Angaben enthalten. Die App
  verlangt vor dem lokalen Export eine Warnbestätigung.
  **Vor jedem externen Upload** sind Unternehmensfreigabe und eigenständige
  Anonymisierung erforderlich.

Die Paket-Pseudonyme werden per lokalem Zufallsschlüssel generiert und
sind **nur innerhalb eines Exports stabil**. Die private Zuordnung wird
nicht in die ZIP eingefügt. Bei wiederholten Analysepaketen können sich
die Pseudonymnummern ändern. Für langfristige Fallvergleiche müssen
die Zuordnungen intern verwaltet werden.

## Zweites Paket: technische Kontextunterlagen

Technische Referenzunterlagen, die **nicht** in NTF Insight gespeichert
sind, können nach geeigneter Bereinigung als **separate ZIP** organisiert werden:

```text
Technische_Referenzen.zip
  01_topologie/         Fahrzeugnetzwerk / ECU-Topologie
  02_setzbedingungen/   DTC-Setzbedingungen.xlsx
  03_ecu_nachrichten/   Botschaften, Signale und ECU-Zuständigkeiten
  04_cdd/               Diagnosebeschreibung / CDD-Dateien
  05_kuehlung/          Kühlkreislauf-Schema und Pumpenfunktion
  06_hw_updates/        HW-Änderungen und Serienabgrenzungen
  README.txt            Dokumentversion, Gültigkeit, Fahrzeugvarianten
```

Die Referenzunterlagen sollen nach Möglichkeit **ECU-Code, DTC-Code,
Baureihe, Teilenummer/Familie und SW-/HW-Versionen** enthalten, damit
sie mit den KI-Tabellen technisch verbunden werden können. Die gleichen
Feldnamen und Einheiten sind wichtig. Keine persönlichen Daten,
Voll-FINs, Anmeldedaten oder interne Pfade im Chat hochladen.
**Freigabe und Informationsschutz gelten auch für technische Dokumente.**

Mit beiden Paketen lässt sich eine externe Clusteranalyse durchführen.
Falls die Referenzunterlagen proprietäre Informationen enthalten, sollten
sie in einer **intern freigegebenen Analyseumgebung** statt einem
öffentlichen Chat verarbeitet werden.

## Bereits beim QEC-Abruf heruntergeladene Lieferantenbelege

Die aktivierte Checkbox **Vollständige QEC-Befundungsdokumente und Anhänge**
schließt referenzgebundene, lokal gespeicherte QEC-Anhänge ein
(`qec_originale/Q00001/anlage_0001.pdf`, `.jpg`, `.png` usw.).
Diese Belege werden bereits mit dem QEC-Downloader gespeichert und müssen nicht
erneut heruntergeladen werden. Fehlende oder ältere Anhänge erscheinen im
`qec_originale/vollstaendigkeit.json`-Nachweis. Die App parst deren
Bild-/PDF-Inhalt dadurch noch nicht automatisch.

Separat archivierte Lieferanten-Analyseberichte außerhalb eines QEC-Anhangs
werden im v3-Paket bislang nur inventarisiert. Ihre Originalbytes sind
nicht enthalten; insbesondere erfolgt **keine** spekulative FIN-/QEC-Zuordnung.
Lieferantenbefunde dürfen technisch ähnliche Vor-Tausch-Fälle nach dem Clustering
prüfen, aber keine Clustereingabe oder Kausalitätsbestätigung darstellen.
