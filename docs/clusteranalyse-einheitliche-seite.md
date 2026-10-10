# Einheitliche Clusteranalyse in NTF Insight

Die bisher getrennten Tabs **2D-Streudiagramm**, **Repräsentative Cluster**
und **ML-Cluster (HDBSCAN)** werden in der FIN-/Fallanalyse durch genau einen
Tab **Clusteranalyse** ersetzt. Der Tab enthält die bisherige Fallauswertung
nicht selbst: `FIN / Fallanalyse` und `QuickTests nach FIN` bleiben eigene
unveränderte Ansichten.

## Analysebestand innerhalb desselben Tabs (keine weiteren Cluster-Tabs)

Im Bereich **Fälle / FIN → Clusteranalyse** steht oben die Wahl
**Analysebestand**. Standard ist **Alle FINs – AutoExport + QEC gemeinsam**:
ein Fahrzeug wird anhand der eindeutigen FIN **genau einmal** geclustert.
AutoExport-DTCs und belegte QEC-/QuickTest-DTCs vor dem Pumpentausch
gehen in **dieselbe FIN-Signatur** ein; doppelte FINs werden vereinigt.
Zusätzliche QEC-only-FINs können den AutoExport-Bestand erweitern.
Die Summen zeigen ausdrücklich die Überlappung beider Bestände.
Für einen belegten Pumpentausch werden nur vor dem frühesten
QEC-**Rep.-Datum** beobachtete DTCs verwendet. Ohne Tauschanker
bleibt die allgemeine AutoExport-Diagnosehistorie nutzbar,
ohne sie als Vor-Tausch- oder Pumpenbefund zu behandeln.

Für die bisherige HDBSCAN-/Complete-Link-Fallanalyse mit 2D/3D
**Nur QEC-Pumpenfälle (Vor-Tausch-Analyse)** wählen.
Es gibt weiterhin nur **einen Reiter „Clusteranalyse“**. Je nach
Analysebestand erscheint eine eigene, passende Visualisierung:
FIN-Muster als interaktive Balken und Fallcluster als 2D/3D.
Das sind methodisch verschiedene Verfahren, **kein Ursachen-Voting**.
Auch der FIN-basierte MiniBatchKMeans-Ansatz ist explorativ und
liefert keine Wahrscheinlichkeit einer gleichen Pumpenursache.

Die folgenden QEC-Fallzahlen und Fachfunktionen gelten nur für
den optionalen QEC-Fallmodus.

## Standardansicht: vier Antworten ohne Statistikkenntnisse

1. **Cluster erstellen:** `Clusteranalyse starten` anklicken.
   Alle zulässigen Methoden werden intern berechnet; in der
   Standardansicht wird **HDBSCAN Leaf** gezeigt.
2. **Wie viele Cluster?** Eine Kennzahl zeigt die Anzahl der
   Cluster für das angezeigte Verfahren (z. B. HDBSCAN Leaf). Ein
   **Kreisdiagramm** teilt die QEC-Fallgrundgesamtheit in genau drei
   disjunkte Gruppen: **Fälle in Clustern**, **auswertbar, aber ohne
   Cluster** und **vor dem Tausch nicht auswertbar**. Die Summe muss
   stets der Anzahl der QEC-Fälle der ausgewählten Bauteilfamilie
   entsprechen. Die Legende zeigt absolute Fallzahlen und Prozentwerte.
   Keine dieser Fallzahlen ist automatisch eine Anzahl eindeutiger FINs.
   Nicht auswertbar bedeutet nicht, dass in der Werkstatt nie eine
   Diagnose erfolgte: Es kann ein geeigneter DTC, Zeitnachweis oder
   Tauschanker fehlen; ein experimenteller Filter kann zudem
   Merkmale entfernen.
3. **Visuell und Fälle:** Die 2D-Grafik stellt echte QEC-Fälle
   dar, 3D bleibt optional. Über **Clusterverfahren** neben 2D/3D
   werden die tatsächlich angezeigten Cluster, Falllisten und
   Erklärungen gewechselt, ohne die Analyse erneut zu berechnen.
   Die Tabelle **Cluster auswählen**
   zeigt die Cluster mit Anzahl QEC-Fällen, FINs und gemeinsamem
   ECU:DTC-Kern. Klick auf eine Zeile oder auf einen Punkt zeigt
   die Fälle im Cluster, einschließlich QEC, FIN und Evidenz
   im Vergleich zum repräsentativen Fall (Medoid).
