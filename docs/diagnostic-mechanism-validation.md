# Diagnostische Merkmale und fachlich bestätigte Fehlermechanismen

Stand: experimentelle Folgeerweiterung auf
[ML-Cluster mit HDBSCAN](experimental-hdbscan.md).
Benutzeroberfläche: **Fälle / FIN → ML-Cluster (HDBSCAN)**, unterhalb
der Fall-/Ausreißerlisten.

## Warum dieser Schritt?

Die lokalen QEC-Screenshots zeigen 336 Schadenfälle, davon nur 170
mit einem belegten Vor-Tausch-ECU:DTC und dokumentiertem Tauschanker.
Die bisherigen Leaf-/EOM-HDBSCAN-Gruppen sind oft *stark heterogen*:
ein großer Anteil ihrer Fallpaare erreicht weniger als den
vorläufigen 45-%-Cosinusindex. Mehr Dichtecluster bedeuten nicht mehr
technisch identische Pumpendefekte.

Deshalb trennt dieser Schritt streng:

1. **Datenverfügbarkeit:** Wie gelangt eine Beobachtung überhaupt in
   die QEC-Signatur, welche Fälle fehlen warum?
2. **Explorative Merkmalsvariante:** Welchen Einfluss haben sehr häufige
   ECU:DTC-Kombinationen auf Gruppenzuordnungen?
3. **Unabhängige fachliche Validierung:** Haben mehrere QEC-Fälle,
   unabhängig von der Diagnose berechnet, denselben *bestätigten*
   Pumpenfehlermechanismus?
4. **Optionales Paarlernen:** Können Vor-Tausch-Merkmale anhand einer
   ausreichend großen, FIN-getrennten Fachlabel-Stichprobe eine
   Bestätigungshypothese unterscheiden? **Noch kein produktiver
   automatischer Ursachentransfer.**

## Diagnoseverfügbarkeit und DTC-Quellen

Die App zeigt je Bauteilfamilie, Quellenfilter und Vor-Tausch-Zeitfenster:

- QEC-Fälle mit Tauschanker und mindestens einer ECU:DTC-Kombination
  **vor** dem untersuchten Tausch;
- Fälle ohne Tauschanker;
- Fälle ohne QEC-zugeordnete DTC-Zeilen;
- Fälle mit DTCs, die nicht nachweisbar vor dem Tausch lagen;
- Fälle mit Vorher-DTC, aber nicht aus den gewählten Quellen;
- Fälle mit Vorher-DTC außerhalb des gewählten Zeitfensters.

Auch ein und derselbe ECU:DTC aus QuickTest und AutoExport wird als
**ein Mengenmerkmal pro QEC-Fall** bewertet und im Diagnoseaudit
als Quellüberschneidung ausgewiesen. Originale und Ereigniszeilen
bleiben in der lokalen Datenbank erhalten; wiederholte tatsächliche
Diagnosebeobachtungen dürfen nicht aus den Rohquellen gelöscht werden.

Es werden weder willkürliche AutoExport-FINs noch TIPS-Vorgangsnummern
als zusätzliche QEC-Schadensfälle gezählt. Das erklärt, warum
336 QEC-Fälle nicht zwangsläufig mit der Zahl aller AutoExport-FINs
übereinstimmen.

Die beobachtete Häufigkeit eines ECU:DTC in den **mit Tauschanker
und Vorher-DTC belegten Fällen** ist

