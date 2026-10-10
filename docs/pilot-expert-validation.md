# Evidenzbasierte Pilot-Fachprüfung und kontrollierter Befundtransfer

## Ziel: ein Repräsentant pro ML-Cluster

Pro HDBSCAN-Cluster einen realen QEC-Medoid fachlich unabhängig untersuchen.
Dessen *spezifischen, belegten* Fehlermechanismus als **prüfbare Hypothese**
für diagnostisch ähnliche Mitglieder verwenden. Mindestens ein
unabhängiges Zielfahrzeug fachlich untersuchen, um die Übertragbarkeit
nachzuweisen oder zu widerlegen.

**Wichtig:** Auch wenn alle bisher geprüften Zielfälle übereinstimmen, wird
kein unbestätigter Fall automatisch zur gleichen Ursache hochgestuft.
Cluster sind Diagnosevergleichsgruppen, keine nachgewiesenen Fehlerursachen
oder Lieferanten-Verursachungsnachweise.

## Bedienung in der lokalen deutschen GUI

1. **Fälle / FIN → ML-Cluster (HDBSCAN)** öffnen und Cluster berechnen.
2. Unter **Pilotprüfungen** auf
   **Priorisierte Pilotfälle zur Fachprüfung lokal exportieren** klicken.
   Die CSV enthält eine Prüfzeile pro Repräsentant und bis zu zwei
   unabhängig ausgewählte QEC-Vergleichsfälle je Cluster.
   *QEC-ID, FIN und QEC-SSL-Freitext sind vertraulich: DATEI LOKAL BELASSEN*.
3. Vor-Ort-Fachprüfung: SSL-Endbefund nur als Kontext lesen. Wenn wirklich
   separate technische Belege existieren, in der CSV
   `review_status=confirmed`, einen **spezifischen**
   `mechanism_code`, `reviewer`, die nachvollziehbare
   `evidence_ref` und `confirmed_on=YYYY-MM-DD` eintragen.
   Sonst die Zeile `pending` belassen. Keine Ursache aus DTC/
   SSL/Fremdcluster blind übernehmen.
4. **Bestätigte Fehlermechanismen lokal einlesen**.
   Vorherige Fachbestätigungen außerhalb der Teilmenge bleiben erhalten.
   Doppelte, *inhaltlich widersprechende* Bestätigungen werden abgewiesen
   und müssen intern aufgelöst werden. Eine FIN, die nicht zur QEC-ID
   passt, wird zurückgewiesen.
5. In **Pilot-Fachvalidierung: Übereinstimmung und Widerspruch** erscheinen
   pro Cluster die tatsächlich separat belegten Zielfahrzeuge und
   Abweichungen. Die **Repräsentanten-Hypothesen** werden automatisch
   gesperrt, wenn irgendein fachlich bestätigter Clusterfall dem
   Repräsentantenmechanismus widerspricht.

Die neue Pilot-CSV ist direkt mit dem **vorhandenen Import-Knopf**
kompatibel. Vorhandene Fachlabels sind bei einem erneuten Export
vorausgefüllt, unbestätigte Ziele bleiben `pending`.
Ein `pending` in einer späteren Teil-Datei entfernt **keine**
bereits bestätigte und in der laufenden App geladene Ursache
(keine stille Löschung).

**Wichtig für mehrtägige Pilotprüfungen:** Nach dem Einlesen von Fachlabels
über **Alle geladenen Fachbestätigungen lokal sichern (NICHT HOCHLADEN)**
eine vollständige lokale Backup-CSV erstellen. Sie enthält **alle**
bislang geladenen bestätigten QEC-Mechanismen (nicht nur die aktuell
noch offenen Pilotfälle), mit FIN, Evidenzreferenz und Prüfer, aber
ohne SSL-Originaltext. Nach einem Neustart diese Datei über
**Bestätigte Fehlermechanismen lokal einlesen** wieder laden.