4. **Warum zusammen?** Die Erklärung nennt echte
   Vor-Tausch-ECU:DTCs, die in **allen Fällen** vorkommen,
   weitere häufige ECU:DTCs mit Fallzahlen sowie – falls
   dokumentiert – gemeinsame Beanstandungsbegriffe.
   Für einzelne QECs erscheint deren ECU:DTC-Überlappung
   mit dem Medoid. Das Ergebnis verwendet genau die gewählte
   Quelle, den Zeitraum und ggf. den DTC-Häufigkeitsfilter.
   Fehlt ein durchgehender DTC-Kern oder sind viele Paar-
   ähnlichkeiten schwach, steht eine gut sichtbare Warnung.
   Die drei einfach lesbaren Abschnitte zeigen gemeinsame
   ECU:DTCs, zusätzliche DTCs mit Fallzahlen, die Art der
   Zuordnung sowie schwache Fallpaare. **Alle qualifizierenden
   DTCs werden vollständig gezeigt**, auch nach dem vierten.
   Wo der DTC-Explorer für **genau die ECU:DTC-Kombination** einen
   in den Diagnosen dokumentierten **DTC-Klartext** kennt, wird
   dieser direkt neben dem Fehlercode angezeigt. Bei fehlendem
   Text bleibt der Code ohne erfundene Interpretation stehen.
   Klartexte können aus anderen Diagnosesitzungen stammen; sie
   beschriften die Codes lediglich und fließen **nicht**
   in Ähnlichkeit oder Clusterbildung ein.
   Das sind beobachtete Gemeinsamkeiten, **keine** mathematische
   Zurechnung zu einer technischen Pumpenursache.

**Gesamtumfang AutoExport:** Direkt unter der gewählten
Datenbasis zeigt die Clusteranalyse die **Zahl lokal importierter
AutoExport-Rohzeilen** (DTC, Werkstatt, TIPS) und die **Anzahl
unterschiedlicher FINs über alle importierten AutoExport-Quellen**.
Gleiche FINs aus mehreren Dateien oder Kategorien werden nicht
mehrfach als Fahrzeug gezählt. Daneben werden **QEC-Fälle und
unterschiedliche QEC-FINs** für die ausgewählte Bauteilfamilie
ausgewiesen. **AutoExport-Datenumfang aufschlüsseln** zeigt die drei
Quellkategorien getrennt. Dies sind nur erfolgreich importierte und
gespeicherte Zeilen, nicht zwingend jede Zeile in einer möglicherweise
noch nicht vollständig importierten Originaldatei. Der große
AutoExport umfasst auch FINs ohne QEC-Pumpenfall. Die vollständigen
Originaldateien und FIN-Listen bleiben ausschließlich lokal.

**Weitere Details für Experten anzeigen** blendet bei Bedarf
die alten, weiterhin voll funktionsfähigen Methoden-, Stabilitäts-,
K-Prüfgruppen- und Ausreißertabellen und technischen Werkzeuge ein.
**Erweiterte Einstellungen anzeigen** ist ein eigener optionaler
Bereich vor dem Start. Nichts davon ist für die vier Fragen nötig.

**Achtung:** Die Zahl der Cluster ist immer methoden- und
parameterabhängig. Gleiche Diagnosen und identische DTCs sind
keine Bestätigung eines mechanischen Pumpendefekts oder einer
Lieferantenverantwortung. SSL- und Lieferantenbefunde fließen
nicht in das Clustering oder diese Erklärung ein.

## Bedienung von oben nach unten

1. **Bauteilfamilie und Datenbasis wählen** (standardmäßig
   Kühlmittelpumpe, soweit vorhanden), DTC-Quelle (QuickTest,
   AutoExport, beide) und Zeitfenster vor dem dokumentierten Tausch.
   Nur QEC-Fälle derselben Bauteilfamilie werden gemeinsam analysiert.
