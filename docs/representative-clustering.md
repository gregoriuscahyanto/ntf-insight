# Homogene Diagnosegruppen mit realen QEC-Repräsentanten

**Ziel:** Fälle mit möglichst ähnlichem diagnostischem Bild in einer
fachlich überprüfbaren Kerngruppe zusammenfassen. **Keine feste
Clusterzahl und keine Begrenzung auf 12/24 Fälle.** Für jede gefundene
Gruppe wird erst **nach der Gruppenbildung** ein tatsächlich vorhandener,
möglichst zentraler QEC-Fall als repräsentativer Untersuchungsfall
ausgewählt.

Zu finden unter **Fälle / FIN → Repräsentative Cluster**. Die ältere
TruncatedSVD-/Jaccard-/Complete-Link-Analyse und ihr eigenes
Streudiagramm bleiben getrennt erhalten.

## Dateneinheiten bleiben getrennt

- QEC-Fall: untersuchter Schadteilfall mit QEC-Referenz und Tauschanker;
- FIN: Fahrzeug, das mehrere voneinander verschiedene Fehlerfälle haben kann;
- TIPS-Nummer: Werkstattvorgang, ohne automatische Beweiskraft eines
  QEC-Kühlmittelpumpenschadens;
- AutoExport-/QuickTest-DTC: Fehlerspeicherbeobachtung, nicht automatisch
  eigenständiges Schadenereignis.

Alle Originalquellen bleiben gespeichert. Mehrfache Meldungen desselben
ECU:DTC werden **pro QEC-Fall nur einmal** in die Diagnosesignatur
übernommen. Ein TIPS-Fall wird einem QEC-Fall nur nach konservativer,
eindeutiger FIN-/Zeitzuordnung beziehungsweise einer **bewussten
manuellen Freigabe** verbunden. Die TIPS-Erstellungszeit ist nicht
gleichzusetzen mit dem Zeitpunkt einer nachfolgenden Reparatur.

## Welche Informationen gehören in die Diagnose?

Die Signatur eines QEC-Falls enthält ausschließlich Beobachtungen,
die **vor** dem untersuchten Tausch dokumentiert wurden:

- eindeutige ECU:DTC-Kombinationen,
- ursprüngliche Kundenbeanstandung vor dem Tausch,
- bis zum Tausch dokumentierter ECU-Softwarestand,
- Fahrzeug-/Baureihenkontext und definierte Bauteilfamilie.

Der Benutzer kann QuickTest/AutoExport/bzw. beide und einen
Vor-Tausch-Zeitraum auswählen. Ein belegter Tauschanker und mindestens
ein DTC vor dem Tausch sind Voraussetzungen für automatische Gruppen.

**Nicht erlaubt als Clustering-Merkmal:** SSL-Endbefund,
Lieferanten-Ergebnis, durchgeführte Reparatur, Erfolg nach Reparatur.
Diese Daten sind für *nachgelagerte Validierung* vorgesehen, nicht
zum Voraussagen einer bereits bekannten Ursache.

## Unterschiedliche DTC-Häufigkeiten korrekt behandeln

Eine DTC-Häufigkeit wird **nur unter den QEC-Fällen mit dokumentiertem
Tauschanker und mindestens einer Vorher-ECU:DTC-Beobachtung** innerhalb
der betrachteten Datenbasis ermittelt. Fälle ohne Vorher-DTC dürfen
den Anteil eines Fehlers nicht künstlich kleiner machen.

