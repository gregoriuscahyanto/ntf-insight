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

Unter **Fälle / FIN → Clusteranalyse** auf **Stabilität prüfen** klicken.
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

Die Robustheitsausgabe wird nach jeder Neueinstellung ungültig und
muss neu berechnet werden. Methodenvergleich/Clusterberechnung bleiben
eigenständig und lassen die Robustheit unberührt.

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
  sondern Knopf, Tabelle und Hintergrundberechnung in der bestehenden
  deutschsprachigen Oberfläche.
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