2. **Clusteranalyse starten** ist die **einzige Aktion zum Erzeugen der
   Cluster**. Die Anwendung berechnet **automatisch** HDBSCAN Leaf,
   HDBSCAN EOM, Complete-Link Cosinus und – wenn mit dem Filter
   kompatibel – das ältere gewichtete DTC-Jaccard-Verfahren.
   Sie erstellt dabei **auch** die konservativen K-Prüfgruppen,
   die Methodenvergleichstabelle und die Robustheitsprüfung zu
   diagnostischen Ein-Faktor-Variationen. Ein Methoden-Voting wird
   **nicht** durchgeführt.
3. **Erweiterte Einstellungen anzeigen** öffnet die optionalen
   methodenspezifischen Filter und die Auswahl des zunächst
   **angezeigten Referenzverfahrens** (Standard Leaf). Darin liegen
   MinSamples, Mindestgröße, Paar-Cosinus, DTC-Jaccard-Schwelle und
   der experimentelle DTC-Häufigkeitsfilter. Wechsel von
   Datenbasis oder Berechnungsparametern invalidiert alte
   Ergebnisse. Der Tab startet **nicht ungefragt beim Öffnen**.
4. **Methodenvergleich** zeigt Clusteranzahl, zugeordnete Fälle,
   Rauschen, exakten DTC-Kern, Zahl der Gruppen mit mindestens zwei
   FINs und Fallpaar-Überlappung. Ein Doppelklick zeigt die echte
   jeweilige Methode im selben Cluster-Tab. Die Robustheitstabelle
   kennzeichnet explizit, zu welchem beim Start gewählten
   Referenzverfahren ihre Werte gehören. Methodenvergleich bedeutet
   nicht unabhängige Fehlerursachenbestätigung.
5. **Robustheitsprüfung** unterscheidet echte Fallpaar-Übereinstimmung
   (Paar-Jaccard), Paarerhalt und Verbindungen zwischen Gruppen.
   Quelle, Zeitfenster und optionale Einstellungen werden einzeln
   variiert. Dabei zählen nur QECs mit nachgewiesener Vor-Tausch-
   Diagnose in **beiden** Szenarien; fehlende Daten gelten nicht
   als Gegenbeleg. Kennzahlen sind keine Pumpendefekt-Wahrscheinlichkeit.
6. **2D/3D** sind Projektionen derselben *ursprünglichen*
   Diagnosedistanzen, niemals Clustering-Eingaben. In 3D dreht
   **linke Maustaste halten und horizontal ziehen** die Ansicht,
   vertikales Ziehen neigt sie. **Einzelklick** wählt weiterhin
   einen Fall. Präzise Regler liegen in den Expertendetails.
   Gruppierte Fälle sind farbig, Ausreißer grau und
   Repräsentanten größer. Zwei Verfahren können in der
   Expertenansicht mit einem **separaten** Dropdown
   `Zweites Verfahren` nebeneinander verglichen werden.
7. **Clustertabelle / Falltabelle** enthalten Medoide, FIN-Anzahl,
   diagnostischen Kern, Mindest-/Medianähnlichkeit, echte
   QEC-IDs und fachliche Vorbehalte. Fall-Doppelklick führt
   in **FIN / Fallanalyse**. Die lokale FIN-/QEC-Suche zeigt
   selbst überlagerte Projektionspunkte. Fälle ohne geeignete
   Diagnose oder ohne Gruppenbindung bleiben separat prüfbar.
8. **Fachprüfung und Exporte**: Pilotprüfgruppen, CPC3-Brücken,
   Wiederauftreten, HDBSCAN-Fachprüfung und weitere bewährte
   lokale Analysewerkzeuge bleiben erreichbar. Vertrauliche
   CSV-Dateien werden nur nach ausdrücklichem Export auf dem
   lokalen Rechner gespeichert; keine Originaldaten in CI/Git.

Die Vergleichsansicht ist **kein Wettbewerb um das beste Verfahren**:
Unterschiedliche Methoden werden als komplementäre Diagnosemodelle
interpretiert. Ihre Ähnlichkeit liefert keine unabhängige Bestätigung
eines mechanischen Pumpendefekts oder einer Lieferantenursache.

