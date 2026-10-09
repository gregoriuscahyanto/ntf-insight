# Fallähnlichkeit, Fall-Cluster und Abhilfekandidaten

## Ziel

Für einen neuen oder ungeklärten NTF-Fall sollen **diagnostisch ähnliche historische Fälle** gefunden werden. Die dort dokumentierten Maßnahmen und ihre beobachteten Ergebnisse helfen einer Fachperson bei der Ursachenanalyse. Ein ähnlicher Fall ist **kein Beweis**, dass dieselbe Maßnahme wieder erfolgreich sein wird.

Es gibt zwei getrennte Fragestellungen:

1. **Diagnostisch ähnlich?** Merkmale, die vor dem untersuchten Austausch beziehungsweise vor dem bekannten Eingriff vorlagen.
2. **Was wurde versucht, was wurde danach beobachtet?** Werkstattaktionen, Teiletausch und Softwareänderungen sowie Kurztests, die nach der *letzten* dokumentierten Maßnahme stattfinden.

Diese Trennung verhindert **Outcome Leakage**: Rekurrenz, Lieferantenbefund und manuell gewählte Root-Cause-Kategorie dürfen nicht in den Diagnoseähnlichkeits-Score einfließen.

## Implementierter MVP (ohne ML-Abhängigkeit)

Die App bietet unter **Cluster & Fälle → Fall-Cluster**:

- Gruppen ähnlicher FIN/Fall-Kombinationen mit eindeutiger Cluster-ID
- eine einstellbare Mindestähnlichkeit (standardmäßig **0,65**)
- eine **Ähnlichkeitsmatrix (Heatmap)** mit Hover-Begründung
- Auswahl eines Falls und Rangliste der nächstähnlichen Fälle; die Detailbegründung
  folgt auch der Tastaturnavigation und die Öffnen-Aktion wird bei ungültiger Auswahl deaktiviert
- **„Ähnliche Fälle finden“** direkt aus **Fälle / FIN → FIN / Fallanalyse**,
  wobei der aktuelle echte Fall automatisch als Vergleichsfokus gewählt wird
- **Cluster-Steckbrief** mit Fallanzahl, unterschiedlichen FINs,
  repräsentativem realem Fall, gemeinsamem ECU:DTC-Muster,
  **schwächster Paarähnlichkeit**, Merkmalsabdeckung und
  Zahl dokumentierter Vorher-/Nachtests
- ein **Doppelklick oder „Vergleichsfall öffnen“** führt aus dem Vergleich
  direkt in die vollständige FIN-/Fallanalyse zurück
- für jeden ausgewählten Vergleichsfall sowohl **gemeinsame als auch
  abweichende DTCs**, gemeinsame Beanstandungen/Softwarestände,
  Merkmalsabdeckung, dokumentierte Maßnahmen und den beobachteten Verlauf
  nach der letzten Maßnahme
- DTC-Koauftretensnetzwerk weiterhin unter **DTC-Netzwerk**

Die Matrix und die Vergleichsbegründung zeigen bei nicht vergleichbaren Paaren **„k. A.“**, nicht 0 % oder 100 %. Falls mehr als 24 Fälle existieren, wird die Matrix auf den Fokusfall und höchstens 23 weitere Fälle begrenzt; die Clusterberechnung berücksichtigt dennoch alle Fälle.

### Diagnostische Signatur

Pro Fall werden aus der bekannten Vorgeschichte bis zum untersuchten Bauteiltausch folgende Signale extrahiert:

| Merkmalsgruppe | Gewicht |
|---|---:|
| ECU + DTC-Code gemeinsam | 0,50 |
| DTC-Code (ECU-unabhängig) | 0,20 |
| beteiligte ECUs | 0,10 |
| Begriffe aus der **Beanstandung**, nicht der Reparaturmaßnahme | 0,13 |
| beobachtete ECU-Softwarestände | 0,04 |
| Fahrzeugbaureihe/-variante | 0,03 |

Die Gewichte sind **transparente, noch nicht kalibrierte Annahmen**, keine aus Felddaten trainierten Wahrscheinlichkeiten.

