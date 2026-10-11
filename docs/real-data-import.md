# Lokaler Import echter Quellen (QuickTest, QEC, AutoExport, CDD, Part History)

Diese Anleitung beschreibt **nur die Softwarefunktion**. Originale Mercedes-Benz
Fahrzeug-, Werkstatt-, Lieferanten- und Diagnoseinformationen dürfen nicht in
diesem öffentlichen GitHub-Repository gespeichert werden.

## Voraussetzungen

- Python 3.11+; `python -m pip install -e ".[dev]"`
- Zugelassener Mercedes-Benz-Rechner / Speicherort mit Zugriffsschutz
- Genügend freier Speicher für das ZIP und die entpackten Rohdateien
- Quelloriginale dürfen für den vorgesehenen Zweck lokal verarbeitet werden

## GUI: Original-ZIP automatisch importieren

1. NTF Insight starten.
2. **Datenquellen** öffnen.
3. Quellenart auf **„Automatisch erkennen (empfohlen)“** belassen.
4. ZIP-Datei auf die Drop-Zone ziehen oder über **„Dateien auswählen…“** öffnen.
5. Hintergrundimport abwarten. Die GUI zeigt den Fortschritt an.
6. Archiv-/Parse-Status kontrollieren. Die neuen globalen Referenzdaten
   findest du unter **Quellenwissen**, fahrzeugbezogene Ereignisse unter
   **Fälle / FIN**, **Zeitplot** oder **DTC-Explorer**.

Mehrere einzelne Dateien können ebenfalls zusammen ausgewählt werden. Bei
Einzeldateien darf die Quellart manuell überschrieben werden; innerhalb eines
ZIP-Pakets wird **jede Datei einzeln anhand ihres Inhalts** klassifiziert.

## Für größere Pakete: CLI

```powershell
python -m pip install -e ".[dev]"
ntf-insight-import "C:\\interner-pfad\\meine-daten.zip"
python -m ntf_insight
```

Optional eigener freigegebener Speicherort:

```powershell
ntf-insight-import "C:\\interner-pfad\\meine-daten.zip" --data-dir "D:\\GeschuetzteNTFDaten"
$env:NTF_INSIGHT_DATA_DIR = "D:\\GeschuetzteNTFDaten"
python -m ntf_insight
```

CLI und GUI verwenden denselben lokalen DuckDB-Speicher und das
SHA-256-Rohdatenarchiv. **Nichts wird durch den Import an GitHub geschickt.**
Die Nutzung eines privaten, zugelassenen Datenverzeichnisses ist wichtig, da
die Archivierung und DuckDB **keine integrierte Dateiverschlüsselung oder
Rollenprüfung** bieten.

## Erste unterstützte Quellformate

| Quelle | Verarbeitung | Status |
|---|---|---|
| QEC-Schadteilliste (.xlsx) | QEC-Fälle und Tauschanker; zusätzlich **alle Quellspalten und -blätter** mit Referenznr. | Struktur- und Fallparser |
| QEC-SSL-Endbefunde ohne FIN (.xlsx) | Blatt `Schadteile` mit `Referenznr.`, `SSL Endbefund` und `SSL-Endbefund Benennung`; ausschließlich Ergänzung vorhandener QEC-Fälle durch identische Referenznummer, **keine neuen FINs** | Referenzbasierte Ergänzung |
| AutoExport Diagnose (.csv) | Vollständige CSV-Rohfelder für alle FINs sowie fallbezogene DTCs/ECU-Stände bei eindeutiger Zuordnung | Parser bereit |
| AutoExport Werkstatt/Claim (.csv) | Alle Werkstatt-/Claim-Zeilen (einschließlich doppelt benannter Spalten), fallbezogene Aktionen bei eindeutiger Zuordnung; widersprüchliche Kilometerangaben werden gekennzeichnet | Parser bereit |
| AutoExport TIPS (.csv) | TIPS-Referenz, Erstellungsdatum, Erst-Beanstandung, Werkstattbefund und Maßnahmen; Rohzeilen für alle FINs, konservative QEC-Zuordnung | Parser bereit |
| QuickTest (.pdf) | FIN, Datum, km, ECU-Diagnosestände, DTCs, Snapshots, vollständige auslesbare PDF-Texte | Parser bereit |
| AutoExport-Aggregat (.csv) | Separat gespeichert, **kein** Ersatz für verbaute Population / Ausfallraten-Nenner | Parser bereit |
| CDD/Candela (.cdd) | Diagnoseklassen, Serviceinstanzen, Qualifier, Semantik und Beschreibungen | CDD-Serviceparser bereit; **keine validierte SMR-D-Triggerlogik** |
| Part History (.pdf) | Produktbezogene Änderungen, Revisionsstände, Referenzen, Tages- bzw. Kalenderwochenzeiträume | Strukturparser bereit; **nicht FIN-spezifisch** |
| Lieferanten-Analysebericht (.pdf) | Alle maschinenlesbaren PDF-Seitentexte lokal gespeichert; keine unbelegte NTF- oder Schuldzuordnung | Quelltextparser bereit; fachliche Befundinterpretation offen |
| SMR-D | Separater Format-/Fachparser notwendig; CDD ersetzt die Triggerlogik **nicht** | Ausstehend |
| ECU-HW-/SW-Releaseänderungen | Release-Wissen benötigt eigene Datei; QuickTest-ECU-Stände sind **keine Release-Änderungsliste** | Ausstehend |

