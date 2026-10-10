# Gemeinsame Verfahren und Cluster-Robustheit (nur lokale Daten)

## Ziel

**Keine einzelne Methode herrscht:** HDBSCAN Leaf findet feinere
Dichtegruppen, HDBSCAN EOM grobe Gruppen, Complete-Link Cosinus prüft
kompakte Fallgruppen und das ältere DTC-Jaccard-Verfahren dient als
fachlich restriktive, methodisch *anders gewichtete* Gegenprobe.

Die Methoden werden **nicht durch Mehrheitsabstimmung** zu einer
automatischen Fehlerursachen- oder Lieferantenentscheidung kombiniert.
Das Ergebnis ist ein Bericht zur Robustheit *diagnostischer Gruppen*.

## GUI

Unter **Fälle / FIN → Clusteranalyse** die lokale Datenbasis wählen und
**Clusteranalyse starten** drücken. Dies ist die **einzige Schaltfläche
zum Erzeugen der Cluster**: Leaf, EOM, Complete-Link Cosinus und – sofern
mit den gewählten Datenfiltern kompatibel – DTC-Jaccard werden automatisch
berechnet. Außerdem entstehen im selben Durchlauf die konservativen
Prüfgruppen und die Robustheitsprüfung. Die GUI startet **nicht automatisch
schon beim Öffnen des Tabs**, sondern erst auf bewussten Klick.

**Erweiterte Einstellungen anzeigen** öffnet die methodenspezifischen
Parameter und die Auswahl des **angezeigten Referenzverfahrens** (Standard:
Leaf). Damit wird kein konkurrierender Analyseablauf aktiviert. In der
Ergebnistabelle lässt sich weiterhin zwischen Verfahren wechseln; die
Robustheitstabelle kennzeichnet ihre beim Start verwendete Referenz
explizit. Ein späterer Wechsel der Ergebnisansicht interpretiert einen
bereits berechneten Robustheitsbericht nicht stillschweigend um.

Methodenvergleich, Stabilitätskennzahlen, K-Prüfgruppen und die
technischen Einzeltabellen sind im Normalbetrieb unter
**Weitere Details für Experten anzeigen** eingeklappt. Die ersten
Antworten stehen unmittelbar unter den Kennzahlen/Grafiken:
Cluster auswählen und **Warum gehören diese Fälle zusammen?**

Die Berechnung läuft in einem Hintergrundthread und schreibt keine
QEC-, FIN- oder Diagnose-Rohdaten auf GitHub. Die Tabelle
**Robustheitsprüfung · Methoden und Datenvarianten** zeigt:

- **Verfahren**: alle mit dem aktuellen Daten-/Parameterstand zulässigen
  Methoden auf genau derselben Vor-Tausch-Kohorte;
- **Daten/Parameter**: dieselbe gewählte Methode mit jeweils EINEM
  variierten Eingang: Quellen (QuickTest, AutoExport oder beide),
  Vor-Tausch-Zeitraum (Vollhistorie, 90 oder 365 Tage),
  optionaler DTC-Häufigkeitsfilter und Clusterparameter
  (Mindestgröße; bei HDBSCAN auch MinSamples).
  Das historische DTC-Jaccard-Verfahren kann nicht mit dem
  experimentellen TF-IDF-Häufigkeitsfilter kombiniert werden.

Neue Datenbasis- oder Parameterwerte machen **alle** zuvor berechneten
Ergebnisse ungültig. Ein erneuter Klick startet den gesamten Ablauf
wieder. Eine reine Auswahl anderer bereits berechneter Verfahren über
**Clusterverfahren** direkt neben `2D / 3D` aktualisiert
Clusterzahl, Grafik, Fallliste und verständliche Erklärung,
ohne neu zu rechnen oder die ursprüngliche Robustheitsreferenz
umzudeuten. Das separate **Zweites Verfahren** unter
den Expertendetails betrifft ausschließlich das optionale
Vergleichsdiagramm. 3D wird standardmäßig per linker
gedrückter Maustaste gedreht (horizontal) und geneigt
(vertikal). Ein Klick wählt weiterhin den Einzelfall.
Die ursprünglichen Schieberegler bleiben optional
unter **Weitere Details für Experten**.

## Kennzahlen und Grenzen

- **Beidseitig geeignet:** Schnittmenge der QEC-Fälle, die in BEIDEN
  Szenarien einen dokumentierten Vor-Tausch-Diagnosenachweis besitzen.
  Ein nicht vorhandener Fall ist kein negativer Ähnlichkeitsbeleg.
- **Paar-Jaccard:** gemeinsame zusammengeclusterte QEC-Paare geteilt
  durch die Vereinigung aller zusammengeclusterten Paare **nur innerhalb
  dieser beidseitig auswertbaren Kohorte**. Clusterbezeichnungen werden
  nicht miteinander verglichen.