## Konservative Kernprüfgruppen direkt im selben Tab

Unter **Clustertabelle** steht die Tabelle
**„Konservative Prüfgruppen · Complete-Link Cosinus“**.
Sie verwendet unabhängig vom aktuell angezeigten Clustering dieselben
ursprünglichen Vor-Tausch-Diagnoseabstände und eine **separat
konfigurierbare Mindestpaar-Cosinusähnlichkeit** (Standard 0,45,
**explorativ, nicht ursachenvalidiert**). Bei jeder Berechnung läuft
die strenge Gruppierung im GUI-Hintergrund mit; kein neuer Tab,
keine zusätzliche Originaldatenbeschaffung.

Die Kernprüfgruppen werden mit `K1`, `K2` usw. bezeichnet, die
jeweils aktive Clustermethode mit `C1`, `C2` usw.
**Die Zahlen dürfen nicht gleichgesetzt werden.**
Die „Zugeordneter Cluster“-Spalte entsteht ausschließlich aus
**wirklichen gemeinsamen QEC-Fall-IDs**. Bei Gruppen, deren Fälle
zwischen mehreren ML-Clustern verteilt sind, wird die Überlappung
explizit aufgeführt. Der Filter **„Nur passend zum gewählten Cluster“**
grenzt die Anzeige auf dessen tatsächlich überlappende Prüfgruppen
ein; ohne Filter werden alle konservativen Kandidaten dargestellt.

Ein Klick auf eine `K`-Zeile zeigt direkt in der **bestehenden
Falltabelle darunter** den echten Repräsentanten und die anderen
QEC-Fälle dieser Kernprüfgruppe. Dieselben QECs werden in
**beiden** aktiven 2D-/3D-Projektionen hervorgehoben.
Ein erneuter Klick auf einen Hauptcluster `C` zeigt wieder dessen
vollständige Falltabelle. Die neue **FIN-/QEC-Suche** unterhalb des
Plots hilft, Einzelfälle auch bei projizierten Punktüberlagerungen
aufzufinden. Lange CPC3- und SSL-Texte sind am Tabellenkopf
nicht unkontrolliert vollbreit; vollständige Zellen sind weiterhin
per Tooltip zugänglich und Spalten individuell verstellbar.

**„Prüfgruppen zur technischen Fachprüfung lokal exportieren“**
schreibt eine vertrauliche `*.csv` mit maximal
drei QECs pro Prüfgruppe: einem echten Medoid,
einem möglichst ähnlichen QEC einer **anderen FIN** und
einem kontrastierenden QEC einer weiteren **anderen FIN**,
falls verfügbar. Mehrere Fälle derselben FIN werden für die
unabhängige Prüfung nicht mehrfach als Replikation gezählt.
Die Datei entspricht den bestehenden
`PILOT_REVIEW_FIELDS` und kann nach einer **echten**
extern belegten Fachprüfung über den bestehenden
Fachvalidierungsimport eingelesen werden.

**Alle Zeilen starten mit `review_status=pending`.** Es werden
weder Mechanismen noch NTF-Klassifikationen aus SSL, DTC-Ähnlichkeit
oder Cluster-Mitgliedschaft automatisch bestätigt.
Die QEC-, FIN- und SSL-Daten bleiben ausschließlich in der
lokalen CSV; die GitHub-Runner-Workflows veröffentlichen
keine neuen Einzelfall-Daten und keine neue Statistik.

Die im Pilot einmal beobachteten fünf Complete-Link-Gruppen
(15 Fälle bei Mindest-Cosinus 0,45) sind **keine
fest verdrahteten Cluster**: Die Tabelle berechnet die
aktuell vorhandenen QECs neu, berücksichtigt alle gewählten
DTC-Quellen, Filter und Parameter und kann daher künftig
mehr, weniger oder andere Gruppen enthalten.

## Methoden und vergleichbare Merkmale