## Wie der Import Fallinformationen verknüpft

**Ausgangsfall:** Ein QEC-Eintrag mit eindeutiger Referenz ist die Fallbasis.
FIN wird als primärer Verbindungsschlüssel verwendet; ein bekannter QEC-Präfix
wird nur bei passender Struktur entfernt. Eine abweichende US-VIN aus dem
QuickTest bleibt ein **separates Quellattribut**. Niemals automatisch annehmen,
dass zwei 17-stellige Identifikatoren austauschbar sind.

Diagnose- und Werkstattdaten werden an den bekannten FIN/Fall angehängt, wenn
sie eindeutig zugeordnet werden können. Bei mehreren Fällen derselben FIN
wird ein zeitlich passender, eindeutig nächster Tauschanker verlangt.
Bei nicht eindeutigem Bezug bleiben Ereignisse **unzugeordnet**.
Als **vorläufige technische Importgrenzen** gelten:

- DTC/ECU-Stand/Kurztest: 365 Tage vor bis 180 Tage nach Tausch
- Werkstatteintrag: 30 Tage vor bis 30 Tage nach Tausch
- TIPS-Erstmeldung: 365 Tage vor bis 180 Tage nach Tausch (nur
  **vor dem Tausch** datierte initiale Beanstandungen können als
  Beanstandungsbegriffe in die diagnostische Fallähnlichkeit einfließen).
  Werkstattbefunde, durchgeführte Maßnahmen, SSL-Endbefunde und
  Reparaturergebnisse beeinflussen **nie** den Ähnlichkeitswert.

Diese Grenzen sind keine validierten physikalischen Fehlerfenster und müssen
anhand realer Fälle geprüft werden. Beim Import wird kein Lieferant als
Verursacher klassifiziert.

**Upload-Reihenfolge:** AutoExport kann auch **vor** der QEC-Liste importiert
werden. Sobald neue QEC-Fälle hinzukommen, verarbeitet die App die bereits
archivierten AutoExport-CSV-Dateien für die eindeutige Fallzuordnung erneut;
das ursprüngliche AutoExport-ZIP muss nicht nochmal hochgeladen werden.
Eine vollständig gespeicherte Rohdatenhistorie wird dabei nicht erneut
geschrieben. Frühere Versionen ohne die aktuellen zeitlichen Metadaten werden
einmalig neu indexiert. Reine FIN-Zeilen ohne QEC-Fall bleiben recherchierbar.

**TIPS-Quellenlogik:** TIPS-Fall-IDs sind eigenständige
Werkstattvorgänge, keine QEC-Schadteilreferenzen. Eine passende FIN allein
reicht für die Verbindung bei mehreren QEC-Fällen nicht aus: Ohne eindeutig
nächsten Tauschanker im zulässigen Zeitraum bleibt die TIPS-Zeile als
FIN-weite Quelle unzugeordnet. Die `CreationDate` datiert den
TIPS-Vorgang und ist kein belegtes Reparaturdatum.

