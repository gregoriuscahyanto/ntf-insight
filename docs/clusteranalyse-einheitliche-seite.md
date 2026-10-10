# Clusteranalyse – eine Oberfläche, alle verfügbaren FINs

## Ausgangspunkt

Unter **Fälle / FIN → Clusteranalyse** gibt es **genau einen** Reiter.
Keine eingebettete zweite Clusterseite, keine getrennten AutoExport-
und QEC-Cluster und **kein KMeans**.

**Grundgesamtheit ist die eindeutige FIN**, nicht die Anzahl der DTC-Zeilen
oder QEC-Schadteilfälle. Die App vereinigt FINs aus allen importierten
AutoExport-Kategorien mit den FINs der QEC-Kühlmittelpumpenfälle.
Eine FIN aus beiden Quellen zählt **einmal**. Zusätzliche QEC-only-FINs
werden aufgenommen und zählen zur Gesamtsumme. Die Angabe
`11.667 + QEC-only-FINs` ist ein BEISPIEL aus lokalen Summen, keine
hartcodierte Berechnungsgröße. Die echte Summe wird nach einem
lokalen Quellenabgleich ermittelt.

## Bedienung von oben nach unten

1. **Kleine Parameter**: Mindestclustergröße (Standard 5) und
   `MinSamples` (Standard 2). Die optionale Auswahl
   **Nur FINs mit QEC-Pumpentauschdatum** grenzt den Analysebestand
   für eine tauschbezogene Prüfung ein. Normalerweise ist sie **aus**,
   damit die vollständige AutoExport-FIN-Population einbezogen wird.
2. **Clusteranalyse starten** ist die einzige Berechnungsaktion.
   Ein Hintergrundthread liest die lokalen AutoExport- und QEC-Merkmale
   und berechnet auf derselben FIN-Grundlage HDBSCAN Leaf,
   HDBSCAN EOM und konservative Complete-Link-Cosinus-Prüfgruppen.
3. **Kleine Übersicht**: FINs insgesamt (aus AutoExport und QEC
   dedupliziert), Anzahl Cluster, FINs in Clustern, FINs mit DTC
   ohne Cluster und FINs ohne geeignete DTCs. Die letzteren bleiben
   Teil der Gesamtzahl, aber erhalten **keine erfundene Gruppe**.
   Die Summe der drei FIN-Statuszahlen entspricht immer dem
   gesamten betrachteten FIN-Bestand.
4. **FIN-Punktwolke in 2D oder 3D** zeigt die echten FIN-Diagnosemuster.
   Farben markieren Cluster, grau steht für DTC-FINs ohne Cluster.
   Repräsentative FINs erhalten eine Umrandung. Klick auf einen
   Punkt wählt FIN bzw. Cluster; in 3D dreht/gekippt die linke
   gedrückte Maustaste beim Ziehen die Darstellung. Das Mausrad zoomt.
   **Die Plotkoordinaten sind niemals Clustering-Merkmale.**
5. **Verfahren wählen** neben 2D/3D wechselt wirklich die
   Clusterzuordnung, die Kennzahlen, Tabelle und Erklärung:
   HDBSCAN Leaf, HDBSCAN EOM oder Complete-Link Cosinus.
   Alle werden beim Start berechnet und bleiben für sofortige
   Umschaltung im Arbeitsspeicher.
6. **Cluster auswählen**: Die Tabelle zeigt Anzahl der FINs,
   FINs mit QEC, repräsentative FIN, Anzahl DTCs im gemeinsamen
   Kern und einen diagnostischen Ähnlichkeitsindex.
7. **Warum gehören die FINs zusammen?** Die Klartextbegründung
   enthält alle wiederkehrenden ECU:DTC-Kombinationen mit
   Häufigkeit **x von y FINs**. Falls in den importierten Daten
   ein DTC-Text vorhanden ist, steht er direkt beim Code.
   Sonst wird **kein Text erfunden**. Außerdem werden
   Verfahren, Grenzen und der Anteil diagnostisch schwacher
   Paare (bei großen Gruppen als ausdrücklich begrenzte Stichprobe)
   erklärt. Ein identischer DTC ist **keine** bestätigte gleiche Ursache.