DTCs, SW-Stände und Beanstandungstexte werden bei vorhandenem Austauschanker ausschließlich aus Ereignissen **vor** diesem Anker entnommen. Wenn nur ein Datum bekannt ist, werden unklare gleichentägige Ereignisse nicht automatisch als „vorher“ betrachtet. Bei Fällen ohne Austauschanker werden alle verfügbaren Diagnoseereignisse provisorisch verwendet; die Vergleichsbegründung weist darauf hin.

Lieferant, Seriennummer, Charge, Reparaturmaßnahme, Lieferantenbefund, manuelle Ursachenbewertung und Post-Tausch-Rekurrenz sind **keine Merkmale des Scores**.

### Vergleich / Ähnlichkeit

Für jedes beidseitig verfügbare Merkmalsfeld wird der **Jaccard-Koeffizient** gebildet. Die verfügbaren Felder werden gewichtet gemittelt. Die getrennte **Merkmalsabdeckung** gibt an, wie viel Gewicht überhaupt beidseitig Daten hatte.

Eine niedrige Merkmalsabdeckung bedeutet, dass ein rechnerisch hoher Ähnlichkeitswert **weniger aussagekräftig** ist. Bei fehlender diagnostischer Basis oder unterschiedlichen Bauteilfamilien wird keine automatische Ähnlichkeit vergeben.

Die Rangliste ähnlicher Fälle sortiert nach Score × Merkmalsabdeckung, damit ein einzelner identischer Freitext nicht Fälle mit übereinstimmenden DTCs verdrängt.

### Clusterbildung

**Complete-Link-Hierarchie**, deterministisch und ohne vorgegebene Clusteranzahl:

- Alle Paarvergleiche innerhalb eines Clusters müssen die Mindestähnlichkeit erfüllen.
- Für den MVP ist mindestens ein gemeinsamer vollständiger ECU:DTC-Code und ausreichende Merkmalsabdeckung nötig.
- **Ohne untersuchten Tauschanker keine automatische Gruppenzugehörigkeit**:
  diese Fälle dürfen weiterhin zur vorsichtigen Fallähnlichkeitssuche
  verwendet werden, aber es ist unklar, welche Beobachtungen wirklich
  vor dem Eingriff lagen.
- Fälle ohne robuste Gruppenzugehörigkeit bleiben als **Einzelfall / unzugeordnet** sichtbar.
- Keine „Clusterung“ allein aufgrund gleicher Baureihe, ECU oder fehlender DTCs.

Hierarchische Cluster mit dieser konservativen Paarbedingung sind für erste manuell geprüfte Stichproben nachvollziehbarer als ein unkalibriertes ML-Modell.

### Cluster-Steckbrief und Auswahl

Der **repräsentative Fall** ist einer der tatsächlich vorhandenen
Clusterfälle, dessen gewichtete durchschnittliche Übereinstimmung
(`Ähnlichkeit × Merkmalsabdeckung`) mit den anderen Mitgliedern
am höchsten ausfällt. Er ist **kein synthetischer Fall** und
**keine empfohlene Reparatur**.

Ein streng konservativer Cluster zeigt zusätzlich die
**schwächste diagnostische Paarähnlichkeit** zwischen
seinen Mitgliedern. So lassen sich auch größere Gruppen
auf fragwürdige Zuordnungen prüfen.

Mehrere Fälle können zur **gleichen FIN** gehören: Der Steckbrief
zeigt daher neben der Fallzahl ausdrücklich die Anzahl
unterschiedlicher FINs. Im Paarvergleich erscheint bei
gleicher FIN ein Hinweis auf möglicherweise nicht unabhängige
Beobachtungen.

### Kein QEC-/NTF-Fall vorhanden

Mehrere QuickTests derselben FIN sind **keine separaten Schadteilfälle**.
Eine FIN mit 18 QuickTests darf nicht als 18 ähnliche NTF-Fälle
ausgegeben werden. Die Fallcluster berücksichtigen nur tatsächlich
angelegte bzw. importierte Fälle. Ohne mindestens zwei Fälle
erscheint ein Hinweis, dass zunächst echte QEC-/NTF-Fälle oder
fachlich erfasste Fälle benötigt werden.

