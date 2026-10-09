# HDBSCAN – experimentelle ML-Clusterung in NTF Insight

Öffne **Fälle / FIN → ML-Cluster (HDBSCAN)**. Die App verwendet
[sklearn.cluster.HDBSCAN](https://scikit-learn.org/stable/modules/generated/sklearn.cluster.HDBSCAN.html)
als **echtes unüberwachtes ML-Verfahren**, nicht nur einen neuen Namen
für Complete-Link. Die bisherige strenge Methode bleibt in separaten
Reitern zum Vergleich erhalten. HDBSCAN bestimmt Anzahl und Größe
der Dichtegruppen aus den Daten; eine feste Anzahl wird nicht gefordert.

## Eingangsdaten und Vermeidung von Ergebnis-Leakage

Alle Merkmale beziehen sich ausschließlich auf Informationen, die vor
dem untersuchten Pumpentausch dokumentiert waren:

| Merkmal | relatives Gewicht |
| --- | ---: |
| exakte ECU:DTC-Kombination | 70 % |
| DTC-Code unabhängig von ECU | 8 % |
| beteiligte ECU | 3 % |
| Wörter der ursprünglichen Kundenbeanstandung | 14 % |
| ECU-Softwarestand | 3 % |
| Baureihe/Fahrzeugvariante | 2 % |

Dies sind **hypothetische Featuregewichte** und ausdrücklich noch
keine aus bestätigten Fehlerursachen erlernten Gewichte.

Merkmale liegen pro echtem QEC-Fall als Mengen vor: Derselbe ECU:DTC
aus QuickTest und AutoExport zählt daher je Fall nur einmal.
TIPS-Vorgänge und historische FINs ohne QEC-Referenz werden
nicht zu künstlichen Schadteilfällen. QEC-Fälle ohne Tauschanker
oder Vorher-ECU:DTC bleiben separat mit Ausschlussgrund sichtbar.

**SSL-Endbefund, Lieferantenbefund, Reparaturmaßnahmen und
Nach-Tausch-Ergebnisse werden niemals für die Eingangsmerkmale
oder Repräsentantenauswahl genutzt.** Diese Ergebnisse können
nach der Gruppierung zur fachlichen Validierung betrachtet werden.

## Der ML-Rechenweg

1. Für jeden relevanten Fall werden binäre Merkmalsmengen erstellt.
2. Jedes Merkmal erhält IDF = 1 + ln((N+1)/(df+1)). Die Häufigkeit
   bezieht sich auf die im aktuellen Modell tatsächlich auswertbaren
   QEC-Fälle derselben Bauteilfamilie.
3. Jede Merkmalsgruppe wird L2-normalisiert und mit Quadratwurzel
   ihres Gewichts skaliert. Die verbundenen Fallvektoren werden nochmals
   L2-normalisiert.
4. Die **euklidische Distanzmatrix** dieser Fallvektoren wird direkt
   an sklearn.HDBSCAN mit metric=precomputed übergeben. HDBSCAN
   arbeitet NICHT auf zweidimensionalen Pixeln.
5. Eine klassische MDS projiziert dieselben hochdimensionalen
   Abstände zur **nur näherungsweisen 2D-Anzeige**.
6. Pro gefundener Gruppe wird ein tatsächlich vorhandener Fall
   ausgewählt, dessen Summe der Distanzen zu den Gruppenmitgliedern
   minimal ist (Medoid). Der Medoid ist kein fiktiver Durchschnitt.

Das Modell benutzt für die Beanstandung bisher bereinigte Wort-Tokens,
**keine semantischen neuronalen Embeddings**. Diese könnten bei
ausreichender fachlicher Textqualität später ergänzt werden.

## Einstellungen

- **Min. Clustergröße** (Standard 3): kleinste dichte Fallgruppe.
- **MinSamples** (Standard 2, inklusive Punkt selbst):
  erforderliche Nachbarschaftsdichte. Größer kann mehr Ausreißer ergeben.
- **HDBSCAN-Gruppenauswahl**: `Leaf` (neuer GUI-Standard)
  bevorzugt die kleineren Blattgruppen der HDBSCAN-Dichtehierarchie;
  `EOM` (*Excess of Mass*) wählt persistente Hauptgruppen und
  kann bei höherer Mindestclustergröße breite, heterogene Gruppen bilden.
  Beide Verfahren verwenden dieselbe hochdimensionale Eingangsmatrix.
- **DTC-Quellen**: QuickTest, AutoExport oder beide.
- **Vor-Tausch-Zeitraum**: vollständige bisherige Historie oder
  letzte 30, 90, 180, 365 Tage.

Der Vergleich von Einstellungen ist eine Sensitivitätsanalyse,
keine nachträgliche Optimierung auf eine gewünschte Clusteranzahl.

**EOM / Leaf vergleichen** berechnet beide Auswahlverfahren auf
*exakt denselben* aktuellen Fällen, mit denselben Quellen, demselben
Zeitfenster, `min_cluster_size` und `min_samples`. Die GUI zeigt
Clusterzahl, gruppierte Fälle, Ausreißer, größte Gruppe, Gruppen
mit gemeinsamem ECU:DTC, Gruppen ohne schwache Fallpaare,
Anteil schwacher Fallpaare und Median der Paarmediane. Die
**Paar-Zuordnungs-Übereinstimmung** ist der Jaccard-Index
der echten positiven Gruppen-Fallpaare beider Ergebnisse.
Dabei werden willkürliche Labels H1/H2 *nicht* gleichgesetzt.
Kein solcher Vergleich bestätigt gleiche Fehlerursachen.

Mit **Qualitätsbericht ohne FIN** kann man die zwei *aggregierten*
Vergleichszeilen lokal als CSV speichern: keine QEC-ID, FIN, DTC-Werte,
Kundenbeanstandungen oder SSL-Rohtexte. Vor einer externen Weitergabe
ist trotzdem eine organisationsinterne Freigabe sinnvoll.

## Interpretation und Qualitätsprüfung

Der ML-Reiter zeigt Gruppengrößen, unterschiedliche FINs,
Cosinus-Ähnlichkeit zum repräsentativen QEC-Fall und das schwächste
Paar innerhalb jeder Gruppe. Für unit-normalisierte Fallvektoren:

    Cosinus(A,B) = 1 - Euclid(A,B)^2 / 2

Außerdem erscheinen gemeinsame exakte ECU:DTC-Kombinationen,
häufige DTCs einschließlich ihrer Fallzahl, HDBSCAN-Stabilität,
QEC-SSL-Befunde **ausschließlich post hoc** und Warnungen.

Neben dem **schwächsten** Fallpaar werden der Median aller
unterschiedlichen internen Fallpaare, das **untere 10-%-Quantil**,
die Zahl der Paare unter der vorläufigen 45-%-Cosinus-Schwelle
sowie eine vorsichtige Bewertung angezeigt. Identitätsvergleiche
mit 100 % zählen nicht in diese Statistik. Numerische
Rundungsreste am Nullpunkt werden auf 0 geklemmt; ein künstliches
`-0,0 %` soll nicht erscheinen.

Eine Gruppe ohne durchgängige ECU:DTC-Kernmenge oder mit einem
unteren 10-%-Quantil unter 45 % wird als **heterogen**
gekennzeichnet. Auch eine diagnostisch weniger heterogene Gruppe
bleibt ein *unbestätigter Prüfkandidat*, kein Ursache-/Reparaturlabel.
Die 45-%-Grenze ist vorläufig und nicht anhand überprüfter
gleicher/ungleicher Defekte kalibriert.

HDBSCAN-Zugehörigkeitsstärke ist eine Dichte-/Stabilitätskennzahl,
**keine Wahrscheinlichkeit derselben Fehlerursache**.

**Wichtig:** Eine Dichtegruppe kann diagnostisch heterogene Paare
enthalten. Falls es keine gemeinsame ECU:DTC-Kernmenge gibt,
das schwächste interne Paar unter 45 % liegt oder SSL-Endbefunde
deutlich unterschiedlich dokumentiert sind, warnt die App.
Solche Fälle dürfen nicht einfach dieselbe Reparatur erhalten.

Einzelne Fälle ohne stabile HDBSCAN-Gruppe bleiben als
**Rauschen** sichtbar, Fälle ohne Eingangsdaten in einer gesonderten
Tabelle. Ein CSV-Export ermöglicht eine lokale Dokumentation.
Um irreführende Großgruppen-Sterne zu vermeiden, zeichnet das
2D-Diagramm nur für die *ausgewählte* Gruppe und höchstens 12
Mitglieder mit mindestens 45 % Ähnlichkeit zum Repräsentanten
gestrichelte Verbindungslinien. Die übrigen Punkte bleiben im
Plot sichtbar und können angeklickt werden.
Es werden keine echten QEC-/FIN-Daten nach GitHub übertragen.

## Nächster fachlicher Schritt

Für die Frage „Kann ein analysierter Fall das Ergebnis anderer Fälle
repräsentieren?“ müssen bekannte Fälle mit **identischen und
unterschiedlichen geprüften technischen Fehlermechanismen**
bezeichnet und anschließend zur externen Cluster-Validierung benutzt
werden. Allein mehr HDBSCAN-Gruppen oder eine höhere
HDBSCAN-Mitgliedschaftsstärke beweisen noch keine ursächliche Gleichheit.