Für einen DTC, der bei \`df\` von \`N\` Fällen dieser diagnostisch
beobachtbaren Basis vorkommt, gilt:

\`\`\`text
df_Anteil = df / N
IDF(DTC) = 1 + ln((N + 1) / (df + 1))
\`\`\`

Bei 72 Vorkommen unter 170 Fällen mit Vorher-DTC ergibt das 42,4 %,
nicht 72/336 = 21,4 %. Der Standardgrenzwert liegt bei 35 %;
die Anzeige kennzeichnet ihn explizit als Anteil der **beobachtbaren**
QEC-Fälle. Die Werte sind keine extern validierten Ursachen-Gewichte.

Ein Fallpaar ist als Kandidat nur zulässig, wenn
- dieselbe Bauteilfamilie untersucht wird,
- beide Fälle einen dokumentierten Tauschanker und Vorher-DTC haben,
- mindestens eine exakt gemeinsame ECU:DTC-Kombination vorliegt,
- mindestens eine gemeinsame ECU:DTC-Kombination ausreichend selten
  (Standard: höchstens 35 % der beobachtbaren QEC-Fälle) ist,
  **oder** mindestens zwei exakte ECU:DTC-Kombinationen gemeinsam sind,
- bekannte Fahrzeug-Baureihen nicht widersprüchlich sind.

Die Alternative mit zwei gemeinsamen Codes ist ebenfalls eine
heuristische Screening-Regel: Zwei häufige Netzwerk-DTCs beweisen
keine gemeinsame Fehlerursache. Die späteren Qualitätswarnungen machen
dies sichtbar. Für die endgültige fachliche Freigabe sollen CDD,
Bauteilrelevanz und geprüfte Ursachen-Fallpaare einfließen.

## Index zwischen zwei QEC-Fällen

Für exakte ECU:DTC-Kombinationen berechnen wir

\`\`\`text
J = IDF-gewichtete Schnittmenge / IDF-gewichtete Vereinigungsmenge
E = IDF-gewichtete Schnittmenge / Minimum(beider IDF-Gesamtmengen)
DTC-Index = 0,60 * J + 0,40 * E
\`\`\`

Dies ist konservativer gegenüber zufälligen Begleitfehlern als der
ältere 0,35-Jaccard/0,65-Enthaltenheit-Ansatz, der umfangreiche
Historien unter Umständen übermäßig ähnlich bewertete.

Die endgültige Formel ist

\`\`\`text
Index = (0,80 * DTC-Index
       + 0,15 * Jaccard(vorherige Beanstandung; falls auf beiden Seiten vorhanden)
       + 0,03 * Jaccard(vorheriger ECU-Softwarestand; falls beidseitig bekannt)
       + 0,02 * Jaccard(Fahrzeugvariante; falls beidseitig bekannt))
       / Summe der tatsächlich verwendeten Gewichte
\`\`\`

Das Ergebnis 0,60 bedeutet **nicht** 60 % Wahrscheinlichkeit
derselben Ursache oder einer erfolgreich übertragbaren Reparatur.

## Automatische Anzahl homogener Gruppen (Complete-Link)

Der frühere Ansatz war eine **Budget-/Abdeckungsoptimierung**:
A und C konnten derselben Medoid-Gruppe angehören, obwohl ihre
Ähnlichkeit nur 4 % oder sogar nicht messbar war, solange beide
den Repräsentanten B ausreichend ähnlich waren.

**Diese Stern-Struktur wird nicht mehr als Cluster ausgegeben.**

Das neue Verfahren:

1. beginnt mit allen qualifizierten QEC-Fällen als Einzelgruppen;
2. prüft Paarvergleiche, stärkste Übereinstimmungen zuerst;
3. verbindet zwei Gruppen **nur, wenn jedes Mitglied jeder Gruppe
   mit jedem Mitglied der anderen Gruppe den Mindestindex
   (Standard 0,60) und alle Nachweisbedingungen besteht**;
4. verlangt zusätzlich eine allen Mitgliedern gemeinsame,
   informative ECU:DTC-Kernmenge, nicht nur eine DTC-Kette;
5. gibt Gruppen erst ab **zwei realen QEC-Fällen** aus; alle übrigen
   Fälle bleiben mit einem expliziten Grund unzugeordnet.

Die Clusterzahl ergibt sich damit *aus den Daten*, nicht aus einer
Zahl wie 12. **Selbst bei Mindestindex 0,60 ist dieselbe technische
Fehlerursache nicht garantiert.** Eine Änderung des Index oder des
Zeitfensters kann neue Gruppen ergeben oder vorhandene aufteilen.
Der Standardwert ist ein vorsichtiger, aber vorläufiger
Engineering-Schwellenwert, kein empirisch kalibrierter Grenzwert.

## Welcher reale Fall ist der beste Repräsentant?

Innerhalb **jeder fertigen Gruppe** wird ein echter QEC-Fall gewählt.

Priorität:
1. höchste **schwächste** Ähnlichkeit zu allen *anderen* Gruppenmitgliedern;
2. höchster Durchschnitt zu allen *anderen* Mitgliedern;
3. bei Gleichstand bessere vorherige Dokumentation:
   QuickTest-Beleg, Kundenbeanstandung, ECU-Softwarestand,
   Fahrzeug-/Variantenkontext;
4. reproduzierbarer QEC-ID-Gleichstand.

Ein Repräsentant mit vielen zusätzlichen, möglicherweise irrelevanten
DTCs ist **nicht allein deshalb** besser.

Der angezeigte **Gruppendurchschnitt schließt den 100-%-Selbstvergleich
des Repräsentanten aus**. Der Wert „schwächstes internes Paar“
prüft wiederum wirklich *alle* unterschiedlichen Fallpaare.
Nicht rechnerisch vergleichbare Paare können nicht Teil einer Gruppe
werden und dürfen daher auch nicht fälschlich als 0-%-Ähnlichkeit
eines bestätigten Clusters erscheinen.

In der Mitgliederliste steht beim Repräsentanten 100 % als
Identitätswert; dieser wird **nicht** für die Gruppenstatistik verwendet.

## Ergebnisdarstellung und Ausnahmen

Die Oberfläche zeigt:

- Anzahl QEC-Fälle und unterschiedliche FINs,
- datenbasierte Anzahl von homogenen Clustern und ihren Repräsentanten,
- die Fälle innerhalb und außerhalb der Gruppen,
- pro Gruppe: gemeinsame ECU:DTC-Kernmenge,
  QEC-/FIN-Zahl, Durchschnitt zum Repräsentanten ohne Selbstvergleich,
  niedrigsten Index zu ihm sowie niedrigsten aller internen Paare,
- jedes nicht gruppierte QEC-Ereignis mit Ausschlussgrund und
  ggf. bestem einzelnem Vergleichshinweis,
- SSL-Endbefunde konsistent mit der fachlichen QEC-Befundfunktion
  (einschließlich in QEC-Ereignissen dokumentierter Befunde);
  Textabweichungen und fehlende Befunde werden als Qualitätswarnungen
  ausgewiesen, nicht zur Gruppeneinteilung verwendet.

Die MDS-Darstellung berechnet zwei Näherungsdimensionen aus den
diagnostischen Paarwerten. Nicht zulässige Vergleiche werden als
Distanz 1 angezeigt, ohne eine tatsächliche metrische Bedeutung
zu behaupten. Die Tabellenwerte sind verbindlicher als der
geometrische 2D-Abstand.

**CSV-Export:** Der lokale Untersuchungsplan enthält pro zugeordnetem
Fall den ausgewählten Repräsentanten, die FIN, den diagnostischen
Index und Prüfwarnungen. Originale werden nicht nach GitHub hochgeladen.

## Wann ist Ergebnisübertragung möglich?

Clusterzugehörigkeit alleine legitimiert **noch keine**
Übertragung eines SSL-Befunds oder einer Reparaturmaßnahme.
Vor einer Übertragung an andere Fälle müssen mindestens die
diagnostische Ursache am Repräsentanten, die gleiche
Bauteil-/Softwarekonfiguration, die Relevanz der DTC-Kernmerkmale
und unabhängige Vergleichsbefunde überprüft werden.
Ein abweichender SSL-Endbefund, eine fehlende Vorher-Diagnose oder
eine nicht dokumentierte Konfiguration begründet Prüfbedarf.

Zur fachlichen Kalibrierung sind mindestens einige Experten-markierte
**gleiche und ungleiche Ursachen-Paare** erforderlich. Erst dann lassen
sich Grenzwerte, Präzision, Vollständigkeit und die Zahl sinnvoller
Entwicklungsuntersuchungen datenbasiert festlegen.

Die alten Complete-Link- und die neuen Gruppen sind getrennte
vergleichbare Analysen, keine konkurrierenden unveränderlichen
Ursachen-Wahrheiten.
