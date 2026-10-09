# Einmaliges pseudonymisiertes Cluster-Prüfpaket als ZIP

## Warum?

Damit eine interne Person nur **eine ZIP** für eine fachliche
Besprechung bereitstellen muss. NTF Insight erstellt diese ZIP
vollständig lokal anhand der bereits importierten Fälle, der
aktuellen HDBSCAN-Gruppierung und vorhandener Fachbestätigungen.

Die ZIP erlaubt eine methodische Überprüfung von Clusterqualität,
DTC-Musterübereinstimmung und möglichen Befund-Prüfhypothesen.
Sie ist **kein Beweis** für gleiche technische Ursachen. Erst
unabhängig bestätigte Befunde ermöglichen eine fachlich belastbare
Ergebnisübertragung (zunächst als überprüfbare Hypothese).

## Ein Klick in der GUI (empfohlen)

1. **Fälle / FIN → ML-Cluster (HDBSCAN)** öffnen und z. B.
   `Coolant Pump`, Leaf, Mindestclustergröße 3, MinSamples 2,
   QuickTest + AutoExport, gesamte Vorher-Historie, DTC-Filter aus
   auswählen.
2. **HDBSCAN berechnen**.
3. Nach unten zu den Repräsentanten-Funktionen scrollen:
   **Pseudonymisiertes Cluster-Prüfpaket als ZIP erstellen**.
4. Speicherort wählen. NTF Insight schreibt **3 lokale Dateien**:
   - `NTF_Cluster_Pruefpaket_ohne_FIN.zip` – das besprechbare Datenpaket.
   - `..._NICHT_HOCHLADEN_FALLZUORDNUNG.csv` – echte QEC-/FIN-Referenzen.
   - `..._NICHT_HOCHLADEN_DTC_ZUORDNUNG.csv` – echte ECU:DTC-Schlüssel.
5. **Nur die ZIP und nur nach interner Freigabe** teilen. Die
   beiden Zuordnungsdateien müssen auf dem autorisierten lokalen
   Rechner bleiben. Die Dateien enthalten keine Rohberichte.

## Ein Skriptaufruf ohne GUI

Im Root des Repositories und mit installiertem NTF Insight:

```powershell
python scripts/export_cluster_review_zip.py
```

Die lokale NTF-Insight-DuckDB wird unter `~/.ntf-insight` oder
`NTF_INSIGHT_DATA_DIR` gesucht. Für einen anderen Zielordner:

```powershell
python scripts/export_cluster_review_zip.py --ausgabe C:\\temp\\Cluster-Pruefung.zip
```

Standard: Bauteilfamilie `coolant_pump`, Leaf, MinClusterSize 3,
MinSamples 2, beide Diagnosequellen, gesamte Vorher-Historie,
kein 35%-Filter. Für eine bereits fachlich vervollständigte
und lokal gespeicherte Prüfdatei:

```powershell
python scripts/export_cluster_review_zip.py --fachpruefung "C:\\intern\\gepruefte_faelle.csv"
```

Mit `--vergleich` kann zusätzlich EOM/Leaf verglichen werden.

## ZIP-Inhalte

- `manifest.json` – Methode, Parameter, Grundgesamtheit, Anzahl
  Cluster und Repräsentanten sowie Sicherheitsgrenzen.
- `cluster.csv` – interne Ähnlichkeit, HDBSCAN-Stabilität, DTC-Kernzahl,
  SSL-Befundverfügbarkeit und Abweichungen, keine SSL-Texte.
- `repraesentanten.csv` – **ein Medoid pro Cluster** und ggf. ein
  ausdrücklich bestätigter Mechanismuscode dieses Repräsentanten.
- `cluster_mitglieder.csv` – jedes Mitglied mit Pseudonym, Cosinus,
  gemeinsamen DTC-Zahlen und Ergebnis der Übertragungsprüfung.
- `interne_fallpaare.csv` – alle paarweisen Ähnlichkeiten innerhalb
  der Cluster.
- `diagnosemerkmale.csv` und `dtc_haeufigkeiten.csv` – wiedererkennbare,
  aber **umbenannte** DTC-Schlüssel (`D0001` usw.) und CPC3-Kennzeichen.
- `diagnosequalitaet.csv` und `ausgeschlossene_faelle.csv` – auditierbare
  Diagnosebasis und Gründe für nicht ausgewertete QEC-Fälle.
- `wiederauftreten.csv` – Vorher-/Nachher-Diagnose-Verfügbarkeit
  und – **nur bei beidseitig vorhandenen Diagnosesitzungen** – Anzahl
  erneut beobachteter, neuer und nicht mehr beobachteter ECU:DTCs.
  Fehlende Nachher-Diagnose darf nicht als Fehlerbehebung gelten.
- `methodenvergleich.csv` – optional EOM/Leaf-Vergleich.

Die QEC- und FIN-Pseudonyme sind **pro ZIP neu erzeugt** und
können ohne die lokalen Zuordnungstabellen nicht unmittelbar auf
Original-IDs zurückgeführt werden. Die ZIP enthält absichtlich keine
direkten Fallkennungen, FINs, technischen Original-DTCs, Zeitstempel
aus Werkstattberichten, privaten SSL-Freitexte, Quelldokumente,
Lieferanten- oder Prüfernamen.

**Datenschutz-/CI-Hinweis:** Pseudonymisierung ist keine Garantie,
dass Informationen unkritisch sind. Technische Muster können
intern vertraulich sein. Mercedes-Benz-Freigaben und der zulässige
Empfängerkreis müssen VOR dem Hochladen geprüft werden.
CI-Tests verwenden ausschließlich synthetische Daten.

## Grenze des Ansatzes

Aus einer ZIP ohne SSL-Labortext und ohne Original-DTC-Schlüssel
kann keine sicher belegte Lieferantenverantwortung oder spezifische
technische Root Cause rekonstruiert werden. Der Bericht dient zum
Nachweis des Analyseprozesses und zur Auswahl sinnvoller
Repräsentanten und Nachprüfungen.
