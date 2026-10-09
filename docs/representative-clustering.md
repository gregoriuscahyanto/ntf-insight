# Repräsentative QEC-Untersuchungsfälle: medoid-basierte Abdeckungsplanung

## Anwendungsziel

Ein verfügbares Untersuchungsbudget (z. B. 12 Entwicklungsfälle) soll
**möglichst viele tatsächlich vergleichbare Fälle abdecken**, statt zufällig
12 Fälle aus einer QEC-Liste auszuwählen. Der Algorithmus ist eine
**abstain-fähige Coverage-first-k-Medoids-/Facility-Location-Variante**,
keine nach Fehlerursache trainierte Klassifikation und kein Zwang, alle
QEC-Fälle in genau 12 disjunkte Cluster zu pressen.

Zu finden unter **Fälle / FIN → Repräsentative Cluster**.
Der bisherige 2D-Streudiagramm-Reiter inklusive der konservativen
gewichteten Jaccard-/Complete-Link-Gruppen bleibt unverändert.

## Warum sind 336 QEC-Fälle nicht 515 TIPS-Fälle?

- **QEC-Fall** = eigenständige QEC-Referenz zu einem untersuchten Schadteil;
- **FIN** = Fahrzeugidentität, die mehrere QEC-/TIPS-Vorgänge umfassen kann;
- **TIPS-Fall** = Werkstattvorgang, der einem QEC-Ereignis entsprechen kann,
  aber nicht ohne Prüfung ein bestätigter Kühlmittelpumpenschaden ist;
- **AutoExport-DTC** = zeitpunktbezogene Fehlerspeicher-Beobachtung, kein
  Schadteilfall.

Nicht zusammenpassende TIPS-Fälle bleiben lokal als eigene Rohdaten
erhalten. Die Prüfliste zeigt **jede möglich zuordenbare FIN-/QEC-Kombination**,
TIPS-ID, Erstellungstag und Abstand zum dokumentierten Tausch.
Bei mehreren QEC-Fällen derselben FIN erfolgt **keine stille Übernahme**.
Nur durch Klick auf **„Ausgewählte Verknüpfung bestätigen“** nach
fachlicher Prüfung wird eine eindeutige Zuordnung dauerhaft protokolliert.
Manuell bestätigte TIPS-Verknüpfungen werden bei erneuten AutoExport-Imports
nicht automatisch in einen zweiten Fall kopiert.

Die manuell bestätigte Zuordnung enthält die ursprüngliche Quellenreferenz
und sämtliche angezeigten TIPS-Felder. Die Einordnung verwendet das
bisherige konservative Fenster **365 Tage vor / 180 Tage nach** dem
untersuchten Tausch; außerhalb wird keine Zuordnung angeboten. Ein
TIPS-Erstellungsdatum ist **kein** beweisbares Reparaturdatum.
Nachgelagerte Werkstattbefunde und Maßnahmen **verändern den Score nicht**.
Nur die zum Zeitpunkt vor dem Tausch dokumentierte Kundenbeanstandung
kann als diagnostisches Textmerkmal dienen.

## Diagnostische Merkmale und explizite Annahmen

Nur die Merkmale **vor** dem untersuchten Tausch fließen in den
Vergleich ein:

- eindeutige ECU:DTC-Paare aus QEC-verknüpften QuickTests/AutoExport;
- vorher dokumentierte Kundenbeanstandungs-Tokens, ohne spätere Befunde;
- vorher bekannte ECU-Softwarestände und Fahrzeugvariante;
- vorhandener dokumentierter Tauschanker und bekannte Baureihe als
  konservative Eignungsbedingungen.

Originale DTC-Zeilen bleiben vollständig erhalten, die Merkmalsmenge zählt
jedes ECU:DTC-Paar aber höchstens einmal pro untersuchtem QEC-Fall.