**SSL-Endbefundexport ohne FIN:** Ein QEC-Excel mit dem Blatt
`Schadteile` und den Spalten `Referenznr.`, `SSL Endbefund` und
`SSL-Endbefund Benennung` wird automatisch erkannt. Solche Listen
enthalten **keine gesicherte FIN** und erzeugen deshalb keine
neuen Fahrzeugfälle. Stattdessen bleibt jede Zeile lokal im
Quellenwissen und ergänzt nur einen bereits vorhandenen Fall mit
**exakt identischer QEC-Referenznummer**. Bei abweichender
Sachnummer, widersprüchlichen Endbefunden oder fehlendem
Referenztreffer wird **nichts zugeordnet**. Der QEC-Fall mit FIN und
die ergänzende SSL-Liste können in beliebiger Reihenfolge importiert
werden. Ein erneuter Import ersetzt keine Originaldatei und
erstellt keine Duplikat-FIN. Unter **Datenquellen** zeigt der
Importstatus die Zahl ergänzter QEC-Fälle und Referenzkonflikte.
Erst nach einem erfolgreichen Abgleich erscheinen die verschiedenen
SSL-Endbefunde im Dropdown der Clusteranalyse. Die Endbefunde
dienen ausschließlich zur Fallselektion, niemals als
Clustermerkmale oder Lieferanten-Verursachernachweis.

**QEC-Quellblatt-Logik:** Die NTF-Clusterblätter im QEC-Export können
Teilansichten derselben Schadteilreferenzen enthalten. Sie werden in der
Quellenablage separat nachvollziehbar gespeichert, aber **nicht als neue
Schadteilfälle doppelt angelegt**.

**Part History:** Fertigungs-/Lieferantenänderungen betreffen zunächst
ein Bauteil bzw. eine Produktionslinie, **nicht** die FIN im QuickTest.
Kalenderwochen werden mit Präzision `calendar_week` und Zeitraum
gespeichert, nicht auf einen frei erfundenen Ereignistag reduziert.

**CDD:** Candela-Diagnoseinstanzen sind Service- und
Steuergerätedefinitionen. Derzeit extrahiert NTF Insight noch keine
validierten Fehlerbedingungen (Set/Enable/Healing). Sie benötigen die
passende SMR-D-Triggerliste und eine fachliche Interpretation.

**Wichtig zur Zeitsemantik:** Bei AutoExport-Diagnosen wird das präzise
Quellfeld `DiagStartTs` verwendet, **sofern es vorhanden und lesbar ist**.
Das ursprüngliche `DiagStartDt` wird ebenfalls als Rohfeld behalten.
Die ISO-UTC-Zeichenkette (`Z`) bleibt als Quellreferenz erhalten; eine
nicht belegte Übertragung in die lokale QuickTest-Zeitzone findet nicht statt.
Fehlt `DiagStartTs`, wird auf das Datum zurückgefallen und die
Uhrzeitpräzision entsprechend gekennzeichnet. Ein solcher DTC wird nur
als *am Tag beobachtet* gespeichert.
Daraus wird **kein vollständiger fehlerfreier Kurztest** und keine exakte
Erstauftretenszeit konstruiert. Im QuickTest-PDF kennzeichnet die
Diagnosezeit ebenfalls den Beobachtungs-/Reportzeitpunkt; historische
Fehlerspeicher-Kilometerwerte bleiben als Metadaten erhalten.

## FIN-Historie und Importqualität

Unter **Fälle / FIN → FIN / Fallanalyse → AutoExport-Gesamthistorie nach FIN**
können beliebige gültige FINs direkt gesucht werden, **auch wenn noch kein
QEC-/NTF-Fall und kein PDF-QuickTest existiert**. Die Tabelle lädt jeweils
maximal 200 Zeilen und bietet Seitennavigation. DTCs, Werkstattzeilen und
TIPS-Vorgänge bleiben als eigenständige Quellenzeilen erhalten; alle Originalfelder
sind unter **Quellenwissen** abrufbar. Die angezeigte Quellzeit wird nicht
stillschweigend in die Ortszeit umgerechnet. Wiederholte DTC-Meldungen
sind nicht automatisch verschiedene Schadensfälle.