\`\`\`text
Häufigkeitsanteil = QEC-Fälle mit ECU:DTC / QEC-Fälle mit Vorher-DTC
\`\`\`

Die Tabelle zeigt die 30 häufigsten Codekombinationen.
Das ist ein statistischer Sichtbarkeitsindikator, **keine fachliche
Aussage über Ursachenrelevanz oder Reparierbarkeit**.

### Experimenteller Filter für häufige ECU:DTC

Der Schalter **„Häufige ECU:DTC ab 35 % testweise aus ML-Merkmalen
ausschließen“** ist standardmäßig **aus**. Bei Aktivierung wird innerhalb
der gewählten QEC-Bauteilfamilie eine DTC-Häufigkeit auf der *unveränderten*
Vorher-Diagnosegrundgesamtheit bestimmt. Die ECU:DTC-Kombinationen mit
Anteilen von mindestens 35 % werden aus den drei DTC-basierten
HDBSCAN-Merkmalsansichten entfernt:

- exakte ECU:DTC;
- DTC-Code ohne ECU;
- über den verbliebenen Codes belegte beteiligte ECU.

Die übrigen Merkmalsansichten bleiben unverändert. **Fälle ohne einen
verbleibenden informativen Vorher-ECU:DTC können nicht allein durch
gleiche Baureihe/Software/Beanstandung eine sichere ML-Gruppe bilden**:
sie werden ausdrücklich als *durch Häufigkeitsscreening nicht
projezierbar* markiert.

Die ECU:DTC-Frequenzen stehen NICHT für ein gelerntes Bauteil-
Relevanzmodell. Ein zentraler Fehlercode kann häufig sein und
trotzdem der wichtigste Pumpenursachenhinweis bleiben.
Der Schalter soll als **Sensitivitätsanalyse** helfen, nicht
eine fachlich bewiesene Ursache aussortieren.

Der EOM/Leaf-Vergleich bekommt stets die gleiche Filtereinstellung,
den gleichen Vor-Tausch-Zeitraum und die gleichen Datenquellen.
Der unveränderte HDBSCAN-Modus (ohne Filter) bleibt verfügbar.

## Fachprüfvorlage mit SSL-Endbefund

Die Schaltfläche **„Fachprüfvorlage lokal exportieren (mit FIN und SSL)“**
schreibt eine CSV mit den folgenden Spalten:

\`\`\`text
qec_case_id;fin;qec_ssl_end_finding;review_status;mechanism_code;reviewer;evidence_ref;confirmed_on
\`\`\`

Alle Zeilen beginnen mit `review_status=pending`, **ohne** bestätigte
Ursache. Die QEC-SSL-Rohtexte werden bewusst nur als unabhängige
Befundquelle angezeigt, nicht vorinterpretiert. Das ist ein
**vertraulicher Export** mit FINs, QEC-IDs und SSL-Befundtexten:
nur auf einem zugelassenen Arbeitsrechner öffnen und nicht in
den GitHub-Branch committen, in E-Mails weiterleiten oder unkontrolliert
an externe Dienste senden.

Erst nach echter fachlicher Bestätigung können folgende Spalten
ausgefüllt werden:

- `review_status=confirmed`: explizite Freigabe einer
  **spezifischen** technischen Ursache;
- `mechanism_code`: zwischen Fällen **einheitlicher** eindeutiger
  Code, etwa `PCB_TRACK_SHORT` oder `CONNECTOR_PIN_CORROSION`
  **nur sofern durch einen unabhängigen Befund bestätigt**;
- `reviewer`: Kennung der fachlich prüfenden Person;
- `evidence_ref`: nachvollziehbare Prüf-/8D-/Laborreferenz;
- `confirmed_on`: Bestätigungsdatum im ISO-Format YYYY-MM-DD.

Bei ungeklärter Ursache bleibt `review_status=unknown` bzw.
`pending`; das ist **kein positives Negativ- oder NTF-Label**.
Die Werte `NTF`, `UNKNOWN`, `ELECTRICAL_FAULT` und weitere
unspezifische Sammelcodes werden **nicht** als bestätigte
Fehlermechanismen akzeptiert. Die App lehnt außerdem widersprüchliche
Doppeleinträge, unbekannte QEC-IDs, fehlende Prüfreferenzen und
ungültige Datumsfelder ab.

Import: **„Bestätigte Fehlermechanismen lokal einlesen“**.
Die Bestätigungen werden für den aktuellen Lauf ausschließlich
**im Arbeitsspeicher** gehalten (kein automatischer Git-/Cloud-/DB-Upload
und keine stillschweigende Persistenz). Die ursprüngliche CSV
bleibt unter deiner lokalen Datenverwaltung.

### Cluster-Fachprüfung nach dem HDBSCAN-Lauf

Die App zeigt für jede bestehende HDBSCAN-Gruppe, wie viele ihrer
QEC-Mitglieder einen bestätigten Mechanismus haben. Nur Fallpaare
**von unterschiedlichen FINs** zählen als unabhängige
Vergleichspaare. Jedes fachlich geprüfte Paar ist entweder

- **gleich:** beide besitzen denselben explizit bestätigten
  spezifischen Mechanismus-Code;
- **abweichend:** beide besitzen unterschiedliche bestätigte
  Mechanismen;
- **nicht auswertbar:** mindestens ein Mitglied ist nicht bestätigt,
  oder beide Fälle stammen von derselben FIN.

Die Paarübereinstimmung bezieht sich **nur auf die geprüften Paare**:
bei einem repräsentativ nicht geprüften Cluster ist sie nicht die
wahre technische Präzision. Eine Abweichung zweier sicher bestätigter
Ursachen innerhalb einer Gruppe verhindert eine pauschale Übertragung.
Die Klassifikation beeinflusst niemals den HDBSCAN-Merkmalsraum,
die Clusterzuordnung, die gewählten Medoids oder die 2D-Projektion.

## Gated Pair-ML-Test statt fiktivem „KI-Lernen“

Der Button **„FIN-getrenntes Paarmodell prüfen“** nutzt nur
manuell bestätigte Fallmechanismen. Er zeigt zunächst „noch keine
belastbare Lernbasis“, solange weniger als

- **30** QEC-Fälle mit bestätigten Mechanismen UND verlässlichem
  Vor-Tausch-ECU:DTC/Tauschanker,
- **2** unterschiedliche Mechanismen,
- **8 unabhängige FINs pro vorhandenem Mechanismus**

existieren. Auch bei Erreichen dieser Untergrenzen kann eine
ausreichend balancierte Aufteilung noch unmöglich sein.

Bei genügend geprüften Daten wird

1. **vor** der Fallpaarbildung nach FIN getrennt
   (`StratifiedGroupKFold` mit reproduzierbarer Startzahl);
2. jeweils **nur innerhalb** der Training- und Testsplits
   ein Label „gleicher vs. verschiedener bestätigter Mechanismus“
   aus zwei unterschiedlichen FINs erzeugt;
3. eine simple regularisierte logistische Regression auf
   dokumentierten Vor-Tausch-**Paarmerkmalen** trainiert:
   DTC-Jaccard, DTC-Enthaltenheit, Übereinstimmung von DTC-Code/
   ECU/Beanstandungs-Tokens/Software/Kontext sowie dokumentierte
   Merkmalsabdeckung;
4. ausschließlich im separaten Testsplit *Precision*, *Recall*,
   *Average Precision*, relative Häufigkeit gleicher Mechanismen und
   Testpaarzahl gemeldet.

**Keine SSL-/Lieferantenbefund-/Reparaturergebnismerkmale,
keine FINs/QEC-IDs und keine Werkstatt-Nach-Tausch-Ereignisse gelangen
in das Paarmodell.** Die Labels dienen ausschließlich als
Trainings-/Testziel und bestimmen nicht die HDBSCAN-Gruppen.

Diese Paarvergleichsbeobachtungen sind trotzdem statistisch
**nicht unabhängig**, wenn mehrere Paare einen Fall teilen.
Eine hohe Test-Metrik ist noch kein zuverlässiger Qualitätsnachweis
für reale zukünftige Ursachenübertragung. Keine automatisch
zugeordnete Ursache, kein Modell-Pickle und keine produktive
Reparaturempfehlung werden gespeichert oder eingesetzt.

## Noch offen: Fachliche CDD-Relevanz

CDD/Candela liefert aus der derzeitigen Quelle keine verbindlich
geprüfte Ursache→ECU:DTC-Relevanzzuordnung für die Kühlmittelpumpe.
Darum erfindet die App keine „pumpenspezifischen DTC-Gewichte“.
Ein mit Entwicklung/Diagnose abgestimmter Katalog der echten
Fehlermechanismen, zugehörigen DTC-/Versorgung-/Software-Signale
und bekannte **unterschiedliche** Ursachenpaare ist die Voraussetzung
für ein kausal interpretierbares Modell.

## Lokale Daten und CI

Alle neuen automatischen Tests arbeiten **ausschließlich mit
synthetischen QEC-Fällen**. Eine GitHub Actions Self-hosted Runner
Installation auf dem Windows-PC mit vertraulichen Originaldateien
ist nicht erforderlich und wird aus Sicherheitsgründen nicht empfohlen.
Echte FIN-, SSL- und Prüfdateien bleiben lokal. Der bestehende
aggregierte **„Qualitätsbericht ohne FIN“** enthält nur Zahlen –
auch solche Aggregate vor einer externen Weitergabe intern freigeben.