Die Pilot-Prüfvorlage wird als offene Prüfliste laufend neu priorisiert.
Bereits bestätigte Ziel-FINs können deshalb bei späterem Export aus der
aktuellen Auswahl verschwinden; die gesonderte **Fachlabel-Sicherung**
verhindert den Verlust solcher Ergebnisse.

Die Anwendung speichert die Labels weiterhin nicht automatisch in einer
dauerhaften Datenbank. Original-QEC-, SSL- und Laborquellen bleiben
durch den ganzen Vorgang unverändert.

## Konservative Validierungsregeln

Verglichen werden immer der fachlich bestätigte Cluster-Repräsentant und
**getrennt belegte Ziel-FINs**. Ein Zielfahrzeug mit mehreren
fachlich bestätigten QEC-Vorgängen wird im Pilot nicht mehrfach gezählt,
sondern bis zur Einzelfallklärung zurückgestellt.

Eine mehrfach verwendete `evidence_ref` – beim Repräsentanten oder
zwischen Zielfahrzeugen – darf keine zusätzliche unabhängige
Bestätigung begründen. Eine **verschiedene** Evidenzreferenz ist aber
noch kein Beweis, dass Laborversuche oder fachliche Belege wirklich
unabhängig sind. Das muss der Fachprüfer sicherstellen.

Die Auswertung zeigt die Counts:
- übereinstimmende und abweichende spezifische Mechanismen,
- davon Paarvergleiche, die das **ungeprüfte 45%-Cosinus-/DTC-Screening**
  erfüllen, und solche außerhalb dieses Screenings,
- Gleich-FIN-, gemeinsame-Evidenz- und Mehrfach-QEC-Ausschlüsse,
- Widersprüche mit ungeklärter Unabhängigkeit,
- übrige QEC-/FIN-Ziele ohne separates bestätigtes Gutachten.

Bewusst **keine Schätzquote oder pauschale Cluster-Ursachenwahrscheinlichkeit**:
selektiv ausgewählte Pilotfälle sind keine repräsentative Zufallsstichprobe.
Auch eine beobachtete 2/2-Übereinstimmung beweist nicht, dass 100 % aller
untersuchten Clusterfälle dieselbe Ursache haben. Für statistische
Grenzwertkalibrierung braucht es eine ausreichend große,
fahrzeuggetrennte, unabhängig bestätigte Stichprobe.

## Pseudonymisierte ZIP v3

Wie bisher über **Pseudonymisiertes Cluster-Prüfpaket als ZIP erstellen** oder
per CLI:

```powershell
python scripts/export_cluster_review_zip.py --fachpruefung "C:\\intern\\pilot_bestaetigt.csv" --ausgabe "Cluster_Review_v3.zip"
```

Neue CSV-Dateien **innerhalb der ZIP**:
- `pilot_fachvalidierung.csv` – pro HDBSCAN-Gruppe Anzahl bestätigter,
  eigenständig belegter Übereinstimmungen/Widersprüche und Sperrstatus.
- `pilot_gepruefte_zielpaare.csv` – pseudonymisierte Ziel-Fälle,
  Vergleichsstatus, Screening und manuelle Mechanismuscodes.

Die ZIP enthält **keine QEC-IDs, FINs, Original-DTC-Schlüssel,
Prüfernamen, Evidenzreferenzen, SSL-Freitexte oder Quellberichte**.
Echte Zuordnungen stehen nur in zwei separat erzeugten
`*_NICHT_HOCHLADEN_*.csv` Dateien. Diese Dateien nie hochladen.
Auch die ZIP darf wegen möglicher vertraulicher technischer Muster
nur nach passender interner Mercedes-Benz-Freigabe geteilt werden.
Die Fahrzeug-/Fallpseudonyme wechseln mit jedem Export.

## Qualitätsgrenzen

Keine automatisch abgeleitete technische Ursache, keine
Lieferantenverantwortung, kein automatisch behobener Fehler.
Alle CI-Tests laufen ausschließlich mit synthetischen
Daten – die reale technische Wirksamkeit muss erst fachlich geprüft werden.
