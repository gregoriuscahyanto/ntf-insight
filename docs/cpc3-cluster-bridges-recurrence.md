# NTF Insight: Clusterübergreifende CPC3-Muster und Sitzungsnachweis

## Zweck

**Fachliches Endziel**: Einen *realen* QEC-Repräsentanten pro Cluster
untersuchen und den unabhängig bestätigten technischen Mechanismus als
**Prüfhypothese** auf ähnliche Fälle übertragen. Ein gleiches Diagnosemuster
ist kein Beweis für dieselbe technische Fehlerursache und ausdrücklich
kein automatisches Lieferantenurteil.

Auswertung bleibt strikt nachgelagert zum HDBSCAN-Clustering. Gruppen,
Medoide, Tauschanker, QEC-SSL-Endbefunde und Originaldiagnosen werden
nicht verändert. Alle Tests und öffentlichen GitHub-Daten sind synthetisch.

## Neue Tabelle: Clusterübergreifende CPC3-Diagnosemuster

Über alle ungeordneten Clusterpaare werden folgende Größen verglichen:

- **CPC3-Kernüberschneidung**: exakte ECU:DTC, die in *jedem*
  Mitglied von *beiden* Clustern vor dem Tausch vorhanden sind.
  Nur DTCs, die Teil der aktuellen ML-Signatur sind.
- **Repräsentanten-Cosinus**: aus der originalen hochdimensionalen
  Diagnosedistanz, **nicht aus dem 2D-Streudiagramm**.
- **Grenzüberschreitende Fallpaare**: Median, unteres 10%-Quantil,
  Zahl aller Paare sowie Zahl unter dem experimentellen 45%-Grenzwert.
- **IDF-Screening**: interpretierbare Summe der Seltenheitsgewichte
  gemeinsamer CPC3-DTCs (IDF auf derselben Vor-Tausch-Kohorte).
  **Keine Ursachenwahrscheinlichkeit**, kein trainingsbasiertes Gewicht.
- **Unterscheidende CPC3-DTCs**: gemeinsame Kerne nur in A bzw. nur in B.
- **Unabhängigkeit**: gleiche FINs zwischen Clustern zählen getrennt als
  nicht unabhängige Vergleiche.
- **Fachlabels**: Widerspruch anzeigen, wenn zwei *independently*
  bestätigte Repräsentanten unterschiedliche Mechanismen besitzen.
  Keine unbestätigte SSL-Benennung wird als Mechanismus übernommen.

Es werden nur Clusterpaare mit wenigstens einem gemeinsamen CPC3-Kern-DTC
angezeigt, keine künstlichen Clusterfusionen. Die
Clusterkennungen sind **laufbezogen** und nicht dauerhaft stabil.

## Neue Tabelle: Diagnosesitzungen und Wiederauftreten

Das vorhandene Rekurrenzmodell wird nicht aufgeweicht.
Es benötigt **mindestens eine explizite QEC-Diagnosesitzung vor
und nach dem betrachteten Tausch**. Eine beobachtete DTC-Zeile
allein weist keine vollständige Diagnosesitzung nach.

Die neue Prüfung zeigt pro QEC-Fall:
- eindeutig datierte Vorher-/Nachher-DTC-Ereignisse,
- DTCs mit unklarer zeitlicher Lage am Tauschtag,
- explizite QEC-Sitzungen vorher und nachher,
- darunter als vollständig gekennzeichnete QuickTests,
- *separate* FIN-Roh-QuickTest-Berichte inklusive Zero-DTC-Tests
  vor, am und nach dem Tauschtag,
- mehrere QEC-Vorgänge zur gleichen FIN und den konkreten
  Grund für die fehlende Rekurrenz-Beurteilbarkeit.

FIN-Rohberichte werden **nie automatisch** einem QEC-Fall zugeordnet.
Wiederholte FINs können identische Rohhinweise zeigen.
Bei gleich datierten Roh-QuickTests/Teiletausch bleibt die
Reihenfolge vorsorglich unbestimmt, auch bei vorhandener Uhrzeit.
Fehlende Nachher-Sitzungen sind ausdrücklich **nicht** mit
einem nachgewiesenen erfolgreichen Pumpentausch gleichzusetzen.

## Pseudonymisierter ZIP-Export

Die bestehende Ein-Klick-Funktion und das Kommando

```powershell
python scripts/export_cluster_review_zip.py
```

enthalten zwei neue CSV-Dateien in der ZIP:

- `cluster_bruecken.csv` mit CPC3-DTC-**Alias** statt Echtnamen,
  Repräsentanten als Fallpseudonyme, Cross-Cluster-Paarstatistik.
- `diagnosesitzungs_pruefung.csv` mit pseudonymisierten QEC-/FIN-Schlüsseln,
  Evidenzabdeckung und fehlender Vorher-/Nachher-Sitzungsprovenienz.

Zusätzlich enthält das Manifest die Zahl der CPC3-Clusterbrücken,
beurteilbarer Rekurrenzfälle und Fälle mit Vorher-DTC ohne Vorher-Sitzung.

**Die zwei neben der ZIP erzeugten Zuordnungsdateien**
`*_NICHT_HOCHLADEN_*.csv` dürfen den autorisierten Rechner
nicht verlassen. Auch das pseudonymisierte ZIP-Paket enthält mögliche
interne technische Muster und darf nur nach entsprechender
Mercedes-Benz-Freigabe geteilt werden.

## Noch nicht möglich

- eine technische Fehlerursache aus DTC-Übereinstimmung beweisen,
- eine defekte Pumpe oder Lieferantenverantwortung automatisch erklären,
- eine Nachher-Diagnosesitzung ohne Quellenbeleg rekonstruieren,
- die Gültigkeit des 45%-Grenzwerts oder die Ähnlichkeitsgewichte
  ohne unabhängige Fachlabels kalibrieren.
