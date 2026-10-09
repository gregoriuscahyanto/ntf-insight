# Cluster-Pilotpriorisierung mit unabhängigen Vergleichsfällen

## Forschungsziel

Pro HDBSCAN-Cluster **einen realen QEC-Fall als Repräsentanten (Medoid)**
technisch untersuchen und danach gezielt prüfen, ob dessen unabhängig
bestätigter Fehlermechanismus für andere Mitglieder eine **prüfbare**
Ursachenhypothese begründet.

Diagnoseähnlichkeit bedeutet **nicht** gleiche Fehlerursache. Weder der
45%-Cosinus-Screeningwert noch die Pilotpriorität sind aus fachlich
bestätigten Ursachen kalibrierte Wahrscheinlichkeiten. Kein QEC-/SSL-/
Lieferantenbefund wird automatisch übertragen.

## Automatische Prüfpriorisierung (explorative Heuristik)

- **P1 – homogener CPC3-Pilot**: Cluster ohne schwache interne Fallpaare
  unter dem experimentellen 45%-Screeningwert und mit mindestens zwei
  durchgehenden CPC3-Kern-DTCs. Priorität für schnelle technische Validierung.
- **P2 – clusterübergreifender CPC3-Vergleich**: gemeinsame CPC3-Kern-DTCs
  zu anderen Clustern und mindestens zwei eigene CPC3-Kern-DTCs;
  Gruppen getrennt untersuchen, nicht verschmelzen.
- **P3 – diagnostische Kontrollgruppe**: ebenfalls ohne schwache interne
  Fallpaare, aber ohne ausreichende durchgehende CPC3-Kernmuster.
  Eignet sich, die Spezifität unseres Diagnoseansatzes kritisch zu prüfen.
- **P4 – explorativ, heterogen**: andere Gruppen, deren Fallpaare
  teilweise deutlich abweichen; hier keine gruppenweite Ursachenzuweisung.

Alle 19 (bzw. alle aktuell gefundenen) echten Repräsentanten werden
immer angezeigt; die Priorität ändert **nicht** die HDBSCAN-Gruppierung.

## Kontrastierende unabhängige Ziel-Fälle

Neben dem Repräsentanten werden **maximal zwei** bislang nicht unabhängig
bestätigte Mitglieder anderer FINs ausgewählt. Mehrere QEC-Vorgänge
derselben FIN werden für die Vorschlagsliste nicht mehrfach gezählt:

1. **Nächster Vergleichsfall**: möglichst viele gemeinsame
   CPC3-Merkmale und mindestens ein gemeinsames ECU:DTC-Merkmal bei
   >=45 % Cosinus zum Medoid. Falls keine CPC3-Übereinstimmung vorhanden,
   erlaubt der Prüfplan auch andere DTC-Übereinstimmung, aber ausdrücklich
   keinen technischen Ursachenbeleg.
2. **Grenz-/Widerspruchsfall**: möglichst schwacher noch unabhängiger Fall
   des Clusters. Die Untersuchung soll gerade mögliche Fehlübertragungen
   sichtbar machen. Auch ein Fall *unter* 45 % kann methodisch interessant
   sein, darf aber keine automatische Befundzuweisung erhalten.

Die Ausgabe ist eine **Stichprobenempfehlung**, kein statistisch
validiertes Active Learning und kein Beleg für die Gesamtgruppe.
Die zwei unabhängigen Vergleichsfälle sind insbesondere für
Gruppen geeignet, bei denen ähnliche Diagnosen unterschiedliche
technische Ursachen abbilden könnten.

## Deutsche GUI und lokaler ZIP-Export

Nach **Fälle / FIN → ML-Cluster (HDBSCAN) → HDBSCAN berechnen**
erscheint der Bereich:

**Pilotprüfungen: ein Repräsentant je Cluster und unabhängige Vergleichsfälle**

Die erste Tabelle zeigt Priorität, Repräsentant, CPC3-Kern-DTCs, interne
Heterogenität und Clusterbrücken. Die zweite gibt eine prüfbare Reihenfolge
mit maximal zwei zusätzlichen Fällen/Cluster und deren Gegenbelegen aus.

Der bestehende GUI-Button zum pseudonymisierten ZIP-Export und
`python scripts/export_cluster_review_zip.py` erzeugen zusätzlich:

- `pilot_cluster_prioritaet.csv` – ein Repräsentant/Cluster, Methodenhinweise.
- `pilot_validierungsfaelle.csv` – die Prüfrollen mit pseudonymisierten
  Fall- und FIN-Aliasnamen, Vergleichsevidenz und offenem Ergebnisstatus.

Die **lokal getrennten `*_NICHT_HOCHLADEN_*.csv`** enthalten weiterhin
echte QEC-/FIN- und DTC-Bezüge und dürfen nicht weitergegeben werden.
Die Export-Pseudonyme ändern sich bei **jedem Paket**. Nicht die
Fall-Aliasse der vorherigen ZIP verwenden, sondern die lokalen
Zuordnungen genau des aktuellen Pakets. Auch das anonymisierte
Technikpaket nur nach interner Mercedes-Benz-Freigabe teilen.

## Was für eine belastbare Übertragung noch nötig ist

Für jeden Pilotmechanismus eine fachlich unabhängige Bestätigung mit
Prüfer, Beleg und Datum. Mindestens ein unabhängiger Ziel-Fall muss
ebenfalls technisch untersucht werden; widersprechende Befunde
blockieren die Hypothese. Erst mit hinreichend vielen Bestätigungen
kann die Schwellwert- und Gewichtskalibrierung auf strikt
fahrzeuggetrennten Prüfgruppen beginnen.