- **Paarerhalt:** wie viele der ursprünglichen zusammengeclusterten Paare
  bleiben im anderen Lauf ebenfalls gemeinsam gruppiert?
- **Gruppentabelle:** Referenz-C-Nummer, ursprüngliche Mitglieder,
  in beiden Läufen geeignete Mitglieder, deren mögliche Vergleichspaare,
  erhaltene Paare und neue Verbindungen zu anderen Gruppen.
  Gruppennummern sind nur innerhalb des jeweiligen Rechenlaufs gültig.
- **Nicht bestimmbar** statt 100 % für Szenarien ohne Gruppen-Fallpaare.
  Die Tabelle darf daher nicht als Ranking "bestes Clustering" oder
  als Ursachenwahrscheinlichkeit interpretiert werden.
- Paarerhalt = 100 % kann trotz starker Zusammenlegung auftreten. Die
  zusätzliche Paar-Jaccard-Kennzahl und "Neue Verbindungen" zeigen
  solche überbreiten Gruppen.
- Der Vergleich unterschiedlicher Datenquellen und Zeitfenster ist eine
  **Sensitivitätsprüfung**, kein kausaler Beweis. Ergebnisse über
  verschieden kleine Stichproben können nur bedingt verglichen werden.
- Verschiedene Verfahren sind **nicht statistisch unabhängig**:
  Sie nutzen teils exakt denselben ursprünglichen Merkmalsraum.

## Technische Umsetzung

- `src/ntf_insight/analysis/cluster_stability.py`: read-only Paarvergleich
  und vordefinierte Ein-Faktor-Szenarien, lokal beschränkter Bericht
  ohne Quellkennungen.
- `src/ntf_insight/app/widgets/cluster_workspace.py`: kein neuer Tab,
  genau ein Hauptbutton, einklappbare Expertenparameter, Vergleichs-
  und Robustheitstabellen sowie Hintergrundberechnung in der
  bestehenden deutschsprachigen Oberfläche.
- Tests ausschließlich mit synthetischen Pumpenfällen in Linux- und
  Windows-CI. Die lokale reale DuckDB wird niemals in GitHub Actions
  eingelesen; keine Telemetrie, API-Aufrufe oder automatischen Berichte.

## Weiterführende Prüfung

Zuerst die fünf konservativen K-Gruppen und Leaf-Gruppen gegen die
Stabilitätstabelle prüfen. Erst später mit echten Befundungsberichten,
unabhängigen technischen Nachweisen, Zeitbezügen und vollständigen
Diagnosesitzungen eine Fehlerursache oder mögliche
Lieferantenverantwortung untersuchen. Die jetzigen Kennzahlen sind
für die Priorisierung von Fachprüfungen geeignet, nicht zum Beweis
einer Pumpenursache.

## Offline-Test unter Windows (nach einmaligem Code-Update)

Auf dem zugelassenen Rechner mit bereits eingerichteter `.venv` die
freigegebene Programmversion **zunächst bei bestehender GitHub-Verbindung**
übernehmen:

```powershell
cd C:\\Pfad\\zu\\ntf-insight
git switch main
git pull --ff-only
```

Nach einem erfolgreichen Merge ist der neue Button in `main` enthalten.
**Zum Vorabtesten des offenen PR** stattdessen diesen Branch laden:

```powershell
git fetch origin
git switch feature/cluster-stabilitaet-verfahren-und-sensitivitaet
```

Die Anwendung läuft danach – mit vorher installierten Paketen – **ohne
Internetverbindung**:

```powershell
.\\.venv\\Scripts\\python.exe -m ntf_insight
```

Zur Sichtprüfung: **Fälle / FIN → Clusteranalyse**, dann
**Clusteranalyse starten**. Nach Abschluss müssen
Methodenvergleich, Robustheitsprüfung und konservative
K-Prüfgruppen erscheinen; der CSV-Export bleibt eine separate lokale
Aktion. Erste Anzeige = HDBSCAN Leaf; andere Gruppierungen lassen sich
per Doppelklick in der Methodenvergleichstabelle anzeigen. Die
Stabilitätsreferenz steht ausdrücklich über der Robustheitstabelle.
**Eingänge ändern** invalidiert alte Ergebnisse. Die Variantenberechnung
überspringt teure, nicht benötigte Plot-Projektionen.

Optional lassen sich ausschließlich die synthetischen Tests ausführen:

```powershell
.\\.venv\\Scripts\\python.exe -m pytest -q tests/test_cluster_stability.py tests/test_cluster_workspace_engine.py tests/test_cluster_workspace_gui.py
```

Keine Originaldaten, FINs, DTC-IDs oder Screenshots mit vertraulichen
Informationen in ein öffentliches Issue hochladen. Für einen
Rückmelde-Check reichen **nur Anzahlen und der Status**
(OK / Fehlermeldung ohne Originalkennung).
