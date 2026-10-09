# Gemeinsamer Arbeitsbereich „Fälle / FIN“ und mathematische 2D-Erklärung

Die Desktop-App hat **nur einen** Arbeitsbereich für den untersuchten Schadteilfall,
seine FIN und die QuickTests. Unter **Fälle / FIN** liegen drei Register:

1. **2D-Streudiagramm** – explorative Lage der echten Fälle, numerische
   Erklärungen und eine Vergleichstabelle.
2. **FIN / Fallanalyse** – Ereignisse, Vorher/Nachher-DTCs, Reparaturen,
   Tauschanker, QEC-SSL-Endbefund und technische Evidenz.
3. **QuickTests nach FIN** – unabhängig von einem QEC-Fall archivierte
   PDF-Reports einschließlich aller ECUs, Snapshot-Werte und Quellseiten.

Der bisherige separate Menüeintrag für Cluster, DTC-Netzwerk und Paarvergleich
wurde entfernt. **Die bestehenden Complete-Link-Cluster werden weiterhin
unverändert berechnet** und liefern die Farben im Scatter; es gibt keinen
neuen Clusteralgorithmus. Die ältere Panel-Implementierung bleibt intern
für Tests vorhanden, ist aber nicht mehr über die Navigation erreichbar.

## Verknüpfung

Die obere Auswahl **„Aktive FIN / Fall“** gilt für den Arbeitsbereich.
Klick auf einen Punkt oder einen Fall in der Koordinatentabelle wählt diesen
echten Fall aus und hält ihn für die Fallanalyse und FIN-QuickTests bereit.
Ein Wechsel der FIN im QuickTest-Reiter synchronisiert die Fallauswahl,
sofern für diese FIN ein Fall bzw. eine FIN-only-Vorschau vorhanden ist.

**Einzelne QuickTests sind niemals automatisch einzelne Schadteilfälle.**
Mehrere Reports derselben FIN können daher keine künstlich höhere Fallzahl
im Streudiagramm erzeugen. Reine QuickTest-FINs ohne zugeordneten QEC-Fall
sind in der Fallanalyse als Vorschau und im QuickTest-Reiter sichtbar, aber
**kein Scatter-Punkt**. Wurde für eine Fall-FIN noch kein PDF importiert,
zeigt der QuickTest-Reiter explizit **0 Reports für diese FIN**, statt
den Bericht einer vorherigen FIN stehen zu lassen.

## Was genau auf X und Y steht

Die *Fall-Signatur* entspricht der des bestehenden
Jaccard-Vergleichs und enthält ausschließlich bekannte Merkmale
vor dem untersuchten Bauteiltausch. Die sechs Gewichte sind:

| Merkmal | Vorläufiges Gewicht |
| --- | ---: |
| ECU:DTC-Paare | 0,50 |
| DTC-Codes ohne ECU | 0,20 |
| Steuergeräte | 0,10 |
| Beanstandungstokens | 0,13 |
| ECU-Softwarestände | 0,04 |
| Baureihe / Fahrzeugvariante | 0,03 |