Die ZIP-Historie mit mehr als 423.000 DTC-Rohzeilen ist technisch durch
die Streaming-Ablage mit bis zu **1.000.000 Zeilen je AutoExport-Quelldatei**
unterstützt. Bei Überschreitung wird **nicht** stillschweigend abgeschnitten:
Die Transaktion wird zurückgerollt, das Original bleibt archiviert und
der Import meldet den Fehler. Ausreichend lokaler Speicher und Importzeit
sind erforderlich.

Nach dem Import werden gescannte CSV-Zeilen, ungeeignete/ungültige Zeilen,
unzugeordnete Ereignisse und verknüpfte TIPS-Datensätze separat ausgewiesen.
Ein erheblicher Teil nicht fallbezogen verwendbarer Zeilen ist bei wenigen
QEC-Fällen normal: Die vollständige, unabhängige FIN-Quellenhistorie bleibt
davon unberührt.

## Schutzmaßnahmen und Wiederholbarkeit

- ZIP-Pfad-Traversal und Symlinks werden abgewiesen.
- Einzel- und Gesamtextraktionsgrößen sowie Kompressionsraten sind limitiert.
- Unbekannte Dateien dürfen sicher archiviert werden, erhalten aber keinen
  vorgetäuschten Parser-Erfolgsstatus.
- Die originalen Dateien liegen unverändert im content-addressierten
  lokalen Archiv.
- Abgeleitete Ereignisse verweisen auf SHA-256 und Zeile/Berichtsbereich.
- Ereignis-IDs sind deterministisch; Wiederholungsimporte erzeugen keine
  mehrfachen Kopien derselben DTC-Beobachtung.
- Bei nicht eindeutigen FIN/Fall-Verknüpfungen gibt es Hinweise statt
  stillschweigender Zuordnung.
- Importierte Daten sind von manuellen Korrekturen getrennt.

## Noch zu validieren

Die Parser sind mit **synthetischen Strukturtests** ausgestattet. Vor einem
produktiven Einsatz müssen Import, Vollständigkeit, Verknüpfung und
Befundinterpretation von fachlich Berechtigten an repräsentativen Fällen
abgenommen werden. Insbesondere fehlen noch:

- fallbezogene Prüfung bei mehreren Tauschen gleicher FIN
- zusätzliche QuickTest-Layouts, Zeichensätze und ECU-Sonderformen
- strukturierter Lieferanten-PDF-Befund mit referenzierter Zuordnung
- DTC-Trigger/Set/Enable/Healing aus echten SMR-D-Dateien
- HW-/SW-Release-/Änderungsliste und Variante/Version-Gültigkeit
- Ableitung der **tatsächlichen** Fehler-Erst-/Letztauftrittszeit aus
  den Diagnose-Snapshotfeldern (der Export enthält Diagnosezeitpunkte,
  nicht zwangsläufig die ursprüngliche Fehlerentstehung)


## Neue Datenbanktabellen und Anzeige

Die **lokale DuckDB** besitzt die Tabellen `source_knowledge_documents`
und `source_knowledge_rows` mit Quellen-SHA-256, Parsertyp, Quellfundstelle,
sofern vorhanden FIN, Kurzbeschreibung und sämtlichen extrahierten
Feldern als JSON. Wiederholte Importe derselben Originaldatei ersetzen ihre
abgeleiteten Quellzeilen transaktional und erzeugen keine Doppelzeilen.

Die neue Desktop-Seite **Quellenwissen** zeigt diese Daten mit Volltextsuche,
Quellentypfiltern, Seitennavigation und vollständig lesbaren Quellfeldern.
Die ursprünglichen PDF-/Excel-/CDD-/CSV-Dateien bleiben im geschützten
Rohdatenarchiv und gelangen nicht nach GitHub.

Zur Nachverarbeitung bereits archivierter CDD-, Part-History- oder QEC-Dateien:
**Datenquellen → Archivansicht → Alle archivierten Dateien → Datei markieren
→ Markierte Datei neu prüfen**. Bei ZIP-Paketen die ZIP erneut importieren.

Die CDD-Serviceinstanzen und globalen Part-History-Änderungen werden
**nicht automatisch als DTC-/Tauschereignis unter einer FIN** abgelegt.
Die technische Referenz muss erst mit Fahrzeugsoftware,
Bauteilnummer/Revision oder einer eindeutigen Fallreferenz verknüpft werden.
