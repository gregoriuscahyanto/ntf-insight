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

## Alternative mit Checkbox: Cluster um QEC-Fälle bilden

Das Kästchen **„QEC-Fälle als Anker für die Clusterbildung verwenden“**
ist **standardmäßig AUS**. Dann bleiben die bisherige
HDBSCAN-Leaf-/EOM- und konservative Complete-Link-Cosinus-Analyse
sowie die in diesem PR ergänzte QEC-Präferenz bei der
*Repräsentantenauswahl* unverändert.

Mit **aktiviertem** Kästchen wird dagegen eine **andere,
QEC-gestützte Diagnosezuordnung** verwendet. Es handelt sich
**nicht** um ein weiteres HDBSCAN-Verfahren:

1. Jede QEC-Pumpenfall-FIN mit geeigneten Diagnosemerkmalen wird
   zum möglichen **echten QEC-Anker**. Mehrere QEC-FINs mit
   identischen ursprünglichen ECU:DTC-Merkmalen teilen sich
   einen kanonischen Anker. Das verhindert Doppelgruppen.
2. Eine andere FIN – auch eine FIN nur aus AutoExport – wird ihrem
   diagnostisch ähnlichsten QEC-Anker zugeordnet, **aber nur bei
   mindestens 45 % originaler Sparse-TF-IDF-Cosinusähnlichkeit
   zur repräsentativen QEC-FIN**. In gleicher Ähnlichkeit
   entscheidet der alphabetisch erste Anker deterministisch.
   FINs ohne passende Anker bleiben **unzugeordnet**.
3. Nur Ankergruppen mit der eingestellten
   **Mindestclustergröße** werden als Cluster ausgewiesen.
   Kleinere Gruppen werden **nicht künstlich aufgefüllt**:
   deren FINs bleiben als „mit DTC, ohne Cluster“ sichtbar.
   Auch QEC-FINs ohne geeignete ECU:DTC-Daten werden nicht
   als Anker eingesetzt.
4. Jede ausgegebene Gruppe besitzt somit einen echten
   **QEC-Repräsentanten**. Die erklärte Ähnlichkeit misst die
   jeweilige FIN **zu diesem Anker** und bedeutet nicht,
   dass alle FIN-Paare der Gruppe die 45-%-Schwelle einhalten.
   Anders als Complete-Link ist dieses Verfahren kein
   Paarweise-Ähnlichkeitsnachweis, und im Gegensatz zu HDBSCAN
   keine unüberwachte Dichtegruppenbildung.

Der **gleiche AutoExport+QEC-FIN-Bestand**, die zugelassenen
vor dem dokumentierten Pumpentausch liegenden DTCs und dieselben
Originalmerkmale werden verwendet. Der Ankerlauf und
HDBSCAN/EOM/Complete-Link werden beim einmaligen Klick auf
**„Clusteranalyse starten“** zusammen berechnet und
im Arbeitsspeicher vorgehalten. Danach kann die Checkbox
**ohne Neuberechnung** ein- und ausgeschaltet werden.
Die Verfahrenauswahl zeigt bei aktiviertem Ankerverfahren
dessen eigene Bezeichnung und ist gesperrt. Beim Ausschalten
kehrt sie zum **zuvor ausgewählten HDBSCAN- bzw.
Complete-Link-Verfahren** zurück.

**Achtung:** Clusteranzahl, Zuordnung und C-Nummern können sich
durch das alternative Verfahren ändern. Nur innerhalb eines
Verfahrens bleiben Clusterkennungen stabil. Die Donutgrafik,
Punktwolke, DTC-Erklärung, FIN-Tabelle und die manuelle
DTC-Prüfpriorität beziehen sich jeweils klar auf das
ausgewählte Verfahren. DTC-Markierungen sind keine Seed-
Auswahlbedingung und beeinflussen keine Ähnlichkeitswerte.
QEC-Ankerzuordnung ist **kein Nachweis**, dass ein Fahrzeug
einen Pumpendefekt hat, dass ein Pumpentausch geholfen hätte
oder dass ein Lieferant verantwortlich ist.

## Repräsentant: vorzugsweise eine FIN mit QEC-Fall

Ein Cluster repräsentiert weiterhin **eine echte FIN aus dem Cluster**,
niemals einen künstlich berechneten Durchschnittsfall. Für jede Gruppe
wird zuerst der diagnostisch zentralste Kandidat auf den originalen
Sparse-TF-IDF-Cosinusmerkmalen ermittelt. Existiert eine FIN mit
zugeordnetem QEC-Pumpenfall, wird die **diagnostisch zentralste
QEC-FIN** bevorzugt, sofern ihr mittlerer Cosinuswert zu den übrigen
Cluster-FINs **mindestens 90 % des optimalen Werts** erreicht.