| Methode | Distanz / Prüfkriterium | Konfiguration |
|---|---|---|
| HDBSCAN Leaf | dieselbe mehransichtige TF-IDF-Euklid-Distanz auf normierten Vektoren | `min_cluster_size`, `min_samples` |
| HDBSCAN EOM | exakt dieselbe TF-IDF-Distanz, andere Dichtegruppen-Auswahl | dieselben Parameter |
| Complete-Link Cosinus | identische TF-IDF-Distanzen, jedes interne Fallpaar muss Mindest-Cosinus erreichen | Mindest-Cosinus und Mindestgröße |
| Complete-Link DTC-Jaccard | älteres Modell: Evidenzgate mit DTC-Kern, DTC-gewichteter Jaccard plus Kontext; **andere Metrik** | eigener Mindestindex, Mindestgröße und feste Kernhäufigkeitsregel |

Die **Paarübereinstimmung** wird auf echten QEC-Paaren berechnet:
`gemeinsam gruppierte Paare / Vereinigung der gruppierten Paare`.
Cluster-IDs wie `C1` zweier Verfahren sind keine gemeinsamen
Identitäten. Dieselbe FIN zählt für Gruppen mit ≥2 FINs nur einmal.

Bei aktiviertem TF-IDF-DTC-Häufigkeitsfilter lässt der direkte
Vierervergleich das historische Jaccard-Verfahren aus, statt
unterschiedliche Filter stillschweigend als identisch auszugeben.

## Grenzen der Aussagekraft

**Cluster und 2D-/3D-Nähe sind keine Fehlerursachenbestätigung.**
Identische CPC3-DTCs belegen nicht automatisch eine defekte Pumpe,
gleichen Fehlermechanismus oder einen Lieferantenfehler.
HDBSCAN-Zugehörigkeit ist keine Ursachenwahrscheinlichkeit.
Ohne unabhängig geprüfte Schadteil-/Laborbefunde sind
`Leaf`, `EOM` und Complete-Link nur explorative
Diagnose-Gruppierungsverfahren. Die bisherige empirische
Prüfstrategie bleibt: Leaf als Suchverfahren, Complete-Link 45 %
als konservativer Filter, anschließend unabhängig belegte Ursachen
in verschiedenen FINs prüfen.

Der 3D-Plot ist keine zusätzliche Information aus Rohquellen:
es handelt sich um eine weitere **approximative Koordinatenprojektion**
derselben multidimensionalen Diagnoseabstände.
Punkte dürfen überlappen; maßgeblich für Gruppenzugehörigkeit sind
Fall- und Clustertabelle, nicht Pixelabstände.

## Technische Erweiterbarkeit

- `src/ntf_insight/analysis/cluster_workspace_engine.py` enthält
  `METHODS`, `MethodDefinition`, `ClusterParameters` und
  `calculate_clusters` mit normierten
  `UnifiedClusterResult`/`UnifiedCluster`-Objekten.
- **Neue Methode hinzufügen:** Methodendefinition im Register anlegen,
  eigenen Berechner/Adapter ergänzen, der dieselbe normierte
  Ergebnisstruktur liefert; die existierenden Diagramme und
  Tabellen werden **automatisch wiederverwendet**. Neue
  spezifische Parameter müssen im gemeinsamen Parameterbereich
  bereitgestellt werden – keine neue QWidget-Tab-Klasse.
- `src/ntf_insight/app/widgets/cluster_projection_plot.py` ist
  die für alle Methoden identische Qt-Grafik. Sie zeichnet
  vorhandene MDS-Koordinaten (in 2D oder aus drei Dimensionen
  gedreht). Für nicht identische Merkmalsräume weist die
  Benutzeroberfläche ausdrücklich auf die Vergleichsgrenze hin.
- Die bisherigen direkt importierbaren Widgets bleiben als
  fachliche Werkzeuge erhalten, aber CasePage registriert
  ausschließlich **einen** Cluster-Tab.

## Vertraulichkeit und CI

Die Qt-Seite verarbeitet FIN, QEC und ECU:DTC **nur lokal**.
`ClusterWorkspace` fügt weder Workflow-Trigger, GitHub-Uploads
noch Analytics/Telemetry hinzu. Der neue lokale CSV-Export enthält
echte FINs und QEC-IDs; deshalb **nicht in Git, Chat oder
GitHub-Logs hochladen**. Alle zugehörigen Linux-/Windows-CI-Tests
verwenden rein synthetische Fälle ohne originale Fahrzeugdaten.