**Seltenheitsgewicht:** Für einen DTC, der bei \`df\` von \`N\` QEC-Fällen
derselben Bauteilfamilie vorkommt, wird
\`IDF = 1 + ln((N + 1) / (df + 1))\` verwendet.
Ein überall gleicher Begleit-DTC liefert damit weniger spezifische
Evidenz. Für eine automatisch zulässige Paarzuordnung ist **entweder**
mindestens ein gemeinsamer DTC erforderlich, der höchstens bei
35 % der QEC-Fälle dieser Bauteilfamilie vorkommt, **oder** mindestens
zwei gemeinsame exakte ECU:DTC-Paare. Die 35-%-Grenze kann in der Oberfläche
zur **Sensitivitätsprüfung** geändert werden und ist **nicht**
wissenschaftlich kalibriert. Gerade häufige Kommunikations-/Netzwerk-DTCs
sollen dadurch nicht automatisch riesige Fehlerursachencluster erzeugen.

Der diagnostische Fault-Index ist eine Mischung aus
35 % IDF-gewichtetem Jaccard und
65 % IDF-gewichteter **symmetrischer Enthaltenheit**
(\`gewichtete Schnittmenge / min(Gewicht A, Gewicht B)\`).
Das reduziert die Strafe vieler zusätzlicher historischer DTCs, ohne sie
völlig zu ignorieren. Die Kombination mit anderen vorhandenen Ansichten
ist:

\`\`\`text
score = (0.80 × Fault-Index
       + 0.15 × Jaccard(Kundenbeanstandungen, wenn beidseitig bekannt)
       + 0.03 × Jaccard(ECU-Softwarestände, wenn beidseitig bekannt)
       + 0.02 × Jaccard(Fahrzeugvariante, wenn beidseitig bekannt))
       / Summe der tatsächlich vergleichbaren Gewichte
\`\`\`

Fehlende Text-/Software-/Konfigurationsinformationen führen zu keiner
künstlichen 0-%-Übereinstimmung. Unterschiedliche *bekannte*
Baureihen, fehlender Tauschanker und fehlender gemeinsamer ECU:DTC
schließen ein automatisches Paar aus. Der Standard-Mindestindex ist 0,35
für **dieses neue Indexmodell** und ist daher **nicht direkt** mit der
Complete-Link-Grenze 0,65 vergleichbar.

**Wichtig:** 0,70 ist ein heuristischer diagnostischer Index,
**keine 70-%-Wahrscheinlichkeit** für dieselbe Fehlerursache.

## Budgetauswahl und Abdeckung

1. Für die aktuelle Bauteilfamilie wird eine Score-/Distanzmatrix
   zwischen allen echten QEC-Fällen erstellt; fachlich ungeeignete
   Paare erhalten keine zuordnungsfähige Verbindung.
2. Ein deterministisches Coverage-first-Greedy-Verfahren wählt einen
   tatsächlich vorhandenen QEC-Fall, der möglichst viele weitere
   **zuordnungsfähige** Fälle abdeckt (keinen künstlichen Zentroid).
3. Weitere Repräsentanten werden nur gewählt, wenn dadurch zusätzliche
   Fallabdeckung entsteht. Bis zu zwei lokale Medoid-Tauschdurchgänge
   verbessern die Abdeckung bzw. die Summe der Indizes.
4. Jeder Fall wird dem am ähnlichsten ausgewählten Medoid zugeordnet,
   aber **nur wenn** sein Paar nach den festen Nachweisregeln zulässig ist
   und den einstellbaren Mindestindex erreicht. Alle anderen bleiben
   **unzugeordnet**. Cluster mit nur einem Mitglied werden nicht als
   fertige Untersuchungsgruppe ausgegeben.

Der neue Reiter zeigt je Gruppe reale QEC-IDs, Anzahl QEC-Fälle,
unterschiedliche FINs, mittleren und niedrigsten Index **zum Medoid**,
niedrigste Paarähnlichkeit **innerhalb** der Gruppe sowie gemeinsame
ECU:DTC-Paare und alle zugeordneten Fall-IDs. Diese Unterscheidung ist
wesentlich: Im Gegensatz zu Complete-Link müssen andere Mitglieder
**nicht** sämtlich untereinander den Mindestindex bestehen.

Abdeckung wird als \`zugeordnete QEC-Fälle / QEC-Fälle der ausgewählten
Bauteilfamilie\` ausgewiesen – **nicht** als Prozentsatz von TIPS-Fällen
oder AutoExport-FINs.

Der neue 2D-Plot verwendet klassische **MDS auf der Screening-Distanz**
(\`1 - score\` für berechenbare Paare, 1 für ungeeignete Vergleiche).
MDS ist eine Näherung; sichtbare Abstände können die Matrix verzerren.
Die numerischen Zuordnungs- und Paarwerte sind maßgeblich.
Große, nummerierte Punkte sind die Medoids, Grau steht für nicht
zugeordnete QEC-Fälle mit darstellbarer Vorher-Diagnose.

## Übertragung eines Untersuchungsergebnisses

Die Auswahl begründet **eine Prüfhypothese**, keine automatische
Übertragung einer Reparaturempfehlung. Für jede Gruppe erscheinen
nachgelagert Warnungen, wenn

- bekannte SSL-Endbefunde unterschiedlich sind;
- keine SSL-Endbefunde für die spätere Gegenprüfung existieren;
- das schwächste interne Paar unter der Medoid-Grenze liegt;
- nur eine FIN vertreten ist oder nur ein gemeinsamer ECU:DTC die
  komplette Gruppe verbindet.

**SSL-Endbefunde, Lieferanten- und Reparaturergebnisse sind explizit
aus der Clusterformel und Medoidauswahl ausgeschlossen.** Sie werden
nur *nach* der Zuordnung verwendet, um die fachliche Übertragbarkeit
zu hinterfragen.

## Validierung und Grenzen

Die im MVP verwendeten 35-%-DF-Grenze, 0,35-Mindestindex,
Gewichte und TIPS-Zeitfenster sind vorläufige **Engineering-Hypothesen**.
Vor einem automatischen Ursachen-Transfer müssen sie mit extern
fachlich bestätigten Pumpendefektfällen bewertet werden.
Empfehlenswerte Messgrößen: Präzision der Fallpaare, tatsächlich
gleiche technische Ursachen, Homogenität von SSL-Endbefunden,
Abdeckung der unabhängigen FINs und Anteil ungelöster Fälle.

Weder dieses Verfahren noch der historische Complete-Link-Algorithmus
stellen aus der Anzahl der Cluster eine Fehlerursachen-Wahrheit fest.
Alle Originaldateien/DuckDB-Rohdaten verbleiben auf dem lokalen Rechner.
Synthetische Tests kommen ins öffentliche Repository; keine echten FINs,
Werkstatttexte oder QEC-Dokumente.
