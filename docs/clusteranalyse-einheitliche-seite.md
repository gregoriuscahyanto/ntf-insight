# Einheitliche Clusteranalyse in NTF Insight

Die bisher getrennten Tabs **2D-Streudiagramm**, **Repräsentative Cluster**
und **ML-Cluster (HDBSCAN)** werden in der FIN-/Fallanalyse durch genau einen
Tab **Clusteranalyse** ersetzt. Der Tab enthält die bisherige Fallauswertung
nicht selbst: `FIN / Fallanalyse` und `QuickTests nach FIN` bleiben eigene
unveränderte Ansichten.

## Bedienung von oben nach unten

1. **Bauteilfamilie wählen** (standardmäßig Kühlmittelpumpe, falls vorhanden).
   Nur QEC-Fälle derselben Familie gehören in eine ML-Kohorte.
2. **Verfahren** wählen: `HDBSCAN · Leaf` (Standard), `HDBSCAN · EOM`,
   `Complete-Link · Cosinus` oder `Complete-Link · DTC-Jaccard`.
   Letzteres ist die bisherige restriktive Repräsentantenmethode mit
   **anderem Ähnlichkeitsmaß**. Der schreibende Datenbestand bleibt unverändert.
3. Gemeinsame Filter: DTC-Quelle (QuickTest/AutoExport/beide),
   Zeitfenster vor Pumpentausch, Mindestgröße je Cluster. Optionaler
   DTC-Häufigkeitsfilter ist eine Sensitivitätsanalyse, keine DTC-Widerlegung.
   Die Methode blendet nicht relevante Eingaben aus:
   `MinSamples` für HDBSCAN; Paar-Cosinus für das neue Complete-Link;
   gewichteter Jaccard-Mindestindex für die ältere Methode.
4. **Cluster berechnen**. Parameterwechsel invalidiert die alte Darstellung;
   die GUI lässt keine alten Zuordnungen als aktuelle Ergebnisse stehen.
   Die Berechnung läuft im Hintergrund, um die Qt-Oberfläche bedienbar zu halten.
5. **Methoden vergleichen** rechnet auf gleicher gewählter Vor-Tausch-Kohorte
   mehrere Verfahren. Die Tabelle zeigt Clusteranzahl, zugeordnete Fälle,
   Rauschen, durchgehenden exakten DTC-Kern, Anzahl Gruppen mit ≥2 FINs
   sowie Fallpaar-Übereinstimmung zum zuerst gewählten Verfahren. Doppelklick
   auf eine Methode zeigt ihre Gruppen. Optional können zwei Projektionen
   nebeneinander betrachtet werden. Das andere Verfahren wird über das
   Dropdown rechts neben der 2D/3D-Umschaltung ausgewählt.
6. **2D**: klassische MDS-Projektion derselben diagnostischen Distanz.
   **3D**: MDS mit dritter Achse, drehbar über Azimut/Neigung und
   rechte Maustaste, per Mausrad zoombar. Plotkoordinaten werden **niemals
   als Clustering-Eingabe** verwendet. Unterschiedlich gruppierte Punkte
   können in der Projektion räumlich zusammenfallen. Unzugeordnete Fälle
   sind grau; repräsentative Fälle erscheinen größer.
7. **Clustertabelle**: pro Gruppe ein echter QEC-Medoid, Anzahl Fälle,
   verschiedene FINs, Diagnostik-Kern und Prüfhinweise.
   **Falltabelle** darunter: reale QECs, FINs, diagnostischer
   Index zum Medoid, bei HDBSCAN die Zugehörigkeit, gemeinsame DTCs,
   und separat markierte *post-hoc* SSL-Endbefunde.
   Per Doppelklick oder **In FIN / Fallanalyse öffnen** navigieren.
   Die Fälle ohne Vor-Tausch-Diagnose bzw. ohne Gruppenbindung sind getrennt
   in einer unteren Tabelle zugänglich.
8. **Fachprüfung und Exporte**: vorhandene HDBSCAN-Fachvalidierung,
   Pilotfälle, CPC3-Brücken, Wiederauftreten, technische
   Expertenbestätigungen, das restriktive Repräsentanten/TIPS-Werkzeug
   sowie die erweiterte Fallpaaranalyse bleiben über drei Schaltflächen
   in Dialogen erreichbar – **keine neuen Cluster-Tabs**.
   Zusätzlich lässt sich die ausgewählte Ergebnismenge als
   **vertrauliche lokale CSV** speichern.

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