Falls QEC-FINs dafür zu untypisch sind, bleibt die diagnostisch
zentralste FIN **ohne** QEC-Bezug Repräsentant. Existiert überhaupt
kein QEC-Fall im Cluster, wird ebenfalls der gewöhnliche
Diagnoserepräsentant gewählt. Im Clustertableau steht die Spalte
**Rep. QEC? (Ja/Nein)**. Die Clustererklärung begründet die Auswahl
oder den Rückgriff auf die diagnostisch bessere FIN.

**Die QEC-Präferenz verändert weder HDBSCAN/Complete-Link, deren
Merkmalsgewichtung, Distanzen, Clusterzuordnung noch Clusternummern.**
Lediglich die Repräsentanten-FIN und die auf diese FIN bezogenen
Cosinusähnlichkeiten/Mediane ändern sich gegebenenfalls. So ist der
Repräsentant leichter fachlich über QEC überprüfbar, ohne einen
untypischen Schadteilfall zum vermeintlichen Gruppenbeweis zu machen.

## Kompakte Donut-Übersicht und DTC-Fachmarkierungen

Statt fünf nebeneinanderliegenden Kennzahlkarten zeigt die
Clusteranalyse **Gefundene Cluster** als große Kennzahl und
**Verteilung der FINs** als gut lesbares Donutdiagramm.
Im Donut steht die Zahl **aller eindeutigen FINs**, die Legende
zeigt absolute Zahlen und den prozentualen Anteil von:

1. FINs in Clustern;
2. FINs mit DTC-Daten, aber ohne Cluster;
3. FINs ohne geeignete DTC-Daten.

Die drei Gruppen schließen einander aus und ergeben in Summe
exakt die Gesamtzahl der FINs. Wird von HDBSCAN Leaf zu EOM
oder Complete-Link gewechselt, aktualisieren sich Donut,
Clusterzahl, Tabelle und Punktwolke anhand gecachter Ergebnisse.

### Wichtigere DTCs fachlich hervorheben

Im **DTC-Explorer** erscheint auch der lokal importierte
AutoExport-Katalog, nicht nur DTCs aus QEC-Fällen.
Unterschiedliche QEC-/AutoExport-FIN-Zahlen stehen absichtlich
in getrennten Spalten, damit keine doppelte Fahrzeugzählung entsteht.

Eine DTC-Zeile auswählen und **★ Für Pumpenprüfung markieren**
drücken. Die Markierung gilt exakt für **ECU:DTC** und wird
lokal in `dtc_manual_review_marks` gespeichert, getrennt
von allen importierten Quelldateien. Optional kann man eine
fachliche Notiz hinterlegen und später ändern. Die Markierung
kann jederzeit wieder entfernt werden.

Ein Cluster enthält einen **manuell markierten DTC**, wenn
mindestens eine seiner FINs die exakte ECU:DTC-Kombination
im zugelassenen Diagnosefenster aufweist.

- **Hohe Prüfpriorität:** mindestens 50 % der FINs im Cluster
  haben mindestens einen manuell markierten DTC.
- **Prüfhinweis:** wenigstens eine, aber weniger als 50 %
  der FINs sind von markierten DTCs betroffen.
- **Keine Markierung:** keine FIN in diesem Cluster hat
  einen aktuell markierten ECU:DTC.

Mehrere markierte DTCs derselben FIN erhöhen die Anzahl
**betroffener FINs nicht künstlich**. Die Spalten
*Prüfpriorität* und *Markierte FINs* stehen in der
Clustertabelle. Gruppen mit hoher Priorität werden dort
zuerst angezeigt; bestehende Clusterkennungen bleiben stabil.
Die Erklärung nennt die einzelnen markierten
ECU:DTCs mit der jeweiligen FIN-Häufigkeit und unterscheidet
sie von der normalen Clusterbegründung.

**Wichtig:** Diese Priorität entsteht **nach** HDBSCAN und
Complete-Link. Die DTC-Markierung verändert keinerlei
TF-IDF-Gewichte, Clustergrenzen, Mitglieder oder 2D-/3D-Punkte.
Sie ist eine **Fachprüf-Reihenfolge**, kein Nachweis einer
defekten Pumpe, kein NTF-Urteil und keine
Lieferantenverantwortung. Kommunikations-DTCs können
beispielsweise auch andere Fehlerursachen haben.
Beim Zurückwechseln vom Explorer zur Clusteransicht werden
Prioritäten ohne erneuten Clusterlauf geladen.

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