Der **Paarvergleich (Basis)** zeigt **„k. A.“** bei
nicht vergleichbaren Fällen statt einer irreführenden
0-%-Ähnlichkeit. Die Begründung bleibt sichtbar.

## Beobachtete Wirkung

Die App zeigt getrennt dokumentierte Maßnahmen (Bauteiltausch, Werkstattaktion, Softwareupdate) und den Verlauf in Kurztests **nach der letzten dokumentierten Maßnahme**:

- derselbe Ausgangs-DTC erneut beobachtet
- Ausgangs-DTC nicht erneut beobachtet
- Ausgangs-DTC weg, aber neuer DTC vorhanden
- **kein verwertbarer Nachtest / Ausgangsbefund unvollständig**

Auch „nicht erneut beobachtet“ beweist keine dauerhaft gelöste Ursache oder Lieferantenverantwortung. Die tatsächliche Lösung muss bei Bedarf durch längere Beobachtung oder Expertenreview bestätigt werden.

## Warum nicht direkt PCA?

PCA ist eine **Dimensionsreduktion**, kein Clusteralgorithmus. Für überwiegend binäre/sparse DTC-Matrizen und gemischte Text-/Ereignisattribute ist gewöhnliche PCA mit Standardisierung ohne aussagekräftige Features nicht die erste Wahl.

Empfohlener Ausbau:

1. **20–50 manuell validierte Fälle:** Merkmale, Ähnlichkeitsrangfolge und Cluster fachlich prüfen.
2. **Sobald genügend Fälle vorliegen:** HDBSCAN (auf sorgfältig kalibrierten Features/Distanzen) zum Finden dichter Gruppen und Ausreißer, ohne feste Clusteranzahl.
3. **2D-Ansicht:** UMAP zur explorativen Darstellung; alternativ TruncatedSVD für sparse DTC-/Textvektoren. 2D-Abstände sind nicht automatisch kausale Beziehungen.
4. **Reparaturkandidaten:** Vergleichsfälle mit tatsächlich bestätigtem und zeitlich richtig zugeordnetem Lösungsergebnis priorisieren; Maßnahmen weiter durch Fachpersonen bewerten.

## Validierung: Werden ähnlichere Fälle tatsächlich ähnlich gelöst?

Das ist eine **zu überprüfende Hypothese**, kein gesicherter Schluss. Mit genügend Fällen und verifizierten Abhilfen:

- Einen historischen Fall als ungelösten Ziel-Fall behandeln (nur Vorher-Daten sichtbar machen).
- Die ähnlichsten historischen Fälle aus dem zeitlich früheren Bestand bestimmen.
- Prüfen, ob unter den Top-3/Top-5 die **von Experten bestätigte wirksame Abhilfe** vorkommt.
- Gegen einfachere Baselines wie reine DTC-Jaccard-Ähnlichkeit vergleichen.
- Datensplits zeitlich und nach FIN gruppieren, damit mehrere Fälle derselben FIN nicht die Validierung künstlich verbessern.
- Parameter, Gewichte, Schwellen, Fälle ohne ausreichende Daten und Fehlempfehlungen protokollieren.

Ohne bestätigte Reparaturerfolge bleibt NTF Insight ein transparentes **Ähnlichkeits- und Evidenzwerkzeug**, kein automatisches „Diese Reparatur ist richtig“-System.

## Dateien

- `src/ntf_insight/analysis/case_clustering.py`: Merkmalsextraktion, Ähnlichkeit, Complete-Link-Cluster, Maßnahmen-/Nachtestzusammenfassung
- `src/ntf_insight/app/widgets/case_cluster_panel.py`: Desktop-Fallcluster, Vergleichstabelle, Heatmap
- `src/ntf_insight/app/models/case_similarity_matrix_model.py`: kontrastfähige Qt-Matrix
- `tests/test_case_clustering.py`, `tests/test_case_cluster_gui.py`: Regressionstests