Aus diesen Mengen wird eine **Sparse-Matrix** erstellt. Für jedes
vorkommende Merkmal (Token) aus Gruppe \`g\` gilt:

\`\`\`text
X[Fall, Token] = sqrt(Gewicht_g / Anzahl_Tokens_des_Falls_in_g)
                oder 0, wenn das Merkmal im Fall nicht vorkommt
\`\`\`

Das trennt die Bedeutung der sechs Gruppen von der Menge der Felder im
jeweiligen Export. Doppelt hochgeladene ECU:DTC-Zeilen erhöhen die Zahl
der eindeutigen Tokens nicht. Die Featurematrix wird pro Bauteilfamilie
gebildet, damit unterschiedliche Komponenten nicht vermischt werden.

**TruncatedSVD** wird deterministisch (\`random_state=0\`) auf diese
Matrix angewandt. Die ersten zwei Projektionskomponenten geben
X/Y-Koordinaten, die danach je Achse um ihren Stichprobenmittelwert
verschoben werden. Wenn nicht genug Fälle/Spalten existieren, werden
nur die mathematisch möglichen Achsen ausgewiesen. Fälle ohne
ausreichende Diagnose-/Beanstandungsbasis bekommen \`k. A.\` statt
erfundener Projektionskoordinaten.

Die Oberfläche enthält **echte Zahlen** zum ausgewählten Datenbestand:

- Anzahl Fälle, ausgeschlossener Fälle und gewichteter Matrixspalten;
- erklärte Matrixvarianz (pro SVD-Achse), soweit mathematisch berechenbar;
- Merkmalsgruppen-Gewichte und Anzahl Tokens des ausgewählten Falls;
- wichtige positive/negative **SVD-Ladungen** pro Achse;
- X/Y-Wert und diagnostische Datenabdeckung **für jeden echten Fall**;
- ausgewählte Paarwerte nach dem bestehenden gewichteten Jaccard.

**Vorsicht:** erklärte SVD-Varianz misst die Varianz der gewichteten
Merkmalsmatrix, nicht die Bewahrung von Jaccard-Abständen. Die Ladung
eines Tokens erklärt einen Teil der Achsenrichtung, **keine
Fehlerursache**. Zwei Punkte, die im Bild nahe sind, müssen deshalb
nicht denselben hohen diagnostischen Vergleichswert haben.
Bei identischen Plotkoordinaten werden die Punktsymbole ausschließlich
zur besseren Bedienung minimal versetzt.

## Exakte Paarvergleichszahlen

Die Auswahl eines Vergleichsfalls in der Tabelle zeigt für jede
Merkmalsgruppe \`g\` die folgenden Werte:

- Anzahl Tokens im Fokusfall und Vergleichsfall,
- Anzahl gemeinsamer Tokens und Tokens in der Vereinigung,
- \`J_g = |A_g ∩ B_g| / |A_g ∪ B_g|\` bei beidseitig vorhandenen Tokens,
- Gruppenanteil \`(Gewicht_g × J_g) / Summe_der_verfügbaren_Gewichte\`.

Die **diagnostische Paarähnlichkeit** wird *unverändert* berechnet als

\`\`\`text
score = Σ (Gewicht_g × J_g) / Σ (Gewicht_g der beidseitig vorhandenen Gruppen)
\`\`\`

Die *Merkmalsabdeckung* ist der zweite Nenner; der UI-Vergleich zeigt
zusätzlich \`score × coverage\` als reine **Sortierhilfe**. Bei
unvergleichbaren Fällen erscheint \`k. A.\`, niemals künstlich 0 %.

Für die automatische Clusterbildung gelten weiterhin alle Bedingungen:
gemeinsame ECU:DTC-Kombination, Merkmalsabdeckung mindestens 0,50,
untersuchte Tauschanker beider Fälle und ein Paarwert mindestens so
hoch wie die im Scatter einstellbare Schwelle (Standard 0,65).
Die Complete-Link-Regel fordert **alle Paarwerte innerhalb einer
Gruppe**; eine bestandene Prüfung eines einzelnen Paares garantiert
daher keine gemeinsame Cluster-ID.

Die Tabelle stellt sowohl den **echten Jaccard-Wert** als auch die
**euklidische Distanz in der 2D-Projektion** getrennt dar – letztere
ist ausschließlich eine anschauliche Hilfszahl.

## Warum QEC SSL-Endbefunde nicht die Punkte verschieben

\`SSL-Endbefund Benennung\`, Reparaturaktionen, Ersatzteil-/Lieferantendaten
und Ergebnisse der Vorher/Nachher-Analyse sind **nachgelagerte Daten**.
Sie dürfen weder in die Merkmalsmatrix noch in den Paarähnlichkeitswert.
Ihre Originaltexte erscheinen separat in der Fallanalyse, im
Streudiagramm-Fokus und in der Fallvergleichstabelle. Damit kann man
nach der Gruppenbildung untersuchen, ob ähnliche Diagnosen
unterschiedliche Befunde liefern.

## QuickTest und AutoExport: doppelte DTC-Quelle

Die zeitlich belegten DTC-Ereignisse beider Quellen werden lokal erhalten.
Ein konservativer Abgleich führt eine AutoExport- und eine
QuickTest-Beobachtung nur zusammen, wenn **FIN, ECU:DTC, Datum und
Kilometerstand übereinstimmen** (bei verfügbarer genauer Uhrzeit
muss auch diese übereinstimmen). Ohne genügende Evidenz bleiben die
Beobachtungen getrennt. Unabhängig davon verwenden die
Cluster-/SVD-Signaturen eindeutige ECU:DTC-Mengen.

## Validierungsstand

Die Softwaretests verwenden synthetische Fälle. Die
SVD-Darstellung, vorläufigen Merkmalsgewichte und Clustergrenzen
müssen noch an repräsentativen, fachlich geprüften realen
AutoExport-, QuickTest- und QEC-Fällen validiert werden.