8. **FINs im Cluster**: Alle Fahrzeuge in der ausgewählten Gruppe
   mit DTC-Anzahl, Ähnlichkeit zur repräsentativen FIN,
   Anzahl und Kennungen zugeordneter QEC-Fälle sowie Datenherkunft
   **AutoExport, QEC/QuickTest oder beides**. FIN-Suche und ein
   Link öffnen die lokale FIN-/Fallhistorie. Echte FINs und
   QEC-Kennungen erscheinen nur in der lokalen Anwendung.

## Diagnose-Zeitregel

Die Clustereingaben sind die pro FIN zusammengeführten
**eindeutigen ECU:DTC-Schlüssel**. QEC-spezifische
Vor-Tausch-Diagnoseereignisse werden zur selben FIN-Signatur
hinzugefügt, nicht als zusätzlicher QEC-Fall-Cluster gezählt.

- **FIN mit QEC-`Rep.-Datum` zum Pumpentausch:** AutoExport- und
  QEC-DTCs von Kalendertagen **streng vor dem frühesten**
  dokumentierten Tausch. Gleichentags-, undatierte und spätere
  DTCs sind keine gesicherte Vor-Tausch-Evidenz. Die
  QEC-QuickTest-Zeitstempel werden ebenfalls geprüft.
- **FIN ohne solchen Tauschanker:** Für die allgemeine
  Diagnosemustersuche dürfen AutoExport-DTCs aus der vorhandenen
  Diagnosehistorie verwendet werden. Es wird **kein** Tauschzeitpunkt
  behauptet.
- **Nur Tausch-FINs:** Der optionale Filter schließt FINs
  ohne QEC-Tauschanker vollständig aus. Das reduziert
  verständlicherweise die Fahrzeuganzahl stark.

Das generische AutoExport-`RepairDt` ist ein **Werkstattdatum,
kein bestätigtes Pumpentauschdatum**. Diagnosen nach dem Tausch
bleiben für spätere Vorher-/Nachher-Prüfung relevant, gehören
aber nicht zu den ursprünglichen Clustering-Merkmalen.
Der Wechsel von allgemeiner Historie zu enger Vor-Tausch-Sicht
führt wegen unterschiedlicher Beobachtungsfenster zu
**explorativen** Gruppen, nicht zu einem Ursachenbeweis.

## Methoden und Laufzeit

- **HDBSCAN Leaf/EOM:** Originale ECU:DTCs liegen in
  **Sparse-TF-IDF**. Ein begrenztes **16D-SVD-Modell**
  ermöglicht die echte HDBSCAN-Berechnung, ohne über 11.000 FINs
  eine vollständige quadratische Distanzmatrix aufzubauen.
  Die vorherige, rein fallbasierte QEC-Version verwendet
  einen anderen Ausgangsmerkmalsraum und ist **nicht**
  unmittelbar mit den neuen Clusterzahlen vergleichbar.
- **Complete-Link Cosinus:** Auf den **originalen Sparse-TF-IDF-
  Cosinusabständen** werden innerhalb von Leaf-Gruppen
  deterministische Teilblöcke bis 450 FINs streng mit
  Complete-Link geprüft. Jeder ausgewiesene Complete-Link-Cluster
  erfüllt den eingestellten Mindestwert 45 % für alle
  **intern** verglichenen Paare. Weil nicht sämtliche FINs
  global hierarchisch zusammengeführt werden, ist dies
  ausdrücklich nur eine **konservative Prüfgruppe** und
  **keine globale Complete-Link-Partition**.
- **Plot:** Erste drei Modellkoordinaten dienen ausschließlich
  der Zeichnung; Rotieren/Zoomen ändern die Gruppen nicht.
  Rendern erfolgt gruppenweise über QPainter und nicht über
  11.000 einzelne QGraphicsItems.

**Geschwindigkeit:** Der Entwicklungszielwert für ca. 11.000 FINs
liegt bei unter einer Minute für die erste Berechnung und
unter einer Sekunde für den gecachten Methodenwechsel.
Das sind **keine gemessenen Laufzeiten der internen Originaldateien**;
Rohdatendichte, Windows-Hardware und Gruppengrößen können
die Dauer verändern.

HDBSCAN-Dichtegruppen sind keine bestätigten Pumpenfehler,
keine NTF-Feststellungen und kein Nachweis für eine
Lieferantenverantwortung. Die bekannten QEC-Fälle
markieren nur den tatsächlich vorliegenden Quellenbezug.
